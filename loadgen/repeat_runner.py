"""Independent-repeat orchestration (R4 README R9; `WEEK2_PLAN.md` §10.3).

## What separates two repeats

    drain to in-flight = 0
    then the next repeat's OWN time-based warmup
    same vLLM process throughout

Not a restart. D4 forbids restarting vLLM between repeats deliberately: the
repeatability estimate is supposed to measure arrival/queue interaction
variability, and a restart would fold cold-process, CUDA-graph and allocator
initialization variance into it — measuring the wrong thing, more loudly.

So the separation has to come from draining instead, and draining has to be
*verified* rather than assumed. If repeat B starts while repeat A still has
open streams, B's early requests queue behind A's tail: B's warmup absorbs
some of it, its first measured requests absorb the rest, and the two repeats
are no longer independent — while every artifact still looks clean, because
nothing in a raw log records "there were 40 of the previous run's streams
open when this one started".

That failure is silent, which is why this refuses rather than warns.

## Why per-repeat artifacts are written before anything is aggregated

An aggregate computed on the fly cannot be re-derived if the aggregation rule
turns out to be wrong — and the first session's whole lesson is that the
analysis layer is where the mistakes were. Each repeat writes its own raw
log, sidecar and point record first; classification reads those files
afterwards (`metrics/classification.py`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

# How long to wait for in-flight streams to close before giving up. Generous
# because a 512-token completion issued just before the schedule ended can
# legitimately still be streaming; anything beyond this is a stuck stream, and
# starting the next repeat on top of it would be worse than stopping.
DEFAULT_DRAIN_TIMEOUT_S = 300.0
DRAIN_POLL_INTERVAL_S = 0.5


class RepeatOverlapError(RuntimeError):
    """Raised when a repeat would start while the previous one is still live."""


class DrainTimeoutError(RuntimeError):
    """Raised when in-flight requests never reach zero."""


@dataclass
class RepeatPlan:
    """One repeat: its identity and the λ points it drives, in order."""
    repeat_id: int
    arrival_seed: int
    assignment_seed: int
    lambda_points: list[float]
    canonical_membership_id: str = ""

    def to_dict(self) -> dict:
        return {
            "repeat_id": self.repeat_id,
            "arrival_seed": self.arrival_seed,
            "assignment_seed": self.assignment_seed,
            "lambda_points": list(self.lambda_points),
            "canonical_prompt_membership_id": self.canonical_membership_id,
        }


@dataclass
class RepeatRunReport:
    started_at: float
    plans: list[dict] = field(default_factory=list)
    points: list[dict] = field(default_factory=list)
    drain_events: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "vllm_restarted_between_repeats": False,
            "repeat_separation": "drain to in-flight = 0, then the next repeat's own "
                                 "time-based warmup",
            "plans": self.plans,
            "points": self.points,
            "drain_events": self.drain_events,
        }


def wait_until_drained(inflight_probe: Callable[[], int],
                       timeout_s: float = DEFAULT_DRAIN_TIMEOUT_S,
                       poll_interval_s: float = DRAIN_POLL_INTERVAL_S,
                       sleep: Callable[[float], None] = time.sleep,
                       clock: Callable[[], float] = time.monotonic) -> dict:
    """Block until `inflight_probe()` reports zero, or raise.

    `sleep`/`clock` are injectable so the gate can be tested without spending
    wall time -- the behaviour under test is the refusal, not the waiting.
    """
    start = clock()
    observations = []
    while True:
        inflight = int(inflight_probe())
        observations.append({"elapsed_s": clock() - start, "in_flight": inflight})
        if inflight == 0:
            return {
                "drained": True,
                "waited_s": clock() - start,
                "polls": len(observations),
                "peak_in_flight_observed": max(o["in_flight"] for o in observations),
            }
        if clock() - start >= timeout_s:
            raise DrainTimeoutError(
                f"{inflight} request(s) still in flight after {timeout_s:.0f}s. The next repeat "
                "is NOT being started: its early requests would queue behind this repeat's "
                "tail, and the two runs would not be independent. Investigate the stuck "
                "streams rather than proceeding.")
        sleep(poll_interval_s)


class RepeatRunner:
    """Drives a repeat family, enforcing the drain boundary between repeats.

    `run_point` and `inflight_probe` are injected rather than constructed
    here: the runner's job is sequencing and refusal, and keeping the server
    interaction outside it is what lets the sequencing be tested without a
    GPU.
    """

    def __init__(self,
                 run_point: Callable[[RepeatPlan, float], dict],
                 inflight_probe: Callable[[], int],
                 drain_timeout_s: float = DEFAULT_DRAIN_TIMEOUT_S,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.run_point = run_point
        self.inflight_probe = inflight_probe
        self.drain_timeout_s = drain_timeout_s
        self._sleep = sleep
        self._clock = clock

    def _require_quiescent(self, repeat_id: int, when: str) -> dict:
        inflight = int(self.inflight_probe())
        if inflight != 0:
            raise RepeatOverlapError(
                f"refusing to {when} repeat {repeat_id}: {inflight} request(s) still in flight "
                "from the previous repeat. Repeats must be separated by a verified drain, not "
                "by elapsed time -- overlapping runs share a queue and stop being independent "
                "while every artifact still looks clean.")
        return {"repeat_id": repeat_id, "checkpoint": when, "in_flight": 0}

    def run(self, plans: list[RepeatPlan]) -> RepeatRunReport:
        report = RepeatRunReport(started_at=self._clock())
        report.plans = [p.to_dict() for p in plans]

        seen_ids: set[int] = set()
        for plan in plans:
            if plan.repeat_id in seen_ids:
                raise ValueError(f"duplicate repeat_id {plan.repeat_id} in the plan")
            seen_ids.add(plan.repeat_id)

        for index, plan in enumerate(plans):
            # Before the first point of every repeat, including the first
            # repeat: a server left busy by preflight probing is the same
            # hazard as one left busy by a previous repeat.
            report.drain_events.append(self._require_quiescent(plan.repeat_id, "start"))

            for nominal_lambda in plan.lambda_points:
                record = self.run_point(plan, nominal_lambda)
                report.points.append(record)
                # Within a repeat the same rule applies between λ points: a
                # point that starts on top of the previous point's tail is
                # measuring the wrong queue.
                drain = wait_until_drained(
                    self.inflight_probe, self.drain_timeout_s,
                    sleep=self._sleep, clock=self._clock)
                drain.update({"repeat_id": plan.repeat_id, "after_lambda": nominal_lambda})
                report.drain_events.append(drain)

            if index + 1 < len(plans):
                report.drain_events.append(
                    self._require_quiescent(plans[index + 1].repeat_id, "advance to"))

        return report

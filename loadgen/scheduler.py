"""Open-loop scheduler (WEEK2_PLAN.md §3.1/§3.3).

Request completion never gates the next send. A closed-loop generator
(send -> wait -> send) lets server latency feed back into arrival timing, so
it backs off exactly at the breach and therefore can't observe it. This is
the one piece Hard Stop 1 (WEEK2_EXECUTION.md) exists to eyeball: the send
loop below must never `await` a send's *issue* -- only the scheduling sleep.

Mechanism (all LOCKED, see WEEK2_PLAN.md §3.3):
- Absolute-time scheduling: each send targets `t_start + scheduled_offset`,
  independently -- a late send does not push later sends late.
- Fire-and-forget async task spawn: the loop sleeps-until the target, spawns
  a task, and immediately continues. It never awaits the send.
- Per-send scheduling lag (`scheduled_offset` vs actual `send_time`) is
  logged -- the ground-truth instrument for open-loop fidelity.
- In-flight *streaming responses* (not sends-in-flight) are bounded by a
  concurrency cap; over-cap spawns fail fast as `shed`, never block.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass, field

import httpx

from loadgen.corpus import Corpus
from loadgen.log import RunLogger, SampleLogger
from loadgen.schedule import Schedule
from metrics.consume import consume_stream
from metrics.types import RequestSample

# Same pattern as mock/timing.py:precise_sleep, applied to absolute-target
# scheduling instead of a fixed duration: bare `asyncio.sleep` on Windows
# doesn't guarantee waking at-or-after its target -- it can occasionally
# return a few/several ms EARLY (observed ~13-15ms, in the neighborhood of
# Windows' ~15.6ms timer tick), which would violate the "send_time >=
# scheduled_offset always -- late allowed, early impossible" contract
# (WEEK2_PLAN.md §3.1, §4 V5). Coarse-sleep for the bulk of the wait, then
# spin the last spin margin against the monotonic clock.
#
# PLATFORM-SPECIFIC, from measurement -- not one constant for both.
# The 5ms was tuned on the Windows dev box and shipping it unverified onto
# the Linux vLLM benchmark was an explicit pre-GPU blocker (WEEK2_PLAN.md §8;
# WEEK2_EXECUTION.md Block C). The A/B that closed it is
# `scripts/calibrate_scheduler_spin.py`; the evidence is
# `benchmarks/calibration/scheduler_spin/`, and the reading is written up in
# `BENCHMARKS.md`. Provenance for each value is on its own line below.
#
# Windows: keep the spin. It is the platform whose bare `asyncio.sleep`
# actually returns early, which is the *correctness* failure the spin exists
# to prevent (V5's `send_time >= scheduled_offset`).
WINDOWS_SPIN_MARGIN_S = 0.005
# Linux: NO spin. Set from the A/B (2026-08-18, dedicated e2-standard-4),
# not assumed. Zero early sends were observed at 0ms in every cell -- the
# correctness property the spin exists to protect holds without it here --
# and where the measurement was clean the 5ms arm bought nothing that matters
# against a 50ms inter-arrival gap while its worst case was 6x worse. It also
# has a real cost in this project's topology: Week 2 drives the loadgen ON the
# GPU instance, so a 5ms busy-wait per send would burn ~40% of a core at 80 RPS
# on the same box as vLLM.
LINUX_SPIN_MARGIN_S = 0.0

# Escape hatch for the calibration harness and for a machine that turns out
# to need something else -- an env var rather than an edit, so a GPU-session
# host can be re-tuned without touching tracked source.
SPIN_MARGIN_ENV = "LOADGEN_SPIN_MARGIN_S"


def default_spin_margin_s() -> float:
    """Resolve this host's spin margin: env override, else per-platform."""
    override = os.environ.get(SPIN_MARGIN_ENV)
    if override is not None and override.strip():
        return float(override)
    return WINDOWS_SPIN_MARGIN_S if sys.platform == "win32" else LINUX_SPIN_MARGIN_S


# Module-level default, resolved at import. Read through the `None` sentinel
# below rather than bound as an argument default, so a test or the
# calibration harness can monkeypatch this module attribute and have it
# actually take effect (same pattern as mock/timing.py:SPIN_MARGIN_S).
SPIN_MARGIN_S = default_spin_margin_s()


async def _sleep_until(target: float, spin_margin_s: float | None = None) -> None:
    if spin_margin_s is None:
        spin_margin_s = SPIN_MARGIN_S
    coarse = target - time.monotonic() - spin_margin_s
    if coarse > 0:
        await asyncio.sleep(coarse)
    while time.monotonic() < target:
        await asyncio.sleep(0)


@dataclass
class RunResult:
    n_scheduled: int
    n_sent: int
    n_shed: int
    n_errored: int
    achieved_rps: float
    window_s: float  # the *offered* window (schedule duration_s) -- what achieved_rps is divided by, §2.5
    wall_clock_drain_s: float  # actual elapsed time incl. draining the last in-flight responses -- informational only
    per_send_lag_s: list[float] = field(default_factory=list)
    samples: dict[int, RequestSample] = field(default_factory=dict)  # request_id -> sample, sent only


class OpenLoopScheduler:
    def __init__(
        self,
        schedule: Schedule,
        corpus: Corpus,
        base_url: str,
        logger: RunLogger,
        concurrency_cap: int,
        endpoint_path: str = "/v1/chat/completions",
        query_params: dict | None = None,
        extra_body: dict | None = None,
        model: str = "mock",
        timeout_s: float = 60.0,
        capture_samples: bool = True,
        sample_logger: SampleLogger | None = None,
        spin_margin_s: float | None = None,
    ):
        # None => this host's resolved default. An explicit value lets the
        # calibration harness drive both A/B arms in one process, on one
        # machine, with everything else held identical.
        self.spin_margin_s = default_spin_margin_s() if spin_margin_s is None else spin_margin_s
        self.schedule = schedule
        self.corpus = corpus
        self.base_url = base_url.rstrip("/")
        self.endpoint_path = endpoint_path
        self.query_params = query_params or {}
        self.extra_body = {"stream": True, **(extra_body or {})}
        self.model = model
        self.logger = logger
        self.sample_logger = sample_logger
        self.concurrency_cap = concurrency_cap
        self.timeout_s = timeout_s
        self.capture_samples = capture_samples
        if sample_logger is not None and not capture_samples:
            raise ValueError(
                "sample_logger given with capture_samples=False -- nothing would ever be "
                "written. TTFT/TPOT only exist when the stream is consumed through "
                "metrics.consume_stream."
            )

        # Plain int, no lock: check-then-increment below has no `await`
        # between the two statements, so it's atomic under asyncio's
        # cooperative (single-threaded, non-preemptive) scheduling -- a lock
        # would add nothing here and asyncio.Lock.acquire() is itself a
        # coroutine, which would just be extra ceremony around the same
        # guarantee.
        self._open_streams = 0
        self._per_send_lag: list[float] = []
        self._n_sent = 0
        self._n_shed = 0
        self._n_errored = 0
        self._samples: dict[int, RequestSample] = {}

    @property
    def open_streams(self) -> int:
        """Streams currently open. The drain gate in `loadgen/repeat_runner.py`
        polls this to decide whether the previous repeat has finished; without
        an observable count, "wait for the drain" could only ever be a sleep.
        """
        return self._open_streams

    async def run(self) -> RunResult:
        limits = httpx.Limits(
            max_connections=None,
            max_keepalive_connections=self.concurrency_cap + 10,
        )
        async with httpx.AsyncClient(timeout=self.timeout_s, limits=limits) as client:
            self._client = client
            t_start = time.monotonic()
            tasks: list[asyncio.Task] = []

            for request_id, entry in enumerate(self.schedule.entries):
                target = t_start + entry.scheduled_offset
                if time.monotonic() < target:
                    await _sleep_until(target, self.spin_margin_s)

                # Fire-and-forget: create the task and move straight to the
                # next scheduled send. Never `await task` here.
                task = asyncio.create_task(self._handle(request_id, entry, t_start))
                tasks.append(task)

            # After every send has been *issued*, wait for in-flight streams
            # to drain so the run only returns once every response is
            # accounted for. This await is outside the scheduling loop, so it
            # cannot delay any send.
            await asyncio.gather(*tasks)
            wall_clock_drain_s = time.monotonic() - t_start

        n_scheduled = len(self.schedule.entries)
        # WEEK2_PLAN.md §2.5: achieved RPS is sends (send_time captured --
        # "sent" AND "errored" both count, since both were actually issued;
        # only "shed" was never attempted) within the *offered* window,
        # divided by that offered window duration -- NOT the wall-clock time
        # to fully drain every response, which includes response-tail time
        # that has nothing to do with how fast the driver was sending.
        window_s = self.schedule.provenance["duration_s"]
        n_issued = self._n_sent + self._n_errored
        achieved_rps = n_issued / window_s if window_s > 0 else 0.0
        return RunResult(
            n_scheduled=n_scheduled,
            n_sent=self._n_sent,
            n_shed=self._n_shed,
            n_errored=self._n_errored,
            achieved_rps=achieved_rps,
            window_s=window_s,
            wall_clock_drain_s=wall_clock_drain_s,
            per_send_lag_s=self._per_send_lag,
            samples=self._samples,
        )

    async def _handle(self, request_id: int, entry, t_start: float) -> None:
        prompt = self.corpus.prompts[entry.prompt_id]

        if self._open_streams >= self.concurrency_cap:
            self._n_shed += 1
            self.logger.write(request_id, None, None, entry.prompt_id, prompt.char_len, "shed")
            return
        self._open_streams += 1

        send_time = time.monotonic()
        send_offset = send_time - t_start
        self._per_send_lag.append(send_time - (t_start + entry.scheduled_offset))
        url = f"{self.base_url}{self.endpoint_path}"
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt.text}], **self.extra_body}

        # Guards the sidecar's one-row-per-issued-request invariant: a stream
        # that yielded a sample and *then* failed on teardown gets its real
        # sample row, not a second error row on top of it.
        sample_written = False

        try:
            async with self._client.stream("POST", url, params=self.query_params, json=body) as response:
                response.raise_for_status()
                if self.capture_samples:
                    sample = await consume_stream(response, send_time, clock=time.monotonic)
                    self._samples[request_id] = sample
                    # Durable-on-produce (§6.3): the sample hits disk here, at
                    # the first instant it exists, not at run end. The whole
                    # breach number is computed from this file.
                    if self.sample_logger is not None:
                        self.sample_logger.write(request_id, send_offset, sample)
                        sample_written = True
                else:
                    async for _ in response.aiter_lines():
                        pass
            close_time = time.monotonic()
            self._n_sent += 1
            self.logger.write(
                request_id, send_offset, close_time - t_start, entry.prompt_id, prompt.char_len, "sent"
            )
        except Exception as exc:
            close_time = time.monotonic()
            self._n_errored += 1
            if self.sample_logger is not None and not sample_written:
                self.sample_logger.write_error(request_id, send_offset, f"{type(exc).__name__}: {exc}")
            self.logger.write(
                request_id, send_offset, close_time - t_start, entry.prompt_id, prompt.char_len, "errored"
            )
        finally:
            self._open_streams -= 1

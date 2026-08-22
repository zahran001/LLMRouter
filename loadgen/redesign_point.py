"""The one execution path for frozen Session #2 (`headline-schedule-v2`)
schedules — Tier A scout and Tier B headline alike.

## Why this module exists

Tier A and Tier B started life on different code. Tier B drove the frozen
family through `drive_headline_family.py` and read it with
`metrics/headline_point.py`; Tier A went through the legacy
`loadgen/_cli.py` runner and `metrics/point.py`, which knows nothing about a
v2 schedule. The result was not a runner that produced slightly different
numbers — it was a runner that could not start at all (it demanded a
`master_seed` the v2 provenance does not carry), and that would have applied
the legacy 10s warmup placeholder to a schedule whose boundary is frozen at
60s and emitted a record with none of the validity gates the runbook tells a
human to read at every scout point.

Sharing the *measurement* is the point. A scout sweep exists to hand Tier B a
bracket; if the two tiers interpreted a frozen schedule differently, the
bracket would be expressed in units the confirmation sweep does not use, and
the ~20 minutes of Tier A would buy nothing.

## What is shared, and what is deliberately not

Shared — everything about reading a frozen schedule:

    workload / membership identity      from the schedule
    corpus identity                     from the schedule
    offered RPS                         from the schedule
    warmup boundary                     from the schedule
    expected post-warmup N              from the schedule
    arrival / assignment provenance     from the schedule
    delivery fidelity + exact-N gates   `metrics/headline_point.py`

Not shared — authority. Scout is N=500 at one repeat; its `point_state` has a
~34% per-run flip rate, which is ample for locating a knee and useless as a
verdict. So every record declares an `evidence_class`, and
`metrics/classification.py` refuses to aggregate anything that is not
headline evidence. The separation is a property of the record, not of the
directory it was written to.

Nothing here re-derives a value the frozen schedule already carries. If a
number can be read off the provenance, reading it from a CLI default or a
shell constant instead is how the two tiers drift apart again.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from loadgen.log import RunLogger, SampleLogger, read_log, read_samples
from loadgen.scheduler import OpenLoopScheduler
from metrics.artifacts import write_json_artifact
from metrics.headline_point import (
    EVIDENCE_CLASSES,
    HEADLINE_EVIDENCE,
    SCOUT_DIAGNOSTIC,
    headline_point_metrics,
)

__all__ = [
    "EVIDENCE_CLASSES",
    "HEADLINE_EVIDENCE",
    "SCOUT_DIAGNOSTIC",
    "BASELINE_CONCURRENCY_CAP",
    "RedesignScheduleError",
    "require_exact_n",
    "drive_redesign_point",
]

# Resolved 2026-08-17 (`WEEK2_PLAN.md` §3.3, §8). Shared by both tiers because
# the cap is a property of the client, not of the tier being driven.
BASELINE_CONCURRENCY_CAP = 3000


class RedesignScheduleError(RuntimeError):
    """A frozen v2 artifact that must not be driven as it stands."""


def require_exact_n(name: str, provenance: dict) -> None:
    """Refuse a frozen schedule whose exact-N contract is already broken.

    Checked before any request is sent, in both tiers. Driving it would spend
    meter time producing a point that `classify_point` must exclude anyway --
    and the record would carry `exact_n_honoured: false` in a file nobody
    reads until after teardown.
    """
    materialized = provenance.get("materialized_post_warmup_count")
    target = provenance.get("post_warmup_target_count")
    if materialized is None or target is None:
        raise RedesignScheduleError(
            f"{name}: provenance is missing the exact-N counts "
            "(materialized_post_warmup_count / post_warmup_target_count). This is not a "
            "frozen Session #2 schedule.")
    if materialized != target:
        raise RedesignScheduleError(
            f"{name}: {materialized} post-warmup arrivals, expected exactly {target}. The "
            "exact-N contract is broken in the frozen artifact; regenerate rather than "
            "driving it.")


def drive_redesign_point(
    schedule,
    corpus,
    *,
    out_dir: Path,
    tag: str,
    evidence_class: str,
    base_url: str,
    model: str,
    schedule_path: Path | str | None = None,
    concurrency_cap: int = BASELINE_CONCURRENCY_CAP,
    timeout_s: float = 60.0,
    extra_body: str | dict | None = None,
    warmup_n_s: float | None = None,
    process_epoch: str | None = None,
) -> dict:
    """Drive one complete frozen v2 schedule, then record it.

    The whole schedule is driven — warmup arrivals included — because the
    warmup is part of the frozen artifact and discarding it at *send* time
    would change the load the measured arrivals see. It is discarded at
    *read* time instead, at the boundary the schedule itself declares.

    `warmup_n_s` exists only so a session can record a boundary smaller than
    the frozen one; `headline_point_metrics` refuses a larger one, because
    filtering past the boundary discards canonical arrivals and silently
    leaves fewer than N measured samples (lock 4A).
    """
    if evidence_class not in EVIDENCE_CLASSES:
        raise ValueError(
            f"unknown evidence_class {evidence_class!r}; expected one of {EVIDENCE_CLASSES}")

    prov = schedule.provenance
    require_exact_n(tag, prov)

    # Corpus identity, measured rather than asserted. The frozen schedule names
    # the corpus it was built against; this hashes the file actually loaded and
    # refuses on drift. Only the v1 path did this before, so every session #2
    # stage was taking the workload JSON's word for it.
    schedule.validate_corpus_version(corpus)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"{tag}.raw_log.jsonl"
    samples_path = out_dir / f"{tag}.samples.jsonl"
    metrics_path = out_dir / f"{tag}.metrics.json"

    if isinstance(extra_body, str):
        extra_body = json.loads(extra_body) if extra_body else {}
    extra_body = dict(extra_body or {})

    sample_logger = SampleLogger(samples_path)
    scheduler = OpenLoopScheduler(
        schedule=schedule,
        corpus=corpus,
        base_url=base_url,
        logger=RunLogger(raw_path),
        sample_logger=sample_logger,
        concurrency_cap=concurrency_cap,
        model=model,
        timeout_s=timeout_s,
        capture_samples=True,
        extra_body=extra_body,
    )

    started = time.time()
    result = asyncio.run(scheduler.run())
    scheduler.logger.close()
    sample_logger.close()

    record = headline_point_metrics(
        raw_rows=read_log(raw_path),
        sample_rows=read_samples(samples_path),
        schedule_provenance=prov,
        # Indexed by request_id, because OpenLoopScheduler assigns request_id
        # as `enumerate(schedule.entries)`. This is what makes the p99
        # population a property of the committed artifact rather than of how
        # the run happened to be paced.
        scheduled_offsets=[e.scheduled_offset for e in schedule.entries],
        # The frozen boundary is the default, and the only value the session
        # is expected to use. Not a CLI default -- a schedule-derived one.
        warmup_n_s=warmup_n_s if warmup_n_s is not None else prov["warmup_boundary_s"],
        evidence_class=evidence_class,
        # Which server process served this point. Lock 3A forbids combining
        # repeats across epochs, and a spot preemption forces exactly that,
        # so it has to travel on the record rather than in someone's memory.
        process_epoch=process_epoch,
        provenance={
            "tag": tag,
            "schedule_path": str(schedule_path) if schedule_path is not None else None,
            "raw_log_path": str(raw_path),
            "samples_path": str(samples_path),
            "base_url": base_url,
            "model": model,
            "concurrency_cap": concurrency_cap,
            "timeout_s": timeout_s,
            "wall_clock_s": time.time() - started,
            "wall_clock_drain_s": result.wall_clock_drain_s,
            "n_scheduled_driven": result.n_scheduled,
            "n_sent": result.n_sent,
            "n_shed": result.n_shed,
            "n_errored": result.n_errored,
        },
    )
    write_json_artifact(metrics_path, record)
    return record


def report_point(record: dict, result_shed: int | None = None) -> None:
    """The two lines a human reads off the terminal while a point finishes.

    Identical for both tiers on purpose: the scout sweep's sanity gates are
    the same gates, and a scout point that sheds or misses delivery is just as
    invalid as a headline one -- it simply invalidates a bracket hint rather
    than a verdict.
    """
    p99 = record["ttft_p99_ms"]
    print(f"    issued {record['provenance']['n_sent'] + record['provenance']['n_errored']}"
          f"/{record['provenance']['n_scheduled_driven']} "
          f"(shed {record['provenance']['n_shed']}, errored {record['provenance']['n_errored']})  "
          f"state={record['point_state']}  "
          f"p99={p99 if p99 is None else round(p99, 1)}ms  "
          f"censoring={record['ttft_censoring_rate']:.1%}")

    shed = record["provenance"]["n_shed"] if result_shed is None else result_shed
    if shed:
        print("    WARNING: the concurrency cap bit. This point is cap-shaped, not "
              "server-shaped (WEEK2_PLAN.md 3.3).")
    if not record["exact_n_honoured"]:
        print(f"    WARNING: exact-N not honoured -- "
              f"{record['materialized_post_warmup_count']} materialized post-warmup arrivals "
              f"against a target of {record['post_warmup_target_count']}.")
    if not record["schedule_delivery_ok"]:
        print(f"    WARNING: driver delivered {record['schedule_delivery_divergence_pct']:+.1f}% "
              "against the materialized schedule -- this point is excluded from "
              "classification.")

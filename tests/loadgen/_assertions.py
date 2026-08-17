"""Shared assertion helpers for the Week 2 mock validations (V1-V5,
WEEK2_PLAN.md §4). Positive tests and their negative-control counterparts
call the SAME helpers, mirroring tests/eval/_assertions.py and
tests/router/_assertions.py -- a control that used its own separate check
would prove nothing about the real one.
"""

from __future__ import annotations

import math

from loadgen.corpus import Corpus
from loadgen.schedule import Schedule


# ---------------------------------------------------------------------------
# V1 -- arrival distribution
# ---------------------------------------------------------------------------


def ks_distance_exponential(gaps: list[float], rate: float) -> float:
    """One-sample Kolmogorov-Smirnov D-statistic between `gaps` and
    Exponential(rate), rate fully specified (not fit from the sample) --
    rate is the schedule's own target_rps, so this is a legitimate
    fully-specified-null KS test, not one with estimated parameters."""
    n = len(gaps)
    xs = sorted(gaps)
    d = 0.0
    for i, x in enumerate(xs):
        cdf = 1.0 - math.exp(-rate * x)
        d = max(d, abs((i + 1) / n - cdf), abs(i / n - cdf))
    return d


def ks_critical_value(n: int, alpha: float = 0.05) -> float:
    """Asymptotic critical value c(alpha)/sqrt(n); c(0.05) ~= 1.36 for a
    two-sided one-sample KS test against a fully-specified distribution."""
    c = {0.05: 1.36, 0.01: 1.63, 0.10: 1.22}.get(alpha, 1.36)
    return c / math.sqrt(n)


def assert_fits_exponential(gaps: list[float], rate: float, alpha: float = 0.05, context: str = "") -> None:
    d = ks_distance_exponential(gaps, rate)
    crit = ks_critical_value(len(gaps), alpha)
    assert d <= crit, (
        f"{context}KS D={d:.4f} exceeds critical {crit:.4f} (n={len(gaps)}, alpha={alpha}) -- "
        f"gaps do not fit Exponential(rate={rate})"
    )


def gaps_from_schedule(schedule: Schedule) -> list[float]:
    offsets = [e.scheduled_offset for e in schedule.entries]
    return [b - a for a, b in zip(offsets, offsets[1:])]


# ---------------------------------------------------------------------------
# V3 / V5 -- reconciliation
# ---------------------------------------------------------------------------

VALID_STATUSES = {"sent", "shed", "errored"}


def assert_log_reconciles(rows: list[dict], schedule: Schedule, epsilon_s: float = 1e-6) -> None:
    """WEEK2_PLAN.md §4 V5: every scheduled send appears once with a valid
    status; scheduled = sent + shed + errored; send_time >= scheduled_offset
    always (late allowed, early impossible). This is the check a dropped
    log-write must trip (Hard Stop 2's V5 control)."""
    n_scheduled = len(schedule.entries)

    request_ids = [r["request_id"] for r in rows]
    assert len(rows) == n_scheduled, (
        f"{len(rows)} log rows != {n_scheduled} scheduled entries -- a send was never logged"
    )
    assert sorted(request_ids) == list(range(n_scheduled)), (
        "log request_ids are not exactly {0..n_scheduled-1} once each -- "
        f"missing={sorted(set(range(n_scheduled)) - set(request_ids))}"
    )

    counts = {"sent": 0, "shed": 0, "errored": 0}
    for row in rows:
        status = row["status"]
        assert status in VALID_STATUSES, f"request_id={row['request_id']} has invalid status {status!r}"
        counts[status] += 1

        entry = schedule.entries[row["request_id"]]
        if status in ("sent", "errored"):
            assert row["send_time"] is not None, f"request_id={row['request_id']} status={status} has no send_time"
            assert row["send_time"] >= entry.scheduled_offset - epsilon_s, (
                f"request_id={row['request_id']}: send_time {row['send_time']} < "
                f"scheduled_offset {entry.scheduled_offset} -- sent before it was scheduled"
            )

    total = counts["sent"] + counts["shed"] + counts["errored"]
    assert total == n_scheduled, (
        f"scheduled({n_scheduled}) != sent({counts['sent']}) + shed({counts['shed']}) + "
        f"errored({counts['errored']}) = {total}"
    )


def assert_samples_reconcile(sample_rows: list[dict], raw_rows: list[dict]) -> None:
    """The sidecar analog of assert_log_reconciles (WEEK2_PLAN.md §6.3): the
    TTFT/TPOT sidecar must carry exactly one row per *issued* request --
    every `sent` or `errored` row in the raw log, and nothing else. A `shed`
    request never opened a stream, so it has no sample.

    This is the check a dropped sample-write must trip. Without it, a
    silently short sidecar and a genuinely quiet point look identical, and
    the breach percentile would be computed over a subset nobody noticed was
    a subset.
    """
    issued_ids = {r["request_id"] for r in raw_rows if r["status"] in ("sent", "errored")}
    shed_ids = {r["request_id"] for r in raw_rows if r["status"] == "shed"}
    sample_ids = [r["request_id"] for r in sample_rows]

    assert len(sample_ids) == len(set(sample_ids)), (
        "sidecar has duplicate request_ids -- a request was sampled twice: "
        f"{sorted(i for i in set(sample_ids) if sample_ids.count(i) > 1)}"
    )
    assert set(sample_ids) == issued_ids, (
        f"sidecar rows ({len(sample_ids)}) != issued requests ({len(issued_ids)}) -- "
        f"missing={sorted(issued_ids - set(sample_ids))}, "
        f"unexpected={sorted(set(sample_ids) - issued_ids)}"
    )
    assert not (set(sample_ids) & shed_ids), (
        f"shed requests appear in the sidecar: {sorted(set(sample_ids) & shed_ids)} -- "
        "a shed request never opened a stream and cannot have a sample"
    )

    raw_send_times = {r["request_id"]: r["send_time"] for r in raw_rows}
    for row in sample_rows:
        assert row["send_time"] == raw_send_times[row["request_id"]], (
            f"request_id={row['request_id']}: sidecar send_time {row['send_time']} != raw log "
            f"{raw_send_times[row['request_id']]} -- the two files disagree on the same request's "
            "position on the wall-clock axis, which would desync the time-based warmup filter"
        )


# ---------------------------------------------------------------------------
# V3 -- concurrency cap
# ---------------------------------------------------------------------------


def peak_concurrency(rows: list[dict]) -> int:
    """Max number of simultaneously-open [send_time, close_time] intervals
    among 'sent'/'errored' rows (shed rows never opened a stream).

    send_time is captured right after cap admission (the increment) and
    close_time right before the matching decrement (loadgen/scheduler.py:
    OpenLoopScheduler._handle), so these intervals are exactly the
    scheduler's own open-stream bookkeeping window -- this replays the
    scheduler's internal _open_streams peak from the log alone, which is
    the direct way to verify the cap was actually respected. A shed-count
    comparison across two different cap VALUES cannot prove the enforcement
    logic itself is correct (see test_negative_controls.py's V3 control);
    this can, because it's checked against the same cap the run was
    configured with.
    """
    events: list[tuple[float, int]] = []
    for r in rows:
        if r["status"] in ("sent", "errored") and r["send_time"] is not None and r["close_time"] is not None:
            events.append((r["send_time"], 1))
            events.append((r["close_time"], -1))
    # At a tied timestamp, process closes (-1) before opens (+1). This is
    # not a conservatism choice -- it's what the scheduler actually
    # guarantees: OpenLoopScheduler._handle has no `await` between capturing
    # close_time and decrementing _open_streams, so a freed slot's decrement
    # always happens-before any subsequent admission check it enables, even
    # when time.monotonic()'s resolution can't distinguish the two events'
    # timestamps (this happens in practice -- verified empirically: a
    # newly-admitted request's send_time can tie exactly with the close_time
    # of the request whose slot it took). Sorting opens-first at a tie
    # attributes that admission to a moment BEFORE the slot was actually
    # freed, phantom-inflating peak by 1 for a run that never really
    # exceeded the cap.
    events.sort(key=lambda e: (e[0], 0 if e[1] == -1 else 1))

    concurrency = 0
    peak = 0
    for _, delta in events:
        concurrency += delta
        peak = max(peak, concurrency)
    return peak


def assert_cap_respected(rows: list[dict], cap: int, context: str = "") -> None:
    """WEEK2_PLAN.md §3.3: in-flight streaming responses bounded by the
    concurrency cap. Checked directly from the raw log's observed peak
    concurrency, not inferred from shed counts."""
    peak = peak_concurrency(rows)
    assert peak <= cap, f"{context}peak observed concurrency {peak} exceeds cap {cap} -- cap enforcement is broken"


# ---------------------------------------------------------------------------
# V4 -- corpus faithfulness
# ---------------------------------------------------------------------------


def assert_all_prompts_valid(corpus: Corpus) -> None:
    """WEEK2_PLAN.md §4 V4: every entry in the pinned corpus must pass the
    validity filter (non-empty text) -- a filter-bypass bug would let junk
    (e.g. an empty string) reach prompt assignment."""
    for p in corpus.prompts:
        assert isinstance(p.text, str) and p.text.strip(), (
            f"prompt_id={p.prompt_id} is empty/invalid -- validity filter did not run or was bypassed"
        )

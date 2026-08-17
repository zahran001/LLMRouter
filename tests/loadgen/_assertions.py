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

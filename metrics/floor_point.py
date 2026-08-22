"""The unloaded intrinsic floor over the canonical workload
(`WEEK2_GPU_SESSION_2_PLAN.md` §2 step 3).

## What this measures, and what it deliberately does not

Every canonical prompt served once, alone, at concurrency 1. No arrival
process, no queueing, no warmup boundary, no delivery band — none of those
concepts exist here, which is why this is a separate reader rather than a
headline point with unusual parameters. Routing the floor through a Poisson
schedule at some low λ would smuggle in queueing and a warmup transient to
measure a quantity defined by their absence.

What comes out is the TTFT the headline curve *starts from*: at concurrency 1
a q99-length prompt already costs ~370ms against a 500ms SLO, so the floor is
most of the budget before any load exists.

## Why it is better than the floor it replaces

Session #1's floor is classified `CACHE_INFLUENCED_DIAGNOSTIC` and can no
longer be cited. It sampled 248 prompts from one schedule's realized draw;
this measures the **exact multiset the headline curve uses**, so the intrinsic
p99 it produces is that curve's actual starting point rather than an estimate
of it.

## Evidence class

`floor_diagnostic`. The floor informs interpretation and never defines the
breach — the breach is a property of the loaded curve. `metrics/classification.py`
refuses it like every other non-headline record.
"""

from __future__ import annotations

from collections import Counter

from metrics.headline_point import (
    BREACH_TTFT_MS,
    CENSORING_HARD_GATE,
    FLOOR_DIAGNOSTIC,
    SEVERE_TTFT_MS,
)
from metrics.percentile import (
    percentile_nearest_rank,
    percentile_provenance,
    top_k_support,
)

FLOOR_RECORD_VERSION = "floor-point-v1"


def floor_point_metrics(
    raw_rows: list[dict],
    sample_rows: list[dict],
    membership: list[int],
    membership_id: str,
    corpus_sha256: str,
    concurrency: int = 1,
    provenance: dict | None = None,
) -> dict:
    """One unloaded-floor record over the canonical membership.

    `membership` is the frozen canonical prompt list — the population is that
    list, exactly, for the same reason the headline population is the frozen
    schedule: it must not become a function of which requests happened to
    succeed.
    """
    if concurrency != 1:
        raise ValueError(
            f"concurrency={concurrency}: the unloaded floor is defined at concurrency 1. "
            "Anything above it measures queueing, which is what the floor exists to exclude.")

    expected_n = len(membership)
    expected_ids = set(membership)

    issued = [r for r in raw_rows if r["status"] in ("sent", "errored")]
    issued_prompt_ids = {r["prompt_id"] for r in issued}
    missing = expected_ids - issued_prompt_ids

    observed = [r for r in sample_rows
                if r.get("ttft_ms") is not None and not r.get("error")]
    ttft = [float(r["ttft_ms"]) for r in observed]

    n_censored = max(len(issued) - len(observed), 0)
    censoring_rate = n_censored / len(issued) if issued else 0.0
    hard_gated = censoring_rate > CENSORING_HARD_GATE

    p50 = p95 = p99 = mean = None
    if ttft and not hard_gated:
        p50 = percentile_nearest_rank(ttft, 50)
        p95 = percentile_nearest_rank(ttft, 95)
        p99 = percentile_nearest_rank(ttft, 99)
        mean = sum(ttft) / len(ttft)

    errors = Counter()
    for row in sample_rows:
        if row.get("error"):
            errors[str(row["error"]).split(":", 1)[0].strip()] += 1

    complete = not missing and not hard_gated and p99 is not None

    return {
        "record_version": FLOOR_RECORD_VERSION,
        "evidence_class": FLOOR_DIAGNOSTIC,
        "may_define_headline_breach": False,
        "workload_class": "unloaded_floor",
        # --- identity --------------------------------------------------------
        "canonical_prompt_membership_id": membership_id,
        "corpus_sha256": corpus_sha256,
        "concurrency": concurrency,
        # --- population ------------------------------------------------------
        "expected_measurement_n": expected_n,
        "reconciled_measurement_n": len(issued),
        "percentile_population_n": expected_n,
        "measurement_membership_basis": "canonical_membership",
        "n_missing_prompts": len(missing),
        "missing_prompt_ids": sorted(missing)[:50],
        "membership_complete": not missing,
        # --- censoring -------------------------------------------------------
        "n_ttft_observed": len(observed),
        "n_censored": n_censored,
        "ttft_censoring_rate": censoring_rate,
        "censoring_hard_gate": CENSORING_HARD_GATE,
        "error_categories": dict(errors),
        # Completeness is a term. A truncated floor discloses itself in
        # `floor_complete` and `n_missing_prompts`, but the one field named
        # "may I publish this" said yes regardless -- and the prompts a prefix
        # truncation drops are the long ones at the end of the id-sorted
        # membership, which is where the floor's tail lives.
        "publish_ordinary_p99": not hard_gated and p99 is not None and not missing,
        # --- the metric ------------------------------------------------------
        "ttft_p50_ms": p50,
        "ttft_p95_ms": p95,
        "ttft_p99_ms": p99,
        "ttft_mean_ms": mean,
        "ttft_min_ms": min(ttft) if ttft else None,
        "ttft_max_ms": max(ttft) if ttft else None,
        "top_1pct_support": top_k_support(len(observed), 99.0),
        "breach_threshold_ms": BREACH_TTFT_MS,
        "severe_threshold_ms": SEVERE_TTFT_MS,
        # Headroom is the number the floor exists to produce: what is left of
        # the SLO before any load is applied.
        "slo_headroom_ms": (BREACH_TTFT_MS - p99) if p99 is not None else None,
        "floor_complete": complete,
        "percentile": percentile_provenance(),
        "provenance": dict(provenance or {}),
    }

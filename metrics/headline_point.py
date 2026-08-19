"""Redesigned per-point metrics: RPS semantics and censoring-aware validity
(R4 README R7/R8; `WEEK2_PLAN.md` §10.4/§10.5/§10.6).

A separate module from `metrics/point.py`, which is frozen. The first
session's records were produced by that code and are pinned to it — the
redesign changes the percentile convention, the fidelity denominator and the
validity model, and applying any of those retroactively would rewrite what
historical artifacts mean. Two readers, each declaring its own semantics, is
the point rather than duplication.

## Three RPS quantities, not one (R7)

    nominal_lambda_rps         the workload parameter, and the chart x-axis
    materialized_schedule_rps  the finite Poisson realization the driver got
    actual_send_rps            what the driver actually issued

The first session collapsed the first two and flagged both its low-RPS points
for it: the 2-RPS schedule materialized 248 arrivals over 130s, was measured
against `λ × duration`, and came out −6.25% "divergent". Nothing was wrong
with the driver. A finite Poisson realization does not contain exactly
`λ × duration` arrivals, and it is not supposed to.

So driver fidelity compares **actual sends against the materialized
schedule** — the list the driver was actually handed. The difference between
that schedule and nominal λ is recorded too, as descriptive metadata, and it
must never fail the driver.

## Censoring decides whether a p99 exists at all (R8)

At 10/20/30 RPS the 60s client timeout removed 33%/70%/81% of requests from
the TTFT sample, and the survivors' p99 sat near 60s. The old gate blessed
those points because enough *survivors* remained to clear `n >= 100`.
`tail_valid` meant "enough survivors", which is the wrong question: the
requests that vanished were precisely the slow ones the tail is made of.

    censoring rate > 5%   ->  CENSORED, no ordinary p99 verdict
    0 < rate <= 5%        ->  p99 eligible, WITH a tail warning

Eligible is not valid. A point carrying any censoring that could decide the
UNDER/OVER crossing needs a recorded tail-sensitivity review before it may
finalize anything; without it the aggregate stays UNCERTAIN (see
`metrics/classification.py`). The 5% line is a hard automatic gate, not a
claim that 4.9% is harmless.
"""

from __future__ import annotations

from collections import Counter

from metrics.percentile import (
    percentile_nearest_rank,
    percentile_provenance,
    top_k_support,
)

# §2.6, unchanged by the redesign.
BREACH_TTFT_MS = 500.0
SEVERE_TTFT_MS = 2000.0

# §10.6: above this, a point cannot report an ordinary p99 at all.
CENSORING_HARD_GATE = 0.05

# §10.4: driver-fidelity band against the MATERIALIZED schedule. Same ±5% as
# before; only the denominator changed.
DEFAULT_DELIVERY_BAND_PCT = 5.0

# The four point states.
UNDER = "UNDER"
OVER = "OVER"
UNCERTAIN = "UNCERTAIN"
CENSORED = "CENSORED"

ISSUED_STATUSES = ("sent", "errored")


def post_warmup(rows: list[dict], warmup_n_s: float) -> list[dict]:
    """Discard the first `warmup_n_s` seconds by send timestamp (§2.4).

    Unchanged from the legacy reader: the warmup rule is one of the few parts
    of §2.4 the first session did not falsify.
    """
    return [r for r in rows if r.get("send_time") is not None and r["send_time"] >= warmup_n_s]


def _error_categories(rows: list[dict]) -> dict:
    """Group errors by exception type.

    Kept separate from the censoring *rate* because they answer different
    questions: the rate decides whether a p99 may be published, while the
    categories say whether the cause was a timeout, a refused connection, or
    the client running out of file descriptors — which is a finding about the
    instrument rather than the server.
    """
    counts = Counter()
    for row in rows:
        error = row.get("error")
        if error:
            counts[str(error).split(":", 1)[0].strip()] += 1
    return dict(counts)


def headline_point_metrics(
    raw_rows: list[dict],
    sample_rows: list[dict],
    schedule_provenance: dict,
    warmup_n_s: float,
    delivery_band_pct: float = DEFAULT_DELIVERY_BAND_PCT,
    tail_censoring_review: dict | None = None,
    provenance: dict | None = None,
) -> dict:
    """One redesigned headline point's record.

    `schedule_provenance` is the frozen v2 schedule's provenance block: it
    carries the materialized counts and duration that the fidelity check
    compares against, so the check reads what was actually offered rather than
    recomputing an expectation.
    """
    nominal_lambda = float(schedule_provenance["nominal_lambda_rps"])
    warmup_boundary = float(schedule_provenance["warmup_boundary_s"])

    # The warmup boundary is frozen INTO the schedule: exactly N arrivals were
    # materialized at or after it. Filtering at a later timestamp would discard
    # some of those N, leaving fewer measured samples than N and a canonical
    # multiset that is no longer complete -- silently undoing the control the
    # whole redesign is built on, while every count still looks plausible.
    #
    # This matters in practice because the per-point warmup value is still
    # [CALIBRATE] and gets resolved from session #2's transient. If the
    # resolved value exceeds the boundary the schedules were generated with,
    # the schedules must be REGENERATED at the larger boundary -- not
    # re-filtered.
    if warmup_n_s > warmup_boundary + 1e-9:
        raise ValueError(
            f"warmup_n_s={warmup_n_s}s exceeds the schedule's frozen warmup boundary "
            f"{warmup_boundary}s. Filtering past the boundary would discard canonical arrivals "
            f"and leave fewer than the frozen N={schedule_provenance['post_warmup_target_count']} "
            "measured samples. Regenerate the schedules with the larger warmup boundary instead "
            "of re-filtering (WEEK2_PLAN.md 10.2)."
        )
    materialized_count = int(schedule_provenance["materialized_schedule_count"])
    materialized_post = int(schedule_provenance["materialized_post_warmup_count"])
    materialized_duration = float(schedule_provenance["materialized_schedule_duration_s"])
    target_n = int(schedule_provenance["post_warmup_target_count"])

    post_window_s = materialized_duration - warmup_boundary
    materialized_rps = materialized_post / post_window_s if post_window_s > 0 else 0.0

    # --- R7: what was offered vs what was sent ---------------------------
    issued = [r for r in raw_rows if r["status"] in ISSUED_STATUSES]
    issued_window = post_warmup(issued, warmup_boundary)
    shed_total = sum(1 for r in raw_rows if r["status"] == "shed")

    actual_sent_count = len(issued_window)
    actual_send_rps = actual_sent_count / post_window_s if post_window_s > 0 else 0.0

    # Driver fidelity: actual sends vs the materialized schedule. This is the
    # gate.
    schedule_delivery_divergence_pct = (
        100.0 * (actual_sent_count - materialized_post) / materialized_post
        if materialized_post else 0.0
    )
    delivery_ok = abs(schedule_delivery_divergence_pct) <= delivery_band_pct

    # Finite-Poisson realization vs nominal lambda. Metadata. Never a failure.
    nominal_realization_delta_pct = (
        100.0 * (materialized_rps - nominal_lambda) / nominal_lambda if nominal_lambda else 0.0
    )

    # --- R8: censoring ----------------------------------------------------
    samples_window = post_warmup(sample_rows, warmup_boundary)
    observed = [r for r in samples_window
                if r.get("ttft_ms") is not None and not r.get("error")]
    censored_rows = [r for r in samples_window
                     if r.get("ttft_ms") is None or r.get("error")]

    n_issued_window = len(issued_window)
    n_observed = len(observed)
    # Denominator is issued requests, not sidecar rows: a request that was
    # issued and produced no sidecar row at all is still a censored
    # observation, and using the sidecar as the denominator would hide it.
    n_censored = max(n_issued_window - n_observed, 0)
    censoring_rate = n_censored / n_issued_window if n_issued_window else 0.0

    ttft = [float(r["ttft_ms"]) for r in observed]

    hard_gated = censoring_rate > CENSORING_HARD_GATE
    tail_warning = (not hard_gated) and censoring_rate > 0.0

    ttft_p50 = ttft_p95 = ttft_p99 = ttft_mean = None
    if ttft and not hard_gated:
        ttft_p50 = percentile_nearest_rank(ttft, 50)
        ttft_p95 = percentile_nearest_rank(ttft, 95)
        ttft_p99 = percentile_nearest_rank(ttft, 99)
        ttft_mean = sum(ttft) / len(ttft)

    if hard_gated:
        state = CENSORED
        reason = (f"TTFT censoring {censoring_rate:.1%} exceeds the {CENSORING_HARD_GATE:.0%} "
                  "hard gate; a survivor-only percentile is not a latency measurement")
    elif ttft_p99 is None:
        state = UNCERTAIN
        reason = "no TTFT observations after the warmup boundary"
    elif ttft_p99 >= BREACH_TTFT_MS:
        state = OVER
        reason = f"nearest-rank p99 {ttft_p99:.1f}ms >= {BREACH_TTFT_MS:.0f}ms"
    else:
        state = UNDER
        reason = f"nearest-rank p99 {ttft_p99:.1f}ms < {BREACH_TTFT_MS:.0f}ms"

    review_status = None
    if tail_warning:
        review_status = (tail_censoring_review or {}).get("status", "REQUIRED_NOT_DONE")

    return {
        "record_version": "headline-point-v1",
        "workload_class": schedule_provenance.get("workload_class", "headline_controlled"),
        # --- repeat identity ------------------------------------------------
        "repeat_id": schedule_provenance.get("repeat_id"),
        "canonical_prompt_membership_id": schedule_provenance.get(
            "canonical_prompt_membership_id"),
        "arrival_seed": schedule_provenance.get("arrival_seed"),
        "assignment_seed": schedule_provenance.get("assignment_seed"),
        # --- R7: the three RPS quantities ------------------------------------
        "nominal_lambda_rps": nominal_lambda,
        "materialized_schedule_count": materialized_count,
        "materialized_post_warmup_count": materialized_post,
        "post_warmup_target_count": target_n,
        "exact_n_honoured": materialized_post == target_n,
        "materialized_schedule_duration_s": materialized_duration,
        "materialized_post_warmup_duration_s": post_window_s,
        "materialized_schedule_rps": materialized_rps,
        "actual_sent_count": actual_sent_count,
        "actual_send_rps": actual_send_rps,
        "schedule_delivery_divergence_pct": schedule_delivery_divergence_pct,
        "schedule_delivery_ok": delivery_ok,
        "delivery_band_pct": delivery_band_pct,
        "nominal_realization_delta_pct": nominal_realization_delta_pct,
        "nominal_realization_is_metadata": True,
        "warmup_boundary_s": warmup_boundary,
        "warmup_n_s_applied": warmup_n_s,
        "n_shed_total": shed_total,
        # --- R8: censoring ---------------------------------------------------
        "n_issued_window": n_issued_window,
        "n_ttft_observed": n_observed,
        "n_censored": n_censored,
        "ttft_censoring_rate": censoring_rate,
        "censoring_hard_gate": CENSORING_HARD_GATE,
        "error_categories": _error_categories(samples_window),
        "tail_censoring_warning": tail_warning,
        "tail_censoring_review_status": review_status,
        "tail_censoring_review": tail_censoring_review,
        "publish_ordinary_p99": not hard_gated and ttft_p99 is not None,
        # --- the metric -------------------------------------------------------
        "ttft_p50_ms": ttft_p50,
        "ttft_p95_ms": ttft_p95,
        "ttft_p99_ms": ttft_p99,
        "ttft_mean_ms": ttft_mean,
        "top_1pct_support": top_k_support(n_observed, 99.0),
        "breach_threshold_ms": BREACH_TTFT_MS,
        "severe_threshold_ms": SEVERE_TTFT_MS,
        "severe_2s": (ttft_p99 >= SEVERE_TTFT_MS) if ttft_p99 is not None else None,
        # --- verdict ----------------------------------------------------------
        "point_state": state,
        "point_state_reason": reason,
        "percentile": percentile_provenance(),
        "provenance": dict(provenance or {}),
    }

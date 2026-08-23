"""Censoring-aware point validity (R4 README R8; `WEEK2_PLAN.md` §10.6).

The failure this replaces is specific and was live in the first session: at
10/20/30 RPS the 60s client timeout removed 33%/70%/81% of requests from the
TTFT sample, the survivors' p99 sat near 60s, and the validity gate passed
those points because enough *survivors* remained to clear `n >= 100`. The gate
was asking "are there enough samples" when the question was "are the missing
ones the samples that mattered" — and at the tail they always are.

R8 originally drew the line at a flat 5% ("CENSORED", ambiguous, no verdict).
GPU session #2's first attempt (2026-08-22) found the real failure one level
up: Tier A's short scout read a point as clean UNDER while Tier B's longer
confirmation at the same neighbourhood came back badly censored -- and a flat
percentage cutoff has no way to say censoring *proves* the breach rather than
merely correlating with it. `OVER_CENSORED` (locked the same day) replaces the
5% gate with the exact order-statistics condition: at N=200 (this file's
fixture size) the nearest-rank p99 position is provably censored once
`n_censored >= 3` (~1.5%) -- a LOWER bar than 5%, so every boundary case below
that used to sit in the old "eligible but warned" or "ambiguous CENSORED" band
and now proves OVER_CENSORED instead.
"""

from __future__ import annotations

import math

import pytest

from metrics.headline_point import (
    CENSORING_HARD_GATE,
    OVER,
    OVER_CENSORED,
    UNCERTAIN,
    UNDER,
    headline_point_metrics,
)

pytestmark = pytest.mark.redesign

N = 200

# The exact rank-based threshold at this fixture's N=200: ceil(0.99*200)=198,
# so n_censored >= 200-198+1 = 3 proves OVER_CENSORED. Computed, not
# hardcoded, so this file stays correct if N above ever changes.
OVER_CENSORED_MIN_N = N - math.ceil(0.99 * N) + 1


def _schedule_provenance(n=N, warmup_s=0.0, nominal_lambda=2.0):
    return {
        "nominal_lambda_rps": nominal_lambda,
        "warmup_boundary_s": warmup_s,
        "materialized_schedule_count": n,
        "materialized_post_warmup_count": n,
        "post_warmup_target_count": n,
        "materialized_schedule_duration_s": n / nominal_lambda + warmup_s,
        "workload_class": "headline_controlled",
        "repeat_id": 1,
        "canonical_prompt_membership_id": "deadbeef",
        "arrival_seed": 1,
        "assignment_seed": 2,
    }


def _rows(n_issued: int, n_censored: int, ttft_ms: float, censored_error="ReadTimeout: timed out"):
    """`n_issued` requests, of which `n_censored` produced no TTFT."""
    raw, samples = [], []
    for i in range(n_issued):
        raw.append({"request_id": i, "send_time": float(i) * 0.01, "close_time": 1.0,
                    "prompt_id": i, "prompt_len": 100,
                    "status": "errored" if i < n_censored else "sent"})
        if i < n_censored:
            samples.append({"request_id": i, "send_time": float(i) * 0.01, "ttft_ms": None,
                            "tpot_samples_ms": [], "content_chunk_count": 0,
                            "error": censored_error})
        else:
            samples.append({"request_id": i, "send_time": float(i) * 0.01, "ttft_ms": ttft_ms,
                            "tpot_samples_ms": [], "content_chunk_count": 5, "error": None})
    # Offsets mirror the send times: these fixtures have no scheduling lag, so
    # scheduled-offset membership and send-time filtering coincide. The tests
    # that pull them apart live in test_exact_n_membership.py.
    offsets = [float(i) * 0.01 for i in range(n_issued)]
    return raw, samples, offsets


def _record(n_censored: int, ttft_ms: float = 300.0, **kw):
    raw, samples, offsets = _rows(N, n_censored, ttft_ms)
    return headline_point_metrics(raw, samples, _schedule_provenance(), warmup_n_s=0.0,
                                  scheduled_offsets=offsets, **kw)


# ---------------------------------------------------------------------------
# The four states R8 requires.
# ---------------------------------------------------------------------------


def test_zero_censoring_is_eligible_with_no_warning():
    record = _record(0, ttft_ms=300.0)
    assert record["ttft_censoring_rate"] == 0.0
    assert record["tail_censoring_warning"] is False
    assert record["tail_censoring_review_status"] is None
    assert record["publish_ordinary_p99"] is True
    assert record["point_state"] == UNDER


def test_just_below_the_over_censored_threshold_is_eligible_but_warned():
    record = _record(OVER_CENSORED_MIN_N - 1)  # 1.0% at N=200 -- below the exact-rank threshold
    assert 0 < record["ttft_censoring_rate"]
    assert record["over_censored_proven"] is False
    assert record["publish_ordinary_p99"] is True
    assert record["tail_censoring_warning"] is True, (
        "sub-threshold censoring must still warn: censored requests are tail events, and near "
        "the SLO even a few of them can decide the verdict")
    assert record["tail_censoring_review_status"] == "REQUIRED_NOT_DONE"
    assert record["point_state"] in (UNDER, OVER)


def test_exactly_at_the_over_censored_threshold_proves_breach():
    record = _record(OVER_CENSORED_MIN_N)  # 1.5% at N=200 -- exactly the exact-rank threshold
    assert record["over_censored_proven"] is True
    assert record["point_state"] == OVER_CENSORED
    assert record["publish_ordinary_p99"] is False
    assert record["tail_censoring_warning"] is False, (
        "a proven breach needs no tail-sensitivity review -- there is nothing ambiguous left")


def test_just_above_the_over_censored_threshold_also_proves_breach():
    record = _record(OVER_CENSORED_MIN_N + 1)
    assert record["over_censored_proven"] is True
    assert record["point_state"] == OVER_CENSORED
    assert record["publish_ordinary_p99"] is False
    assert record["ttft_p99_ms"] is None, (
        "a proven-breach point must not carry an ordinary p99 at all; a suppressed verdict with "
        "a published number is not suppressed")


def test_the_legacy_five_percent_gate_still_computes_as_metadata_only():
    """5% no longer decides the state (OVER_CENSORED fires well before it at any
    realistic N), but `censoring_hard_gate_exceeded` still reports whether the
    old rule would independently have fired, for continuity with pre-2026-08-22
    records."""
    record = _record(11)  # 5.5% -- above the legacy 5% gate AND the new threshold
    assert record["ttft_censoring_rate"] > CENSORING_HARD_GATE
    assert record["censoring_hard_gate_exceeded"] is True
    assert record["point_state"] == OVER_CENSORED


@pytest.mark.parametrize("rate", [0.33, 0.70, 0.81])
def test_the_first_sessions_saturated_points_now_prove_over_censored(rate):
    """33/70/81% are the measured censoring rates at 10/20/30 RPS."""
    record = _record(int(N * rate), ttft_ms=59_000.0)
    assert record["point_state"] == OVER_CENSORED
    assert record["ttft_p99_ms"] is None
    assert "censored" in record["point_state_reason"]


def test_no_observations_at_all_proves_over_censored_not_uncertain():
    """100% censoring is the strongest form of the proof, not an ambiguous
    case: every one of the top-1% order statistics is censored, so p99 is
    provably beyond the SLO regardless of what the (zero) survivors show."""
    raw, samples, offsets = _rows(N, N, 0.0)
    record = headline_point_metrics(raw, samples, _schedule_provenance(), warmup_n_s=0.0,
                                    scheduled_offsets=offsets)
    assert record["point_state"] == OVER_CENSORED
    assert record["ttft_p99_ms"] is None


def test_a_delivery_failure_with_zero_offered_requests_is_uncertain():
    """UNCERTAIN is still reachable -- just not via censoring rate. An empty
    offered window (e.g. every canonical request shed before send) has no
    censoring proof to make and no TTFT to read a verdict from."""
    record = headline_point_metrics([], [], _schedule_provenance(n=0), warmup_n_s=0.0,
                                    scheduled_offsets=[])
    assert record["over_censored_proven"] is False
    assert record["point_state"] == UNCERTAIN
    assert record["ttft_p99_ms"] is None


# ---------------------------------------------------------------------------
# The control: survivor-only p99 must be rejected.
# ---------------------------------------------------------------------------


def test_control_survivor_only_p99_is_refused_above_the_gate():
    """The exact shape of the first session's invalid points: plenty of
    surviving samples, all fast, with the slow ones timed out and gone."""
    n_censored = int(N * 0.33)
    raw, samples, offsets = _rows(N, n_censored, ttft_ms=120.0)
    record = headline_point_metrics(raw, samples, _schedule_provenance(), warmup_n_s=0.0,
                                    scheduled_offsets=offsets)

    survivors = [s for s in samples if s["ttft_ms"] is not None]
    assert len(survivors) > 100, (
        "this control needs MORE than 100 survivors, or it is not reproducing the failure -- "
        "the old rule passed these points precisely because the survivor count looked healthy")
    assert record["n_ttft_observed"] == len(survivors)
    assert record["point_state"] == OVER_CENSORED
    assert record["ttft_p99_ms"] is None, (
        "the survivors' p99 (120ms, comfortably UNDER) was suppressed. If it were published, a "
        "point that dropped a third of its requests would read as a clean pass")


def test_control_the_old_min_samples_rule_would_have_passed_it():
    """Shows the specific inadequacy, rather than asserting it in prose."""
    n_censored = int(N * 0.33)
    raw, samples, offsets = _rows(N, n_censored, ttft_ms=120.0)
    survivors = [s for s in samples if s["ttft_ms"] is not None]

    from metrics.point import MIN_TAIL_SAMPLES

    assert len(survivors) >= MIN_TAIL_SAMPLES, (
        "the old n>=100 gate would have blessed this point"
    )
    record = headline_point_metrics(raw, samples, _schedule_provenance(), warmup_n_s=0.0,
                                    scheduled_offsets=offsets)
    assert record["point_state"] == OVER_CENSORED, "the new gate must not"


# ---------------------------------------------------------------------------
# Review plumbing for boundary-determining points.
# ---------------------------------------------------------------------------


def test_a_completed_tail_review_is_recorded():
    review = {"status": "COMPLETE", "reviewer": "human",
              "finding": "excluding the censored requests moves p99 by 4ms; verdict unchanged"}
    # Must stay below OVER_CENSORED_MIN_N: a proven breach has no ambiguity
    # left for a human tail-sensitivity review to resolve.
    record = _record(OVER_CENSORED_MIN_N - 1, tail_censoring_review=review)
    assert record["over_censored_proven"] is False
    assert record["tail_censoring_review_status"] == "COMPLETE"
    assert record["tail_censoring_review"] == review


def test_error_categories_are_reported_separately_from_the_rate():
    """The rate decides whether a p99 may be published; the categories say
    whether the cause was the server or the client. A run that hit EMFILE is a
    finding about the instrument, not about saturation."""
    raw, samples, offsets = _rows(N, 9, 300.0, censored_error="ConnectError: refused")
    record = headline_point_metrics(raw, samples, _schedule_provenance(), warmup_n_s=0.0,
                                    scheduled_offsets=offsets)
    assert record["error_categories"] == {"ConnectError": 9}
    assert record["ttft_censoring_rate"] == pytest.approx(9 / N)


def test_timeout_and_error_counts_are_always_reported():
    for n_censored in (0, 3, 50):
        record = _record(n_censored)
        assert record["n_censored"] == n_censored
        assert record["n_issued_window"] == N
        assert "ttft_censoring_rate" in record

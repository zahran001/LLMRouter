"""Nominal λ vs materialized schedule vs actual sends (R4 README R7;
`WEEK2_PLAN.md` §10.4).

The first session flagged both its clean low-RPS points for driver
divergence. Neither had a driver problem. A finite Poisson schedule simply
does not contain `λ × duration` arrivals — the 2-RPS schedule materialized 248
over 130s and was scored −6.25% against the nominal rate.

So the controls here point in opposite directions, and both must hold:

  - finite-Poisson realization noise must NOT fail the driver;
  - actually dropping scheduled sends MUST fail it.

A gate that only satisfied the first would pass everything.
"""

from __future__ import annotations

import pytest

from metrics.headline_point import headline_point_metrics

pytestmark = pytest.mark.redesign


def _provenance(nominal_lambda, materialized_post, duration_s, warmup_s=0.0, target=None):
    return {
        "nominal_lambda_rps": nominal_lambda,
        "warmup_boundary_s": warmup_s,
        "materialized_schedule_count": materialized_post,
        "materialized_post_warmup_count": materialized_post,
        "post_warmup_target_count": target if target is not None else materialized_post,
        "materialized_schedule_duration_s": duration_s,
        "workload_class": "headline_controlled",
        "repeat_id": 1,
        "canonical_prompt_membership_id": "deadbeef",
        "arrival_seed": 1,
        "assignment_seed": 2,
    }


def _rows(n_sent: int, n_scheduled: int, duration_s: float):
    """`n_scheduled` scheduled arrivals of which only `n_sent` were issued.

    Returns `(raw, samples, scheduled_offsets)`. The offsets cover all
    `n_scheduled` arrivals -- including the ones never issued -- because they
    are the frozen schedule, and the measurement population is defined by the
    schedule rather than by what the driver managed to send.
    """
    step = duration_s / max(n_scheduled, 1)
    offsets = [i * step for i in range(n_scheduled)]
    raw, samples = [], []
    for i in range(n_sent):
        raw.append({"request_id": i, "send_time": i * step, "close_time": i * step + 0.1,
                    "prompt_id": i, "prompt_len": 100, "status": "sent"})
        samples.append({"request_id": i, "send_time": i * step, "ttft_ms": 120.0,
                        "tpot_samples_ms": [], "content_chunk_count": 3, "error": None})
    return raw, samples, offsets


# ---------------------------------------------------------------------------
# The three quantities are recorded separately.
# ---------------------------------------------------------------------------


def test_all_three_rps_quantities_are_persisted():
    prov = _provenance(2.0, 248, 130.0)
    raw, samples, offsets = _rows(248, 248, 130.0)
    record = headline_point_metrics(raw, samples, prov, warmup_n_s=0.0, scheduled_offsets=offsets)

    for field in ("nominal_lambda_rps", "materialized_schedule_count",
                  "materialized_schedule_duration_s", "materialized_schedule_rps",
                  "actual_sent_count", "actual_send_rps",
                  "schedule_delivery_divergence_pct", "nominal_realization_delta_pct"):
        assert field in record, f"R7 requires {field}"

    assert record["nominal_lambda_rps"] == 2.0
    assert record["materialized_schedule_rps"] == pytest.approx(248 / 130.0)
    assert record["actual_send_rps"] == pytest.approx(248 / 130.0)


def test_the_first_sessions_flagged_point_is_no_longer_a_driver_failure():
    """Reproduces the 2-RPS point's numbers exactly: 248 arrivals over 130s
    against a nominal 2.0, delivered in full."""
    prov = _provenance(2.0, 248, 130.0)
    raw, samples, offsets = _rows(248, 248, 130.0)
    record = headline_point_metrics(raw, samples, prov, warmup_n_s=0.0, scheduled_offsets=offsets)

    assert record["schedule_delivery_divergence_pct"] == 0.0
    assert record["schedule_delivery_ok"] is True, (
        "the driver issued every scheduled arrival; it must not be flagged")
    assert record["nominal_realization_delta_pct"] < 0, (
        "the schedule itself realized below nominal lambda -- recorded, but as metadata")
    assert record["nominal_realization_is_metadata"] is True


@pytest.mark.parametrize("materialized,duration", [(248, 130.0), (182, 130.0), (4048, 2651.5)])
def test_control_finite_poisson_variance_never_fails_the_driver(materialized, duration):
    nominal = 2.0
    prov = _provenance(nominal, materialized, duration)
    raw, samples, offsets = _rows(materialized, materialized, duration)
    record = headline_point_metrics(raw, samples, prov, warmup_n_s=0.0, scheduled_offsets=offsets)

    assert record["schedule_delivery_ok"] is True
    # ...even when the realization sits well away from nominal.
    assert abs(record["nominal_realization_delta_pct"]) >= 0.0


def test_control_dropped_sends_do_fail_the_driver():
    """The opposite control. If this passed, the gate would be inert."""
    prov = _provenance(2.0, 248, 130.0)
    raw, samples, offsets = _rows(200, 248, 130.0)  # 48 scheduled sends never issued
    record = headline_point_metrics(raw, samples, prov, warmup_n_s=0.0, scheduled_offsets=offsets)

    assert record["schedule_delivery_divergence_pct"] < -5.0
    assert record["schedule_delivery_ok"] is False, (
        "the driver dropped 48 of 248 scheduled sends and the fidelity gate did not fire")


def test_control_a_small_delivery_shortfall_stays_within_band():
    prov = _provenance(2.0, 1000, 500.0)
    raw, samples, offsets = _rows(980, 1000, 500.0)  # -2%
    record = headline_point_metrics(raw, samples, prov, warmup_n_s=0.0, scheduled_offsets=offsets)
    assert record["schedule_delivery_ok"] is True


def test_exact_n_mismatch_is_visible_in_the_record():
    """If materialization ever produced the wrong post-warmup count, the point
    record has to say so -- classification excludes such repeats."""
    prov = _provenance(2.0, 3999, 2000.0, target=4000)
    raw, samples, offsets = _rows(3999, 3999, 2000.0)
    record = headline_point_metrics(raw, samples, prov, warmup_n_s=0.0, scheduled_offsets=offsets)
    assert record["exact_n_honoured"] is False

    prov_ok = _provenance(2.0, 4000, 2000.0, target=4000)
    raw, samples, offsets = _rows(4000, 4000, 2000.0)
    assert headline_point_metrics(raw, samples, prov_ok, warmup_n_s=0.0, scheduled_offsets=offsets)["exact_n_honoured"] is True


def test_warmup_requests_are_excluded_from_the_window():
    prov = _provenance(2.0, 100, 60.0, warmup_s=10.0)
    step = 60.0 / 100
    offsets = [i * step for i in range(100)]
    raw = [{"request_id": i, "send_time": i * step, "close_time": i * step + 0.1,
            "prompt_id": i, "prompt_len": 100, "status": "sent"} for i in range(100)]
    samples = [{"request_id": i, "send_time": i * step, "ttft_ms": 120.0,
                "tpot_samples_ms": [], "content_chunk_count": 3, "error": None}
               for i in range(100)]
    record = headline_point_metrics(raw, samples, prov, warmup_n_s=10.0, scheduled_offsets=offsets)

    # This run has no scheduling lag, so scheduled-offset membership and
    # send-time filtering happen to agree. The tests that separate them live
    # in test_exact_n_membership.py.
    expected_in_window = sum(1 for i in range(100) if i * step >= 10.0)
    assert record["n_issued_window"] == expected_in_window
    assert record["percentile_population_n"] == expected_in_window
    assert record["warmup_boundary_s"] == 10.0


def test_control_a_warmup_filter_past_the_frozen_boundary_is_refused():
    """The subtle way exact-N dies.

    The per-point warmup value is still [CALIBRATE]. If session #2's transient
    turns out to last longer than the boundary the schedules were generated
    with, the tempting move is to re-filter the sidecars at the larger value --
    which is what §2.4 always allowed, because the old warmup filter was purely
    metrics-side. Under exact-N it is no longer harmless: the schedule
    materialized exactly N arrivals at or after ITS boundary, so filtering
    later discards some of them and the canonical multiset is no longer
    complete. The counts still look plausible, which is why this refuses.
    """
    prov = _provenance(2.0, 4000, 2030.0, warmup_s=30.0, target=4000)
    raw, samples, offsets = _rows(4000, 4000, 2030.0)

    with pytest.raises(ValueError, match="exceeds the schedule's frozen warmup boundary"):
        headline_point_metrics(raw, samples, prov, warmup_n_s=45.0, scheduled_offsets=offsets)

    # At or below the boundary it is fine -- the frozen N is intact.
    record = headline_point_metrics(raw, samples, prov, warmup_n_s=30.0, scheduled_offsets=offsets)
    assert record["warmup_n_s_applied"] == 30.0

"""The p99 population comes from the frozen schedule, not from the clock
(Phase B).

    measurement_member(request) := scheduled_offset >= warmup_boundary_s

The reader used to select the measured population by *actual send time*. That
is wrong in both directions at once, and both directions were observed rather
than imagined:

  - a warmup arrival scheduled at 59.9s but sent at 60.2s entered the
    percentile. Warmup requests are load; their TTFT is measured against a
    server that has just started taking traffic, so they are exactly the
    observations most likely to be extreme;
  - a canonical arrival scheduled at 60.1s but sent at 59.9s left it, silently
    shrinking N below the frozen count the whole redesign is built on.

Neither shows up in any count that a reader would check. The real committed
λ=16 scout schedule drove 510 sends at or after its boundary against a frozen
N of 500 — a 2% swing in the estimator population caused by nothing but client
lag on a Windows dev box.

So membership is a pure function of the committed artifact. Delivery timing is
still measured, and still able to invalidate a point; it just cannot decide
which requests the point is about.
"""

from __future__ import annotations

import pytest

from metrics.headline_point import headline_point_metrics, measurement_membership

pytestmark = pytest.mark.redesign

BOUNDARY = 60.0
N = 40
WARMUP_COUNT = 10

# Warmup TTFTs are absurd on purpose. If even one of them reaches the
# estimator the p99 moves by an amount no rounding could explain.
WARMUP_TTFT_MS = 9_000.0
CANONICAL_TTFT_MS = 100.0


def _provenance(warmup_s=BOUNDARY, n=N, duration=None):
    return {
        "nominal_lambda_rps": 2.0,
        "warmup_boundary_s": warmup_s,
        "materialized_schedule_count": n + WARMUP_COUNT,
        "materialized_post_warmup_count": n,
        "post_warmup_target_count": n,
        "materialized_schedule_duration_s": duration if duration is not None else warmup_s + 20.0,
        "workload_class": "headline_controlled",
        "repeat_id": 1,
        "canonical_prompt_membership_id": "deadbeef",
        "arrival_seed": 1,
        "assignment_seed": 2,
        "schedule_scheme_version": "headline-schedule-v2",
    }


def _late_warmup_fixture():
    """The scenario the plan specifies.

    10 requests scheduled just BEFORE the boundary, every one of them
    delivered AFTER it, all carrying extreme TTFT; then N canonical requests
    scheduled after the boundary with normal TTFT.
    """
    offsets, raw, samples = [], [], []

    for i in range(WARMUP_COUNT):
        # scheduled at 59.5 .. 59.95, sent at 60.5 .. 60.95 -- a full second late
        scheduled = BOUNDARY - 0.5 + i * 0.05
        sent = scheduled + 1.0
        offsets.append(scheduled)
        raw.append({"request_id": i, "send_time": sent, "close_time": sent + 1.0,
                    "prompt_id": i, "prompt_len": 100, "status": "sent"})
        samples.append({"request_id": i, "send_time": sent, "ttft_ms": WARMUP_TTFT_MS,
                        "tpot_samples_ms": [], "content_chunk_count": 3, "error": None})

    for j in range(N):
        request_id = WARMUP_COUNT + j
        scheduled = BOUNDARY + 0.5 + j * 0.5
        offsets.append(scheduled)
        raw.append({"request_id": request_id, "send_time": scheduled,
                    "close_time": scheduled + 1.0, "prompt_id": request_id,
                    "prompt_len": 100, "status": "sent"})
        samples.append({"request_id": request_id, "send_time": scheduled,
                        "ttft_ms": CANONICAL_TTFT_MS + j,
                        "tpot_samples_ms": [], "content_chunk_count": 3, "error": None})

    return offsets, raw, samples


# ---------------------------------------------------------------------------
# The membership function itself.
# ---------------------------------------------------------------------------


def test_membership_is_decided_by_scheduled_offset():
    offsets = [59.0, 59.9, 60.0, 60.1, 61.0]
    assert measurement_membership(offsets, 60.0) == {2, 3, 4}, (
        "the boundary is inclusive: an arrival scheduled exactly at it is canonical")


def test_membership_ignores_everything_except_the_schedule():
    """Same schedule, twice, with nothing else supplied. If this could vary,
    the population would not be a property of the committed artifact."""
    offsets, _raw, _samples = _late_warmup_fixture()
    assert measurement_membership(offsets, BOUNDARY) == measurement_membership(offsets, BOUNDARY)
    assert len(measurement_membership(offsets, BOUNDARY)) == N


# ---------------------------------------------------------------------------
# Late warmup sends: the plan's primary scenario.
# ---------------------------------------------------------------------------


def test_late_warmup_sends_never_enter_the_percentile_population():
    offsets, raw, samples = _late_warmup_fixture()
    record = headline_point_metrics(raw, samples, _provenance(), warmup_n_s=BOUNDARY,
                                    scheduled_offsets=offsets)

    # Wall-clock sends after the boundary exceed N -- all 50 landed late.
    assert record["sends_after_boundary_wallclock"] == N + WARMUP_COUNT
    assert record["sends_after_boundary_wallclock"] > N

    # ...and the population is still exactly N.
    assert record["expected_measurement_n"] == N
    assert record["percentile_population_n"] == N
    assert record["reconciled_measurement_n"] == N
    assert record["n_issued_window"] == N
    assert record["measurement_membership_basis"] == "scheduled_offset"


def test_late_warmup_sends_do_not_move_the_p99():
    offsets, raw, samples = _late_warmup_fixture()
    record = headline_point_metrics(raw, samples, _provenance(), warmup_n_s=BOUNDARY,
                                    scheduled_offsets=offsets)

    canonical = [CANONICAL_TTFT_MS + j for j in range(N)]
    assert record["ttft_p99_ms"] == max(canonical), (
        "nearest-rank p99 over 40 samples is the largest; a 9000ms warmup leaking in "
        "would show here immediately")
    assert record["ttft_p99_ms"] < WARMUP_TTFT_MS
    assert record["ttft_mean_ms"] == pytest.approx(sum(canonical) / len(canonical))


def test_control_send_time_filtering_would_have_corrupted_this_point():
    """The bug, reproduced against the same fixture.

    Without this the test above only proves the current code is
    self-consistent -- it would pass just as happily if the fixture could
    never have triggered the defect.
    """
    from metrics.headline_point import post_warmup

    _offsets, _raw, samples = _late_warmup_fixture()
    by_send_time = post_warmup(samples, BOUNDARY)

    assert len(by_send_time) == N + WARMUP_COUNT, "the old rule swept up the late warmup sends"
    ttfts = [r["ttft_ms"] for r in by_send_time]
    assert max(ttfts) == WARMUP_TTFT_MS, (
        "under send-time filtering the 9000ms warmup observations are in the estimator")


def test_the_lag_is_still_visible_as_a_diagnostic():
    """Membership stopped depending on delivery timing. Delivery timing did
    not stop being measured."""
    offsets, raw, samples = _late_warmup_fixture()
    record = headline_point_metrics(raw, samples, _provenance(), warmup_n_s=BOUNDARY,
                                    scheduled_offsets=offsets)

    assert record["late_warmup_sends"] == WARMUP_COUNT
    assert record["early_measurement_sends"] == 0
    assert record["max_send_lag_s"] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# The reverse control: a late canonical request.
# ---------------------------------------------------------------------------


def test_a_late_canonical_request_stays_in_the_population():
    """It is delivered badly, not delivered elsewhere. Dropping it would
    shrink N, which is the failure exact-N exists to prevent."""
    offsets, raw, samples = _late_warmup_fixture()
    victim = WARMUP_COUNT  # the first canonical request
    raw[victim]["send_time"] = BOUNDARY + 300.0
    samples[victim]["send_time"] = BOUNDARY + 300.0

    record = headline_point_metrics(raw, samples, _provenance(), warmup_n_s=BOUNDARY,
                                    scheduled_offsets=offsets)

    assert record["percentile_population_n"] == N
    assert record["reconciled_measurement_n"] == N
    assert record["n_ttft_observed"] == N, "the late request is still measured, not discarded"
    assert record["max_send_lag_s"] > 290.0, "and its lag is on the record"


def test_control_an_undelivered_canonical_request_fails_the_gate_rather_than_shrinking_n():
    """The other half of the invariant. If delivery becomes unacceptable the
    POINT is invalidated; N is never quietly reduced to match what arrived."""
    offsets, raw, samples = _late_warmup_fixture()
    # Drop 4 of the 40 canonical sends entirely: 10% short, past the 5% band.
    dropped = {WARMUP_COUNT + j for j in range(4)}
    raw = [r for r in raw if r["request_id"] not in dropped]
    samples = [s for s in samples if s["request_id"] not in dropped]

    record = headline_point_metrics(raw, samples, _provenance(), warmup_n_s=BOUNDARY,
                                    scheduled_offsets=offsets)

    assert record["expected_measurement_n"] == N, "the frozen population does not move"
    assert record["percentile_population_n"] == N
    assert record["reconciled_measurement_n"] == N - 4
    assert record["schedule_delivery_divergence_pct"] == pytest.approx(-10.0)
    assert record["schedule_delivery_ok"] is False, (
        "a point that never delivered 10% of its canonical arrivals must be invalid, not "
        "silently measured over the 36 that arrived")


def test_a_shortfall_inside_the_band_stays_valid():
    """The paired positive: the gate must not fire on ordinary noise."""
    offsets, raw, samples = _late_warmup_fixture()
    dropped = {WARMUP_COUNT}  # 1 of 40 = -2.5%
    raw = [r for r in raw if r["request_id"] not in dropped]
    samples = [s for s in samples if s["request_id"] not in dropped]

    record = headline_point_metrics(raw, samples, _provenance(), warmup_n_s=BOUNDARY,
                                    scheduled_offsets=offsets)
    assert record["schedule_delivery_divergence_pct"] == pytest.approx(-2.5)
    assert record["schedule_delivery_ok"] is True
    assert record["percentile_population_n"] == N


# ---------------------------------------------------------------------------
# Shed canonical requests are censored, not invisible.
# ---------------------------------------------------------------------------


def test_control_shed_canonical_requests_count_as_censored():
    """The subtle version of the same failure membership-by-send-time was.

    A shed canonical request produced no TTFT, so it is a censored
    observation. Excluding it from the denominator instead SUBTRACTS it: a
    point that shed 4% of its canonical arrivals reported 0.0% censoring while
    4% of the population was simply absent from the p99 -- and shed requests
    cluster at the highest-concurrency instants, which is exactly the tail.
    Below the ±5% delivery band nothing else would have caught it.
    """
    offsets, raw, samples = _late_warmup_fixture()
    shed_ids = {WARMUP_COUNT + j for j in range(2)}  # 2 of 40 = 5% of the population
    for row in raw:
        if row["request_id"] in shed_ids:
            row["status"] = "shed"
            row["send_time"] = None
    samples = [s for s in samples if s["request_id"] not in shed_ids]

    record = headline_point_metrics(raw, samples, _provenance(), warmup_n_s=BOUNDARY,
                                    scheduled_offsets=offsets)

    assert record["n_shed_in_window"] == 2
    assert record["n_offered_window"] == N, "shed requests were still offered"
    assert record["n_ttft_observed"] == N - 2
    assert record["n_censored"] == 2
    assert record["ttft_censoring_rate"] == pytest.approx(2 / N)
    assert record["percentile_population_n"] == N, "the frozen population never shrinks"


def test_control_duplicate_sidecar_rows_cannot_inflate_the_estimator():
    """`SampleLogger` should make this impossible, but if it happened the
    duplicate TTFT would enter the percentile and push the observed count past
    the offered count, where the `max(..., 0)` clamp would hide the
    inconsistency."""
    offsets, raw, samples = _late_warmup_fixture()
    samples.append(dict(samples[WARMUP_COUNT]))

    record = headline_point_metrics(raw, samples, _provenance(), warmup_n_s=BOUNDARY,
                                    scheduled_offsets=offsets)
    assert record["n_duplicate_sample_rows"] == 1
    assert record["n_ttft_observed"] == N
    assert record["n_censored"] == 0


def test_control_a_warmup_value_below_the_frozen_boundary_is_refused():
    """Since membership became schedule-based, a smaller `warmup_n_s` selects
    nothing -- but the record would still report it as applied, which reads to
    an operator as what happened."""
    offsets, raw, samples = _late_warmup_fixture()
    with pytest.raises(ValueError, match="below the schedule's frozen warmup boundary"):
        headline_point_metrics(raw, samples, _provenance(), warmup_n_s=30.0,
                               scheduled_offsets=offsets)


def test_an_exhausted_iterator_cannot_silently_blank_the_diagnostics():
    """Passing a generator once emptied `offsets_by_id`, blanking the lag
    fields with no error -- delivery evidence disappearing quietly."""
    offsets, raw, samples = _late_warmup_fixture()
    record = headline_point_metrics(raw, samples, _provenance(), warmup_n_s=BOUNDARY,
                                    scheduled_offsets=(o for o in offsets))
    assert record["percentile_population_n"] == N
    assert record["max_send_lag_s"] is not None


# ---------------------------------------------------------------------------
# The frozen families produce exactly the populations the plan names.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family,expected_n", [("scout", 500), ("headline", 4000)])
def test_the_committed_schedules_yield_their_frozen_population(family, expected_n):
    """Computed from the committed artifacts, not asserted about them: the
    membership rule is applied to every frozen schedule and must return
    exactly the N its provenance claims."""
    import json
    from pathlib import Path

    root = (Path(__file__).resolve().parents[2] / "benchmarks" / "schedules"
            / "week2_redesign" / family)
    schedules = sorted(root.glob("*.schedule.json"))
    assert schedules, f"no committed schedules under {root}"

    for path in schedules:
        data = json.loads(path.read_text(encoding="utf-8"))
        prov = data["provenance"]
        offsets = [e["scheduled_offset"] for e in data["entries"]]
        members = measurement_membership(offsets, prov["warmup_boundary_s"])
        # Threshold-gated schedules (attempt-2 low-lambda points,
        # schedule_generation_rule="min_duration_and_count") realize whatever
        # count the duration+count rule produced, not a fixed N shared by the
        # whole family -- only exact-N schedules are checked against the
        # parametrized `expected_n`. Every schedule, regardless of rule, must
        # still match its OWN declared target.
        if prov.get("schedule_generation_rule") == "min_duration_and_count":
            assert len(members) == prov["post_warmup_target_min_count"] \
                or prov["materialized_post_warmup_duration_s"] >= prov["post_warmup_target_min_duration_s"], \
                f"{path.name}: {len(members)} members satisfies neither threshold"
        else:
            assert len(members) == expected_n, \
                f"{path.name}: {len(members)} members, want {expected_n}"
        assert len(members) == prov["post_warmup_target_count"]
        assert len(members) == prov["materialized_post_warmup_count"]

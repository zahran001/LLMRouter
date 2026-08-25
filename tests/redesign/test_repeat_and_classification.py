"""Repeat orchestration and repeat-level classification
(R4 README R9/R10; `WEEK2_PLAN.md` §10.3/§10.6).

Two guards that both protect the same thing — that "three independent
repeats agreed" means what it says:

R9  repeats must be separated by a VERIFIED drain. If repeat B starts while
    A still has open streams, B queues behind A's tail and the two are not
    independent — while every artifact still looks clean, because nothing in
    a raw log records how busy the server was when the run began.

R10 the verdict comes from those repeats, and must not be manufactured by
    pooling a censored repeat with valid ones, by finalizing a boundary point
    whose sub-5% censoring was never reviewed, or by escalating past the
    authorized evidence ceiling to avoid reporting an interval.
"""

from __future__ import annotations

import pytest

from loadgen.repeat_runner import (
    DrainTimeoutError,
    RepeatOverlapError,
    RepeatPlan,
    RepeatRunner,
    wait_until_drained,
)
from metrics.classification import (
    HeadlineEvidenceSpec,
    RepeatPolicy,
    classify_point,
    resolve_breach,
)
from metrics.headline_point import CENSORED, OVER, OVER_CENSORED, UNCERTAIN, UNDER

pytestmark = pytest.mark.redesign

MEMBERSHIP = "a49ecdd8071920303f240fcf0b8da42dbbc66da593ae88e3c07aa246c4b5aa7b"
N_PER_RUN = 4000


def _repeat(repeat_id: int, nominal_lambda: float, state: str, p99: float | None,
            censoring: float = 0.0, review: str | None = None,
            delivery_ok: bool = True, exact_n: bool = True,
            population: int = N_PER_RUN) -> dict:
    """A record that has PROVEN it is session #2 headline evidence.

    The identity fields are not decoration: `classify_point` fails closed, so
    a record missing any of them is refused before its state is even read.
    The controls for that live in test_headline_evidence_gate.py; here they
    are simply satisfied so the aggregation logic can be tested.
    """
    return {
        "record_version": "headline-point-v1",
        "evidence_class": "headline_evidence",
        "may_define_headline_breach": True,
        "schedule_scheme_version": "headline-schedule-v2",
        "process_epoch": "vllm-start-1000",
        "percentile_population_n": population,
        "repeat_id": repeat_id,
        "canonical_prompt_membership_id": MEMBERSHIP,
        "arrival_seed": 1000 + repeat_id,
        "assignment_seed": 2000 + repeat_id,
        "nominal_lambda_rps": nominal_lambda,
        "point_state": state,
        "point_state_reason": f"synthetic {state}",
        "ttft_p99_ms": p99,
        "n_ttft_observed": 4000,
        "ttft_censoring_rate": censoring,
        "tail_censoring_warning": censoring > 0.0,
        "tail_censoring_review_status": review,
        "schedule_delivery_ok": delivery_ok,
        "exact_n_honoured": exact_n,
    }


# ===========================================================================
# R9 -- the drain boundary
# ===========================================================================


class FakeInflight:
    """A probe that reports a scripted sequence of in-flight counts."""

    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.calls = 0

    def __call__(self) -> int:
        self.calls += 1
        return self.sequence[min(self.calls - 1, len(self.sequence) - 1)]


def test_drain_gate_returns_once_in_flight_reaches_zero():
    probe = FakeInflight([12, 5, 1, 0])
    result = wait_until_drained(probe, timeout_s=10.0, sleep=lambda _s: None,
                                clock=_counter())
    assert result["drained"] is True
    assert result["peak_in_flight_observed"] == 12
    assert probe.calls == 4


def test_control_drain_gate_times_out_rather_than_proceeding():
    """A stuck stream must stop the family, not be waited out silently."""
    probe = FakeInflight([3])  # never drains
    with pytest.raises(DrainTimeoutError, match="still in flight"):
        wait_until_drained(probe, timeout_s=5.0, sleep=lambda _s: None, clock=_counter())


def _counter():
    """Monotonic fake clock: one second per call, so timeouts are reached
    without spending wall time."""
    state = {"t": 0.0}

    def clock() -> float:
        state["t"] += 1.0
        return state["t"]

    return clock


def test_control_the_runner_refuses_to_start_a_repeat_with_requests_in_flight():
    plans = [RepeatPlan(1, 101, 201, [2.0]), RepeatPlan(2, 102, 202, [2.0])]
    runner = RepeatRunner(run_point=lambda plan, lam: {"repeat_id": plan.repeat_id},
                          inflight_probe=lambda: 7,
                          sleep=lambda _s: None, clock=_counter())

    with pytest.raises(RepeatOverlapError, match="still in flight"):
        runner.run(plans)


def test_a_cleanly_drained_family_runs_every_point():
    plans = [RepeatPlan(1, 101, 201, [1.5, 2.0]), RepeatPlan(2, 102, 202, [1.5, 2.0])]
    driven = []

    def run_point(plan, nominal_lambda):
        driven.append((plan.repeat_id, nominal_lambda))
        return {"repeat_id": plan.repeat_id, "nominal_lambda_rps": nominal_lambda,
                "process_epoch": "vllm-start-1000"}

    runner = RepeatRunner(run_point=run_point, inflight_probe=lambda: 0,
                          sleep=lambda _s: None, clock=_counter())
    report = runner.run(plans)

    assert driven == [(1, 1.5), (1, 2.0), (2, 1.5), (2, 2.0)]
    assert len(report.points) == 4
    assert report.to_dict()["vllm_restarted_between_repeats"] is False
    assert report.to_dict()["process_epochs_observed"] == ["vllm-start-1000"]


def test_control_a_restart_between_repeats_is_reported_not_asserted_away():
    """`vllm_restarted_between_repeats` was a hardcoded `False` -- the same
    inert-check shape the drain probe exists to avoid, sitting on the one
    claim lock 3A depends on. It is now computed from what the points
    recorded."""
    epochs = iter(["vllm-start-1000", "vllm-start-2000"])

    def run_point(plan, nominal_lambda):
        return {"repeat_id": plan.repeat_id, "nominal_lambda_rps": nominal_lambda,
                "process_epoch": next(epochs)}

    runner = RepeatRunner(run_point=run_point, inflight_probe=lambda: 0,
                          sleep=lambda _s: None, clock=_counter())
    report = runner.run([RepeatPlan(1, 101, 201, [2.0]), RepeatPlan(2, 102, 202, [2.0])])
    assert report.to_dict()["vllm_restarted_between_repeats"] is True
    assert len(report.to_dict()["process_epochs_observed"]) == 2


def test_an_unrecorded_epoch_reports_unknown_rather_than_no_restart():
    """Absence of evidence is not evidence of absence -- especially for the
    claim a spot preemption is most likely to falsify."""
    runner = RepeatRunner(run_point=lambda p, l: {"repeat_id": p.repeat_id},
                          inflight_probe=lambda: 0, sleep=lambda _s: None, clock=_counter())
    report = runner.run([RepeatPlan(1, 101, 201, [2.0])])
    assert report.to_dict()["vllm_restarted_between_repeats"] is None


def test_control_the_runner_refuses_duplicate_repeat_ids():
    runner = RepeatRunner(run_point=lambda p, l: {}, inflight_probe=lambda: 0,
                          sleep=lambda _s: None, clock=_counter())
    with pytest.raises(ValueError, match="duplicate repeat_id"):
        runner.run([RepeatPlan(1, 1, 1, [2.0]), RepeatPlan(1, 2, 2, [2.0])])


def test_drain_is_enforced_between_lambda_points_too():
    """Within a repeat, a point that starts on the previous point's tail is
    measuring the wrong queue."""
    inflight = {"value": 0}

    def run_point(plan, nominal_lambda):
        inflight["value"] = 3  # leave streams open
        return {"repeat_id": plan.repeat_id}

    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        if inflight["value"] and calls["n"] % 2 == 0:
            inflight["value"] = 0
        return inflight["value"]

    runner = RepeatRunner(run_point=run_point, inflight_probe=probe,
                          sleep=lambda _s: None, clock=_counter())
    report = runner.run([RepeatPlan(1, 101, 201, [1.5, 2.0])])
    assert any(e.get("drained") for e in report.drain_events)


# ===========================================================================
# R10 -- classification
# ===========================================================================

POLICY = RepeatPolicy(min_valid_repeats=3, require_unanimous=True,
                      n_per_run=N_PER_RUN, n_max=5000, max_repeats_authorized=3,
                      headline=HeadlineEvidenceSpec(membership_id=MEMBERSHIP,
                                                    percentile_population_n=N_PER_RUN))


def test_unanimous_repeats_produce_a_verdict():
    records = [_repeat(i, 2.0, UNDER, 300.0 + i) for i in (1, 2, 3)]
    aggregate = classify_point(records, POLICY)
    assert aggregate.state == UNDER
    assert len(aggregate.valid_repeats) == 3
    assert aggregate.ttft_p99_spread_ms == pytest.approx(2.0)


def test_control_disagreeing_repeats_are_uncertain_not_averaged():
    """Two UNDER and one OVER must not average into UNDER. Averaging across
    repeats is how a coin-flip becomes a result."""
    records = [_repeat(1, 2.0, UNDER, 480.0), _repeat(2, 2.0, UNDER, 470.0),
               _repeat(3, 2.0, OVER, 540.0)]
    aggregate = classify_point(records, POLICY)
    assert aggregate.state == UNCERTAIN
    assert "disagree" in aggregate.reason
    assert len(aggregate.valid_repeats) == 3, "all three are still preserved as evidence"


def test_over_censored_agrees_with_over_not_a_split():
    """Attempt-2 (locked 2026-08-22): OVER (computed p99) and OVER_CENSORED
    (proven via censoring) both mean breach confirmed. A family mixing them
    must agree on OVER, not read as a 2-1 disagreement."""
    records = [_repeat(1, 2.0, OVER, 540.0),
               _repeat(2, 2.0, OVER_CENSORED, None, censoring=0.36),
               _repeat(3, 2.0, OVER_CENSORED, None, censoring=0.37)]
    aggregate = classify_point(records, POLICY)
    assert aggregate.state == OVER
    assert len(aggregate.valid_repeats) == 3, (
        "OVER_CENSORED is a proven breach, not an excluded/ambiguous repeat")
    assert "agree" in aggregate.reason


def test_unanimous_over_censored_agrees_on_over():
    records = [_repeat(i, 1.5, OVER_CENSORED, None, censoring=0.3 + 0.01 * i) for i in (1, 2, 3)]
    aggregate = classify_point(records, POLICY)
    assert aggregate.state == OVER
    assert len(aggregate.valid_repeats) == 3


def test_control_under_and_over_censored_is_still_a_real_split():
    """The equivalence is ONLY between OVER and OVER_CENSORED -- UNDER
    disagreeing with a proven breach must still read as UNCERTAIN."""
    records = [_repeat(1, 2.0, UNDER, 470.0),
               _repeat(2, 2.0, OVER_CENSORED, None, censoring=0.36),
               _repeat(3, 2.0, OVER_CENSORED, None, censoring=0.37)]
    aggregate = classify_point(records, POLICY)
    assert aggregate.state == UNCERTAIN
    assert "disagree" in aggregate.reason


def test_control_a_censored_repeat_is_never_pooled_with_valid_ones():
    records = [_repeat(1, 2.0, UNDER, 300.0), _repeat(2, 2.0, UNDER, 305.0),
               _repeat(3, 2.0, CENSORED, None, censoring=0.4)]
    aggregate = classify_point(records, POLICY)
    assert aggregate.state == UNCERTAIN, (
        "two valid repeats plus one censored one is two repeats of evidence, not three")
    assert len(aggregate.valid_repeats) == 2
    assert len(aggregate.excluded_repeats) == 1


def test_control_a_repeat_that_missed_exact_n_is_excluded():
    records = [_repeat(1, 2.0, UNDER, 300.0), _repeat(2, 2.0, UNDER, 305.0),
               _repeat(3, 2.0, UNDER, 310.0, exact_n=False)]
    aggregate = classify_point(records, POLICY)
    assert aggregate.state == UNCERTAIN
    assert len(aggregate.excluded_repeats) == 1


def test_control_a_repeat_with_a_delivery_failure_is_excluded():
    records = [_repeat(1, 2.0, UNDER, 300.0), _repeat(2, 2.0, UNDER, 305.0),
               _repeat(3, 2.0, UNDER, 310.0, delivery_ok=False)]
    assert classify_point(records, POLICY).state == UNCERTAIN


def test_control_reused_seeds_are_refused_as_repeats():
    """Prompt permutation alone is not a repeat, and neither is re-running one
    seed twice."""
    same_arrival = [_repeat(1, 2.0, UNDER, 300.0), _repeat(2, 2.0, UNDER, 305.0)]
    same_arrival[1]["arrival_seed"] = same_arrival[0]["arrival_seed"]
    with pytest.raises(ValueError, match="share arrival seeds"):
        classify_point(same_arrival, POLICY)

    same_assignment = [_repeat(1, 2.0, UNDER, 300.0), _repeat(2, 2.0, UNDER, 305.0)]
    same_assignment[1]["assignment_seed"] = same_assignment[0]["assignment_seed"]
    with pytest.raises(ValueError, match="share assignment seeds"):
        classify_point(same_assignment, POLICY)


def test_control_repeats_with_different_membership_are_refused():
    """Caught one step earlier than it used to be.

    This previously failed because the two repeats disagreed with each other.
    Now it fails because the odd one out disagrees with the *policy's* headline
    membership — which is strictly stronger: a family where every repeat shares
    the same wrong membership was consistent with itself and would have passed
    the old check.
    """
    records = [_repeat(1, 2.0, UNDER, 300.0), _repeat(2, 2.0, UNDER, 305.0)]
    records[1]["canonical_prompt_membership_id"] = "different"
    with pytest.raises(ValueError, match="not the headline workload"):
        classify_point(records, POLICY)


def test_control_a_uniformly_wrong_membership_is_also_refused():
    """The case the old pairwise check could not see."""
    records = [_repeat(i, 2.0, UNDER, 300.0) for i in (1, 2, 3)]
    for record in records:
        record["canonical_prompt_membership_id"] = "e9470f8f" * 8  # the scout workload
    with pytest.raises(ValueError, match="not the headline workload"):
        classify_point(records, POLICY)


def test_control_duplicate_repeat_ids_are_refused():
    records = [_repeat(1, 2.0, UNDER, 300.0), _repeat(1, 2.0, UNDER, 305.0)]
    with pytest.raises(ValueError, match="duplicate repeat_ids"):
        classify_point(records, POLICY)


def test_boundary_point_with_unreviewed_censoring_cannot_finalize():
    records = [_repeat(i, 2.0, OVER, 540.0, censoring=0.02) for i in (1, 2, 3)]
    assert classify_point(records, POLICY, boundary_determining=False).state == OVER
    assert classify_point(records, POLICY, boundary_determining=True).state == UNCERTAIN, (
        "a point that could decide the crossing must not finalize on un-reviewed censoring")


def test_a_completed_review_lets_a_boundary_point_finalize():
    records = [_repeat(i, 2.0, OVER, 540.0, censoring=0.02, review="COMPLETE")
               for i in (1, 2, 3)]
    assert classify_point(records, POLICY, boundary_determining=True).state == OVER


# ---------------------------------------------------------------------------
# Sweep-level resolution.
# ---------------------------------------------------------------------------


def _sweep(states: dict[float, str], **kw) -> dict:
    return {
        lam: [_repeat(i, lam, state, 300.0 if state == UNDER else 600.0, **kw)
              for i in (1, 2, 3)]
        for lam, state in states.items()
    }


def test_a_clean_sweep_reports_a_bracketed_interval():
    result = resolve_breach(_sweep({1.5: UNDER, 2.0: UNDER, 2.5: OVER, 3.0: OVER}), POLICY)
    assert result["resolution"] == "BRACKETED"
    assert result["breach_interval"]["lower_exclusive"] == 2.0
    assert result["breach_interval"]["upper_inclusive"] == 2.5


def test_an_unresolved_point_inside_the_bracket_at_the_ceiling_reports_an_interval():
    records = _sweep({1.5: UNDER, 2.5: OVER})
    records[2.0] = [_repeat(1, 2.0, UNDER, 480.0), _repeat(2, 2.0, OVER, 520.0),
                    _repeat(3, 2.0, UNDER, 495.0)]
    result = resolve_breach(records, POLICY, n_used=5000, repeats_used=3)

    assert result["resolution"] == "INTERVAL_AT_EVIDENCE_CEILING"
    assert result["breach_interval"]["notation"] == "(1.5, 2.5]"
    assert 2.0 in result["breach_interval"]["unresolved_points_inside"]
    assert "forbidden" in result["message"]


def test_below_the_ceiling_escalation_is_permitted_rather_than_forced():
    records = _sweep({1.5: UNDER, 2.5: OVER})
    records[2.0] = [_repeat(1, 2.0, UNDER, 480.0), _repeat(2, 2.0, OVER, 520.0),
                    _repeat(3, 2.0, UNDER, 495.0)]
    policy = RepeatPolicy(min_valid_repeats=3, n_per_run=N_PER_RUN, n_max=5000,
                          max_repeats_authorized=5,
                          headline=HeadlineEvidenceSpec(
                              membership_id=MEMBERSHIP, percentile_population_n=N_PER_RUN))
    result = resolve_breach(records, policy, n_used=4000, repeats_used=3)

    assert result["resolution"] == "MORE_EVIDENCE_AUTHORIZED"
    assert "pre-authorized evidence plan" in result["message"]


def test_control_no_over_point_is_reported_as_such_not_as_a_breach():
    result = resolve_breach(_sweep({1.5: UNDER, 2.0: UNDER}), POLICY)
    assert result["resolution"] == "NO_BREACH_OBSERVED"
    assert result["breach_interval"] is None


def test_control_no_under_anchor_is_reported_as_such():
    result = resolve_breach(_sweep({1.5: OVER, 2.0: OVER}), POLICY)
    assert result["resolution"] == "NO_UNDER_ANCHOR"
    assert result["breach_interval"] is None


def test_control_a_non_monotone_sweep_is_refused_as_a_crossing():
    result = resolve_breach(_sweep({1.5: OVER, 2.0: UNDER, 2.5: UNDER}), POLICY)
    assert result["resolution"] == "NO_VALID_BRACKET"
    assert result["breach_interval"] is None


def test_per_repeat_evidence_survives_aggregation():
    result = resolve_breach(_sweep({1.5: UNDER, 2.5: OVER}), POLICY)
    point = result["points"]["1.5"]
    assert len(point["per_repeat"]) == 3
    for repeat in point["per_repeat"]:
        assert repeat["ttft_p99_ms"] is not None
        assert repeat["arrival_seed"] is not None, (
            "per-repeat provenance must remain readable from the aggregate; an aggregate that "
            "hides its inputs cannot be audited")


def test_the_evidence_ceiling_is_the_policys_to_state():
    policy = RepeatPolicy(n_max=5000, max_repeats_authorized=3)
    assert policy.evidence_ceiling_reached(n_used=5000, repeats_used=1) is True
    assert policy.evidence_ceiling_reached(n_used=4000, repeats_used=3) is True
    assert policy.evidence_ceiling_reached(n_used=4000, repeats_used=2) is False


# ===========================================================================
# D-ATTEMPT2-2 -- threshold lambdas classify on a population FLOOR
#
# Found live, offline, from GPU session #2 attempt 2's real Tier B data:
# repeat_policy.json was updated for the diagnostic sustained-scout tier's
# threshold parameters (D-ATTEMPT2-1) but never for the fact that the real
# HEADLINE family at lambda<=1.25 also switched from a fixed N=4000 to the
# same min(45min, 2000) threshold rule. Each repeat is an independently-
# seeded draw, so its realized count legitimately varies -- the real
# lambda=0.75 family this session drove realized 2069/2078/2065 across its
# three repeats, all frozen into the committed schedule files themselves.
# Before this fix, `classify_point` refused repeat 2 outright:
#   percentile_population_n=2078, expected 2069
# which would have made every threshold-lambda headline family
# unclassifiable, including the one this session actually produced.
# ===========================================================================

THRESHOLD_POLICY = RepeatPolicy(
    min_valid_repeats=3, require_unanimous=True, n_per_run=N_PER_RUN, n_max=5000,
    max_repeats_authorized=3,
    headline=HeadlineEvidenceSpec(membership_id=MEMBERSHIP, percentile_population_n=N_PER_RUN,
                                  threshold_lambdas=(0.5, 0.75, 1.0, 1.25),
                                  threshold_min_count=2000))


def test_a_threshold_lambda_accepts_naturally_varying_population_across_repeats():
    records = [_repeat(1, 0.75, OVER, 589.2, population=2069),
              _repeat(2, 0.75, OVER, 559.0, population=2078),
              _repeat(3, 0.75, OVER_CENSORED, None, censoring=0.025, population=2065)]
    aggregate = classify_point(records, THRESHOLD_POLICY)
    assert aggregate.state == OVER
    assert len(aggregate.valid_repeats) == 3


def test_a_threshold_lambda_still_refuses_a_population_below_the_floor():
    """The floor is not a no-op: something that looks like a scout point
    (N=500) smuggled in under a threshold lambda must still be caught."""
    from metrics.classification import NotHeadlineEvidence

    records = [_repeat(1, 0.75, UNDER, 400.0, population=2069),
              _repeat(2, 0.75, UNDER, 410.0, population=500)]
    with pytest.raises(NotHeadlineEvidence, match="expected >= 2000"):
        classify_point(records, THRESHOLD_POLICY)


def test_an_exact_n_lambda_still_requires_an_exact_population_match():
    """The control: fixing the threshold case must not loosen the legacy
    exact-N=4000 family's protection. lambda=2.0 is not in threshold_lambdas,
    so a record with more than N_PER_RUN samples is still refused outright,
    not merely accepted because it clears a floor."""
    from metrics.classification import NotHeadlineEvidence

    records = [_repeat(1, 2.0, UNDER, 400.0, population=N_PER_RUN),
              _repeat(2, 2.0, UNDER, 410.0, population=N_PER_RUN + 1)]
    with pytest.raises(NotHeadlineEvidence, match=r"percentile_population_n=4001, expected 4000"):
        classify_point(records, THRESHOLD_POLICY)


def test_from_frozen_reads_the_headline_threshold_block():
    """Pins the parse: `HeadlineEvidenceSpec.from_frozen()` must read the new
    `headline_threshold` block from the real committed repeat_policy.json,
    not just from a hand-built spec in this file."""
    policy = RepeatPolicy.from_frozen()
    spec = policy.headline
    assert spec.threshold_lambdas == (0.5, 0.75, 1.0, 1.25)
    assert spec.threshold_min_count == 2000
    assert spec.percentile_population_n == 4000


@pytest.mark.integration
def test_the_real_session_2_attempt_2_lambda_0_75_family_classifies():
    """The actual regression: GPU session #2 attempt 2's real pulled Tier B
    records for lambda=0.75, driven straight through `RepeatPolicy.from_frozen()`
    with no synthetic data. This is what failed live before the fix."""
    import json
    from pathlib import Path

    run_dir = Path(__file__).resolve().parents[2] / "benchmarks" / "runs" / "headline"
    paths = [run_dir / f"headline_r{r}_rps0.75.metrics.json" for r in (1, 2, 3)]
    if not all(p.exists() for p in paths):
        pytest.skip("session #2 attempt 2 artifacts not present in this checkout")

    records = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    populations = {r["percentile_population_n"] for r in records}
    assert len(populations) > 1, (
        "this fixture is only meaningful while the real repeats still have varying "
        "population -- if they ever come back identical, this no longer proves the floor "
        "logic (rather than exact-match) is what's doing the work")

    policy = RepeatPolicy.from_frozen()
    aggregate = classify_point(records, policy)
    assert aggregate.state == OVER

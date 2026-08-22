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
That gate is superseded and `n >= 100` is no longer sufficient for anything:
`tail_valid` meant "enough survivors", which is the wrong question, because
the requests that vanished were precisely the slow ones the tail is made of.

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

# --- evidence class: who is allowed to define the breach ---------------------
#
# Scout and headline points are measured by this same reader, deliberately:
# they interpret a frozen v2 schedule identically, and a scout point that was
# read under different semantics could not locate a bracket the headline curve
# would agree with.
#
# What must NOT be shared is authority. A scout point is N=500, one repeat, and
# its UNDER/OVER is a bracket hint with a ~34% per-run flip rate. It carries a
# `point_state` that looks exactly like a headline verdict, so the separation
# cannot rest on a reader noticing the directory a file came from -- the record
# declares its own class, and `metrics/classification.py` refuses to aggregate
# anything that is not headline evidence.
HEADLINE_EVIDENCE = "headline_evidence"
SCOUT_DIAGNOSTIC = "scout_diagnostic"
SECONDARY_DIAGNOSTIC = "secondary_diagnostic"
ADVERSARIAL_DIAGNOSTIC = "adversarial_diagnostic"
FLOOR_DIAGNOSTIC = "floor_diagnostic"
EVIDENCE_CLASSES = (HEADLINE_EVIDENCE, SCOUT_DIAGNOSTIC, SECONDARY_DIAGNOSTIC,
                    ADVERSARIAL_DIAGNOSTIC, FLOOR_DIAGNOSTIC)

# Stamped into every record this module writes. The classifier requires it, so
# a session #1 record -- produced by the frozen `metrics/point.py`, which has
# no such field -- cannot be mistaken for session #2 evidence.
HEADLINE_POINT_RECORD_VERSION = "headline-point-v1"

ISSUED_STATUSES = ("sent", "errored")


def post_warmup(rows: list[dict], warmup_n_s: float) -> list[dict]:
    """Rows whose ACTUAL send landed at or after `warmup_n_s`.

    Retained for delivery diagnostics only. It is **not** how the measurement
    population is chosen — see `measurement_membership`. Selecting the p99
    population this way is the bug this module was corrected for: it makes
    membership a function of how the client happened to be scheduled, so the
    same frozen workload yields a different estimator population on a laggy
    run than on a clean one.
    """
    return [r for r in rows if r.get("send_time") is not None and r["send_time"] >= warmup_n_s]


def measurement_membership(scheduled_offsets, warmup_boundary_s: float) -> set[int]:
    """The canonical measurement population, from the frozen schedule alone.

        measurement_member(request) := scheduled_offset >= warmup_boundary_s

    `request_id` is the index of the entry in the frozen schedule
    (`OpenLoopScheduler` assigns it with `enumerate(schedule.entries)`), so
    this set is a pure function of the committed artifact: same schedule, same
    population, on every run, on every machine, regardless of how the server
    behaved or how late the client sent.

    Two consequences the tests pin:

      - a warmup arrival stays a warmup arrival even if scheduling lag pushes
        its actual send past the boundary. It is load, not measurement, and
        its TTFT never reaches the percentile;
      - a canonical arrival stays canonical even if it is delivered late. Late
        delivery is a validity problem, recorded as one; it never shrinks N by
        quietly dropping the request.
    """
    return {i for i, offset in enumerate(scheduled_offsets) if offset >= warmup_boundary_s}


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
    scheduled_offsets,
    delivery_band_pct: float = DEFAULT_DELIVERY_BAND_PCT,
    tail_censoring_review: dict | None = None,
    provenance: dict | None = None,
    evidence_class: str = SCOUT_DIAGNOSTIC,
    process_epoch: str | None = None,
) -> dict:
    """One redesigned point's record — headline or scout.

    `schedule_provenance` is the frozen v2 schedule's provenance block: it
    carries the materialized counts and duration that the fidelity check
    compares against, so the check reads what was actually offered rather than
    recomputing an expectation.

    `scheduled_offsets` is the frozen schedule's arrival offsets, indexed by
    `request_id`. It is required rather than optional because it is what
    decides the p99 population; making it defaultable would let a caller fall
    back to send-time filtering, which is the defect this signature exists to
    prevent.

    `evidence_class` decides only what the record may be *used for*, never how
    it is measured. Tier A passes `SCOUT_DIAGNOSTIC` so the record cannot be
    pooled into a headline classification family.

    It defaults to the LEAST privileged class, not the most. A caller that
    forgets to say what it is producing gets a diagnostic; silence never
    grants the authority to define the breach. `drive_redesign_point` requires
    it explicitly, so nothing in production relies on the default.

    `process_epoch` identifies the server process the point was driven
    against. Repeats from different vLLM processes may not be combined
    (lock 3A) and a spot preemption forces exactly that situation, so the
    epoch has to be ON the record -- three metrics files on disk otherwise
    cannot even be ordered in time, let alone checked for a restart between
    them.
    """
    if evidence_class not in EVIDENCE_CLASSES:
        raise ValueError(
            f"unknown evidence_class {evidence_class!r}; expected one of {EVIDENCE_CLASSES}. "
            "A record that cannot say what it may be used for must not be written.")
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
    # A SMALLER value is refused too, and for a less obvious reason: since
    # membership became schedule-based, `warmup_n_s` no longer selects
    # anything. Accepting 30s against a 60s boundary would record
    # `warmup_n_s_applied: 30.0` on a record measured at 60 -- an operator
    # would read the field as what happened. Either the boundary is the
    # boundary, or the schedules are regenerated.
    if warmup_n_s < warmup_boundary - 1e-9:
        raise ValueError(
            f"warmup_n_s={warmup_n_s}s is below the schedule's frozen warmup boundary "
            f"{warmup_boundary}s. The measurement population is defined by the boundary the "
            "schedule was materialized with, so a smaller value would change nothing while "
            "the record claimed it had. Regenerate the schedules at the boundary you want.")

    # Materialized once: an exhausted iterator would silently produce an empty
    # `offsets_by_id` below and blank the lag diagnostics with no error.
    scheduled_offsets = list(scheduled_offsets)
    materialized_count = int(schedule_provenance["materialized_schedule_count"])
    materialized_post = int(schedule_provenance["materialized_post_warmup_count"])
    materialized_duration = float(schedule_provenance["materialized_schedule_duration_s"])
    target_n = int(schedule_provenance["post_warmup_target_count"])

    post_window_s = materialized_duration - warmup_boundary
    materialized_rps = materialized_post / post_window_s if post_window_s > 0 else 0.0

    # --- the canonical measurement population ----------------------------
    # Chosen from the FROZEN schedule, never from wall-clock send times. The
    # boundary used is the schedule's own, not `warmup_n_s`: a smaller
    # `warmup_n_s` would pull warmup arrivals into the population, and the
    # population is a property of the committed artifact rather than of a
    # reader's argument.
    measurement_ids = measurement_membership(scheduled_offsets, warmup_boundary)
    expected_measurement_n = len(measurement_ids)

    # --- R7: what was offered vs what was sent ---------------------------
    issued = [r for r in raw_rows if r["status"] in ISSUED_STATUSES]
    issued_window = [r for r in issued if r["request_id"] in measurement_ids]
    shed_rows = [r for r in raw_rows if r["status"] == "shed"]
    shed_total = len(shed_rows)
    shed_in_window = sum(1 for r in shed_rows if r["request_id"] in measurement_ids)

    actual_sent_count = len(issued_window)
    actual_send_rps = actual_sent_count / post_window_s if post_window_s > 0 else 0.0

    # Driver fidelity: how much of the canonical population actually got
    # issued. A late send still counts as delivered -- lateness is reported
    # separately below -- so this measures requests that never went out at
    # all (shed, or dropped), which is the failure that would otherwise
    # shrink N.
    reconciled_measurement_n = actual_sent_count
    schedule_delivery_divergence_pct = (
        100.0 * (actual_sent_count - expected_measurement_n) / expected_measurement_n
        if expected_measurement_n else 0.0
    )
    delivery_ok = abs(schedule_delivery_divergence_pct) <= delivery_band_pct

    # --- delivery-timing diagnostics -------------------------------------
    # These are what send-time filtering used to silently fold into
    # membership. Keeping them as named diagnostics means the lag is still
    # visible -- it just cannot change which requests the p99 is computed
    # over.
    offsets_by_id = {i: off for i, off in enumerate(scheduled_offsets)}
    sends_after_boundary_wallclock = len(post_warmup(issued, warmup_boundary))
    late_warmup_sends = sum(
        1 for r in issued
        if r["request_id"] not in measurement_ids
        and r.get("send_time") is not None and r["send_time"] >= warmup_boundary)
    early_measurement_sends = sum(
        1 for r in issued_window
        if r.get("send_time") is not None and r["send_time"] < warmup_boundary)
    lags = [r["send_time"] - offsets_by_id[r["request_id"]]
            for r in issued_window
            if r.get("send_time") is not None and r["request_id"] in offsets_by_id]
    max_send_lag_s = max(lags) if lags else None
    mean_send_lag_s = (sum(lags) / len(lags)) if lags else None

    # Finite-Poisson realization vs nominal lambda. Metadata. Never a failure.
    nominal_realization_delta_pct = (
        100.0 * (materialized_rps - nominal_lambda) / nominal_lambda if nominal_lambda else 0.0
    )

    # --- R8: censoring ----------------------------------------------------
    # Same membership rule as the sends: a sidecar row belongs to the window
    # because its request was scheduled after the boundary, not because it
    # was sent after it.
    samples_window = [r for r in sample_rows if r.get("request_id") in measurement_ids]

    # De-duplicated by request_id. `SampleLogger` writes one row per issued
    # request, so a duplicate should be impossible -- but if one ever appeared
    # it would add a TTFT to the estimator and push `n_observed` above
    # `n_offered_window`, where `max(..., 0)` would clamp the censoring count
    # to zero and hide it.
    seen: set[int] = set()
    unique_window = []
    for row in samples_window:
        request_id = row.get("request_id")
        if request_id in seen:
            continue
        seen.add(request_id)
        unique_window.append(row)
    n_duplicate_sample_rows = len(samples_window) - len(unique_window)
    samples_window = unique_window

    observed = [r for r in samples_window
                if r.get("ttft_ms") is not None and not r.get("error")]

    n_issued_window = len(issued_window)
    n_observed = len(observed)
    # Denominator is every canonical request the driver OFFERED -- issued or
    # shed -- not the sidecar rows.
    #
    # Shed is included deliberately. A shed canonical request produced no
    # TTFT, so leaving it out subtracts it from the denominator instead of
    # counting it as censored: 4% of a headline point shed reads as 0.0%
    # censoring while 160 canonical requests are simply absent from the p99,
    # and shed requests cluster at the highest-concurrency instants, which is
    # precisely the tail. Below the +/-5% delivery band nothing else would
    # catch that.
    n_offered_window = n_issued_window + shed_in_window
    n_censored = max(n_offered_window - n_observed, 0)
    censoring_rate = n_censored / n_offered_window if n_offered_window else 0.0

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
        "record_version": HEADLINE_POINT_RECORD_VERSION,
        "workload_class": schedule_provenance.get("workload_class", "headline_controlled"),
        # --- what this record may be used for --------------------------------
        # `workload_class` above comes from the frozen schedule and describes
        # the arrival process; it reads `headline_controlled` on the scout
        # schedules too, because they are controlled Poisson draws. It is
        # therefore NOT the field that separates evidence from diagnostics.
        "evidence_class": evidence_class,
        "may_define_headline_breach": evidence_class == HEADLINE_EVIDENCE,
        # Which server process produced this. Lock 3A forbids combining
        # repeats across epochs; without this field the rule is unenforceable
        # and the family report's claim that no restart happened would be an
        # assertion rather than a measurement.
        "process_epoch": process_epoch,
        # --- repeat identity ------------------------------------------------
        "repeat_id": schedule_provenance.get("repeat_id"),
        "canonical_prompt_membership_id": schedule_provenance.get(
            "canonical_prompt_membership_id"),
        # Carried into the record so the classifier can verify identity from
        # the record alone, without re-opening the schedule it came from. A
        # legacy v1 artifact driven through a session #2 entry point would
        # surface here as the wrong scheme rather than as a plausible number.
        "schedule_scheme_version": schedule_provenance.get("schedule_scheme_version"),
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
        # --- the three populations, inspectable ------------------------------
        # expected: what the frozen schedule says the population IS
        # reconciled: how many of those were actually issued
        # percentile: what the p99 was computed over -- always the canonical
        #             population, never a wall-clock slice of it
        "expected_measurement_n": expected_measurement_n,
        "reconciled_measurement_n": reconciled_measurement_n,
        "percentile_population_n": expected_measurement_n,
        "measurement_membership_basis": "scheduled_offset",
        # --- delivery timing, as diagnostics rather than as membership -------
        "sends_after_boundary_wallclock": sends_after_boundary_wallclock,
        "late_warmup_sends": late_warmup_sends,
        "early_measurement_sends": early_measurement_sends,
        "max_send_lag_s": max_send_lag_s,
        "mean_send_lag_s": mean_send_lag_s,
        "nominal_realization_delta_pct": nominal_realization_delta_pct,
        "nominal_realization_is_metadata": True,
        "warmup_boundary_s": warmup_boundary,
        "warmup_n_s_applied": warmup_n_s,
        "n_shed_total": shed_total,
        # --- R8: censoring ---------------------------------------------------
        "n_issued_window": n_issued_window,
        "n_shed_in_window": shed_in_window,
        "n_offered_window": n_offered_window,
        "n_duplicate_sample_rows": n_duplicate_sample_rows,
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

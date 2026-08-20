"""Repeat-level classification and the bounded-UNCERTAIN fallback
(R4 README R10; `WEEK2_PLAN.md` §10.3/§10.6).

## Who decides the verdict

Not the bootstrap. The R2 study sized a run — it answered "how large must one
run be before its p99 stops being fragile" — and it cannot answer whether two
independent runs agree, because every resample comes from the same run. The
verdict comes from **independent repeats**: same canonical membership, new
arrival seed, new assignment seed, drained in between.

Slices of one continuous run are not repeats. Neither is a prompt permutation
on its own. Both look like replication and neither carries run-to-run
variance.

## Why the policy is an argument rather than a constant

How many repeats must agree, and how much spread is tolerable, is a human
call about how much evidence this project wants to buy. Baking a number in
here would be the agent quietly setting the GPU budget. `RepeatPolicy`
carries it, `resolve_breach` applies it, and the values live wherever the
human recorded them.

## The escape hatch is a real outcome, not a fallback to apologise for

A ≤1% per-run flip rate would need N ≈ 7,500 — above `N_max = 5,000`, which is
structural: the pinned corpus holds 5,000 prompts and repeating prompts inside
a run is not neutral on this server. So "the crossing cannot be resolved to a
point with the authorized evidence" is a reachable, correct answer, and the
honest report of it is an interval:

    breach interval = (highest defensible UNDER λ, lowest defensible OVER λ]

Manufacturing a point estimate by escalating past the ceiling would be
choosing a number over the evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from metrics.headline_point import CENSORED, OVER, UNCERTAIN, UNDER

# A repeat that could not measure anything is never pooled with ones that
# could -- averaging a censored repeat into valid ones manufactures a clean
# aggregate out of a broken measurement.
MEASURABLE_STATES = (UNDER, OVER)


@dataclass(frozen=True)
class RepeatPolicy:
    """The human-approved evidence policy. No defaults are load-bearing: every
    field is expected to come from a recorded decision."""

    min_valid_repeats: int = 3
    require_unanimous: bool = True
    n_per_run: int = 4000
    n_max: int = 5000
    max_repeats_authorized: int = 3
    max_ttft_p99_spread_ms: float | None = None

    def to_dict(self) -> dict:
        return {
            "min_valid_repeats": self.min_valid_repeats,
            "require_unanimous": self.require_unanimous,
            "n_per_run": self.n_per_run,
            "n_max": self.n_max,
            "max_repeats_authorized": self.max_repeats_authorized,
            "max_ttft_p99_spread_ms": self.max_ttft_p99_spread_ms,
        }

    def evidence_ceiling_reached(self, n_used: int, repeats_used: int) -> bool:
        return n_used >= self.n_max or repeats_used >= self.max_repeats_authorized


@dataclass
class PointAggregate:
    """One nominal λ, across its repeats."""

    nominal_lambda_rps: float
    state: str
    reason: str
    repeats: list[dict] = field(default_factory=list)
    valid_repeats: list[dict] = field(default_factory=list)
    excluded_repeats: list[dict] = field(default_factory=list)
    ttft_p99_values_ms: list[float] = field(default_factory=list)
    ttft_p99_spread_ms: float | None = None
    boundary_determining: bool = False
    pending_tail_reviews: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "nominal_lambda_rps": self.nominal_lambda_rps,
            "state": self.state,
            "reason": self.reason,
            "n_repeats": len(self.repeats),
            "n_valid_repeats": len(self.valid_repeats),
            "ttft_p99_values_ms": self.ttft_p99_values_ms,
            "ttft_p99_spread_ms": self.ttft_p99_spread_ms,
            "boundary_determining": self.boundary_determining,
            "pending_tail_reviews": self.pending_tail_reviews,
            # Per-repeat evidence stays available even when an aggregate
            # exists: an aggregate that hides its inputs cannot be audited.
            "per_repeat": [
                {
                    "repeat_id": r.get("repeat_id"),
                    "state": r.get("point_state"),
                    "reason": r.get("point_state_reason"),
                    "ttft_p99_ms": r.get("ttft_p99_ms"),
                    "n_ttft_observed": r.get("n_ttft_observed"),
                    "ttft_censoring_rate": r.get("ttft_censoring_rate"),
                    "tail_censoring_warning": r.get("tail_censoring_warning"),
                    "tail_censoring_review_status": r.get("tail_censoring_review_status"),
                    "schedule_delivery_ok": r.get("schedule_delivery_ok"),
                    "exact_n_honoured": r.get("exact_n_honoured"),
                    "arrival_seed": r.get("arrival_seed"),
                    "assignment_seed": r.get("assignment_seed"),
                }
                for r in self.repeats
            ],
            "excluded_repeats": [
                {"repeat_id": r.get("repeat_id"), "state": r.get("point_state"),
                 "reason": r.get("point_state_reason")}
                for r in self.excluded_repeats
            ],
        }


def _independent_repeats(records: list[dict]) -> None:
    """Refuse anything that is not actually a set of independent repeats.

    The two ways this goes wrong both look fine in a table: reusing one
    repeat's artifacts twice, and varying only one of the two seeds. Both
    would report replication that was never performed.
    """
    repeat_ids = [r.get("repeat_id") for r in records]
    if len(set(repeat_ids)) != len(repeat_ids):
        raise ValueError(
            f"duplicate repeat_ids {repeat_ids} -- the same run cannot count twice toward "
            "run-to-run agreement")

    memberships = {r.get("canonical_prompt_membership_id") for r in records}
    if len(memberships) > 1:
        raise ValueError(
            f"repeats span {len(memberships)} canonical memberships -- repeats must share "
            "membership exactly; re-drawing prompts across repeats reintroduces the realized-"
            "tail variance the canonical construction removes")

    if len(records) > 1:
        arrivals = [r.get("arrival_seed") for r in records]
        assignments = [r.get("assignment_seed") for r in records]
        if len(set(arrivals)) != len(arrivals):
            raise ValueError(f"repeats share arrival seeds {arrivals} -- the Poisson "
                             "realization is not independent across them")
        if len(set(assignments)) != len(assignments):
            raise ValueError(f"repeats share assignment seeds {assignments} -- the prompt "
                             "order is not independent across them")


def classify_point(records: list[dict], policy: RepeatPolicy,
                   boundary_determining: bool = False) -> PointAggregate:
    """Aggregate one nominal λ's repeats into a single state."""
    if not records:
        raise ValueError("classify_point: no repeat records")
    _independent_repeats(records)

    lambdas = {r["nominal_lambda_rps"] for r in records}
    if len(lambdas) != 1:
        raise ValueError(f"classify_point: records span multiple lambdas {lambdas}")
    nominal = lambdas.pop()

    valid, excluded = [], []
    for record in records:
        if record.get("point_state") not in MEASURABLE_STATES:
            excluded.append(record)
        elif not record.get("schedule_delivery_ok", True):
            excluded.append(record)
        elif not record.get("exact_n_honoured", True):
            excluded.append(record)
        else:
            valid.append(record)

    p99s = [r["ttft_p99_ms"] for r in valid if r.get("ttft_p99_ms") is not None]
    spread = (max(p99s) - min(p99s)) if len(p99s) > 1 else None

    pending = [
        r.get("repeat_id") for r in valid
        if r.get("tail_censoring_warning") and r.get("tail_censoring_review_status") != "COMPLETE"
    ]

    aggregate = PointAggregate(
        nominal_lambda_rps=nominal,
        state=UNCERTAIN,
        reason="",
        repeats=list(records),
        valid_repeats=valid,
        excluded_repeats=excluded,
        ttft_p99_values_ms=p99s,
        ttft_p99_spread_ms=spread,
        boundary_determining=boundary_determining,
        pending_tail_reviews=pending,
    )

    if len(valid) < policy.min_valid_repeats:
        aggregate.reason = (
            f"{len(valid)} valid repeat(s), policy requires {policy.min_valid_repeats}"
            + (f"; {len(excluded)} excluded ("
               + ", ".join(f"r{r.get('repeat_id')}:{r.get('point_state')}" for r in excluded)
               + ")" if excluded else ""))
        if excluded and all(r.get("point_state") == CENSORED for r in excluded) and not valid:
            aggregate.state = CENSORED
            aggregate.reason = ("every repeat was censored above the hard gate; no ordinary p99 "
                                "verdict exists at this point")
        return aggregate

    states = {r["point_state"] for r in valid}
    if policy.require_unanimous and len(states) > 1:
        aggregate.reason = (
            "repeats disagree: "
            + ", ".join(f"r{r['repeat_id']}={r['point_state']} "
                        f"(p99 {r['ttft_p99_ms']:.1f}ms)" for r in valid))
        return aggregate

    if policy.max_ttft_p99_spread_ms is not None and spread is not None \
            and spread > policy.max_ttft_p99_spread_ms:
        aggregate.reason = (f"p99 spread across repeats {spread:.1f}ms exceeds the policy limit "
                            f"{policy.max_ttft_p99_spread_ms:.1f}ms")
        return aggregate

    # A boundary-determining point may not finalize while any of its repeats
    # carries un-reviewed sub-5% censoring. The gate is deliberately narrow:
    # away from the crossing, a little censoring cannot change the verdict.
    if boundary_determining and pending:
        aggregate.reason = (
            f"repeat(s) {pending} carry sub-{100 * 0.05:.0f}% TTFT censoring with no completed "
            "tail-sensitivity review, and this point could decide the crossing")
        return aggregate

    verdict = states.pop()
    aggregate.state = verdict
    aggregate.reason = (
        f"{len(valid)} independent repeat(s) agree on {verdict}"
        + (f"; p99 {min(p99s):.1f}-{max(p99s):.1f}ms" if len(p99s) > 1
           else f"; p99 {p99s[0]:.1f}ms" if p99s else ""))
    return aggregate


def resolve_breach(records_by_lambda: dict[float, list[dict]], policy: RepeatPolicy,
                   n_used: int | None = None, repeats_used: int | None = None) -> dict:
    """The sweep-level verdict: a crossing interval, or an honest failure to
    resolve one.

    Two passes. The first classifies every λ without knowing which points
    matter; the second re-classifies the two that bracket the crossing with
    `boundary_determining=True`, which is what activates the tail-review gate.
    Doing it in one pass would either apply the gate everywhere (rejecting
    points far from the crossing for irrelevant censoring) or nowhere.
    """
    provisional = {lam: classify_point(recs, policy)
                   for lam, recs in sorted(records_by_lambda.items())}

    unders = sorted(lam for lam, agg in provisional.items() if agg.state == UNDER)
    overs = sorted(lam for lam, agg in provisional.items() if agg.state == OVER)

    boundary = set()
    if unders and overs:
        candidate_under = max(lam for lam in unders if lam < max(overs)) if any(
            lam < max(overs) for lam in unders) else None
        candidate_over = min(lam for lam in overs if lam > min(unders)) if any(
            lam > min(unders) for lam in overs) else None
        boundary = {lam for lam in (candidate_under, candidate_over) if lam is not None}

    aggregates = {
        lam: classify_point(recs, policy, boundary_determining=lam in boundary)
        for lam, recs in sorted(records_by_lambda.items())
    }

    unders = sorted(lam for lam, agg in aggregates.items() if agg.state == UNDER)
    overs = sorted(lam for lam, agg in aggregates.items() if agg.state == OVER)
    unresolved = sorted(lam for lam, agg in aggregates.items()
                        if agg.state in (UNCERTAIN, CENSORED))

    n_used = n_used if n_used is not None else policy.n_per_run
    repeats_used = repeats_used if repeats_used is not None else max(
        (len(a.repeats) for a in aggregates.values()), default=0)
    ceiling_reached = policy.evidence_ceiling_reached(n_used, repeats_used)

    result = {
        "policy": policy.to_dict(),
        "evidence_used": {"n_per_run": n_used, "repeats": repeats_used,
                          "ceiling_reached": ceiling_reached},
        "points": {str(lam): agg.to_dict() for lam, agg in aggregates.items()},
        "under_lambdas": unders,
        "over_lambdas": overs,
        "unresolved_lambdas": unresolved,
        "percentile": None,
    }

    if not overs:
        result.update({
            "resolution": "NO_BREACH_OBSERVED",
            "breach_interval": None,
            "message": "no λ was classified OVER. The swept range does not contain the "
                       "crossing; extend upward before spending more evidence on these points.",
        })
        return result

    if not unders:
        result.update({
            "resolution": "NO_UNDER_ANCHOR",
            "breach_interval": None,
            "message": "no λ was classified UNDER. The crossing is at or below the lowest swept "
                       "point; extend downward.",
        })
        return result

    lowest_over = min(overs)
    candidates = [lam for lam in unders if lam < lowest_over]
    if not candidates:
        result.update({
            "resolution": "NO_VALID_BRACKET",
            "breach_interval": None,
            "message": (f"every UNDER λ ({unders}) sits above the lowest OVER λ ({lowest_over}). "
                        "The curve is not monotone in the swept range, or a point is "
                        "misclassified; this cannot be reported as a crossing."),
        })
        return result

    highest_under = max(candidates)
    inside = [lam for lam in unresolved if highest_under < lam < lowest_over]

    result["breach_interval"] = {
        "lower_exclusive": highest_under,
        "upper_inclusive": lowest_over,
        "notation": f"({highest_under}, {lowest_over}]",
        "unresolved_points_inside": inside,
    }

    if inside and ceiling_reached:
        result.update({
            "resolution": "INTERVAL_AT_EVIDENCE_CEILING",
            "message": (
                f"λ {inside} remain UNCERTAIN/CENSORED inside the bracket, and the authorized "
                f"evidence ceiling is reached (N={n_used} of N_max={policy.n_max}, "
                f"{repeats_used} of {policy.max_repeats_authorized} repeats). Reporting the "
                f"breach as the interval ({highest_under}, {lowest_over}] rather than "
                "escalating. Raising N further would require repeating corpus prompts, which "
                "is forbidden."),
        })
    elif inside:
        result.update({
            "resolution": "MORE_EVIDENCE_AUTHORIZED",
            "message": (
                f"λ {inside} remain unresolved inside the bracket and the evidence ceiling is "
                f"NOT reached (N={n_used} of {policy.n_max}, {repeats_used} of "
                f"{policy.max_repeats_authorized} repeats). Escalation is permitted, and must "
                "follow the pre-authorized evidence plan rather than being decided on the "
                "meter."),
        })
    else:
        result.update({
            "resolution": "BRACKETED",
            "message": (f"the crossing lies in ({highest_under}, {lowest_over}], resolved to the "
                        "swept step granularity with no unresolved point inside it."),
        })
    return result

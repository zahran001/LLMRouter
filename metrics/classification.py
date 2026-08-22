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

import json
from dataclasses import dataclass, field
from pathlib import Path

from loadgen.headline_schedule import HEADLINE_SCHEDULE_SCHEME_VERSION
from metrics.headline_point import (
    CENSORED,
    CENSORING_HARD_GATE,
    HEADLINE_EVIDENCE,
    HEADLINE_POINT_RECORD_VERSION,
    OVER,
    UNCERTAIN,
    UNDER,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
HEADLINE_WORKLOAD_PATH = (REPO_ROOT / "benchmarks" / "workloads" / "week2_headline"
                          / "canonical_v1.json")
HEADLINE_POLICY_PATH = (REPO_ROOT / "benchmarks" / "workloads" / "week2_headline"
                        / "repeat_policy.json")

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
    # Which artifacts are even eligible. Deliberately has NO default: a policy
    # that does not say which workload defines the headline cannot be used to
    # classify one, and defaulting it would reintroduce exactly the fail-open
    # this field exists to close.
    headline: HeadlineEvidenceSpec | None = None

    @classmethod
    def from_frozen(cls, policy_path: Path | str = HEADLINE_POLICY_PATH,
                    workload_path: Path | str = HEADLINE_WORKLOAD_PATH) -> "RepeatPolicy":
        """The production constructor: every value from a recorded decision."""
        raw = json.loads(Path(policy_path).read_text(encoding="utf-8"))["policy"]
        return cls(
            min_valid_repeats=int(raw["min_valid_repeats"]),
            require_unanimous=bool(raw["require_unanimous"]),
            n_per_run=int(raw["n_per_run"]),
            n_max=int(raw["n_max"]),
            max_repeats_authorized=int(raw["max_repeats_authorized"]),
            max_ttft_p99_spread_ms=raw["max_ttft_p99_spread_ms"],
            headline=HeadlineEvidenceSpec.from_frozen(workload_path, policy_path),
        )

    def require_headline_spec(self) -> HeadlineEvidenceSpec:
        if self.headline is None:
            raise NotHeadlineEvidence(
                "this RepeatPolicy states no headline evidence spec, so it cannot verify that a "
                "record belongs to the headline workload. Build it with "
                "RepeatPolicy.from_frozen(), or pass an explicit HeadlineEvidenceSpec.")
        return self.headline

    def to_dict(self) -> dict:
        return {
            "min_valid_repeats": self.min_valid_repeats,
            "require_unanimous": self.require_unanimous,
            "n_per_run": self.n_per_run,
            "n_max": self.n_max,
            "max_repeats_authorized": self.max_repeats_authorized,
            "max_ttft_p99_spread_ms": self.max_ttft_p99_spread_ms,
            "headline_evidence_spec": (
                None if self.headline is None else {
                    "membership_id": self.headline.membership_id,
                    "percentile_population_n": self.headline.percentile_population_n,
                    "schedule_scheme_version": self.headline.schedule_scheme_version,
                    "record_version": self.headline.record_version,
                }),
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
                    "evidence_class": r.get("evidence_class"),
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


class NotHeadlineEvidence(ValueError):
    """A record that did not prove it may define the Session #2 breach."""


@dataclass(frozen=True)
class HeadlineEvidenceSpec:
    """What a record must **prove** before it may define the breach.

    Fail-closed by construction. The classifier does not ask "is there
    anything wrong with this record"; it asks "has this record demonstrated
    every property of session #2 headline evidence", and anything unproven —
    missing, null, or unrecognised — fails.

    That direction matters because `records_by_lambda` is assembled from files
    on disk after teardown, in a directory tree where the scout family's
    filenames (`headline_r1_rps2.metrics.json`) are indistinguishable from the
    headline family's, and where session #1's promoted artifacts sit two
    directories away. A permissive default here is not a small bug: it is the
    breach number being computed from the wrong workload while every field in
    the report still looks plausible.
    """

    membership_id: str
    percentile_population_n: int
    schedule_scheme_version: str = HEADLINE_SCHEDULE_SCHEME_VERSION
    record_version: str = HEADLINE_POINT_RECORD_VERSION

    @classmethod
    def from_frozen(cls, workload_path: Path | str = HEADLINE_WORKLOAD_PATH,
                    policy_path: Path | str = HEADLINE_POLICY_PATH) -> "HeadlineEvidenceSpec":
        """Read the expectation off the frozen artifacts, not off a constant.

        The canonical workload is the only authority on which membership is
        the headline one, and `repeat_policy.json` is the only authority on N.
        Hard-coding either here would let the code and the frozen inputs drift
        apart silently — and the drift would be invisible precisely when it
        mattered, because both would still be internally consistent.
        """
        workload = json.loads(Path(workload_path).read_text(encoding="utf-8"))
        policy = json.loads(Path(policy_path).read_text(encoding="utf-8"))
        return cls(membership_id=workload["membership_id"],
                   percentile_population_n=int(policy["policy"]["n_per_run"]))


def _headline_evidence_only(records: list[dict], spec: HeadlineEvidenceSpec) -> None:
    """Refuse anything that has not proven it is session #2 headline evidence.

    Every check is an equality against `spec`, and every absent field is a
    failure rather than a pass. The rejected populations this is built for:

      scout_diagnostic     same reader, same `point_state` vocabulary, N=500
                           at one repeat -- a ~34% per-run flip rate, which
                           locates a bracket and cannot support a verdict
      secondary/adversarial  never define the breach (lock 6A)
      session #1 records   produced by the frozen `metrics/point.py`; they
                           carry no `record_version`, no `evidence_class`, and
                           a different percentile convention
      scout membership     a scout schedule pushed through a headline entry
                           point gets the headline stamp but keeps the scout
                           workload -- caught on membership, not on the stamp
    """
    for record in records:
        problems: list[str] = []

        evidence_class = record.get("evidence_class")
        if evidence_class != HEADLINE_EVIDENCE:
            problems.append(
                f"evidence_class={evidence_class!r}, expected {HEADLINE_EVIDENCE!r}")
        # Checked independently of `evidence_class` rather than derived from
        # it: the two are written together, so requiring both means a record
        # hand-edited to flip one still fails on the other.
        if record.get("may_define_headline_breach") is not True:
            problems.append(
                f"may_define_headline_breach={record.get('may_define_headline_breach')!r}, "
                "expected True")

        if record.get("record_version") != spec.record_version:
            problems.append(
                f"record_version={record.get('record_version')!r}, expected "
                f"{spec.record_version!r} (a session #1 record carries none)")

        if record.get("schedule_scheme_version") != spec.schedule_scheme_version:
            problems.append(
                f"schedule_scheme_version={record.get('schedule_scheme_version')!r}, expected "
                f"{spec.schedule_scheme_version!r}")

        membership = record.get("canonical_prompt_membership_id")
        if membership != spec.membership_id:
            problems.append(
                f"canonical_prompt_membership_id={_short(membership)}, expected "
                f"{_short(spec.membership_id)} -- this is not the headline workload")

        population = record.get("percentile_population_n")
        if population != spec.percentile_population_n:
            problems.append(
                f"percentile_population_n={population!r}, expected "
                f"{spec.percentile_population_n}")

        # Lock 3A is only enforceable if the record says which server process
        # produced it. A spot preemption forces a vLLM restart mid-family, so
        # this is the expected failure mode rather than a hypothetical.
        if not record.get("process_epoch"):
            problems.append(
                "process_epoch is absent -- without it, repeats from different vLLM "
                "processes cannot be told apart (lock 3A)")

        # Presence, not just truth. `.get(key, True)` would let a record that
        # never computed a gate pass the gate.
        for gate in ("schedule_delivery_ok", "exact_n_honoured"):
            if gate not in record:
                problems.append(f"{gate} is absent -- the gate was never computed")
            elif not isinstance(record[gate], bool):
                problems.append(f"{gate}={record[gate]!r} is not a boolean")
        if not isinstance(record.get("ttft_censoring_rate"), (int, float)):
            problems.append(
                f"ttft_censoring_rate={record.get('ttft_censoring_rate')!r} is not a number")

        if problems:
            raise NotHeadlineEvidence(
                f"repeat_id={record.get('repeat_id')!r} is not session #2 headline evidence "
                "and may not enter the classification family:\n  - "
                + "\n  - ".join(problems)
                + "\nOnly the controlled Poisson headline family defines the breach "
                  "(repeat_policy.json, secondary_scope.headline_defining). Diagnostic and "
                  "session #1 records stay readable through their own analysis paths.")


def _short(value) -> str:
    return f"{value[:16]}..." if isinstance(value, str) and len(value) > 16 else repr(value)


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

    epochs = {r.get("process_epoch") for r in records}
    if len(epochs) > 1:
        raise ValueError(
            f"repeats span {len(epochs)} vLLM process epochs {sorted(map(str, epochs))} -- "
            "lock 3A forbids combining them into one classification family. A restart resets "
            "the engine state the repeats were meant to hold constant, so process-"
            "initialization variance would enter one repeat and not the others, silently, at "
            "exactly the boundary where the verdict is decided. Re-drive all repeats in the "
            "fresh process; the schedules are frozen, so only meter time is lost.")

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
    _headline_evidence_only(records, policy.require_headline_spec())
    _independent_repeats(records)

    lambdas = {r["nominal_lambda_rps"] for r in records}
    if len(lambdas) != 1:
        raise ValueError(f"classify_point: records span multiple lambdas {lambdas}")
    nominal = lambdas.pop()

    valid, excluded = [], []
    for record in records:
        # Direct indexing, not `.get(key, True)`: `_headline_evidence_only`
        # has already proven both keys are present and boolean, and a default
        # here would be a second place for a missing gate to read as a passing
        # one.
        if record.get("point_state") not in MEASURABLE_STATES:
            excluded.append(record)
        elif not record["schedule_delivery_ok"]:
            excluded.append(record)
        elif not record["exact_n_honoured"]:
            excluded.append(record)
        else:
            valid.append(record)

    p99s = [r["ttft_p99_ms"] for r in valid if r.get("ttft_p99_ms") is not None]
    spread = (max(p99s) - min(p99s)) if len(p99s) > 1 else None

    # Derived from the censoring rate, not read from a stamped boolean.
    #
    # `r.get("tail_censoring_warning")` returned None for a record that never
    # stamped the flag, None is falsy, and the point then finalized with no
    # review -- the same `.get(key, truthy)` shape this module removed
    # elsewhere, surviving in the one gate that decides whether a boundary
    # point may finalize. `ttft_censoring_rate` is proven present and numeric
    # by `_headline_evidence_only`, so the warning can be recomputed instead
    # of trusted.
    pending = [
        r.get("repeat_id") for r in valid
        if 0.0 < float(r["ttft_censoring_rate"]) <= CENSORING_HARD_GATE
        and r.get("tail_censoring_review_status") != "COMPLETE"
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
    # The caller builds `records_by_lambda` by hand after teardown -- there is
    # no loader in the repo that does it -- so the key is the one part of the
    # input nothing has validated. Everything below reports at the key, so a
    # mis-keyed entry would publish a breach interval naming a lambda that no
    # record was measured at.
    for lam, recs in records_by_lambda.items():
        for record in recs:
            actual = record.get("nominal_lambda_rps")
            if actual is None or abs(float(actual) - float(lam)) > 1e-9:
                raise ValueError(
                    f"records_by_lambda[{lam}] contains a record measured at "
                    f"nominal_lambda_rps={actual!r}. The breach interval is reported at the "
                    "key, so a mis-keyed record would publish a lambda nothing was measured "
                    "at.")

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
                       "crossing. This is an OFFLINE conclusion about a finished session, "
                       "not an instruction to extend the sweep live -- inventing λ values on "
                       "the meter is forbidden (lock 5A). A wider range needs regenerated "
                       "schedules, a new benchmark SHA and a fresh session.",
        })
        return result

    if not unders:
        result.update({
            "resolution": "NO_UNDER_ANCHOR",
            "breach_interval": None,
            "message": "no λ was classified UNDER. The crossing is at or below the lowest "
                       "swept point. Offline conclusion only: extending the range means "
                       "regenerated schedules and a new session, never a live decision "
                       "(lock 5A).",
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

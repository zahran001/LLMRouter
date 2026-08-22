"""What each session #2 scenario is allowed to drive, and with what authority.

One table, consulted by every driver. The alternative — each command deciding
for itself — is how a scout schedule ends up driven as headline evidence, and
the directory layout actively invites it: `scout/` and `headline/` hold files
with byte-identical names (`headline_r1_rps2.schedule.json`), and both declare
`workload_class: headline_controlled`, because a scout point IS a controlled
Poisson draw. Filename and directory are not authority. The schedule's own
provenance is.

Each contract states the four things a mismatch could otherwise hide:

    scheme          which measurement contract reads it
    workload_class  which scenario it was generated for
    membership      which prompt multiset it draws from
    evidence_class  what the resulting record may be used for

`validate()` checks the first three against the frozen artifact and refuses on
any disagreement. The fourth is stamped onto the record, so authority travels
with the measurement rather than with the command that produced it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

HEADLINE_WORKLOAD = REPO_ROOT / "benchmarks" / "workloads" / "week2_headline" / "canonical_v1.json"
SCOUT_WORKLOAD = REPO_ROOT / "benchmarks" / "workloads" / "week2_scout" / "canonical_v1.json"

V2 = "headline-schedule-v2"
V1 = "loadgen-schedule-v1"


class ScenarioMismatch(RuntimeError):
    """The artifact does not match the scenario it was handed to."""


@dataclass(frozen=True)
class ScenarioContract:
    name: str
    scheme: str | None
    workload_class: str
    evidence_class: str
    membership_source: Path | None
    role: str

    def expected_membership(self) -> str | None:
        if self.membership_source is None:
            return None
        return json.loads(self.membership_source.read_text(encoding="utf-8"))["membership_id"]


CONTRACTS = {
    # The floor has no schedule -- it drives the canonical membership directly
    # -- so `scheme` is None and `validate()` is not the right entry point for
    # it. It is in the table anyway because the table is what pins WHICH
    # workload each stage measures, and the floor's whole purpose is to be the
    # headline curve's starting point. A floor over any other membership is a
    # floor of something else.
    "floor": ScenarioContract(
        name="floor", scheme=None, workload_class="unloaded_floor",
        evidence_class="floor_diagnostic", membership_source=HEADLINE_WORKLOAD,
        role="Unloaded intrinsic floor: canonical membership, concurrency 1."),
    "headline": ScenarioContract(
        name="headline", scheme=V2, workload_class="headline_controlled",
        evidence_class="headline_evidence", membership_source=HEADLINE_WORKLOAD,
        role="Defines the breach. N=4000, three repeats, unanimous."),
    "scout": ScenarioContract(
        name="scout", scheme=V2, workload_class="headline_controlled",
        evidence_class="scout_diagnostic", membership_source=SCOUT_WORKLOAD,
        role="Tier A. Locates the crossing region; never a verdict."),
    "steady": ScenarioContract(
        name="steady", scheme=V2, workload_class="secondary_steady_reference",
        evidence_class="secondary_diagnostic", membership_source=SCOUT_WORKLOAD,
        role="Lower-variance arrival-process reference. Never redefines the breach."),
    "secondary": ScenarioContract(
        name="secondary", scheme=V1, workload_class="secondary_natural_random",
        evidence_class="secondary_diagnostic", membership_source=None,
        role="Natural-random realism check. Never redefines the breach."),
    "adversarial": ScenarioContract(
        name="adversarial", scheme=V1, workload_class="adversarial_long_context",
        evidence_class="adversarial_diagnostic", membership_source=None,
        role="Long-context flood. Separate scenario; runs LAST."),
}

# Headline and scout are the pair that cannot be told apart by scheme or
# workload_class -- only by membership. Stated here so the reason is visible
# at the table rather than only in the validator.
AMBIGUOUS_BY_SCHEME_ALONE = ("headline", "scout")


def validate(scenario: str, schedule_path: Path | str) -> dict:
    """Refuse a schedule that was not generated for this scenario.

    Returns the schedule's provenance on success.
    """
    if scenario not in CONTRACTS:
        raise ScenarioMismatch(
            f"unknown scenario {scenario!r}; expected one of {sorted(CONTRACTS)}")
    contract = CONTRACTS[scenario]

    path = Path(schedule_path)
    if not path.exists():
        raise ScenarioMismatch(f"no such schedule: {path}")
    prov = json.loads(path.read_text(encoding="utf-8")).get("provenance", {})

    if contract.scheme is None:
        raise ScenarioMismatch(
            f"the '{scenario}' scenario drives no schedule, so there is nothing here to "
            "validate. Its workload is pinned by the driver itself.")

    scheme = prov.get("schedule_scheme_version")
    if scheme != contract.scheme:
        raise ScenarioMismatch(
            f"{path.name} declares schedule_scheme_version {scheme!r}, but the "
            f"'{scenario}' scenario drives {contract.scheme!r}. The two formats are read "
            "under different measurement contracts; driving one as the other produces a "
            "record whose numbers all look plausible.")

    workload_class = prov.get("workload_class")
    if workload_class != contract.workload_class:
        raise ScenarioMismatch(
            f"{path.name} was generated as {workload_class!r}, but the '{scenario}' "
            f"scenario drives {contract.workload_class!r}. Scenario roles come from the "
            "artifact, never from the directory it happens to sit in.")

    expected_membership = contract.expected_membership()
    if expected_membership is not None:
        membership = prov.get("canonical_prompt_membership_id")
        if membership != expected_membership:
            # Schedule-driving contracts only: `floor` shares the headline
            # membership, so including it would name the floor as the owner of
            # a headline schedule.
            other = next((c.name for c in CONTRACTS.values()
                          if c.scheme is not None
                          and c.expected_membership() == membership), "an unknown workload")
            raise ScenarioMismatch(
                f"{path.name} draws from {str(membership)[:16]}..., which belongs to "
                f"{other}, but the '{scenario}' scenario requires "
                f"{expected_membership[:16]}.... Membership is the ONLY thing separating "
                "the headline and scout families -- same scheme, same workload_class, "
                "same filenames.")

    return prov

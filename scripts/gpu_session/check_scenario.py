#!/usr/bin/env python
"""Refuse a schedule that was not generated for the scenario it was handed to.

A one-line gate the shell can call before driving a legacy v1 point. The v2
scenarios validate through the same table inside `drive_scenario_point.py`;
this exists because the v1 scenarios (natural-random secondary, adversarial)
are driven by `loadgen/_cli.py`, which knows nothing about scenario roles.

Without it, `run` distinguishes only v1 from v2 — so a natural-random schedule
handed to `adversarial` would drive happily, produce a full set of artifacts,
and be filed under a scenario it never measured. Both are v1; nothing in the
format tells them apart.

Usage:
    python scripts/gpu_session/check_scenario.py \
        --scenario adversarial --schedule benchmarks/.../adversarial_rps2.schedule.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scenario_contract import CONTRACTS, ScenarioMismatch, validate  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", required=True, choices=sorted(CONTRACTS))
    parser.add_argument("--schedule", type=Path, required=True)
    args = parser.parse_args()

    try:
        prov = validate(args.scenario, args.schedule)
    except ScenarioMismatch as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc

    contract = CONTRACTS[args.scenario]
    print(f"scenario OK: {args.schedule.name} is {contract.workload_class} "
          f"({contract.scheme}); role: {contract.role}")
    print(f"  evidence class on the record will be: {contract.evidence_class}")
    if prov.get("never_defines_headline_breach"):
        print("  never_defines_headline_breach: true")


if __name__ == "__main__":
    main()

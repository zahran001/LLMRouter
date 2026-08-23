#!/usr/bin/env python
"""Generate the sustained-scout schedule family (attempt 2, §4 locked 2026-08-22).

Replaces attempt 1's N=500 Tier A scout as the tool for locating the
sustained crossing at low lambda. N=500 read lambda=1 as a clean UNDER over
~5.5 minutes; the real (N=4000, ~45 minute) Tier B confirmation at the
adjacent lambda=1.5 came back 36% censored. A short window cannot see a
queue that is only slowly diverging, so this family freezes on whichever
binds last of a MINIMUM duration and a MINIMUM count, rather than either
alone (`loadgen/headline_schedule.py`'s `materialize_min_duration_and_count`).

Draws from the 4000-prompt HEADLINE canonical workload, not the 500-prompt
scout workload -- the scout pool is too small for the >= 2000 count floor at
low lambda. `workload_class="sustained_scout_controlled"` is deliberately
distinct from `"headline_controlled"`: it shares scheme AND membership with
the real headline family, so workload_class is the only thing
`scripts/gpu_session/scenario_contract.py` has left to disambiguate them —
without a distinct value, a sustained-scout schedule and a headline schedule
would be indistinguishable to the runtime, exactly the ambiguity that
contract exists to refuse.

One repeat only (diagnostic, not evidence) -- `evidence_class` is stamped
`scout_diagnostic` at drive time by the scenario contract, same as the
existing N=500 scout, so it can never enter headline classification.

Usage:
    .venv/Scripts/python.exe scripts/generate_sustained_scout_schedules.py
    .venv/Scripts/python.exe scripts/generate_sustained_scout_schedules.py --verify
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from loadgen.canonical import load_frozen  # noqa: E402
from loadgen.corpus import load_corpus  # noqa: E402
from loadgen.headline_schedule import (  # noqa: E402
    HEADLINE_SCHEDULE_SCHEME_VERSION,
    RepeatIdentity,
    build_thresholded_headline_schedule,
    save_headline_schedule,
)
from metrics.artifacts import write_json_artifact  # noqa: E402

WORKLOAD = REPO_ROOT / "benchmarks" / "workloads" / "week2_headline" / "canonical_v1.json"
SCHEDULE_ROOT = REPO_ROOT / "benchmarks" / "schedules" / "week2_redesign"
SUSTAINED_SCOUT_DIR = SCHEDULE_ROOT / "sustained_scout"
MANIFEST_PATH = SCHEDULE_ROOT / "SUSTAINED_SCOUT_MANIFEST.json"

# Distinct from every other family's seed base (headline: 20260819_0/5xx,
# steady: 20260821_1/6xx) so its arrival/warmup streams can never collide.
ARRIVAL_SEED_BASE = 20260822_100
ASSIGNMENT_SEED_BASE = 20260822_600

LAMBDAS = (0.5, 0.75, 1.0, 1.25)
WARMUP_S = 60.0
MIN_DURATION_S = 2700.0
MIN_COUNT = 2000
WORKLOAD_CLASS = "sustained_scout_controlled"


def generate(out_dir: Path) -> list[dict]:
    workload = load_frozen(WORKLOAD)
    corpus = load_corpus()
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for index, nominal_lambda in enumerate(LAMBDAS):
        identity = RepeatIdentity(
            canonical_membership_id=workload["membership_id"],
            repeat_id=1,
            arrival_seed=ARRIVAL_SEED_BASE + index,
            assignment_seed=ASSIGNMENT_SEED_BASE + index,
        )
        schedule = build_thresholded_headline_schedule(
            canonical=workload, corpus=corpus, identity=identity,
            nominal_lambda_rps=nominal_lambda, warmup_s=WARMUP_S,
            min_duration_s=MIN_DURATION_S, min_count=MIN_COUNT,
            workload_class=WORKLOAD_CLASS)
        schedule.provenance["never_defines_headline_breach"] = True
        schedule.provenance["scenario"] = "sustained_scout"
        path, digest = save_headline_schedule(schedule, out_dir)
        prov = schedule.provenance
        rows.append({
            "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "sha256": digest,
            "nominal_lambda_rps": nominal_lambda,
            "materialized_schedule_count": prov["materialized_schedule_count"],
            "materialized_warmup_count": prov["materialized_warmup_count"],
            "materialized_post_warmup_count": prov["materialized_post_warmup_count"],
            "materialized_schedule_duration_s": prov["materialized_schedule_duration_s"],
            "materialized_post_warmup_duration_s": prov["materialized_post_warmup_duration_s"],
        })
    return rows


def build_manifest(rows: list[dict]) -> dict:
    return {
        "what": "Sustained-scout schedule family: freezes on min(duration, count), not a fixed N "
                "(attempt-2 design, WEEK2_GPU_SESSION_2_ATTEMPT_2_PLAN.md, locked 2026-08-22).",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "schedule_scheme_version": HEADLINE_SCHEDULE_SCHEME_VERSION,
        "workload_class": WORKLOAD_CLASS,
        "canonical_workload": str(WORKLOAD.relative_to(REPO_ROOT)).replace("\\", "/"),
        "canonical_membership_id": load_frozen(WORKLOAD)["membership_id"],
        "lambdas": list(LAMBDAS),
        "repeats": 1,
        "warmup_s": WARMUP_S,
        "min_duration_s": MIN_DURATION_S,
        "min_count": MIN_COUNT,
        "arrival_seed_base": ARRIVAL_SEED_BASE,
        "assignment_seed_base": ASSIGNMENT_SEED_BASE,
        "never_defines_headline_breach": True,
        "schedules": rows,
    }


def verify() -> int:
    """Regenerate in memory and compare against what is committed -- same
    discipline as `generate_secondary_scenarios.py --verify`."""
    import json

    if not MANIFEST_PATH.exists():
        print(f"FAIL: no manifest at {MANIFEST_PATH}")
        return 1
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    problems = []
    listed_lambdas = [row["nominal_lambda_rps"] for row in manifest["schedules"]]
    if sorted(listed_lambdas) != sorted(LAMBDAS):
        problems.append(f"manifest lists lambdas {sorted(listed_lambdas)}, "
                        f"generator produces {sorted(LAMBDAS)}")

    listed_paths = set()
    for row in manifest["schedules"]:
        path = REPO_ROOT / row["path"]
        listed_paths.add(path.resolve())
        if not path.exists():
            problems.append(f"{row['path']}: listed in the manifest but missing on disk")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != row["sha256"]:
            problems.append(f"{row['path']}: sha256 {digest[:16]}... != manifest {row['sha256'][:16]}...")

    for path in sorted(SUSTAINED_SCOUT_DIR.glob("*.schedule.json")):
        if path.resolve() not in listed_paths:
            rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            problems.append(f"{rel}: on disk but absent from the manifest")

    workload = load_frozen(WORKLOAD)
    corpus = load_corpus()
    rebuilt = 0
    for index, nominal_lambda in enumerate(LAMBDAS):
        path = SUSTAINED_SCOUT_DIR / f"headline_r1_rps{nominal_lambda:g}.schedule.json"
        if not path.exists():
            continue
        identity = RepeatIdentity(
            canonical_membership_id=workload["membership_id"], repeat_id=1,
            arrival_seed=ARRIVAL_SEED_BASE + index, assignment_seed=ASSIGNMENT_SEED_BASE + index)
        schedule = build_thresholded_headline_schedule(
            canonical=workload, corpus=corpus, identity=identity,
            nominal_lambda_rps=nominal_lambda, warmup_s=WARMUP_S,
            min_duration_s=MIN_DURATION_S, min_count=MIN_COUNT, workload_class=WORKLOAD_CLASS)
        schedule.provenance["never_defines_headline_breach"] = True
        schedule.provenance["scenario"] = "sustained_scout"
        from metrics.artifacts import json_artifact_bytes
        if json_artifact_bytes(schedule.to_dict()) != path.read_bytes():
            problems.append(f"{path.name}: regeneration does not reproduce the committed bytes")
        rebuilt += 1

    if rebuilt != len(LAMBDAS):
        problems.append(f"regenerated {rebuilt} of {len(LAMBDAS)} schedules -- the rest are "
                        "missing from the working tree")

    if problems:
        print("VERIFY FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"VERIFY OK: {rebuilt} sustained-scout schedule(s) match the manifest and regenerate "
          "byte-for-byte; no unlisted artifacts present")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verify", action="store_true",
                        help="check committed artifacts against the manifest and against a "
                             "fresh regeneration; write nothing")
    args = parser.parse_args()

    if args.verify:
        raise SystemExit(verify())

    rows = generate(SUSTAINED_SCOUT_DIR)
    write_json_artifact(MANIFEST_PATH, build_manifest(rows))

    print(f"sustained scout: {len(rows)} schedule(s), 1 repeat, "
          f"min_duration={MIN_DURATION_S:g}s min_count={MIN_COUNT}")
    print(f"\n{'lambda':>7} {'total':>7} {'warmup':>7} {'post':>6} {'duration_s':>11}")
    total_s = 0.0
    for row in rows:
        total_s += row["materialized_schedule_duration_s"]
        print(f"{row['nominal_lambda_rps']:>7g} {row['materialized_schedule_count']:>7} "
              f"{row['materialized_warmup_count']:>7} {row['materialized_post_warmup_count']:>6} "
              f"{row['materialized_schedule_duration_s']:>11.1f}")
    print(f"\ntotal sustained-scout drive time: {total_s / 3600:.2f} h")
    print(f"\nwritten: {MANIFEST_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

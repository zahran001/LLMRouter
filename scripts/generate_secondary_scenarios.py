#!/usr/bin/env python
"""Freeze the steady reference and the adversarial scenario (Phase D).

Both were in Week 2's scope from the start (lock 6A) and neither had a
committed artifact: `loadgen/steady.py` and `loadgen/adversarial.py` could
generate one at runtime, but `run_on_instance.sh bootstrap` refuses a dirty or
unpushed tree, so generating on the meter would cost a commit, a push and a
new benchmark SHA mid-session. The GPU session drives frozen inputs only.

## The two operating points were human decisions, not derivations

`WEEK2_PLAN.md` §2.1 specifies that steady is captured "over the same or a
subset of points" and that adversarial is one scenario rather than a length
sweep. Neither names λ, and no other authoritative document does either. That
gap was surfaced rather than filled in, and closed by the human on 2026-08-21:

  steady        λ ∈ {1.5, 2, 2.5, 3, 4} -- the headline λ set -- under session
                #2 exact-N mechanics (N=500, 60s frozen boundary). Same
                operating points as the headline curve, so the only thing that
                differs is Poisson vs fixed intervals. That is what makes it
                an arrival-process comparison rather than a second experiment.
                A 2/3/4 subset saves little and weakens the comparison.

  adversarial   one point, λ=2, 600s. The purpose is to show what a
                long-context-heavy workload does, not to build a second breach
                curve. λ=5 would likely collapse into a trivial
                saturation/censoring result; λ=2 sits in the expected headline
                neighbourhood, where the q90 long-context selection is already
                supplying the adversarial pressure.

## Why the two families use different schedule formats

Steady is `headline-schedule-v2` because it is an exact-N comparison against
the headline curve and has to be read under the same gates. Adversarial is
`loadgen-schedule-v1`, duration-based, because its size is a duration decision
(600s) rather than an evidence-count decision, and because the long-context
draw lives in the v1 builder. Neither may define the breach; both are stamped
so `metrics/classification.py` refuses them.

Usage:
    .venv/Scripts/python.exe scripts/generate_secondary_scenarios.py
    .venv/Scripts/python.exe scripts/generate_secondary_scenarios.py --verify
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from loadgen.canonical import load_frozen  # noqa: E402
from loadgen.corpus import load_corpus  # noqa: E402
from loadgen.headline_schedule import (  # noqa: E402
    RepeatIdentity,
    build_headline_schedule,
    save_headline_schedule,
)
from loadgen.schedule import build_poisson_schedule  # noqa: E402
from metrics.artifacts import json_artifact_bytes, write_json_artifact  # noqa: E402

import hashlib  # noqa: E402

SCHEDULE_ROOT = REPO_ROOT / "benchmarks" / "schedules" / "week2_redesign"
STEADY_DIR = SCHEDULE_ROOT / "secondary_steady"
ADVERSARIAL_DIR = SCHEDULE_ROOT / "adversarial"
MANIFEST_PATH = SCHEDULE_ROOT / "SECONDARY_SCENARIOS_MANIFEST.json"

# The N=500 canonical workload. Reused rather than re-drawn: a third 500-prompt
# membership would be a new identity with no new information, and reusing this
# one means the steady curve and the Tier A scout curve are the same prompts
# under two arrival processes.
STEADY_WORKLOAD = REPO_ROOT / "benchmarks" / "workloads" / "week2_scout" / "canonical_v1.json"

# Appended, not prepended: `_steady_schedule` seeds off `index` (the
# enumerate position), so the original five must keep indices 0-4 or their
# committed bytes (and the real GPU evidence already read against them) would
# silently change. New lower anchors go after 4.0 for exactly this reason --
# added 2026-08-22 alongside the headline family's lower anchors, because Tier
# B repeat 1 showed even lambda=1.5 CENSORED (36.2%) at N=4000, so the steady
# reference needs the same lower range the headline curve now covers.
STEADY_LAMBDAS = (1.5, 2.0, 2.5, 3.0, 4.0, 0.5, 0.75, 1.0, 1.25)
STEADY_WARMUP_S = 60.0
STEADY_WORKLOAD_CLASS = "secondary_steady_reference"

# Distinct from the headline and scout bases so a steady schedule can never
# collide with either family's stream.
STEADY_ARRIVAL_SEED_BASE = 20260821_100
STEADY_ASSIGNMENT_SEED_BASE = 20260821_600

ADVERSARIAL_LAMBDA = 2.0
ADVERSARIAL_DURATION_S = 600.0
ADVERSARIAL_SEED = 20260821_900


def _steady_schedule(workload: dict, corpus, index: int, nominal_lambda: float):
    """One steady schedule. Shared by `generate` and `verify` so the two cannot
    drift into disagreeing about what the committed bytes should be."""
    # Seeds vary per λ so the warmup draw is not identical across points; the
    # arrival stream is unused by steady materialization, but the layout is
    # kept so both processes derive streams the same way.
    identity = RepeatIdentity(
        canonical_membership_id=workload["membership_id"],
        repeat_id=1,
        arrival_seed=STEADY_ARRIVAL_SEED_BASE + index,
        assignment_seed=STEADY_ASSIGNMENT_SEED_BASE + index,
    )
    schedule = build_headline_schedule(
        canonical=workload, corpus=corpus, identity=identity,
        nominal_lambda_rps=nominal_lambda, warmup_s=STEADY_WARMUP_S,
        arrival_process="steady", workload_class=STEADY_WORKLOAD_CLASS)
    schedule.provenance["never_defines_headline_breach"] = True
    schedule.provenance["scenario"] = "secondary_steady"
    return schedule


def generate_steady(out_dir: Path) -> list[dict]:
    workload = load_frozen(STEADY_WORKLOAD)
    corpus = load_corpus()
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for index, nominal_lambda in enumerate(STEADY_LAMBDAS):
        schedule = _steady_schedule(workload, corpus, index, nominal_lambda)
        prov = schedule.provenance
        path = out_dir / f"secondary_steady_rps{nominal_lambda:g}.schedule.json"
        digest = write_json_artifact(path, schedule.to_dict())
        rows.append({
            "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "sha256": digest,
            "nominal_lambda_rps": nominal_lambda,
            "arrival_process": "steady",
            "materialized_schedule_count": prov["materialized_schedule_count"],
            "materialized_warmup_count": prov["materialized_warmup_count"],
            "materialized_post_warmup_count": prov["materialized_post_warmup_count"],
            "materialized_schedule_duration_s": prov["materialized_schedule_duration_s"],
        })
    return rows


def _adversarial_schedule(corpus):
    """The single adversarial schedule. Shared by `generate` and `verify`."""
    # `long_context=True` selects from the corpus's q90 char_len tail. The cut
    # is a fixed Week 2 constant in `loadgen.corpus`, deliberately not a flag:
    # a sweepable cut would make this a length sweep, which §2.2 defers to
    # Week 3.
    schedule = build_poisson_schedule(ADVERSARIAL_LAMBDA, ADVERSARIAL_DURATION_S,
                                      ADVERSARIAL_SEED, corpus, long_context=True)
    schedule.provenance["workload_class"] = "adversarial_long_context"
    schedule.provenance["scenario"] = "adversarial"
    schedule.provenance["arrival_process"] = "adversarial"
    schedule.provenance["arrival_shape"] = "poisson"
    schedule.provenance["never_defines_headline_breach"] = True
    schedule.provenance["long_context_selection"] = (
        "corpus q90 char_len tail, fixed Week 2 constant "
        "(loadgen.corpus.draw_prompt_id_long_context). Not a knob: a sweepable cut would "
        "make this a length sweep, which WEEK2_PLAN.md 2.2 defers to Week 3.")
    schedule.provenance["note"] = (
        "Adversarial long-context flood (WEEK2_PLAN.md 2.1). A separate Week 2 scenario, "
        "NOT part of the baseline breach number: its cost is driven by per-request length, "
        "not arrival rate. Runs LAST -- it drives the replica toward saturation.")
    return schedule


def generate_adversarial(out_dir: Path) -> list[dict]:
    corpus = load_corpus()
    out_dir.mkdir(parents=True, exist_ok=True)
    schedule = _adversarial_schedule(corpus)

    path = out_dir / f"adversarial_rps{ADVERSARIAL_LAMBDA:g}.schedule.json"
    digest = write_json_artifact(path, schedule.to_dict())
    prov = schedule.provenance
    return [{
        "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "sha256": digest,
        "nominal_lambda_rps": ADVERSARIAL_LAMBDA,
        "arrival_process": "adversarial",
        "duration_s": ADVERSARIAL_DURATION_S,
        "n_scheduled": prov["n_scheduled"],
        "long_context": prov.get("long_context"),
    }]


def build_manifest(steady: list[dict], adversarial: list[dict]) -> dict:
    return {
        "what": "Frozen session #2 secondary scenarios: steady reference and adversarial "
                "long-context flood (lock 6A).",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision_provenance": "Operating points are human decisions recorded 2026-08-21; "
                               "WEEK2_PLAN.md 2.1 constrains the shape of both scenarios but "
                               "names no lambda for either.",
        "steady": {
            "schedule_scheme_version": "headline-schedule-v2",
            "workload_class": STEADY_WORKLOAD_CLASS,
            "canonical_workload": str(STEADY_WORKLOAD.relative_to(REPO_ROOT)).replace("\\", "/"),
            "lambdas": list(STEADY_LAMBDAS),
            "warmup_boundary_s": STEADY_WARMUP_S,
            "post_warmup_target_count": 500,
            "arrival_seed_base": STEADY_ARRIVAL_SEED_BASE,
            "assignment_seed_base": STEADY_ASSIGNMENT_SEED_BASE,
            "never_defines_headline_breach": True,
            "schedules": steady,
        },
        "adversarial": {
            "schedule_scheme_version": "loadgen-schedule-v1",
            "workload_class": "adversarial_long_context",
            "nominal_lambda_rps": ADVERSARIAL_LAMBDA,
            "duration_s": ADVERSARIAL_DURATION_S,
            "seed": ADVERSARIAL_SEED,
            "long_context_cut": "corpus q90 char_len, fixed constant",
            "execution_order": "LAST -- it drives the replica toward saturation",
            "never_defines_headline_breach": True,
            "schedules": adversarial,
        },
    }


def verify() -> int:
    """Regenerate in memory and compare against what is committed.

    The freeze is only worth anything if it reproduces: this checks that the
    committed bytes are what the recorded parameters produce, rather than what
    some earlier run of this script happened to produce.

    Three things this deliberately does NOT do quietly:

      - pass on an empty or short manifest. An earlier version compared only
        the rows the manifest listed, so an empty manifest beside an empty
        directory printed `VERIFY OK: 0 schedule(s)` and exited 0;
      - skip a missing file. It used to `continue`;
      - claim more than it checked. It said "6 regenerate byte-for-byte" while
        regenerating five -- adversarial was compared only against a hash the
        same invocation had written, which is circular.
    """
    if not MANIFEST_PATH.exists():
        print(f"FAIL: no manifest at {MANIFEST_PATH}")
        return 1
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    problems = []

    # The manifest must describe the family the generator is configured for,
    # not merely be internally consistent with itself.
    listed_lambdas = [row["nominal_lambda_rps"] for row in manifest["steady"]["schedules"]]
    if sorted(listed_lambdas) != sorted(STEADY_LAMBDAS):
        problems.append(f"steady manifest lists lambdas {sorted(listed_lambdas)}, "
                        f"generator produces {sorted(STEADY_LAMBDAS)}")
    if len(manifest["adversarial"]["schedules"]) != 1:
        problems.append("adversarial must be exactly one point, not a sweep "
                        f"(manifest lists {len(manifest['adversarial']['schedules'])})")

    listed_paths = set()
    for family in ("steady", "adversarial"):
        for row in manifest[family]["schedules"]:
            path = REPO_ROOT / row["path"]
            listed_paths.add(path.resolve())
            if not path.exists():
                problems.append(f"{row['path']}: listed in the manifest but missing on disk")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != row["sha256"]:
                problems.append(f"{row['path']}: sha256 {digest[:16]}... != manifest "
                                f"{row['sha256'][:16]}...")

    # ...and nothing may sit in these directories that the manifest does not
    # name. An unlisted schedule is an artifact nobody froze.
    for directory in (STEADY_DIR, ADVERSARIAL_DIR):
        for path in sorted(directory.glob("*.schedule.json")):
            if path.resolve() not in listed_paths:
                rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
                problems.append(f"{rel}: on disk but absent from the manifest")

    # Determinism: rebuild both families and compare bytes, without touching
    # the tree.
    corpus = load_corpus()
    workload = load_frozen(STEADY_WORKLOAD)
    rebuilt = 0
    for index, nominal_lambda in enumerate(STEADY_LAMBDAS):
        path = STEADY_DIR / f"secondary_steady_rps{nominal_lambda:g}.schedule.json"
        if not path.exists():
            continue
        schedule = _steady_schedule(workload, corpus, index, nominal_lambda)
        if json_artifact_bytes(schedule.to_dict()) != path.read_bytes():
            problems.append(f"{path.name}: regeneration does not reproduce the committed bytes")
        rebuilt += 1

    adversarial_path = ADVERSARIAL_DIR / f"adversarial_rps{ADVERSARIAL_LAMBDA:g}.schedule.json"
    if adversarial_path.exists():
        schedule = _adversarial_schedule(corpus)
        if json_artifact_bytes(schedule.to_dict()) != adversarial_path.read_bytes():
            problems.append(
                f"{adversarial_path.name}: regeneration does not reproduce the committed bytes")
        rebuilt += 1

    expected_total = len(STEADY_LAMBDAS) + 1
    if rebuilt != expected_total:
        problems.append(f"regenerated {rebuilt} of {expected_total} schedules -- the rest are "
                        "missing from the working tree")

    if problems:
        print("VERIFY FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"VERIFY OK: {rebuilt} secondary-scenario schedule(s) match the manifest and "
          "regenerate byte-for-byte; no unlisted artifacts present")
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

    steady = generate_steady(STEADY_DIR)
    adversarial = generate_adversarial(ADVERSARIAL_DIR)
    write_json_artifact(MANIFEST_PATH, build_manifest(steady, adversarial))

    print(f"steady reference: {len(steady)} schedule(s) under {STEADY_DIR.name}/")
    for row in steady:
        print(f"  lambda {row['nominal_lambda_rps']:<4g} "
              f"{row['materialized_schedule_count']:>5} total / "
              f"{row['materialized_warmup_count']:>4} warmup / "
              f"{row['materialized_post_warmup_count']:>4} post   "
              f"{row['materialized_schedule_duration_s']:.1f}s")
    total_s = sum(r["materialized_schedule_duration_s"] for r in steady)
    print(f"  total drive time: {total_s / 60:.1f} min")

    print(f"\nadversarial: {len(adversarial)} schedule(s) under {ADVERSARIAL_DIR.name}/")
    for row in adversarial:
        print(f"  lambda {row['nominal_lambda_rps']:g}  {row['n_scheduled']} arrivals over "
              f"{row['duration_s']:.0f}s  long_context={row['long_context']}")

    print(f"\nmanifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()

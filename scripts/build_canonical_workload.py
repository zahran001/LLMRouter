#!/usr/bin/env python
"""Build and freeze the canonical headline workload (R4 README R4A / R4C).

Two stages, deliberately separated, because R4C says the freeze may only
happen *after* the tokenizer capacity proof passes:

    --emit-candidate   select the membership, write canonical_v1.candidate.json
    (then run scripts/check_tokenizer_capacity.py)
    --freeze           verify the capacity report covers THIS membership and
                       passed, then write canonical_v1.json

The ordering is enforced here rather than documented, because "freeze only
after capacity validation" is the kind of step that is easy to skip once and
then never notice: a frozen workload that does not fit the server produces a
GPU session that dies on its first long prompt, at which point the workload is
already the thing every artifact references.

The freeze also refuses a capacity report for a *different* membership. The
two artifacts are joined on `membership_id`, so validating one candidate and
freezing another is a refusal rather than an accident.

Idempotent: freezing over an identical existing artifact is a no-op; freezing
over a *different* one is a refusal, because a frozen workload that silently
changes is not frozen.

Usage:
    .venv/Scripts/python.exe scripts/build_canonical_workload.py --emit-candidate
    .venv/Scripts/python.exe scripts/check_tokenizer_capacity.py
    .venv/Scripts/python.exe scripts/build_canonical_workload.py --freeze
    .venv/Scripts/python.exe scripts/build_canonical_workload.py --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from loadgen.canonical import (  # noqa: E402
    CANONICAL_N,
    CANONICAL_SELECTION_SEED,
    CanonicalWorkloadError,
    build,
    load_frozen,
)
from loadgen.corpus import load_corpus  # noqa: E402
from metrics.artifacts import json_artifact_bytes, write_json_artifact  # noqa: E402

WORKLOAD_ROOT = REPO_ROOT / "benchmarks" / "workloads"
HEADLINE_DIR = WORKLOAD_ROOT / "week2_headline"

# The Tier A scout workload is built through this same pipeline, into its own
# namespace. Same construction, smaller N, and -- critically -- the same R4C
# capacity gate, so a scout run cannot be the thing that discovers the context
# limit is too small. Separate directory so a scout membership can never be
# mistaken for the headline one.
SCOUT_DIR = WORKLOAD_ROOT / "week2_scout"


def paths(workload_dir: Path) -> tuple[Path, Path, Path]:
    return (workload_dir / "canonical_v1.candidate.json",
            workload_dir / "canonical_v1.json",
            workload_dir / "tokenizer_capacity_report.json")


def _describe(workload: dict) -> None:
    locks = workload["locks"]
    tail = workload["tail_support"]
    profile = workload["char_len_profile"]
    print(f"  membership_id  {workload['membership_id']}")
    print(f"  scheme         {workload['scheme_version']}")
    print(f"  k={locks['k']} ({locks['k_name']})  L=q{locks['L_pct']:g}={locks['L_chars']:.0f} chars  "
          f"N={locks['N']}  N_max={locks['N_max']}")
    print(f"  corpus         {workload['corpus']['sha256'][:16]}... ({workload['corpus']['size']} prompts)")
    print(f"  tail support   {tail['canonical_prompts_above_L']} prompts >= L "
          f"({tail['fraction_of_N'] * 100:.2f}% of N; corpus holds {tail['corpus_prompts_above_L']})")
    print(f"  char_len       p50={profile['quantiles']['50']:.0f} "
          f"p99={profile['quantiles']['99']:.0f} max={profile['max']:.0f}")
    print(f"  {'i':>2} {'q-range':>14} {'char range':>22} {'avail':>6} {'selected':>9}")
    for s in workload["strata"]:
        print(f"  {s['index']:>2} {str(s['quantile_range_pct']):>14} "
              f"{str([round(x, 1) for x in s['char_len_range']]):>22} "
              f"{s['available_count']:>6} {s['selected_count']:>9}")


def emit_candidate(n: int, seed: int, workload_dir: Path) -> int:
    CANDIDATE_PATH, FROZEN_PATH, CAPACITY_PATH = paths(workload_dir)
    workload = build(load_corpus(), n=n, seed=seed)
    workload["stage"] = "candidate"
    workload["built_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sha = write_json_artifact(CANDIDATE_PATH, workload)
    print("candidate canonical workload:")
    _describe(workload)
    print(f"\nwritten: {CANDIDATE_PATH.relative_to(REPO_ROOT)}  sha256={sha[:16]}...")
    print("\nNEXT: .venv/Scripts/python.exe scripts/check_tokenizer_capacity.py")
    print("      The freeze will refuse until that report exists, covers this membership_id,")
    print("      and says PASS (R4C).")
    return 0


def freeze(workload_dir: Path) -> int:
    CANDIDATE_PATH, FROZEN_PATH, CAPACITY_PATH = paths(workload_dir)
    if not CANDIDATE_PATH.exists():
        print(f"no candidate at {CANDIDATE_PATH.relative_to(REPO_ROOT)} -- run --emit-candidate first")
        return 1
    candidate = load_frozen(CANDIDATE_PATH)

    if not CAPACITY_PATH.exists():
        print(f"REFUSED: no tokenizer capacity report at "
              f"{CAPACITY_PATH.relative_to(REPO_ROOT)}.\n"
              "R4C freezes only after R4B passes. Run scripts/check_tokenizer_capacity.py.")
        return 1

    capacity = json.loads(CAPACITY_PATH.read_text(encoding="utf-8"))
    if capacity["workload"]["membership_id"] != candidate["membership_id"]:
        print("REFUSED: the capacity report covers a different membership.\n"
              f"  report:    {capacity['workload']['membership_id']}\n"
              f"  candidate: {candidate['membership_id']}\n"
              "Re-run the capacity check against the current candidate.")
        return 1
    if capacity["verdict"] != "PASS":
        print(f"REFUSED: capacity report verdict is {capacity['verdict']!r}, not PASS.\n"
              "Raise the context limit or have a human change the locked construction. Do not "
              "drop long prompts to make it fit.")
        return 1

    frozen = dict(candidate)
    frozen["stage"] = "frozen"
    frozen["frozen_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    frozen["capacity_proof"] = {
        "path": str(CAPACITY_PATH.relative_to(REPO_ROOT)).replace("\\", "/"),
        "sha256": hashlib.sha256(CAPACITY_PATH.read_bytes()).hexdigest(),
        "verdict": capacity["verdict"],
        "max_input_tokens": capacity["input_tokens"]["max"],
        "proposed_max_model_len": capacity["capacity"]["proposed_max_model_len"],
        "tokenizer_repo": capacity["tokenizer"]["gated_repo"],
        "tokenizer_repo_commit": capacity["tokenizer"]["gated_repo_commit"],
    }

    new_bytes = json_artifact_bytes(frozen)
    if FROZEN_PATH.exists():
        existing = json.loads(FROZEN_PATH.read_text(encoding="utf-8"))
        if existing["membership_id"] != frozen["membership_id"]:
            print("REFUSED: a DIFFERENT canonical workload is already frozen here.\n"
                  f"  frozen:    {existing['membership_id']}\n"
                  f"  candidate: {frozen['membership_id']}\n"
                  "A frozen workload that silently changes is not frozen. Every schedule and "
                  "artifact built against the existing one references its membership_id; "
                  "replacing it needs an explicit human decision and a new version.")
            return 1
        # Same membership -- only the timestamps differ. Keep the original
        # bytes so re-running the pipeline does not churn the artifact.
        print(f"already frozen with the same membership_id "
              f"({existing['membership_id'][:16]}...); leaving the artifact untouched")
        return 0

    sha = write_json_artifact(FROZEN_PATH, frozen)
    print("FROZEN canonical headline workload:")
    _describe(frozen)
    print(f"\n  capacity proof {frozen['capacity_proof']['verdict']}: "
          f"max_input={frozen['capacity_proof']['max_input_tokens']:,} tokens, "
          f"proposed --max-model-len={frozen['capacity_proof']['proposed_max_model_len']:,}")
    print(f"\nwritten: {FROZEN_PATH.relative_to(REPO_ROOT)}  sha256={sha[:16]}...")
    return 0


def verify(workload_dir: Path) -> int:
    CANDIDATE_PATH, FROZEN_PATH, CAPACITY_PATH = paths(workload_dir)
    if not FROZEN_PATH.exists():
        print(f"no frozen workload at {FROZEN_PATH.relative_to(REPO_ROOT)}")
        return 1
    frozen = load_frozen(FROZEN_PATH)
    rebuilt = build(load_corpus(), n=frozen["locks"]["N"], seed=frozen["selection"]["seed"])

    if rebuilt["membership"] != frozen["membership"]:
        print("VERIFY FAILED: deterministic rebuild produced a DIFFERENT membership.\n"
              f"  frozen:  {frozen['membership_id']}\n"
              f"  rebuilt: {rebuilt['membership_id']}")
        return 1

    # Byte-level: everything except the stage/timestamp/capacity fields, which
    # are added at freeze time and are not part of the construction.
    volatile = {"stage", "built_at", "frozen_at", "capacity_proof"}
    a = {k: v for k, v in frozen.items() if k not in volatile}
    b = {k: v for k, v in rebuilt.items() if k not in volatile}
    if json_artifact_bytes(a) != json_artifact_bytes(b):
        print("VERIFY FAILED: rebuild matches the membership but differs elsewhere "
              "(strata, provenance or profile) -- the construction changed underneath the "
              "frozen artifact")
        return 1

    print(f"VERIFY OK: {frozen['membership_id'][:16]}... regenerates byte-for-byte from "
          f"seed {frozen['selection']['seed']} against corpus "
          f"{frozen['corpus']['sha256'][:16]}...")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--emit-candidate", action="store_true")
    group.add_argument("--freeze", action="store_true")
    group.add_argument("--verify", action="store_true")
    parser.add_argument("--n", type=int, default=CANONICAL_N,
                        help="override N (refused above N_max)")
    parser.add_argument("--seed", type=int, default=CANONICAL_SELECTION_SEED)
    parser.add_argument("--scout", action="store_true",
                        help="build the Tier A scout workload into benchmarks/workloads/"
                             "week2_scout/ instead of the headline namespace")
    args = parser.parse_args()

    workload_dir = SCOUT_DIR if args.scout else HEADLINE_DIR

    try:
        if args.emit_candidate:
            raise SystemExit(emit_candidate(args.n, args.seed, workload_dir))
        if args.freeze:
            raise SystemExit(freeze(workload_dir))
        raise SystemExit(verify(workload_dir))
    except CanonicalWorkloadError as exc:
        print(f"\n{exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()

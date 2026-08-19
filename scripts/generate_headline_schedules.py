#!/usr/bin/env python
"""Generate the redesigned schedule families (R4 README R5/R6/R11).

Two families, written to separate namespaces because they answer different
questions and must never be pooled:

  headline   controlled matched workload -- the frozen canonical multiset,
             identical membership at every λ and in every repeat. Defines the
             breach RPS.
  secondary  natural-random ShareGPT draws, independently seeded. Answers
             whether the same knee survives unconstrained traffic. Never
             contributes a point to the headline classification.

The headline family's defining property is enforced in
`loadgen/headline_schedule.py`: each schedule is materialized offline until it
holds **exactly N post-warmup scheduled arrivals**, and the duration falls out
of the Poisson realization rather than being an input. Runtime drives the
frozen list to exhaustion.

Everything here is offline and GPU-free. Schedules are inputs; generate and
commit them before the meter starts.

Usage:
    .venv/Scripts/python.exe scripts/generate_headline_schedules.py \
        --repeats 3 --lambdas 1.5 2 2.5 3 4 --warmup-s 60
    .venv/Scripts/python.exe scripts/generate_headline_schedules.py --secondary
"""

from __future__ import annotations

import argparse
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
    build_headline_schedule,
    save_headline_schedule,
)
from loadgen.schedule import build_poisson_schedule  # noqa: E402
from metrics.artifacts import write_json_artifact  # noqa: E402

WORKLOAD = REPO_ROOT / "benchmarks" / "workloads" / "week2_headline" / "canonical_v1.json"
SCHEDULE_ROOT = REPO_ROOT / "benchmarks" / "schedules" / "week2_redesign"
HEADLINE_DIR = SCHEDULE_ROOT / "headline"
SECONDARY_DIR = SCHEDULE_ROOT / "secondary_natural"

# Seed bases. Per repeat the actual seeds are base + repeat_id, so the two
# streams stay independent of each other and reproducible from these two
# numbers plus the repeat index.
ARRIVAL_SEED_BASE = 20260819_000
ASSIGNMENT_SEED_BASE = 20260819_500
SECONDARY_SEED_BASE = 20260819_900

DEFAULT_LAMBDAS = (1.5, 2.0, 2.5, 3.0, 4.0)
DEFAULT_REPEATS = 3
# Deliberately generous. The per-point warmup value is still [CALIBRATE] and
# is resolved from session #2's transient -- but the boundary is FROZEN INTO
# the schedule, because exactly N arrivals were materialized at or after it.
# A resolved warmup larger than the boundary cannot be applied by re-filtering
# (it would discard canonical arrivals and leave fewer than N measured
# samples); the schedules would have to be regenerated. 60s buys that headroom
# for the cost of ~90-240 extra warmup requests per point, against 4,000
# measured ones.
DEFAULT_WARMUP_S = 60.0

# The secondary curve is a realism check, not a crossing measurement, so it is
# sized by duration rather than by the calibrated N. Stated explicitly so it
# is never mistaken for an under-powered headline point.
SECONDARY_DURATION_S = 600.0


def generate_headline(lambdas: tuple[float, ...], repeats: int, warmup_s: float,
                      out_dir: Path, workload_path: Path = WORKLOAD) -> list[dict]:
    workload = load_frozen(workload_path)
    corpus = load_corpus()
    written = []

    for repeat_id in range(1, repeats + 1):
        identity = RepeatIdentity(
            canonical_membership_id=workload["membership_id"],
            repeat_id=repeat_id,
            arrival_seed=ARRIVAL_SEED_BASE + repeat_id,
            assignment_seed=ASSIGNMENT_SEED_BASE + repeat_id,
        )
        for nominal_lambda in lambdas:
            schedule = build_headline_schedule(
                canonical=workload, corpus=corpus, identity=identity,
                nominal_lambda_rps=nominal_lambda, warmup_s=warmup_s)
            path, digest = save_headline_schedule(schedule, out_dir)
            prov = schedule.provenance
            written.append({
                "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                "sha256": digest,
                "repeat_id": repeat_id,
                "nominal_lambda_rps": nominal_lambda,
                "materialized_schedule_count": prov["materialized_schedule_count"],
                "materialized_warmup_count": prov["materialized_warmup_count"],
                "materialized_post_warmup_count": prov["materialized_post_warmup_count"],
                "materialized_schedule_duration_s": prov["materialized_schedule_duration_s"],
                "materialized_schedule_rps": prov["materialized_schedule_rps"],
                "nominal_realization_delta_pct":
                    100.0 * (prov["materialized_schedule_rps"] - nominal_lambda) / nominal_lambda,
            })
    return written


def generate_secondary(lambdas: tuple[float, ...], out_dir: Path,
                       duration_s: float = SECONDARY_DURATION_S) -> list[dict]:
    """Natural-random draws, the original §3.4 sampling rules, kept verbatim.

    This family is exactly what the headline stopped being: unconstrained
    i.i.d. draws over the pinned corpus, fixed duration, realized tail left to
    luck. That is the point -- it is the control for whether the controlled
    workload's knee is an artifact of the control.
    """
    corpus = load_corpus()
    written = []
    for nominal_lambda in lambdas:
        seed = SECONDARY_SEED_BASE + int(nominal_lambda * 10)
        schedule = build_poisson_schedule(nominal_lambda, duration_s, seed, corpus)
        schedule.provenance["workload_class"] = "secondary_natural_random"
        schedule.provenance["never_defines_headline_breach"] = True
        schedule.provenance["note"] = (
            "Natural-random secondary curve (R4 README R11). Realism validation only: its "
            "points must never be pooled with, or substituted for, controlled headline points.")
        rps = f"{nominal_lambda:g}"
        path = out_dir / f"secondary_rps{rps}.schedule.json"
        digest = write_json_artifact(path, schedule.to_dict())
        written.append({
            "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "sha256": digest,
            "nominal_lambda_rps": nominal_lambda,
            "n_scheduled": len(schedule.entries),
            "duration_s": duration_s,
            "seed": seed,
        })
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lambdas", type=float, nargs="+", default=list(DEFAULT_LAMBDAS))
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--warmup-s", type=float, default=DEFAULT_WARMUP_S)
    parser.add_argument("--secondary", action="store_true",
                        help="also generate the natural-random secondary family")
    parser.add_argument("--headline-dir", type=Path, default=HEADLINE_DIR)
    parser.add_argument("--secondary-dir", type=Path, default=SECONDARY_DIR)
    parser.add_argument("--workload", type=Path, default=WORKLOAD,
                        help="frozen canonical workload to build the family from")
    parser.add_argument("--scout", action="store_true",
                        help="Tier A scouting family: the week2_scout workload, one repeat, "
                             "written to a separate namespace so a diagnostic schedule can "
                             "never be driven as a headline point")
    args = parser.parse_args()

    if args.scout:
        args.workload = REPO_ROOT / "benchmarks" / "workloads" / "week2_scout" / "canonical_v1.json"
        args.headline_dir = SCHEDULE_ROOT / "scout"
        if args.repeats != DEFAULT_REPEATS:
            pass  # explicit override respected
        else:
            args.repeats = 1

    lambdas = tuple(args.lambdas)
    headline = generate_headline(lambdas, args.repeats, args.warmup_s, args.headline_dir,
                                 workload_path=args.workload)

    print(f"headline family: {len(headline)} schedule(s), "
          f"{args.repeats} repeat(s) x {len(lambdas)} lambda point(s), "
          f"warmup {args.warmup_s:g}s, format {HEADLINE_SCHEDULE_SCHEME_VERSION}")
    print(f"\n{'repeat':>7} {'lambda':>7} {'total':>7} {'warmup':>7} {'post':>6} "
          f"{'duration_s':>11} {'realized':>9} {'vs nominal':>11}")
    total_s = 0.0
    for row in headline:
        total_s += row["materialized_schedule_duration_s"]
        print(f"{row['repeat_id']:>7} {row['nominal_lambda_rps']:>7g} "
              f"{row['materialized_schedule_count']:>7} {row['materialized_warmup_count']:>7} "
              f"{row['materialized_post_warmup_count']:>6} "
              f"{row['materialized_schedule_duration_s']:>11.1f} "
              f"{row['materialized_schedule_rps']:>9.3f} "
              f"{row['nominal_realization_delta_pct']:>+10.2f}%")

    print(f"\ntotal headline drive time: {total_s / 3600:.2f} h "
          f"(schedule duration only -- excludes standup, drain and the response tail "
          "after the last arrival)")

    manifest = {
        "what": "Redesigned Week 2 schedule families (R4 README R5/R6/R11).",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "headline": {
            "schedule_scheme_version": HEADLINE_SCHEDULE_SCHEME_VERSION,
            "tier": "A_scout_diagnostic_only" if args.scout else "B_headline_confirmation",
            "canonical_workload": str(args.workload.relative_to(REPO_ROOT)).replace("\\", "/"),
            "canonical_membership_id": load_frozen(args.workload)["membership_id"],
            "lambdas": list(lambdas),
            "repeats": args.repeats,
            "warmup_s": args.warmup_s,
            "arrival_seed_base": ARRIVAL_SEED_BASE,
            "assignment_seed_base": ASSIGNMENT_SEED_BASE,
            "seed_rule": "arrival_seed = base + repeat_id; assignment_seed = base + repeat_id",
            "total_schedule_duration_s": total_s,
            "schedules": headline,
        },
    }

    if args.secondary:
        secondary = generate_secondary(lambdas, args.secondary_dir)
        manifest["secondary"] = {
            "workload_class": "secondary_natural_random",
            "duration_s": SECONDARY_DURATION_S,
            "seed_base": SECONDARY_SEED_BASE,
            "never_defines_headline_breach": True,
            "schedules": secondary,
        }
        print(f"\nsecondary family: {len(secondary)} schedule(s), natural-random draws, "
              f"{SECONDARY_DURATION_S:g}s each")
        for row in secondary:
            print(f"  rps{row['nominal_lambda_rps']:<5g} n={row['n_scheduled']:>5} "
                  f"seed={row['seed']}")

    manifest_name = "SCOUT_MANIFEST.json" if args.scout else "MANIFEST.json"
    manifest_path = SCHEDULE_ROOT / manifest_name
    write_json_artifact(manifest_path, manifest)
    print(f"\nwritten: {manifest_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

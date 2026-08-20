#!/usr/bin/env python
"""Generate frozen schedule artifacts for any set of RPS points
(WEEK2_PLAN.md §3.2/§5, WEEK2_EXECUTION.md Block D/E).

**Why this is generic.** Stage B's fine sweep is derived from Stage A's
bracket, which is only known mid-session (§6.2 step 4). A generator with a
hard-coded RPS list would mean editing tracked source on the meter -- and
`run_on_instance.sh bootstrap` pins the instance to a commit and refuses a
dirty tree, so an edit mid-session is not a small thing: it invalidates the
"which code drove this sweep" answer `BASELINE.md` has to give. This script
takes the points as arguments so Stage B is a command, not a patch.

Every workload lock is preserved because this does not reimplement anything:
it calls the same `loadgen.schedule` builders Stage A already used, so RNG
scheme, arrival/corpus stream independence, materialization-time prompt
assignment, the pinned corpus, the provenance header and replay compatibility
are all inherited rather than re-established here.

Two ways to name the points, both routing through the same code path:

    # explicit points
    python scripts/generate_schedules.py --rps 32 34 36 38

    # inclusive range
    python scripts/generate_schedules.py --rps-start 30 --rps-stop 40 --rps-step 2

Stage A is `scripts/generate_stage_a_schedules.py`, which is a thin wrapper
over `generate()` below -- one implementation, two entry points.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loadgen.corpus import DEFAULT_CORPUS_PATH, load_corpus
from loadgen.schedule import Schedule, build_poisson_schedule, build_steady_schedule

REPO_ROOT = Path(__file__).resolve().parent.parent

# Locked for the whole Week 2 baseline sweep. §2.2 requires every RPS point to
# draw from the SAME seeded ShareGPT sample, so the prompt-length contribution
# to p99 is held constant and only offered RPS moves across the sweep. Stage B
# MUST reuse this seed for its points to sit on the same curve as Stage A's.
BASELINE_SEED = 20260817

# [CALIBRATE] (§2.4) -- the real N comes off the Block F transient plot. The
# schedule does not need regenerating when N is resolved: the warmup filter is
# metrics-side and time-based, so a different N just discards more or less
# from the front by timestamp. Only an N large enough to shrink the
# post-warmup window below Y would force regeneration.
WARMUP_N_PLACEHOLDER_S = 10.0
WINDOW_Y_S = 120.0  # RESOLVED at Hard Stop 3, 2026-08-17 (WEEK2_PLAN.md §8)
DURATION_S = WARMUP_N_PLACEHOLDER_S + WINDOW_Y_S

BUILDERS = {"poisson": build_poisson_schedule, "steady": build_steady_schedule}


def _fmt_rps(rps: float) -> str:
    """`20` not `20.0`, `2.5` stays `2.5` -- keeps Stage A's committed
    filenames (poisson_rps20.schedule.json) byte-stable while still allowing
    fractional Stage B points."""
    return f"{rps:g}"


def frange(start: float, stop: float, step: float) -> list[float]:
    """Inclusive range tolerant of float drift.

    `stop` is included when it lands on a step boundary -- a fine sweep
    "between 30 and 40" that silently omitted 40 would leave the bracket's
    upper end unmeasured, which is the one point the operator explicitly
    asked for. Values are rounded to 6dp so 0.1-style steps do not produce
    30.000000000000004 in a filename.
    """
    if step <= 0:
        raise ValueError(f"--rps-step must be positive, got {step}")
    if stop < start:
        raise ValueError(f"--rps-stop ({stop}) must be >= --rps-start ({start})")
    points: list[float] = []
    i = 0
    while True:
        value = round(start + i * step, 6)
        if value > stop + 1e-9:
            break
        points.append(value)
        i += 1
    return points


def resolve_rps_points(args: argparse.Namespace) -> list[float]:
    """Turn either argument style into the one list `generate()` consumes."""
    explicit = args.rps is not None
    ranged = any(v is not None for v in (args.rps_start, args.rps_stop, args.rps_step))

    if explicit and ranged:
        raise SystemExit(
            "give EITHER --rps (explicit points) OR --rps-start/--rps-stop/--rps-step "
            "(a range), not both -- which one wins would otherwise be silent"
        )
    if not explicit and not ranged:
        raise SystemExit(
            "no RPS points given. Use --rps 32 34 36 38, or "
            "--rps-start 30 --rps-stop 40 --rps-step 2"
        )
    if explicit:
        if not args.rps:
            raise SystemExit("--rps needs at least one value")
        if any(r <= 0 for r in args.rps):
            raise SystemExit(f"RPS values must be positive, got {args.rps}")
        return list(args.rps)

    missing = [
        name for name, value in (
            ("--rps-start", args.rps_start), ("--rps-stop", args.rps_stop), ("--rps-step", args.rps_step)
        ) if value is None
    ]
    if missing:
        raise SystemExit(f"range mode needs all three of --rps-start/--rps-stop/--rps-step; missing {', '.join(missing)}")
    if args.rps_start <= 0:
        raise SystemExit(f"--rps-start must be positive, got {args.rps_start}")
    try:
        return frange(args.rps_start, args.rps_stop, args.rps_step)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def generate(
    rps_points: list[float],
    out_dir: Path,
    *,
    arrival_process: str = "poisson",
    seed: int = BASELINE_SEED,
    duration_s: float = DURATION_S,
    corpus_path: Path | str = DEFAULT_CORPUS_PATH,
    long_context: bool = False,
    prefix: str | None = None,
) -> list[tuple[float, Path, Schedule]]:
    """The single schedule-generation implementation. Both CLI modes and the
    Stage A wrapper land here, so there is exactly one place where a workload
    lock could be broken."""
    if arrival_process not in BUILDERS:
        raise SystemExit(f"unknown --arrival-process {arrival_process!r}; expected one of {sorted(BUILDERS)}")

    corpus = load_corpus(corpus_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    build = BUILDERS[arrival_process]
    name_prefix = arrival_process if prefix is None else prefix

    written: list[tuple[float, Path, Schedule]] = []
    for rps in rps_points:
        schedule = build(rps, duration_s, seed, corpus, long_context=long_context)
        path = out_dir / f"{name_prefix}_rps{_fmt_rps(rps)}.schedule.json"
        schedule.save(path)
        written.append((rps, path, schedule))
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_argument_group("RPS points (choose exactly one style)")
    mode.add_argument("--rps", type=float, nargs="+", default=None,
                      help="explicit points, e.g. --rps 32 34 36 38")
    mode.add_argument("--rps-start", type=float, default=None, dest="rps_start")
    mode.add_argument("--rps-stop", type=float, default=None, dest="rps_stop",
                      help="inclusive upper bound")
    mode.add_argument("--rps-step", type=float, default=None, dest="rps_step")

    parser.add_argument("--out-dir", required=True, type=Path,
                        help="where the .schedule.json artifacts land (e.g. benchmarks/schedules/stage_b)")
    parser.add_argument("--arrival-process", default="poisson", choices=sorted(BUILDERS),
                        dest="arrival_process",
                        help="poisson defines the headline breach RPS (§2.1); steady is the reference curve")
    parser.add_argument("--seed", type=int, default=BASELINE_SEED,
                        help=f"master seed; default {BASELINE_SEED} is the locked baseline seed. §2.2 requires "
                             "every point in the sweep to share it -- changing it puts the points on a "
                             "different curve")
    parser.add_argument("--duration-s", type=float, default=DURATION_S, dest="duration_s",
                        help=f"one continuous schedule, warmup + window (§2.4); default {DURATION_S}")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS_PATH))
    parser.add_argument("--long-context", action="store_true", dest="long_context",
                        help="adversarial long-context draw (§2.1) -- NOT the baseline workload")
    parser.add_argument("--prefix", default=None,
                        help="filename prefix; defaults to the arrival process")
    args = parser.parse_args()

    rps_points = resolve_rps_points(args)
    written = generate(
        rps_points, args.out_dir,
        arrival_process=args.arrival_process,
        seed=args.seed,
        duration_s=args.duration_s,
        corpus_path=args.corpus,
        long_context=args.long_context,
        prefix=args.prefix,
    )

    for rps, path, schedule in written:
        print(f"rps={_fmt_rps(rps):>6} -> {len(schedule.entries):>6} entries  {path}")
    print(f"\n{len(written)} schedule(s) written to {args.out_dir}")
    print(f"seed={args.seed} duration_s={args.duration_s} arrival={args.arrival_process}")
    print(
        "NOTE: the metrics-side warmup filter is time-based (§2.4), so these do NOT need "
        "regenerating when Block F resolves the real warmup N -- only an N large enough to "
        f"shrink the post-warmup window below Y={WINDOW_Y_S}s would."
    )


if __name__ == "__main__":
    main()

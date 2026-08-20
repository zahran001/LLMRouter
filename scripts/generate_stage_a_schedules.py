#!/usr/bin/env python
"""Pre-generate and commit the Stage A coarse-sweep schedules
(WEEK2_PLAN.md §6.2 step 3, WEEK2_EXECUTION.md Block D pre-flight) --
deterministic, so generated offline and committed; the GPU session just
drives them (§6.1: "they are deterministic, so generate offline, commit,
and the session just drives them").

**This is a thin wrapper over `scripts/generate_schedules.py`.** Stage A's
only distinguishing content is *which* RPS points it sweeps; everything else
(seed, duration, corpus, arrival process, provenance, filenames) comes from
the shared implementation, so Stage A and Stage B cannot drift apart. The
generic script is what Block E uses mid-session to produce Stage B's fine
bracket without editing tracked source.

RPS points: low anchor (2 RPS) to capture the unloaded floor, then wide steps
up through the range §6.2 names as an example (5/10/20/30/40/60/80). Poisson
only -- Poisson defines the baseline headline breach RPS (§2.1); the steady
reference curve (§6.2 step 5) and Stage B's fine schedules are generated with
the generic script, not here.

Usage:
    .venv/Scripts/python.exe scripts/generate_stage_a_schedules.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.generate_schedules import (
    BASELINE_SEED,
    DURATION_S,
    WARMUP_N_PLACEHOLDER_S,
    WINDOW_Y_S,
    generate,
)

STAGE_A_RPS_POINTS = [2, 5, 10, 20, 30, 40, 60, 80]

OUT_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "schedules" / "stage_a"


def main() -> None:
    # Passed through as ints, deliberately: the committed artifacts record
    # `"target_rps": 2`, and coercing to float here would rewrite every
    # frozen Stage A schedule as `2.0` -- a no-op for the workload but a diff
    # on an artifact whose whole job is to be immutable (§5).
    written = generate(
        STAGE_A_RPS_POINTS,
        OUT_DIR,
        arrival_process="poisson",
        seed=BASELINE_SEED,
        duration_s=DURATION_S,
    )

    for rps, path, schedule in written:
        print(f"rps={rps:>5g} -> {len(schedule.entries)} entries, {path}")

    print(f"\n{len(written)} schedules written to {OUT_DIR}")
    print(
        f"duration_s={DURATION_S} (warmup_N_placeholder={WARMUP_N_PLACEHOLDER_S}s + Y={WINDOW_Y_S}s). "
        "NOTE: if Block F's real GPU-derived warmup N later differs from the 10s placeholder, these "
        "schedules do NOT need regenerating -- the metrics-side warmup filter just discards more or "
        "less from the front by timestamp (§2.4). Only a real N *larger* than the schedule can absorb "
        f"without shrinking the post-warmup measurement window below Y={WINDOW_Y_S}s would require "
        "regenerating with a larger duration_s; unlikely at these placeholder magnitudes but worth a "
        "sanity check once Block F resolves N."
    )


if __name__ == "__main__":
    main()

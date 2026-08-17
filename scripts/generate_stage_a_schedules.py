#!/usr/bin/env python
"""Pre-generate and commit the Stage A coarse-sweep schedules
(WEEK2_PLAN.md §6.2 step 3, WEEK2_EXECUTION.md Block D pre-flight) --
deterministic, so generated offline and committed; the GPU session just
drives them (§6.1: "they are deterministic, so generate offline, commit,
and the session just drives them").

RPS points: low anchor (2 RPS) to capture the unloaded floor, then wide
steps up through the range §6.2 names as an example (5/10/20/30/40/60/80).
Poisson only -- Poisson defines the baseline headline breach RPS (§2.1);
the steady reference curve (§6.2 step 5) and Stage B's fine schedules
(generated live, mid-session, from Stage A's bracket) are not this script's
job.

Duration: BASELINE_WARMUP_N_PLACEHOLDER (10s, [CALIBRATE] -- real value
awaits GPU transient data, deferred per Hard Stop 3) + BASELINE_WINDOW_Y
(120s, confirmed at Hard Stop 3) = 130s. One continuous schedule per §2.4;
warmup is discarded metrics-side by timestamp, not re-generated if N's
real value later differs -- see the module docstring note below.

Usage:
    .venv/Scripts/python.exe scripts/generate_stage_a_schedules.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loadgen.corpus import load_corpus
from loadgen.schedule import build_poisson_schedule

# Locked for the whole Week 2 baseline sweep (coarse + fine + steady, if
# steady reuses it): WEEK2_PLAN.md §2.2 requires "every RPS point draws from
# the SAME seeded ShareGPT sample" so the prompt-length contribution to p99
# is held constant across the sweep -- only offered RPS moves. Do not vary
# this per RPS point.
BASELINE_SEED = 20260817

WARMUP_N_PLACEHOLDER_S = 10.0  # [CALIBRATE], deferred to Block F per Hard Stop 3 (2026-08-17)
WINDOW_Y_S = 120.0  # confirmed at Hard Stop 3 (2026-08-17)
DURATION_S = WARMUP_N_PLACEHOLDER_S + WINDOW_Y_S

STAGE_A_RPS_POINTS = [2, 5, 10, 20, 30, 40, 60, 80]

OUT_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "schedules" / "stage_a"


def main() -> None:
    corpus = load_corpus()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for rps in STAGE_A_RPS_POINTS:
        schedule = build_poisson_schedule(rps, DURATION_S, BASELINE_SEED, corpus)
        path = OUT_DIR / f"poisson_rps{rps}.schedule.json"
        schedule.save(path)
        print(f"rps={rps:3d} -> {len(schedule.entries)} entries, {path}")

    print(f"\n{len(STAGE_A_RPS_POINTS)} schedules written to {OUT_DIR}")
    print(
        f"duration_s={DURATION_S} (warmup_N_placeholder={WARMUP_N_PLACEHOLDER_S}s + Y={WINDOW_Y_S}s). "
        "NOTE: if Block F's real GPU-derived warmup N later differs from the 10s placeholder, these "
        "schedules do NOT need regenerating -- the metrics-side warmup filter just discards more or "
        "less from the front by timestamp (§2.4). Only a real N *larger* than the schedule can absorb "
        "without shrinking the post-warmup measurement window below Y=120s would require regenerating "
        "with a larger duration_s; unlikely at these placeholder magnitudes but worth a sanity check "
        "once Block F resolves N."
    )


if __name__ == "__main__":
    main()

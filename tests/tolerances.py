"""Tolerance constants for the deterministic eval (Tier 3).

These validate the PIPELINE against the mock's known timing -- not an
accuracy claim about real vLLM (WEEK1_MEASUREMENT_SPEC.md §4).

The two values the spec marks [CALIBRATE] (TOLERANCE_FLOOR_MS and
HIGH_VARIANCE_P99_OVER_P50_MULTIPLIER) are now locked from measurement --
see CALIBRATION_TASK.md and BENCHMARKS.md for provenance. Re-run
scripts/calibrate_noise_floor.py and re-derive rather than hand-tuning
either if the mock's timing behavior changes.
"""

from __future__ import annotations

# Calibrated (CALIBRATION_TASK.md Part A) from scripts/calibrate_noise_floor.py,
# fast config (100ms TTFT / 20ms TPOT -- floor-dominated: 10% of TPOT is only
# 2ms, so this config's tolerance is governed by the floor, not the
# percentage), 200 sequential runs (DRIVE_CONCURRENCY=1) x 110 requests/run,
# post-timing-fix (benchmarks/calibration/noise_floor/noise_floor_fast.json):
#
#   TTFT p50 across runs: mean=105.67ms stdev=0.88ms range=4.20ms
#                          max |p50 - 100ms configured| = 7.56ms
#   TPOT p50 across runs: mean=20.23ms  stdev=0.05ms range=0.27ms
#                          max |p50 - 20ms configured|  = 0.37ms
#
# The number that matters is max-deviation-from-CONFIGURED, not the centered
# spread: the hybrid_band assertion checks p50 against the raw configured
# value (ground truth stays the config, not a measured baseline -- see
# BENCHMARKS.md "Mock timing precision fix"), so a floor set only from
# stdev/range would ignore TTFT's systematic ~5-8ms structural offset (one-
# way latency: connection + send + role chunk + transport, WEEK1_MEASUREMENT_
# SPEC.md #2) and flake against it. TPOT has no such bias (it's a difference
# of two chunk arrivals, so constant per-chunk transport cancels out).
#
# TTFT's 7.56ms is both the binding case (>> TPOT's 0.37ms) and consistent
# with the independently-measured ~8-10ms structural TTFT floor from
# tests/mock/test_timing_accuracy.py's TTFT_TIGHT_BAND_MS (measured via a
# different method: direct per-request median, not p50-of-200-runs) --
# two independent measurements of the same physical constant converge, so
# 10ms (that already-validated value) is used here too, giving ~2.4ms
# margin above the worst observed deviation rather than shaving it thin.
# Tighter than the old 15ms placeholder, as expected post-fix.
TOLERANCE_FLOOR_MS = 10.0

TOLERANCE_PCT = 0.10

# Loose skew flag: mean must be within p50 + this many hybrid bands.
MEAN_SKEW_BAND_MULTIPLIER = 3.0

# Loose upper bound: p99 must be below this multiple of the configured
# value. Catches a broken (e.g. flat/mean-returning) percentile fn without
# flaking on legitimate tail noise from the *stable* configs.
P99_LOOSE_UPPER_MULTIPLIER = 2.0

# Calibrated (CALIBRATION_TASK.md Part B) from the measured high-variance
# tail: post-timing-fix, seeded, 150-request run gave p50=304.13ms,
# p99=1207.04ms -> p99/p50 = 3.97x (BENCHMARKS.md "Post-fix results"). The
# true tail is reproducible: the mock's per-request RNG is seedable
# (mock/app.py) and tests/eval/test_deterministic_eval.py:test_tail_computation
# already drives it with a fixed base seed (20260813, +i per request) over
# n=150 -- both of spec §5's reproducibility options (seed AND "enough
# samples"), not just one.
#
# 2.5x sits with margin on both sides of the two bounds it must separate:
#   - lower bound ~1.0-1.5x: what a broken/flat percentile fn (returns the
#     mean or median regardless of p) would produce, since it collapses
#     p50/p95/p99 together -- the multiplier must clear this to catch it.
#   - upper bound 3.97x: the measured true tail -- the multiplier must stay
#     below this with margin so the real tail passes without flaking on
#     stochastic dips.
# 2.5x is ~1x above the flat-p99 bound and ~1.5x below the true tail --
# comfortable margin on both sides, not tuned to either edge.
HIGH_VARIANCE_P99_OVER_P50_MULTIPLIER = 2.5


def hybrid_band(configured_ms: float) -> float:
    """max(±10ms, ±10% of configured) -- spec §4."""
    return max(TOLERANCE_FLOOR_MS, TOLERANCE_PCT * configured_ms)

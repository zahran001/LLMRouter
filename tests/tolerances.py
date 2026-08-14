"""Tolerance constants for the deterministic eval (Tier 3).

These validate the PIPELINE against the mock's known timing -- not an
accuracy claim about real vLLM (WEEK1_MEASUREMENT_SPEC.md §4).

Two values are marked [CALIBRATE] in the spec and are placeholders here on
purpose -- do not tune them by feel. See the calibration task:
scripts/calibrate_noise_floor.py.
"""

from __future__ import annotations

# [CALIBRATE] spec §4: "run one mock config 200x, observe run-to-run p50
# spread, set the floor just above observed jitter." Until that run happens,
# this is a placeholder chosen to be generous enough not to flake on the
# author's dev machine, NOT an empirically-measured noise floor. Re-run
# scripts/calibrate_noise_floor.py and replace this value before trusting
# the eval's pass/fail boundary for real.
TOLERANCE_FLOOR_MS = 15.0

TOLERANCE_PCT = 0.10

# Loose skew flag: mean must be within p50 + this many hybrid bands.
MEAN_SKEW_BAND_MULTIPLIER = 3.0

# Loose upper bound: p99 must be below this multiple of the configured
# value. Catches a broken (e.g. flat/mean-returning) percentile fn without
# flaking on legitimate tail noise from the *stable* configs.
P99_LOOSE_UPPER_MULTIPLIER = 2.0

# [CALIBRATE] spec §5 / METRICS_TEST_SUITE.md Tier 3: "pick a threshold the
# true tail clears comfortably but a broken (flat) p99 fails." This depends
# on the injected tail magnitude (mock/configs.py: TAIL_PROBABILITY,
# TAIL_MULTIPLIER), which is itself not yet calibrated against real
# noise-floor data. 1.5x is the spec's own placeholder pending that work --
# left as-is rather than guessed tighter/looser.
HIGH_VARIANCE_P99_OVER_P50_MULTIPLIER = 1.5


def hybrid_band(configured_ms: float) -> float:
    """max(±15ms [CALIBRATE], ±10% of configured) -- spec §4."""
    return max(TOLERANCE_FLOOR_MS, TOLERANCE_PCT * configured_ms)

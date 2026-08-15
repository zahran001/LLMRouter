"""The four locked mock configs (WEEK1_MEASUREMENT_SPEC.md §5).

This mock exists only to give the metrics module's integration/deterministic
tests (METRICS_TEST_SUITE.md Tiers 2-3) something real to drive over HTTP. It
is intentionally minimal: just enough of the streaming contract to be
faithful (§1), with the four named configs selectable per-request.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MockConfig:
    name: str
    ttft_ms: float
    tpot_ms: float
    heavy_tailed: bool


# Tail shape for the high-variance config: "a minority (e.g. ~5-10%) inject a
# large extra delay (e.g. 3-5x base)" (spec §5). These are ordinary generator
# parameters (not [CALIBRATE] items -- those are the 15ms tolerance floor and
# the p99 multiplier, which live in the test suite, not here).
TAIL_PROBABILITY = 0.08
TAIL_MULTIPLIER = 4.0

CONFIGS: dict[str, MockConfig] = {
    "fast": MockConfig(name="fast", ttft_ms=100, tpot_ms=20, heavy_tailed=False),
    "slow": MockConfig(name="slow", ttft_ms=500, tpot_ms=100, heavy_tailed=False),
    "bursty": MockConfig(name="bursty", ttft_ms=300, tpot_ms=50, heavy_tailed=False),
    "high-variance": MockConfig(
        name="high-variance", ttft_ms=300, tpot_ms=50, heavy_tailed=True
    ),
}

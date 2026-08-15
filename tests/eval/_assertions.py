"""Shared "what does a correct run look like" assertions for Tier 3.

Not a test module itself (no test_ prefix) -- imported by both
test_deterministic_eval.py (expects these to PASS on real pipeline output)
and test_negative_controls.py (expects these to RAISE on deliberately
broken output). One source of truth for "correct" keeps the negative
controls honest: they exercise the exact same gate the real eval uses.
"""

from __future__ import annotations

import pytest

from metrics.types import RunMetrics
from tests.tolerances import (
    HIGH_VARIANCE_P99_OVER_P50_MULTIPLIER,
    MEAN_SKEW_BAND_MULTIPLIER,
    P99_LOOSE_UPPER_MULTIPLIER,
    hybrid_band,
)


def assert_stable_config_pipeline_correct(result: RunMetrics, ttft_ms: float, tpot_ms: float) -> None:
    """METRICS_TEST_SUITE.md Tier 3, stable-config assertions (spec §4)."""
    assert result.valid, "run invalid: fewer than min_samples measured requests"

    ttft_band = hybrid_band(ttft_ms)
    tpot_band = hybrid_band(tpot_ms)

    # Tight gate: p50 must land within the hybrid band of the configured value.
    assert result.ttft_p50 == pytest.approx(ttft_ms, abs=ttft_band), (
        f"ttft p50 {result.ttft_p50:.2f}ms outside band {ttft_ms}+-{ttft_band}ms"
    )
    assert result.tpot_p50 == pytest.approx(tpot_ms, abs=tpot_band), (
        f"tpot p50 {result.tpot_p50:.2f}ms outside band {tpot_ms}+-{tpot_band}ms"
    )

    # Loose skew flag: a large p50/mean gap signals an unexpected heavy tail.
    assert result.ttft_mean <= result.ttft_p50 + MEAN_SKEW_BAND_MULTIPLIER * ttft_band, (
        f"ttft mean {result.ttft_mean:.2f}ms too far above p50 {result.ttft_p50:.2f}ms"
    )
    assert result.tpot_mean <= result.tpot_p50 + MEAN_SKEW_BAND_MULTIPLIER * tpot_band, (
        f"tpot mean {result.tpot_mean:.2f}ms too far above p50 {result.tpot_p50:.2f}ms"
    )

    # Loose upper bound: catches a broken percentile fn without flaking on
    # legitimate tail noise from a *stable* config.
    assert result.ttft_p99 < P99_LOOSE_UPPER_MULTIPLIER * ttft_ms, (
        f"ttft p99 {result.ttft_p99:.2f}ms >= {P99_LOOSE_UPPER_MULTIPLIER}x configured {ttft_ms}ms"
    )


def assert_high_variance_tail_correct(result: RunMetrics, base_ttft_ms: float) -> None:
    """METRICS_TEST_SUITE.md Tier 3, high-variance tail assertions (spec §5)."""
    assert result.valid, "run invalid: fewer than min_samples measured requests"

    band = hybrid_band(base_ttft_ms)
    # The tail must not move the median: p50 stays near the base config.
    assert result.ttft_p50 == pytest.approx(base_ttft_ms, abs=band), (
        f"ttft p50 {result.ttft_p50:.2f}ms outside band {base_ttft_ms}+-{band}ms "
        "-- the tail should not move the median"
    )

    # p99 must be meaningfully elevated above p50 -- proves the tail was
    # captured, not flattened.
    assert result.ttft_p99 > result.ttft_p50 * HIGH_VARIANCE_P99_OVER_P50_MULTIPLIER, (
        f"ttft p99 {result.ttft_p99:.2f}ms not elevated enough above p50 "
        f"{result.ttft_p50:.2f}ms (need > {HIGH_VARIANCE_P99_OVER_P50_MULTIPLIER}x)"
    )

    # Strict ordering: a broken percentile impl often violates this.
    assert result.ttft_p99 > result.ttft_p95 > result.ttft_p50, (
        f"percentile ordering violated: p99={result.ttft_p99:.2f} "
        f"p95={result.ttft_p95:.2f} p50={result.ttft_p50:.2f}"
    )

"""Tier 3 -- the deterministic eval: the bulletproof gate.

One parametrized test across the three stable configs, plus a dedicated
tail test for the high-variance config (the only one that can actually
catch a broken p95/p99 -- see METRICS_TEST_SUITE.md Tier 3).
"""

from __future__ import annotations

import pytest

from metrics.compute import aggregate
from mock.configs import CONFIGS
from tests.eval._assertions import assert_high_variance_tail_correct, assert_stable_config_pipeline_correct
from tests.helpers import drive_requests

pytestmark = [pytest.mark.integration, pytest.mark.eval]

WARMUP = 10
MIN_SAMPLES = 100
STABLE_CONFIGS = ["fast", "slow", "bursty"]

# Concurrency=1 (fully sequential) is deliberate, not a performance
# oversight: this single-process Starlette/uvicorn dev mock's delivered
# TTFT degrades roughly linearly with concurrent streams (measured +7ms at
# concurrency=1 up to +75ms at concurrency=15 for the SAME config, and
# confirmed via an A/B test to be identical whether the mock uses
# precise_sleep or bare asyncio.sleep -- so it is not a spin-wait
# regression, it's this mock's single-process throughput ceiling under
# concurrent SSE streams). See BENCHMARKS.md for the full measurement.
# Sequential driving keeps this eval measuring pipeline correctness against
# the mock's precise per-stream timing, not this server's concurrent
# throughput -- a different, real limitation that a production-grade mock
# (or the eventual router benchmark) would need to address separately.
DRIVE_CONCURRENCY = 1


@pytest.mark.parametrize("config_name", STABLE_CONFIGS)
async def test_pipeline_correct(config_name, mock_base_url):
    cfg = CONFIGS[config_name]
    samples = await drive_requests(
        mock_base_url, config_name, n=WARMUP + MIN_SAMPLES, num_tokens=5,
        concurrency=DRIVE_CONCURRENCY,
    )
    result = aggregate(
        samples, warmup=WARMUP, min_samples=MIN_SAMPLES,
        config={"name": config_name, "ttft_ms": cfg.ttft_ms, "tpot_ms": cfg.tpot_ms},
    )
    assert_stable_config_pipeline_correct(result, ttft_ms=cfg.ttft_ms, tpot_ms=cfg.tpot_ms)


async def test_tail_computation(mock_base_url):
    cfg = CONFIGS["high-variance"]
    # More measured requests than the stable-config tests: the tail is
    # stochastic (~8% of requests per mock/configs.py), so a larger sample
    # makes p95/p99 estimates reliable rather than noisy. Seeded for
    # reproducibility (spec §5 offers seeding OR "run enough samples" --
    # doing both). Kept at 150 rather than a larger count specifically
    # because concurrency=1 (see DRIVE_CONCURRENCY) makes each additional
    # sample cost real wall-clock time; 150 measured * ~8% tail rate is
    # still ~12 tail draws, enough to move p95/p99 measurably.
    n_measured = 150
    samples = await drive_requests(
        mock_base_url, "high-variance", n=WARMUP + n_measured, num_tokens=5,
        concurrency=DRIVE_CONCURRENCY, seed=20260813,
    )
    result = aggregate(
        samples, warmup=WARMUP, min_samples=MIN_SAMPLES,
        config={"name": "high-variance", "ttft_ms": cfg.ttft_ms, "tpot_ms": cfg.tpot_ms},
    )
    assert_high_variance_tail_correct(result, base_ttft_ms=cfg.ttft_ms)

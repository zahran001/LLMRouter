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


@pytest.mark.parametrize("config_name", STABLE_CONFIGS)
async def test_pipeline_correct(config_name, mock_base_url):
    cfg = CONFIGS[config_name]
    samples = await drive_requests(
        mock_base_url, config_name, n=WARMUP + MIN_SAMPLES, num_tokens=5, concurrency=10
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
    # doing both).
    n_measured = 300
    samples = await drive_requests(
        mock_base_url, "high-variance", n=WARMUP + n_measured, num_tokens=5,
        concurrency=15, seed=20260813,
    )
    result = aggregate(
        samples, warmup=WARMUP, min_samples=MIN_SAMPLES,
        config={"name": "high-variance", "ttft_ms": cfg.ttft_ms, "tpot_ms": cfg.tpot_ms},
    )
    assert_high_variance_tail_correct(result, base_ttft_ms=cfg.ttft_ms)

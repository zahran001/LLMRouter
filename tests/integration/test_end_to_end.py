"""Tier 2 -- integration tests against the live mock.

Drives real HTTP through metrics.consume_stream, confirming the full
consume -> aggregate path, not just the pure core in isolation.
"""

from __future__ import annotations

import statistics

import pytest

from metrics.compute import aggregate
from tests.helpers import drive_requests
from tests.tolerances import hybrid_band

pytestmark = pytest.mark.integration


async def test_end_to_end_fast_config(mock_base_url):
    warmup, min_samples = 10, 100
    samples = await drive_requests(mock_base_url, "fast", n=warmup + min_samples, num_tokens=5)
    result = aggregate(samples, warmup=warmup, min_samples=min_samples, config={"name": "fast"})

    assert result.valid is True
    assert result.ttft_p50 == pytest.approx(100.0, abs=hybrid_band(100.0))
    assert result.tpot_p50 == pytest.approx(20.0, abs=hybrid_band(20.0))


async def test_metadata_recorded(mock_base_url):
    warmup, min_samples = 10, 100
    samples = await drive_requests(mock_base_url, "fast", n=warmup + min_samples, num_tokens=5)
    result = aggregate(samples, warmup=warmup, min_samples=min_samples, config={"name": "fast", "ttft_ms": 100, "tpot_ms": 20})
    record = result.to_dict()

    for key in (
        "config", "n_requests", "n_warmup_discarded", "n_ttft_samples", "n_tpot_samples",
        "valid", "ttft_p50", "ttft_p95", "ttft_p99", "ttft_mean",
        "tpot_p50", "tpot_p95", "tpot_p99", "tpot_mean", "raw_ttft_ms", "raw_tpot_ms",
    ):
        assert key in record

    assert record["config"] == {"name": "fast", "ttft_ms": 100, "tpot_ms": 20}
    assert record["n_requests"] == min_samples
    assert record["n_warmup_discarded"] == warmup
    assert record["n_ttft_samples"] == len(record["raw_ttft_ms"])
    assert record["n_tpot_samples"] == len(record["raw_tpot_ms"])
    assert record["valid"] is True


async def test_connection_pooling_active(mock_base_url):
    # Soft check (per METRICS_TEST_SUITE.md Tier 2): post-warmup TTFT
    # variance should be low for a stable config once the connection pool
    # is warm -- a per-request handshake spike would show up as a much
    # wider spread than the mock's own scheduling jitter.
    warmup, min_samples = 10, 100
    samples = await drive_requests(mock_base_url, "fast", n=warmup + min_samples, num_tokens=3)
    result = aggregate(samples, warmup=warmup, min_samples=min_samples, config={"name": "fast"})

    assert result.valid is True
    stdev = statistics.pstdev(result.raw_ttft_ms)
    # Generous bound: a real per-request TCP/TLS handshake would add tens
    # of ms of spread on top of the configured 100ms wait, not this.
    assert stdev < hybrid_band(100.0) * 3

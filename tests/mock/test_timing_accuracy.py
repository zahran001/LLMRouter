"""Mock timing accuracy self-test (AGENT_TIMING_FIX_BRIEF.md Part 2).

Tests ONE claim, kept deliberately separate from the metrics pipeline: is
the mock's DELIVERED timing faithful to its configured target? This is not
"does the pipeline measure correctly" (that's Tier 3, tests/eval/) and not
"is the percentile fn right" (that's Tier 1, tests/unit/) -- conflating
these would mean a failure here could be misdiagnosed as a pipeline bug,
or vice versa.

Drives the mock directly over HTTP and computes medians with stdlib
statistics.median, deliberately NOT via metrics.compute.percentile/aggregate
-- this test must not depend on the correctness of the code it's meant to
be independent of.
"""

from __future__ import annotations

import json
import statistics
import time

import httpx
import pytest

from mock.configs import CONFIGS

pytestmark = pytest.mark.integration

STABLE_CONFIGS = ["fast", "slow", "bursty"]
TIGHT_BAND_MS = 5.0  # stricter than the pipeline eval's hybrid band on purpose
N_REQUESTS = 40
NUM_TOKENS = 5


async def _measure_one(client: httpx.AsyncClient, url: str, config_name: str) -> tuple[float, list[float]]:
    """Return (ttft_ms, [tpot_gap_ms, ...]) from raw chunk arrival times,
    with no metrics.parse/metrics.compute involvement beyond plain json."""
    t0 = time.perf_counter()
    content_times: list[float] = []
    async with client.stream(
        "POST", url, params={"config": config_name, "num_tokens": NUM_TOKENS},
        json={"model": "mock", "messages": []},
    ) as response:
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if payload == "[DONE]":
                break
            chunk = json.loads(payload)
            content = chunk["choices"][0]["delta"].get("content")
            if content:
                content_times.append(time.perf_counter())

    ttft_ms = (content_times[0] - t0) * 1000.0
    tpot_gaps_ms = [
        (content_times[i] - content_times[i - 1]) * 1000.0 for i in range(1, len(content_times))
    ]
    return ttft_ms, tpot_gaps_ms


@pytest.mark.parametrize("config_name", STABLE_CONFIGS)
async def test_mock_timing_accuracy(config_name, mock_base_url):
    cfg = CONFIGS[config_name]
    url = f"{mock_base_url}/v1/chat/completions"

    ttfts: list[float] = []
    all_tpot_gaps: list[float] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for _ in range(N_REQUESTS):
            ttft_ms, tpot_gaps_ms = await _measure_one(client, url, config_name)
            ttfts.append(ttft_ms)
            all_tpot_gaps.extend(tpot_gaps_ms)

    ttft_median = statistics.median(ttfts)
    tpot_median = statistics.median(all_tpot_gaps)
    ttft_overshoot = ttft_median - cfg.ttft_ms
    tpot_overshoot = tpot_median - cfg.tpot_ms

    print(
        f"\n[mock timing accuracy] {config_name}: "
        f"ttft median={ttft_median:.2f}ms (configured {cfg.ttft_ms}ms, overshoot {ttft_overshoot:+.2f}ms) "
        f"tpot median={tpot_median:.2f}ms (configured {cfg.tpot_ms}ms, overshoot {tpot_overshoot:+.2f}ms)"
    )

    assert ttft_median == pytest.approx(cfg.ttft_ms, abs=TIGHT_BAND_MS), (
        f"mock delivered TTFT median {ttft_median:.2f}ms, configured {cfg.ttft_ms}ms "
        f"(overshoot {ttft_overshoot:+.2f}ms) -- outside the {TIGHT_BAND_MS}ms mock-fidelity band"
    )
    assert tpot_median == pytest.approx(cfg.tpot_ms, abs=TIGHT_BAND_MS), (
        f"mock delivered TPOT median {tpot_median:.2f}ms, configured {cfg.tpot_ms}ms "
        f"(overshoot {tpot_overshoot:+.2f}ms) -- outside the {TIGHT_BAND_MS}ms mock-fidelity band"
    )

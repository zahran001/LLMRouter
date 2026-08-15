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
N_REQUESTS = 40
NUM_TOKENS = 5

# TPOT is a DIFFERENCE between two chunk arrival times, so per-chunk HTTP/
# ASGI transport latency (request write, socket round trip, httpx line
# parsing) cancels out of the subtraction as long as it's roughly constant
# per chunk -- and precise_sleep's own overshoot is <0.2ms in isolation
# (see mock/timing.py). Measured post-fix TPOT overshoot: +0.34 to +0.42ms
# across fast/slow/bursty. 5ms leaves comfortable headroom.
TPOT_TIGHT_BAND_MS = 5.0

# TTFT is measured from t0 (before .send() is awaited) to the first content
# chunk's arrival -- a ONE-WAY latency, so unlike TPOT it does NOT get to
# cancel a per-chunk transport constant against anything. It structurally
# includes connection + request-send + role-chunk + ASGI/transport delivery
# time, which spec (WEEK1_MEASUREMENT_SPEC.md #2) deliberately says TTFT
# SHOULD include -- precise_sleep controls wait *duration*, not this
# surrounding machinery, so it cannot and should not remove this.
#
# Measured post-fix TTFT overshoot (median, 40 req/run, warm connection
# pool, this dev machine): fast +8.54ms, +7.80ms (rerun); slow +8.40ms;
# bursty +7.97ms -- config-independent (as expected for a fixed transport
# constant, not a scaled timer error) and consistent within ~0.7ms across
# four independent runs. 10ms clears that measured floor with headroom
# without being loose enough to hide a real regression.
TTFT_TIGHT_BAND_MS = 10.0


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

    assert ttft_median == pytest.approx(cfg.ttft_ms, abs=TTFT_TIGHT_BAND_MS), (
        f"mock delivered TTFT median {ttft_median:.2f}ms, configured {cfg.ttft_ms}ms "
        f"(overshoot {ttft_overshoot:+.2f}ms) -- outside the {TTFT_TIGHT_BAND_MS}ms mock-fidelity band"
    )
    assert tpot_median == pytest.approx(cfg.tpot_ms, abs=TPOT_TIGHT_BAND_MS), (
        f"mock delivered TPOT median {tpot_median:.2f}ms, configured {cfg.tpot_ms}ms "
        f"(overshoot {tpot_overshoot:+.2f}ms) -- outside the {TPOT_TIGHT_BAND_MS}ms mock-fidelity band"
    )

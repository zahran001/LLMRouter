"""Negative controls -- prove the Tier 3 gate actually catches broken measurement.

A test suite that only ever passes proves nothing. These deliberately break
the pipeline in two specific, realistic ways and assert the SAME assertion
helpers used by the real eval (tests/eval/_assertions.py) reject the
result. If either of these tests fails (i.e. the broken pipeline still
passes), the eval has no teeth and must not be trusted.
"""

from __future__ import annotations

import time

import pytest

from metrics import compute, parse
from metrics.compute import aggregate
from metrics.types import ChunkEvent, RequestSample
from mock.configs import CONFIGS
from tests.eval._assertions import assert_high_variance_tail_correct, assert_stable_config_pipeline_correct
from tests.helpers import drive_requests
from tests.tolerances import hybrid_band

pytestmark = [pytest.mark.integration, pytest.mark.negative_control]

WARMUP = 10
MIN_SAMPLES = 100
# See tests/eval/test_deterministic_eval.py:DRIVE_CONCURRENCY -- sequential
# driving keeps the mock's delivered timing precise (concurrent SSE streams
# on this single-process dev mock degrade TTFT independent of which sleep
# primitive it uses; see BENCHMARKS.md). The "sanity: real pipeline passes
# before we break it" check below needs that precision to mean anything.
DRIVE_CONCURRENCY = 1


async def test_broken_percentile_would_fail(mock_base_url, monkeypatch):
    """A percentile fn that returns the mean regardless of p must fail the
    high-variance tail test: it flattens p50/p95/p99 to the same value,
    which both breaks the strict p99 > p95 > p50 ordering and (since the
    mean of a right-skewed distribution isn't 1.5x the true median here)
    the "p99 elevated above p50" check.
    """
    cfg = CONFIGS["high-variance"]
    samples = await drive_requests(
        mock_base_url, "high-variance", n=WARMUP + 150, num_tokens=5,
        concurrency=DRIVE_CONCURRENCY, seed=999,
    )

    # Sanity: the real pipeline passes on this data before we break it --
    # otherwise this test would "pass" for the wrong reason (data problem,
    # not a broken-percentile-detection problem).
    good_result = aggregate(
        samples, warmup=WARMUP, min_samples=MIN_SAMPLES,
        config={"name": "high-variance", "ttft_ms": cfg.ttft_ms},
    )
    assert_high_variance_tail_correct(good_result, base_ttft_ms=cfg.ttft_ms)

    def broken_percentile(values, p):
        # Deliberately wrong: ignores p entirely, always returns the mean.
        return float(sum(values) / len(values))

    monkeypatch.setattr(compute, "percentile", broken_percentile)

    broken_result = aggregate(
        samples, warmup=WARMUP, min_samples=MIN_SAMPLES,
        config={"name": "high-variance", "ttft_ms": cfg.ttft_ms},
    )
    with pytest.raises(AssertionError):
        assert_high_variance_tail_correct(broken_result, base_ttft_ms=cfg.ttft_ms)


def _leaky_request_sample_from_events(events: list[ChunkEvent], t0: float) -> RequestSample:
    """BROKEN on purpose: the first "TPOT" gap is measured from t0 (the TTFT
    reference point) instead of from the previous CONTENT chunk -- i.e. it
    sleeps the TTFT wait into the first TPOT gap, inflating it by ~TTFT on
    top of what should have been a real ~tpot_ms gap. This is exactly the
    bug metrics.compute.request_sample_from_events must not have.

    Uses num_tokens=2 (see test below): with only one real content-to-
    content gap per request, corrupting "the first gap" corrupts the
    request's *entire* TPOT contribution, so the effect isn't diluted away
    by other, uncorrupted gaps once flattened across many requests.
    """
    content_events = [e for e in events if e.is_content]
    if not content_events:
        return RequestSample(ttft_ms=None, tpot_samples_ms=[], content_chunk_count=0, error="no_content_chunks")

    ttft_ms = (content_events[0].recv_time - t0) * 1000.0
    if len(content_events) < 2:
        return RequestSample(ttft_ms=ttft_ms, tpot_samples_ms=[], content_chunk_count=len(content_events), error=None)

    leaked_first_gap_ms = (content_events[1].recv_time - t0) * 1000.0  # BUG: should be - content_events[0].recv_time
    real_gaps_ms = [
        (content_events[i].recv_time - content_events[i - 1].recv_time) * 1000.0
        for i in range(2, len(content_events))
    ]
    tpot_samples_ms = [leaked_first_gap_ms] + real_gaps_ms

    return RequestSample(
        ttft_ms=ttft_ms, tpot_samples_ms=tpot_samples_ms,
        content_chunk_count=len(content_events), error=None,
    )


async def _consume_stream_leaky(response, t0: float, clock=time.perf_counter) -> RequestSample:
    """A consumer variant that leaks the TTFT wait into the first TPOT gap
    (spec's negative-control scenario), built by swapping in the broken
    pure function above -- everything else mirrors metrics.consume_stream.
    """
    events: list[ChunkEvent] = []
    async for line in response.aiter_lines():
        parsed = parse.parse_sse_line(line)
        if parsed is None:
            continue
        if parsed == parse.DONE:
            break
        recv_time = clock()
        is_content = parse.is_content_chunk(parsed)
        content = parse.extract_content(parsed) if is_content else None
        events.append(ChunkEvent(recv_time=recv_time, is_content=is_content, content=content, raw=parsed))
    return _leaky_request_sample_from_events(events, t0)


async def test_leaked_ttft_into_tpot_would_fail(mock_base_url):
    """Drive the fast config (ttft=100ms, tpot=20ms) through the leaky
    consumer: the first (here, only) TPOT sample per request becomes
    ~t0-to-second-content-chunk (~TTFT-sized, ~100ms+) instead of a real
    ~20ms inter-token gap. That should drag TPOT p50 well outside the
    hybrid band and the eval must catch it.
    """
    import asyncio

    import httpx

    cfg = CONFIGS["fast"]
    n = WARMUP + MIN_SAMPLES
    url = f"{mock_base_url}/v1/chat/completions"
    sem = asyncio.Semaphore(DRIVE_CONCURRENCY)

    async def drive_one_leaky(client: httpx.AsyncClient) -> RequestSample:
        async with sem:
            t0 = time.perf_counter()
            async with client.stream(
                "POST", url, params={"config": "fast", "num_tokens": 2},
                json={"model": "mock", "messages": []},
            ) as response:
                return await _consume_stream_leaky(response, t0)

    async with httpx.AsyncClient(timeout=30.0) as client:
        samples = await asyncio.gather(*[drive_one_leaky(client) for _ in range(n)])

    broken_result = aggregate(
        samples, warmup=WARMUP, min_samples=MIN_SAMPLES,
        config={"name": "fast", "ttft_ms": cfg.ttft_ms, "tpot_ms": cfg.tpot_ms},
    )

    # Direct, unambiguous proof of the mechanism: TPOT p50 is corrupted by
    # roughly the TTFT magnitude, independent of any TTFT-side assertion.
    assert broken_result.tpot_p50 > cfg.tpot_ms + hybrid_band(cfg.tpot_ms), (
        f"leaked TPOT p50 {broken_result.tpot_p50:.2f}ms did not blow out "
        f"of the {cfg.tpot_ms}ms band -- negative control has no teeth"
    )

    with pytest.raises(AssertionError):
        assert_stable_config_pipeline_correct(broken_result, ttft_ms=cfg.ttft_ms, tpot_ms=cfg.tpot_ms)

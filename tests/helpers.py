"""Test-only helper: drive N requests against the live mock and collect
RequestSamples in submission order.

This is test scaffolding, not the loadgen (out of scope per
AGENT_METRICS_BRIEF.md §7) -- it exists only so Tier 2/3 tests can exercise
metrics.consume_stream over real HTTP without reimplementing a driver in
every test file.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from metrics.consume import consume_stream
from metrics.types import RequestSample


async def _drive_one(
    client: httpx.AsyncClient, url: str, params: dict, json_body: dict
) -> RequestSample:
    # t0 captured immediately before the send is awaited, per the
    # consume_stream contract (WEEK1_MEASUREMENT_SPEC.md §2).
    t0 = time.perf_counter()
    async with client.stream("POST", url, params=params, json=json_body) as response:
        return await consume_stream(response, t0)


async def drive_requests(
    base_url: str,
    config: str,
    n: int,
    num_tokens: int = 5,
    seed: int | None = None,
    concurrency: int = 20,
) -> list[RequestSample]:
    """Fire n requests at the mock's /v1/chat/completions.

    Returns results in submission order (index 0..n-1), regardless of
    completion order, so callers can rely on warmup-discard-by-order being
    well-defined. Bounded to `concurrency` requests in flight at once to
    keep wall-clock time down without serializing everything.
    """
    url = f"{base_url}/v1/chat/completions"
    limits = httpx.Limits(max_connections=concurrency + 5, max_keepalive_connections=concurrency + 5)
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(timeout=30.0, limits=limits) as client:

        async def bounded(i: int) -> RequestSample:
            async with sem:
                params = {"config": config, "num_tokens": num_tokens}
                if seed is not None:
                    # Vary per request so a fixed seed doesn't replay the
                    # exact same tail/no-tail draw on every request.
                    params["seed"] = seed + i
                return await _drive_one(client, url, params, {"model": "mock", "messages": []})

        tasks = [asyncio.create_task(bounded(i)) for i in range(n)]
        return await asyncio.gather(*tasks)

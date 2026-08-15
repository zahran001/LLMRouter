"""Thin streaming consumer — the only I/O in this module.

Reads an SSE response as it arrives, timestamps each parsed chunk with a
monotonic clock, and hands the timestamped events to the pure
metrics.compute.request_sample_from_events for the actual TTFT/TPOT math.
This file must not contain timing *logic* — only timing *capture*.
"""

from __future__ import annotations

import time
from typing import Callable, Protocol

from metrics import compute, parse
from metrics.types import ChunkEvent, RequestSample


class _LineStreamingResponse(Protocol):
    def aiter_lines(self): ...  # async iterator of str


async def consume_stream(
    response: _LineStreamingResponse,
    t0: float,
    clock: Callable[[], float] = time.perf_counter,
) -> RequestSample:
    """Consume one SSE response and return its RequestSample.

    Contract (WEEK1_MEASUREMENT_SPEC.md §2):
    - `t0` MUST be captured by the caller BEFORE awaiting the HTTP client's
      `.send()` / `.stream()` call that produced `response` — i.e. before
      this function is even invoked. This deliberately includes connection
      + request-send time in TTFT. This function never reads a "start" time
      itself; it only ever measures forward from the t0 you hand it.
    - `clock` MUST be a monotonic clock (default time.perf_counter) — never
      wall-clock (time.time()), which can jump under NTP adjustment and
      corrupt gap math. Injectable for tests.
    - `response` is expected to expose `aiter_lines()` (as httpx's streaming
      Response does): an async iterator yielding one raw SSE line per item.

    Every parsed chunk is timestamped and classified via metrics.parse
    (role/final/empty chunks are parsed but excluded from timing there).
    A malformed `data:` payload raises (parse.parse_sse_line's contract) —
    this function does not swallow that; a malformed chunk is a real bug.
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
        events.append(
            ChunkEvent(recv_time=recv_time, is_content=is_content, content=content, raw=parsed)
        )

    return compute.request_sample_from_events(events, t0)

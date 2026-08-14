"""Tier 1f -- monotonic clock usage.

consume_stream must use an injectable monotonic clock (default
time.perf_counter), never read wall-clock time itself. Proven by injecting
a fully-controlled fake clock and confirming every timestamp in the result
traces back to that clock's scripted sequence -- if consume_stream secretly
read time.time() anywhere, these exact values would not appear.
"""

from __future__ import annotations

import inspect
import time

import pytest

from metrics.consume import consume_stream


class _FakeResponse:
    def __init__(self, lines: list[str]):
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line


_ROLE_LINE = 'data: {"choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}'
_CONTENT_A = 'data: {"choices":[{"index":0,"delta":{"content":"a"},"finish_reason":null}]}'
_CONTENT_B = 'data: {"choices":[{"index":0,"delta":{"content":"b"},"finish_reason":null}]}'
_DONE_LINE = "data: [DONE]"


def test_default_clock_is_perf_counter():
    sig = inspect.signature(consume_stream)
    assert sig.parameters["clock"].default is time.perf_counter


async def test_uses_injected_clock_not_wallclock():
    response = _FakeResponse([_ROLE_LINE, _CONTENT_A, _CONTENT_B, _DONE_LINE])

    # Values with no relation to real wall-clock time -- if consume_stream
    # read time.time() anywhere instead of calling this clock, the results
    # below would not match.
    scripted = iter([1000.0, 1000.3, 1000.5])  # role, content-a, content-b
    sample = await consume_stream(response, t0=999.9, clock=lambda: next(scripted))

    assert sample.ttft_ms == pytest.approx((1000.3 - 999.9) * 1000)
    assert sample.tpot_samples_ms == [pytest.approx((1000.5 - 1000.3) * 1000)]


async def test_gaps_stay_positive_with_monotonic_clock():
    # A wall-clock NTP step backward mid-stream would produce a negative
    # gap. A monotonic clock is guaranteed never to do that; simulate one
    # via a fully-controlled, strictly-increasing scripted sequence and
    # confirm the computed gap is sane (positive, matches the script).
    response = _FakeResponse([_ROLE_LINE, _CONTENT_A, _CONTENT_B, _DONE_LINE])
    scripted = iter([5.0, 5.02, 5.05])
    sample = await consume_stream(response, t0=5.0, clock=lambda: next(scripted))

    assert all(gap > 0 for gap in sample.tpot_samples_ms)
    assert sample.tpot_samples_ms[0] == pytest.approx(30.0)

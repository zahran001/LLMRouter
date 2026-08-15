"""Tier 1d -- TTFT/TPOT extraction from synthetic ChunkEvent sequences.

These call metrics.compute.request_sample_from_events directly with
hand-built ChunkEvents -- no HTTP, no mock server. This is exactly the pure
core / thin shell split paying off: the timing math is testable with plain
data.
"""

from __future__ import annotations

import pytest

from metrics.compute import request_sample_from_events
from metrics.types import ChunkEvent


def _role_event(recv_time: float) -> ChunkEvent:
    return ChunkEvent(recv_time=recv_time, is_content=False, content=None, raw={"delta": {"role": "assistant"}})


def _content_event(recv_time: float, text: str = "x") -> ChunkEvent:
    return ChunkEvent(recv_time=recv_time, is_content=True, content=text, raw={"delta": {"content": text}})


def _empty_event(recv_time: float) -> ChunkEvent:
    return ChunkEvent(recv_time=recv_time, is_content=False, content=None, raw={"delta": {}})


def _final_event(recv_time: float) -> ChunkEvent:
    return ChunkEvent(
        recv_time=recv_time,
        is_content=False,
        content=None,
        raw={"delta": {}, "finish_reason": "stop"},
    )


def test_ttft_is_first_content_chunk():
    t0 = 0.0
    events = [_role_event(0.0), _content_event(0.300)]
    sample = request_sample_from_events(events, t0)
    assert sample.ttft_ms == pytest.approx(300.0)


def test_role_chunk_excluded():
    # Role chunk arrives well before the content chunk; if it leaked into
    # TTFT the result would be ~0ms instead of ~300ms.
    t0 = 0.0
    events = [_role_event(0.001), _content_event(0.300)]
    sample = request_sample_from_events(events, t0)
    assert sample.ttft_ms == pytest.approx(300.0)
    assert sample.ttft_ms != pytest.approx(1.0)


def test_tpot_gap_count():
    t0 = 0.0
    # K=5 content chunks -> exactly K-1=4 gaps.
    times = [0.100, 0.120, 0.145, 0.170, 0.200]
    events = [_content_event(t) for t in times]
    sample = request_sample_from_events(events, t0)
    assert sample.content_chunk_count == 5
    assert len(sample.tpot_samples_ms) == 4
    expected_gaps_ms = [20.0, 25.0, 25.0, 30.0]
    for actual, expected in zip(sample.tpot_samples_ms, expected_gaps_ms):
        assert actual == pytest.approx(expected)


def test_tpot_ignores_noncontent():
    t0 = 0.0
    # An empty-content chunk sits between two content chunks; it must not
    # create an extra (bogus) gap, and must not split the real gap in two.
    events = [
        _content_event(0.100),
        _empty_event(0.110),
        _content_event(0.140),
    ]
    sample = request_sample_from_events(events, t0)
    assert sample.content_chunk_count == 2
    assert len(sample.tpot_samples_ms) == 1
    assert sample.tpot_samples_ms[0] == pytest.approx(40.0)  # 140 - 100, not 140 - 110


def test_final_chunk_excluded():
    t0 = 0.0
    events = [
        _role_event(0.0),
        _content_event(0.100),
        _content_event(0.120),
        _final_event(0.121),
    ]
    sample = request_sample_from_events(events, t0)
    assert sample.content_chunk_count == 2
    assert len(sample.tpot_samples_ms) == 1
    assert sample.tpot_samples_ms[0] == pytest.approx(20.0)


def test_no_content_chunk():
    t0 = 0.0
    events = [_role_event(0.0), _final_event(0.005)]
    sample = request_sample_from_events(events, t0)
    assert sample.ttft_ms is None
    assert sample.tpot_samples_ms == []
    assert sample.content_chunk_count == 0
    assert sample.error is not None

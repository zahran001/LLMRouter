"""Tier 1e -- SSE line parsing and chunk classification."""

from __future__ import annotations

import pytest

from metrics.parse import DONE, extract_content, is_content_chunk, parse_sse_line


def test_parse_done_sentinel():
    assert parse_sse_line("data: [DONE]") == DONE


def test_parse_ignores_blank_and_comment():
    assert parse_sse_line("") is None
    assert parse_sse_line(": this is an SSE comment") is None


def test_parse_malformed_json_raises():
    with pytest.raises(ValueError):
        parse_sse_line("data: {not json")


def test_parse_valid_chunk():
    line = 'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"m","choices":[{"index":0,"delta":{"content":"hi"},"finish_reason":null}]}'
    parsed = parse_sse_line(line)
    assert isinstance(parsed, dict)
    assert parsed["choices"][0]["delta"]["content"] == "hi"


def test_index_nonzero_raises():
    chunk = {"choices": [{"index": 1, "delta": {"content": "hi"}, "finish_reason": None}]}
    with pytest.raises(ValueError):
        is_content_chunk(chunk)


def test_is_content_chunk_variants():
    role_chunk = {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
    empty_content_chunk = {"choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": None}]}
    final_chunk = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
    whitespace_chunk = {"choices": [{"index": 0, "delta": {"content": " "}, "finish_reason": None}]}
    real_content_chunk = {"choices": [{"index": 0, "delta": {"content": "hello"}, "finish_reason": None}]}

    assert is_content_chunk(role_chunk) is False
    assert is_content_chunk(empty_content_chunk) is False
    assert is_content_chunk(final_chunk) is False
    # Chosen rule (documented in parse.is_content_chunk): a whitespace-only
    # string is still content -- a real token can be a single space.
    assert is_content_chunk(whitespace_chunk) is True
    assert is_content_chunk(real_content_chunk) is True

    assert extract_content(role_chunk) is None
    assert extract_content(empty_content_chunk) is None
    assert extract_content(whitespace_chunk) == " "
    assert extract_content(real_content_chunk) == "hello"

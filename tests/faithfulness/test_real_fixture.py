"""Faithfulness Layers 1 & 3 (WEEK1_MEASUREMENT_SPEC.md §6) -- the GPU-session
half of the faithfulness check. test_schema.py's Layer 2 only proves the mock
is internally consistent; this module proves the mock matched real vLLM.

Requires tests/fixtures/vllm_real_stream.txt, captured once from real vLLM
during the GPU session (see WEEK1_CLOSEOUT.md step C). Skipped entirely until
that fixture exists, so it never blocks CI before the session runs -- once
the fixture is committed, these become permanent regression guards against
it, not just against the mock.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from metrics.parse import extract_content, is_content_chunk, parse_sse_line
from tests.faithfulness._schema_assertions import assert_faithful_sse_schema

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "vllm_real_stream.txt"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not FIXTURE_PATH.exists(),
        reason="tests/fixtures/vllm_real_stream.txt not captured yet -- run the GPU session (WEEK1_CLOSEOUT.md)",
    ),
]


def _load_fixture_lines() -> list[str]:
    return FIXTURE_PATH.read_text(encoding="utf-8").splitlines()


def _parsed_chunks(lines: list[str]) -> list[dict]:
    chunks = []
    for line in lines:
        result = parse_sse_line(line)
        if isinstance(result, dict):
            chunks.append(result)
    return chunks


def _keys_recursive(d: dict, prefix: str = "") -> set[str]:
    """All key paths in a dict, recursing into nested dicts (not lists)."""
    keys: set[str] = set()
    for k, v in d.items():
        path = f"{prefix}.{k}" if prefix else k
        keys.add(path)
        if isinstance(v, dict):
            keys |= _keys_recursive(v, path)
    return keys


def _choice0_keys(chunk: dict) -> set[str]:
    return {f"choices[0].{k}" for k in _keys_recursive(chunk["choices"][0])}


async def _live_mock_chunks(mock_base_url: str) -> list[dict]:
    """One real streamed response from the live mock -- same code path a
    deployed mock actually serves, not a hand-copied literal."""
    lines: list[str] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        async with client.stream(
            "POST", f"{mock_base_url}/v1/chat/completions",
            params={"config": "fast", "num_tokens": 3},
            json={"model": "mock", "messages": [{"role": "user", "content": "count to five"}]},
        ) as response:
            async for line in response.aiter_lines():
                lines.append(line)
    return _parsed_chunks(lines)


def test_real_stream_matches_locked_schema():
    """Layer 2's assertion, re-run unmodified against the real fixture --
    that reuse is the proof, per _schema_assertions.py's docstring."""
    assert_faithful_sse_schema(_load_fixture_lines())


async def test_real_stream_key_set_matches_mock(mock_base_url):
    """Layer 3: key-SET diff (not values) between a real vLLM chunk and the
    mock's chunk for the same role, recursive into choices[0] and delta. Any
    key vLLM sends that the mock omits is a real gap -- add it to
    mock/app.py. The reverse (mock has extra keys) is not a failure here.
    """
    real_chunks = _parsed_chunks(_load_fixture_lines())
    real_role = next(c for c in real_chunks if c["choices"][0]["delta"].get("role") == "assistant")
    real_content = next(c for c in real_chunks if c["choices"][0]["delta"].get("content"))
    real_final = real_chunks[-1]

    mock_chunks = await _live_mock_chunks(mock_base_url)
    mock_role = next(c for c in mock_chunks if c["choices"][0]["delta"].get("role") == "assistant")
    mock_content = next(c for c in mock_chunks if c["choices"][0]["delta"].get("content"))
    mock_final = mock_chunks[-1]

    for label, real, mock in (
        ("role", real_role, mock_role),
        ("content", real_content, mock_content),
        ("final", real_final, mock_final),
    ):
        real_keys = _keys_recursive(real) | _choice0_keys(real)
        mock_keys = _keys_recursive(mock) | _choice0_keys(mock)
        gap = real_keys - mock_keys
        assert not gap, (
            f"{label} chunk: vLLM sends keys the mock omits: {sorted(gap)} -- "
            f"add these to mock/app.py._make_chunk (real chunk: {real!r})"
        )


def test_existing_parser_is_a_noop_on_real_stream():
    """The real proof (WEEK1_CLOSEOUT.md step E): the metrics parser needs
    zero changes to read the real fixture."""
    chunks = _parsed_chunks(_load_fixture_lines())
    assert chunks, "no chunks parsed from the real fixture"

    content_seen = False
    for chunk in chunks:
        if is_content_chunk(chunk):
            content_seen = True
            token = extract_content(chunk)
            assert isinstance(token, str) and token

    assert content_seen, "no content chunk found in the real fixture"

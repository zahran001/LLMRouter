"""Shared schema assertion for faithfulness Layer 2 (and, later, Layer 3).

WEEK1_MEASUREMENT_SPEC.md §6: "A test consuming the mock stream asserts
every chunk's shape." Written so the SAME function can later be pointed at
a captured real-vLLM fixture (Layer 3, GPU session) without modification --
that reuse is the actual proof of faithfulness, not just passing against
the mock alone.
"""

from __future__ import annotations

from metrics.parse import parse_sse_line


def assert_faithful_sse_schema(lines: list[str]) -> None:
    """Assert a full SSE line sequence matches the locked streaming contract.

    Raises AssertionError on the first violation. `lines` should be the raw
    lines of one complete response (role chunk through the [DONE] terminator).
    """
    parsed_chunks: list[dict] = []
    saw_done = False

    for line in lines:
        if not line:
            continue
        result = parse_sse_line(line)
        if result is None:
            continue
        if result == "DONE":
            saw_done = True
            continue
        assert isinstance(result, dict), f"data line did not parse to a JSON object: {line!r}"
        parsed_chunks.append(result)

    assert saw_done, "stream did not end with the literal 'data: [DONE]' terminator"
    assert parsed_chunks, "no chunks parsed from the stream"

    for chunk in parsed_chunks:
        for key in ("id", "object", "created", "model", "choices"):
            assert key in chunk, f"chunk missing required key {key!r}: {chunk!r}"
        assert chunk["object"] == "chat.completion.chunk", chunk["object"]

        choices = chunk["choices"]
        assert choices, f"chunk has empty choices: {chunk!r}"
        choice0 = choices[0]
        assert choice0.get("index") == 0, f"choices[0].index != 0: {choice0!r}"
        assert "delta" in choice0, f"choices[0] missing delta: {choice0!r}"

    role_chunk = parsed_chunks[0]
    role_delta = role_chunk["choices"][0]["delta"]
    assert role_delta.get("role") == "assistant", f"first chunk is not the role chunk: {role_chunk!r}"
    assert "content" not in role_delta or not role_delta["content"], "role chunk carries content"

    content_chunks = [
        c for c in parsed_chunks
        if c["choices"][0]["delta"].get("content")
    ]
    assert content_chunks, "no content-bearing chunk found in stream"
    first_content_delta = content_chunks[0]["choices"][0]["delta"]
    assert isinstance(first_content_delta["content"], str) and len(first_content_delta["content"]) > 0

    final_chunk = parsed_chunks[-1]
    assert final_chunk["choices"][0].get("finish_reason") == "stop", (
        f"final chunk before [DONE] does not have finish_reason == 'stop': {final_chunk!r}"
    )

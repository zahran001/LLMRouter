"""SSE chunk parsing (pure).

No I/O, no clock reads. Implements the parser rules from
WEEK1_MEASUREMENT_SPEC.md §1 ("Parser rules") against the streaming contract
in the same section.
"""

from __future__ import annotations

import json
from typing import Literal

DONE: Literal["DONE"] = "DONE"


def parse_sse_line(line: str) -> dict | None | Literal["DONE"]:
    """Parse one raw SSE line from the response body.

    Contract:
    - A line that is blank, or an SSE comment line (starts with ':'), or any
      line not starting with the `data:` field name -> None (ignore).
    - `data: [DONE]` (the literal terminator) -> the sentinel "DONE".
    - `data: {json}` -> the parsed dict.
    - A `data:` line whose payload is not valid JSON and not "[DONE]" raises
      ValueError. A malformed chunk is a real bug, not something to silently
      skip (AGENT_METRICS_BRIEF.md §3).

    Input is expected pre-stripped of the line's trailing "\\n"; a trailing
    "\\r" (as left by some line splitters) is tolerated and stripped here.
    """
    line = line.rstrip("\r")

    if not line or line.startswith(":"):
        return None
    if not line.startswith("data:"):
        return None

    payload = line[len("data:") :].strip()
    if payload == "[DONE]":
        return DONE

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed SSE data payload (not valid JSON): {line!r}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"SSE data payload did not parse to a JSON object: {line!r}")

    return parsed


def _choice0(chunk: dict) -> dict:
    """Return choices[0], enforcing the n=1 boundary assumption (spec §1)."""
    choices = chunk.get("choices")
    if not choices:
        raise ValueError(f"chunk has no choices: {chunk!r}")
    choice = choices[0]
    index = choice.get("index", 0)
    if index != 0:
        raise ValueError(
            f"chunk choices[0].index == {index!r}, expected 0 — "
            "n > 1 completions are out of contract (spec §1)"
        )
    return choice


def is_content_chunk(chunk: dict) -> bool:
    """True iff this chunk is a "token chunk" per the streaming contract.

    True iff choices[0].delta.content is a non-empty string. Any non-empty
    string counts as content, INCLUDING whitespace-only strings — a real
    token can be a single space or newline. Only the empty string "" or a
    missing/None content field is excluded.

    False for the role chunk (delta.role, no content), the final chunk
    (delta == {}, finish_reason == "stop"), and any empty-content chunk.

    Raises if choices[0].index != 0 (n > 1 is out of contract, spec §1).
    Content is read from delta.content only; delta.reasoning_content
    (reasoning models) is out of scope for v1 and is never read.
    """
    delta = _choice0(chunk).get("delta", {})
    content = delta.get("content")
    return isinstance(content, str) and len(content) > 0


def extract_content(chunk: dict) -> str | None:
    """Return delta.content if this is a content chunk, else None.

    Delegates the "is this content" decision to is_content_chunk so the two
    functions can never disagree about what counts as a token.
    """
    if not is_content_chunk(chunk):
        return None
    return chunk["choices"][0]["delta"]["content"]

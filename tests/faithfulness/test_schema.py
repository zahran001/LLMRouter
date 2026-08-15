"""Faithfulness Layer 2 (WEEK1_MEASUREMENT_SPEC.md §6) -- $0, runs in CI.

Asserts the mock's stream matches the locked schema, for every config.

Layers 1 and 3 (capturing a real vLLM golden fixture and diffing its key
set against the mock) require a GPU session running real vLLM and are
explicitly out of scope for this module's build -- see
tests/fixtures/README.md. This is the one layer that's $0 and automatable.
"""

from __future__ import annotations

import httpx
import pytest

from mock.configs import CONFIGS
from tests.faithfulness._schema_assertions import assert_faithful_sse_schema

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("config_name", sorted(CONFIGS))
async def test_mock_stream_matches_locked_schema(config_name, mock_base_url):
    url = f"{mock_base_url}/v1/chat/completions"
    lines: list[str] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        async with client.stream(
            "POST", url, params={"config": config_name, "num_tokens": 4},
            json={"model": "mock", "messages": [{"role": "user", "content": "count to five"}]},
        ) as response:
            async for line in response.aiter_lines():
                lines.append(line)

    assert_faithful_sse_schema(lines)

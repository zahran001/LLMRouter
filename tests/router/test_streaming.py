"""S1-S2 -- the router does not collect the body (WEEK1_ROUTER_IMPL.md §4.2).

The honest assertion is a **separation** assertion, never "the first chunk
arrived at exactly ttft_ms": per the §1 scope note, per-chunk TCP delivery is
below the application. Both bounds here are orders of magnitude away from the
values a correct router produces, and orders of magnitude away in the other
direction from what a buffering router produces.

These tests are meaningless on their own. Their validity lives in
test_negative_controls.py, where the same assertions must go red against
WRONG_ROUTER_BUFFERS.
"""

from __future__ import annotations

import pytest

from tests.router._assertions import assert_first_chunk_early, assert_incremental_delivery
from tests.router._client import request_params, sample_one
from tests.router.tolerances import STREAMING_CONFIG, STREAMING_NUM_TOKENS

pytestmark = [pytest.mark.integration, pytest.mark.router, pytest.mark.slow]


async def test_s1_incremental_delivery(router_base_url):
    """S1 -- first-to-last content chunk spans most of the configured
    content-stream duration, i.e. the client got data as it was produced."""
    sample = await sample_one(router_base_url, request_params(STREAMING_CONFIG, STREAMING_NUM_TOKENS))
    assert_incremental_delivery(sample)


async def test_s2_first_chunk_is_early(router_base_url):
    """S2 -- the first content chunk lands near the configured TTFT rather
    than near completion."""
    sample = await sample_one(router_base_url, request_params(STREAMING_CONFIG, STREAMING_NUM_TOKENS))
    assert_first_chunk_early(sample)

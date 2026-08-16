"""F1-F3 -- bytes out == bytes in (WEEK1_ROUTER_IMPL.md §4.1).

F3 is not a separate test: it is the parametrization of F1 and F2 over all
four locked mock configs. The high-variance config earns its place here --
if the router ever coalesced chunks, its irregular tail structure is where
F2's sample counts would diverge first.

Ground truth is the direct-to-mock stream plus the locked metrics parser.
Nothing in this file re-derives what a correct stream looks like.
"""

from __future__ import annotations

import pytest

from mock.configs import CONFIGS
from tests.router._assertions import assert_byte_identical, assert_gating_identical, assert_parser_agrees
from tests.router._client import (
    CHAT_PATH,
    capture_raw,
    first_content_index,
    parsed_chunks,
    request_params,
    sample_one,
)

pytestmark = [pytest.mark.integration, pytest.mark.router]

ALL_CONFIGS = sorted(CONFIGS)
NUM_TOKENS = 5

# Fixed seed: makes the mock's response byte-reproducible (mock/app.py
# _identity_for), which is what lets F1 compare two necessarily-separate
# requests byte-for-byte instead of retreating to semantic equivalence.
SEED = 20260815


@pytest.mark.parametrize("config", ALL_CONFIGS)
async def test_f1_byte_identity(mock_base_url, router_base_url, config):
    """F1 -- the proxied body is byte-identical to the direct body."""
    params = request_params(config, NUM_TOKENS, seed=SEED)

    direct = await capture_raw(mock_base_url, params)
    proxied = await capture_raw(router_base_url, params, path=CHAT_PATH)

    assert direct.status == proxied.status == 200
    assert_byte_identical(direct.body, proxied.body)


@pytest.mark.parametrize("config", ALL_CONFIGS)
async def test_f2_parser_no_op(mock_base_url, router_base_url, config):
    """F2 -- the locked metrics parser cannot tell the two paths apart."""
    params = request_params(config, NUM_TOKENS, seed=SEED)

    direct_sample = await sample_one(mock_base_url, params)
    proxied_sample = await sample_one(router_base_url, params)
    assert_parser_agrees(direct_sample, proxied_sample)

    direct_raw = await capture_raw(mock_base_url, params)
    proxied_raw = await capture_raw(router_base_url, params)
    assert_gating_identical(direct_raw.body, proxied_raw.body)


@pytest.mark.parametrize("config", ALL_CONFIGS)
async def test_f2_gating_excludes_the_role_chunk(mock_base_url, config):
    """Ground-truth check for F2's gating assertion.

    F2 compares first-content-chunk *position* between the two paths, which
    would be satisfied trivially if the parser counted the role chunk as
    content on both. This pins the direct-path position to 1 (the role chunk
    is index 0), so F2's agreement is agreement about the correct answer.
    """
    raw = await capture_raw(mock_base_url, request_params(config, NUM_TOKENS, seed=SEED))
    chunks = parsed_chunks(raw.body)

    assert first_content_index(chunks) == 1, "role chunk should be index 0 and excluded from t_first"
    assert sum(1 for c in chunks if c["choices"][0]["delta"].get("content")) == NUM_TOKENS

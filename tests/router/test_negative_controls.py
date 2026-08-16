"""The router eval's teeth (WEEK1_ROUTER_IMPL.md §4, §5).

Each test here drives one of the two deliberately-wrong routers through the
*same* assertion helper the real eval uses, and asserts it goes red. A test
in this file failing means the corresponding real test proves nothing:

    S1/S2 vs WRONG_ROUTER_BUFFERS  -- the streaming claim
    O1    vs WRONG_ROUTER_BUFFERS  -- the same failure via the overhead signal
    F1    vs WRONG_ROUTER_REEMIT   -- byte-identity, not semantic equivalence

A negative control that silently starts passing is itself a CI failure; that
is the whole point of running these in CI rather than keeping them as a
one-off demonstration.

> "A green S1/S2 means nothing until you've watched it go red against the
>  buffer." (§4.2)
"""

from __future__ import annotations

import pytest

from tests.router._assertions import (
    assert_byte_identical,
    assert_first_chunk_early,
    assert_incremental_delivery,
    assert_overhead_small_and_constant,
    assert_parser_agrees,
)
from tests.router._client import (
    WRONG_BUFFERS_PATH,
    WRONG_REEMIT_PATH,
    capture_raw,
    measure_overhead_arm,
    request_params,
    sample_one,
)
from tests.router.tolerances import (
    OVERHEAD_CONFIG,
    OVERHEAD_LARGE_NUM_TOKENS,
    OVERHEAD_SMALL_NUM_TOKENS,
    OVERHEAD_WARMUP,
    STREAMING_CONFIG,
    STREAMING_NUM_TOKENS,
)

pytestmark = [pytest.mark.integration, pytest.mark.router, pytest.mark.negative_control]

# Fewer samples than the real O1 run (tolerances.OVERHEAD_N = 21): the
# buffering router's overhead is ~(N-1) x tpot_ms, i.e. hundreds of
# milliseconds against a 10ms bound, so it does not need 21 samples to be
# unambiguous -- and the large arm is expensive to drive through a handler
# that waits for the whole response.
CONTROL_OVERHEAD_N = 7

SEED = 20260815


async def test_s1_fails_against_wrong_router_buffers(router_base_url):
    """S1 must bite: a collected body arrives all at once, so the
    first->last content chunk gap collapses toward zero."""
    sample = await sample_one(
        router_base_url, request_params(STREAMING_CONFIG, STREAMING_NUM_TOKENS), path=WRONG_BUFFERS_PATH
    )

    observed_gap_ms = sum(sample.tpot_samples_ms)
    with pytest.raises(AssertionError):
        assert_incremental_delivery(sample)

    print(f"\nWRONG_ROUTER_BUFFERS S1: first->last gap {observed_gap_ms:.1f}ms (streaming router: ~1900ms)")


async def test_s2_fails_against_wrong_router_buffers(router_base_url):
    """S2 must bite: first-chunk time balloons toward completion time."""
    sample = await sample_one(
        router_base_url, request_params(STREAMING_CONFIG, STREAMING_NUM_TOKENS), path=WRONG_BUFFERS_PATH
    )

    with pytest.raises(AssertionError):
        assert_first_chunk_early(sample)

    print(f"\nWRONG_ROUTER_BUFFERS S2: first chunk at {sample.ttft_ms:.1f}ms (configured TTFT: 500ms)")


@pytest.mark.slow
async def test_o1_fails_against_wrong_router_buffers(mock_base_url, router_base_url):
    """O1 must bite through the overhead signal alone -- an independent
    detector of the same bug S1/S2 catch through timing. The buffering
    handler's overhead is not constant: it grows with response length."""
    small = await measure_overhead_arm(
        "small(buffering)", mock_base_url, router_base_url, OVERHEAD_CONFIG,
        OVERHEAD_SMALL_NUM_TOKENS, CONTROL_OVERHEAD_N, OVERHEAD_WARMUP, proxied_path=WRONG_BUFFERS_PATH,
    )
    large = await measure_overhead_arm(
        "large(buffering)", mock_base_url, router_base_url, OVERHEAD_CONFIG,
        OVERHEAD_LARGE_NUM_TOKENS, CONTROL_OVERHEAD_N, OVERHEAD_WARMUP, proxied_path=WRONG_BUFFERS_PATH,
    )

    print(f"\nWRONG_ROUTER_BUFFERS O1 {small.describe()}\nWRONG_ROUTER_BUFFERS O1 {large.describe()}")

    # Not just "it failed somehow": the failure must be the *growth* signature,
    # so this control proves O1 detects buffering rather than a generic slowdown.
    assert large.delta_ms > small.delta_ms, "buffering overhead did not grow with response size"

    with pytest.raises(AssertionError):
        assert_overhead_small_and_constant(small, large)


async def test_f1_fails_against_wrong_router_reemit(mock_base_url, router_base_url):
    """F1 must bite: a JSON round-trip reorders keys and compacts
    separators, so the bytes differ even though the meaning does not."""
    params = request_params("fast", 5, seed=SEED)

    direct = await capture_raw(mock_base_url, params)
    reemitted = await capture_raw(router_base_url, params, path=WRONG_REEMIT_PATH)

    with pytest.raises(AssertionError):
        assert_byte_identical(direct.body, reemitted.body)

    print(f"\nWRONG_ROUTER_REEMIT F1: {len(direct.body)} bytes direct vs {len(reemitted.body)} re-emitted")


async def test_f2_still_passes_against_wrong_router_reemit(mock_base_url, router_base_url):
    """The other half of the same proof: F2 (parser no-op) *passes* against
    the re-emit router, because the round-trip preserves semantics. If F1 and
    F2 both failed here, F1's failure would not be evidence that it tests
    byte-identity specifically -- it is the divergence between them that is."""
    params = request_params("fast", 5, seed=SEED)

    direct_sample = await sample_one(mock_base_url, params)
    reemitted_sample = await sample_one(router_base_url, params, path=WRONG_REEMIT_PATH)

    assert_parser_agrees(direct_sample, reemitted_sample)

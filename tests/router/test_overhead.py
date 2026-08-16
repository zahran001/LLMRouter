"""O1 -- small, roughly constant sequential router overhead
(WEEK1_ROUTER_IMPL.md §4.3, WEEK1_MEASUREMENT_SPEC.md §7).

Strictly sequential, by design and not by accident: concurrency here would
mix the router's overhead with the mock's known concurrency artifact
(MOCK_TRUST_BOUNDARY.md §1) and produce a number nobody could interpret.

Two response sizes, one config. Both deltas must be small, and the delta must
not grow between them -- growth is per-chunk work, which is the overhead-side
signature of the same bug S1/S2 detect through timing.
"""

from __future__ import annotations

import pytest

from tests.router._assertions import assert_overhead_small_and_constant
from tests.router._client import measure_overhead_arm
from tests.router.tolerances import (
    OVERHEAD_CONFIG,
    OVERHEAD_LARGE_NUM_TOKENS,
    OVERHEAD_N,
    OVERHEAD_SMALL_NUM_TOKENS,
    OVERHEAD_WARMUP,
)

pytestmark = [pytest.mark.integration, pytest.mark.router, pytest.mark.slow]


async def test_o1_sequential_overhead(mock_base_url, router_base_url):
    small = await measure_overhead_arm(
        "small", mock_base_url, router_base_url, OVERHEAD_CONFIG,
        OVERHEAD_SMALL_NUM_TOKENS, OVERHEAD_N, OVERHEAD_WARMUP,
    )
    large = await measure_overhead_arm(
        "large", mock_base_url, router_base_url, OVERHEAD_CONFIG,
        OVERHEAD_LARGE_NUM_TOKENS, OVERHEAD_N, OVERHEAD_WARMUP,
    )

    # Printed so a run leaves the measured numbers behind, not just a green
    # tick -- the metadata habit from WEEK1_MEASUREMENT_SPEC.md §7.
    print(f"\nO1 {small.describe()}\nO1 {large.describe()}")

    assert_overhead_small_and_constant(small, large)

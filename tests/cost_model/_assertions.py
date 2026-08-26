"""Shared assertion helper for Week 3 request-cost tests.

test_negative_controls.py imports this SAME helper -- proving a broken
implementation is caught by the real check, not a check invented just for
the control (this repo's established pattern,
tests/loadgen/test_negative_controls.py).
"""

from __future__ import annotations

from cost_model.types import RequestCost


def assert_matches_golden(cost: RequestCost, golden: dict) -> None:
    assert cost.input_tokens == golden["input_tokens"], (
        f"input_tokens {cost.input_tokens} != golden {golden['input_tokens']}"
    )
    assert cost.reserved_tokens == golden["reserved_tokens"], (
        f"reserved_tokens {cost.reserved_tokens} != golden {golden['reserved_tokens']}"
    )
    assert cost.estimated_kv_bytes == golden["estimated_kv_bytes"], (
        f"estimated_kv_bytes {cost.estimated_kv_bytes} != golden {golden['estimated_kv_bytes']}"
    )

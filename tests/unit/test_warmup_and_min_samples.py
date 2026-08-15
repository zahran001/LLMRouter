"""Tier 1b/1c -- warmup discard (by order, not value) and the min-sample rule."""

from __future__ import annotations

import math

from metrics.compute import aggregate
from metrics.types import RequestSample


def _sample(ttft_ms: float) -> RequestSample:
    return RequestSample(ttft_ms=ttft_ms, tpot_samples_ms=[], content_chunk_count=1, error=None)


def test_warmup_discards_first_n():
    # ttft = request index, so "min ttft in population == 10" proves the
    # discard is positional, not value-based (a value-based discard would
    # instead drop the smallest values, which happen to be the same ones
    # here -- so we also shuffle a second run to rule that confound out).
    samples = [_sample(i) for i in range(30)]
    result = aggregate(samples, warmup=10, min_samples=1, config={})
    assert min(result.raw_ttft_ms) == 10
    assert max(result.raw_ttft_ms) == 29
    assert result.n_requests == 20
    assert result.n_warmup_discarded == 10

    # Same values, different order: warmup drops the first 10 BY POSITION,
    # so a different arrangement discards different values even though the
    # value set is identical -- proving order, not value, drives the cut.
    import random

    shuffled_values = list(range(30))
    rng = random.Random(0)
    rng.shuffle(shuffled_values)
    shuffled_samples = [_sample(v) for v in shuffled_values]
    result2 = aggregate(shuffled_samples, warmup=10, min_samples=1, config={})
    discarded_positionally = set(shuffled_values[:10])
    kept_positionally = set(shuffled_values[10:])
    assert set(result2.raw_ttft_ms) == kept_positionally
    assert set(result2.raw_ttft_ms).isdisjoint(discarded_positionally)


def test_warmup_larger_than_samples():
    samples = [_sample(i) for i in range(5)]
    result = aggregate(samples, warmup=10, min_samples=100, config={})
    assert result.n_requests == 0
    assert result.valid is False
    assert result.n_warmup_discarded == 5  # can't discard more than exist
    assert math.isnan(result.ttft_p50)
    assert result.raw_ttft_ms == []


def test_below_min_samples_invalid():
    samples = [_sample(i) for i in range(10 + 99)]  # 99 measured after warmup
    result = aggregate(samples, warmup=10, min_samples=100, config={})
    assert result.n_requests == 99
    assert result.valid is False
    assert math.isnan(result.ttft_p95)
    assert math.isnan(result.ttft_p99)
    assert math.isnan(result.tpot_p95)
    assert math.isnan(result.tpot_p99)
    # p50/mean still computed for visibility even though invalid.
    assert not math.isnan(result.ttft_p50)
    assert not math.isnan(result.ttft_mean)


def test_at_min_samples_valid():
    samples = [_sample(i) for i in range(10 + 100)]  # exactly 100 measured
    result = aggregate(samples, warmup=10, min_samples=100, config={})
    assert result.n_requests == 100
    assert result.valid is True
    assert not math.isnan(result.ttft_p95)
    assert not math.isnan(result.ttft_p99)

"""Tier 1a -- percentile correctness against independently-derived literals.

The percentile function is the single most correctness-critical piece of
this module. Every expected value below was derived WITHOUT calling
metrics.compute.percentile: by hand (shown in comments) and cross-checked
with a one-off `numpy.percentile(..., method="linear")` invocation run
separately from this test suite. If you find yourself tempted to compute an
"expected" value by calling percentile() itself, stop -- a wrong-but-
consistent implementation would pass that test, which defeats the point.
"""

from __future__ import annotations

import math

import pytest

from metrics.compute import percentile


def test_percentile_known_values():
    # data = [1, 2, ..., 100], zero-indexed a[0..99].
    # Method: linear interpolation between closest ranks, rank r = p/100*(n-1).
    #   p50: r = 0.50 * 99 = 49.5  -> a[49]=50, a[50]=51 -> 50 + 0.5*(51-50) = 50.5
    #   p95: r = 0.95 * 99 = 94.05 -> a[94]=95, a[95]=96 -> 95 + 0.05*(96-95) = 95.05
    #   p99: r = 0.99 * 99 = 98.01 -> a[98]=99, a[99]=100 -> 99 + 0.01*(100-99) = 99.01
    # Cross-checked: numpy.percentile(np.arange(1,101,dtype=float), [50,95,99], method="linear")
    #   -> array([50.5 , 95.05, 99.01])
    data = list(range(1, 101))
    assert percentile(data, 50) == pytest.approx(50.5)
    assert percentile(data, 95) == pytest.approx(95.05)
    assert percentile(data, 99) == pytest.approx(99.01)


def test_percentile_single_element():
    assert percentile([42], 50) == 42
    assert percentile([42], 95) == 42
    assert percentile([42], 99) == 42


def test_percentile_two_elements():
    # data = [10, 20], n=2, rank r = p/100 * 1.
    #   p25: r=0.25 -> 10 + 0.25*(20-10) = 12.5
    #   p50: r=0.50 -> 10 + 0.50*(20-10) = 15.0
    #   p75: r=0.75 -> 10 + 0.75*(20-10) = 17.5
    # Cross-checked: numpy.percentile([10,20], [25,50,75], method="linear")
    #   -> array([12.5, 15. , 17.5])
    data = [10, 20]
    assert percentile(data, 25) == pytest.approx(12.5)
    assert percentile(data, 50) == pytest.approx(15.0)
    assert percentile(data, 75) == pytest.approx(17.5)


def test_percentile_empty_raises():
    with pytest.raises(ValueError):
        percentile([], 50)


def test_percentile_unsorted_input():
    # Contract (documented in compute.percentile's docstring): the function
    # sorts internally: unsorted input must match the same computation on
    # the sorted version.
    unsorted = [50, 10, 30, 20, 40, 90, 70, 60, 100, 80]
    sorted_ = sorted(unsorted)
    for p in (0, 25, 50, 75, 99, 100):
        assert percentile(unsorted, p) == pytest.approx(percentile(sorted_, p))
    # And against a hand-derived value: sorted = [10..100 step 10], n=10.
    # p50: r = 0.5*9 = 4.5 -> a[4]=50, a[5]=60 -> 50 + 0.5*10 = 55.0
    assert percentile(unsorted, 50) == pytest.approx(55.0)


def test_percentile_p0_p100():
    data = [7, 3, 19, 1, 42, 8]
    assert percentile(data, 0) == min(data)
    assert percentile(data, 100) == max(data)


def test_percentile_nan_never_silently_returned_for_nonempty_input():
    # Guards against a "helpful" implementation that swallows edge cases
    # into NaN instead of computing a real value.
    result = percentile([1, 2, 3], 50)
    assert not math.isnan(result)

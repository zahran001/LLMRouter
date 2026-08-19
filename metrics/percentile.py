"""The redesigned percentile definition (R4 README L5; `WEEK2_PLAN.md` §10.5).

## Why this module exists separately from `metrics.compute.percentile`

The first GPU session's artifacts contain two percentile conventions, and on the
near-boundary point the choice alone decides the verdict. Same 225 samples:

    nearest-rank            552.9ms   OVER
    linear (numpy default)  524.6ms   OVER
    midpoint                493.9ms   UNDER
    lower                   434.8ms   UNDER

Nothing chose that; it was inherited from whichever code path ran. Every Stage A
point record used `metrics.compute.percentile` (numpy linear), while the unloaded
floor was written by a one-off on-instance script that used nearest-rank.

So the redesign locks the definition. **Nearest-rank**, because it returns an
*actually observed* latency: at the tail the neighbouring order statistics are
far apart, and an interpolated p99 is a number no request ever experienced. On
the 2-RPS array, linear interpolation reports 524.6ms — a value strictly between
two real observations 118ms apart.

## Why the legacy function is not simply changed

`metrics.compute.percentile` keeps its linear behaviour permanently. The first
session's records were computed with it, and `WEEK2_PLAN.md` §10.5 requires that
historical metrics keep their historical meaning rather than being silently
recomputed under a new convention. Two conventions therefore coexist **on
purpose** — the difference is that now each one is named, versioned, and recorded
in the provenance of every record it produces.

`tests/redesign/test_percentile_definition.py` holds both halves: that the
methods genuinely disagree on a near-boundary sample (otherwise this lock would
be decorative), and that the redesigned path always returns nearest-rank.
"""

from __future__ import annotations

import math

# Bump when the definition changes. Persisted into every redesigned point
# record so a reader can tell which convention produced a number without
# having to know which script wrote it.
PERCENTILE_METHOD = "nearest_rank"
PERCENTILE_METHOD_VERSION = "nearest-rank-v1"

# The legacy convention, named so historical records can declare themselves
# rather than being identified by absence.
LEGACY_PERCENTILE_METHOD = "numpy_linear"
LEGACY_PERCENTILE_METHOD_VERSION = "numpy-linear-v1"


def percentile_nearest_rank(samples, p: float) -> float:
    """The p-th percentile by nearest-rank order statistic.

        sorted_samples = sorted(samples)
        rank           = ceil(p/100 * n)     # one-indexed
        result         = sorted_samples[rank - 1]

    Properties, and why each is what the measurement wants:

    - The result is **always an observed value**. No interpolation invents a
      latency between two real ones.
    - `p=100` returns the max; `p=0` returns the min (rank 0 clamps to 1, since
      there is no zeroth order statistic).
    - Monotonic in `p`, and stable under duplicate values.
    - Input may be in any order; this sorts internally.

    Raises `ValueError` on an empty sample: there is no percentile of nothing,
    and returning a sentinel would let a point with no data print a latency.
    """
    values = sorted(float(x) for x in samples)
    n = len(values)
    if n == 0:
        raise ValueError("percentile_nearest_rank: cannot take a percentile of an empty sample")
    if not 0.0 <= p <= 100.0:
        raise ValueError(f"percentile_nearest_rank: p must be in [0, 100], got {p}")

    rank = math.ceil(p / 100.0 * n)
    rank = max(1, min(rank, n))
    return values[rank - 1]


def percentile_provenance() -> dict:
    """The block every redesigned point record embeds, so a number always
    carries the convention that produced it."""
    return {
        "percentile_method": PERCENTILE_METHOD,
        "percentile_method_version": PERCENTILE_METHOD_VERSION,
        "definition": "rank = ceil(p/100 * n), one-indexed, over sorted valid samples",
        "note": "Legacy first-session records used "
                f"{LEGACY_PERCENTILE_METHOD} ({LEGACY_PERCENTILE_METHOD_VERSION}) and are "
                "deliberately NOT recomputed under this convention (WEEK2_PLAN.md 10.5).",
    }


def top_k_support(n: int, p: float = 99.0) -> int:
    """How many samples sit at or above the p-th percentile rank.

    The number that makes a tail percentile meaningful or not: at n=225 the top
    1% is 3 observations, which is why the first session's 2-RPS verdict moved
    when one prompt was excluded.
    """
    if n <= 0:
        return 0
    return n - math.ceil(p / 100.0 * n) + 1

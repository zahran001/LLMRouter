"""Percentile + aggregation logic (pure).

No I/O, no clock reads: every function here takes timestamps/samples that
were already captured elsewhere and returns metrics. This is what the
deterministic tests exercise directly (METRICS_TEST_SUITE.md Tier 1).
"""

from __future__ import annotations

import math

import numpy as np

from metrics.types import ChunkEvent, RequestSample, RunMetrics


def percentile(samples: list[float], p: float) -> float:
    """Return the p-th percentile of samples using linear interpolation
    between closest ranks (numpy's method="linear", the default): for a
    sorted array a of length n, the estimate at fractional rank
    r = p/100 * (n-1) is a[floor(r)] + (r - floor(r)) * (a[ceil(r)] - a[floor(r)]).

    Contract: samples may be passed in ANY order — this function sorts
    internally (via numpy.percentile) rather than requiring pre-sorted
    input.

    Edge cases:
    - Empty input raises ValueError (there is no percentile of nothing).
    - A single-element list returns that element for any p.
    - p=0 returns the min, p=100 returns the max.

    Do not change `method=` without updating the hard-coded expected values
    in tests/unit/test_percentile.py — those are independently derived for
    this exact method and would silently stop meaning anything otherwise.
    """
    if len(samples) == 0:
        raise ValueError("percentile: cannot compute a percentile of an empty sample list")
    if len(samples) == 1:
        return float(samples[0])
    return float(np.percentile(np.asarray(samples, dtype=float), p, method="linear"))


def request_sample_from_events(events: list[ChunkEvent], t0: float) -> RequestSample:
    """Derive TTFT/TPOT for one request from its parsed, timestamped chunks.

    Pure: takes already-captured ChunkEvents and t0, reads no clock.

    - TTFT = recv_time of the FIRST content chunk minus t0, in ms. Non-content
      chunks (role, final, empty) are ignored entirely — they cannot set TTFT.
    - TPOT samples = consecutive recv_time differences between content chunks
      ONLY, in ms. Non-content chunks in between do not create gaps: K content
      chunks yield exactly K-1 samples, computed from the content-chunk
      subsequence, not from raw event order.
    - If there are zero content chunks, ttft_ms is None and error is set;
      this is not a crash.
    """
    content_events = [e for e in events if e.is_content]

    if not content_events:
        return RequestSample(
            ttft_ms=None,
            tpot_samples_ms=[],
            content_chunk_count=0,
            error="no_content_chunks",
        )

    ttft_ms = (content_events[0].recv_time - t0) * 1000.0
    tpot_samples_ms = [
        (content_events[i].recv_time - content_events[i - 1].recv_time) * 1000.0
        for i in range(1, len(content_events))
    ]

    return RequestSample(
        ttft_ms=ttft_ms,
        tpot_samples_ms=tpot_samples_ms,
        content_chunk_count=len(content_events),
        error=None,
    )


def _stat(pop: list[float], p: float | None) -> float:
    """mean (p=None) or percentile(p) of pop, or NaN if pop is empty."""
    if not pop:
        return math.nan
    if p is None:
        return float(sum(pop) / len(pop))
    return percentile(pop, p)


def aggregate(
    samples: list[RequestSample],
    warmup: int,
    min_samples: int,
    config: dict,
) -> RunMetrics:
    """Aggregate per-request samples into run-level percentiles.

    - Discards the first `warmup` samples BY REQUEST ORDER (the order they
      appear in `samples`), not by sorting on any value. Order is the
      caller's responsibility to preserve (submission order).
    - measured = samples[warmup:]. If warmup >= len(samples), measured is
      empty — this does not crash; it just produces an invalid, empty run.
    - TTFT population = every non-None ttft_ms among measured samples.
    - TPOT population = every tpot_samples_ms entry among measured samples,
      flattened.
    - valid = (number of measured REQUESTS) >= min_samples. This is a count
      of requests, not of TTFT/TPOT samples (a request can contribute 0
      TTFT samples on error, or many TPOT samples).
    - When not valid, p95/p99 are NaN for both TTFT and TPOT and MUST NOT be
      read as real tail estimates. p50/mean are still computed when the
      population is non-empty, for visibility only.
    - Never clips, smooths, or drops outliers beyond the fixed warmup — the
      full post-warmup population feeds the percentiles and is preserved
      verbatim in raw_ttft_ms / raw_tpot_ms.
    """
    n_warmup_discarded = min(warmup, len(samples))
    measured = samples[warmup:]
    n_requests = len(measured)
    valid = n_requests >= min_samples

    raw_ttft_ms = [s.ttft_ms for s in measured if s.ttft_ms is not None]
    raw_tpot_ms = [t for s in measured for t in s.tpot_samples_ms]

    ttft_p95 = percentile(raw_ttft_ms, 95) if valid and raw_ttft_ms else math.nan
    ttft_p99 = percentile(raw_ttft_ms, 99) if valid and raw_ttft_ms else math.nan
    tpot_p95 = percentile(raw_tpot_ms, 95) if valid and raw_tpot_ms else math.nan
    tpot_p99 = percentile(raw_tpot_ms, 99) if valid and raw_tpot_ms else math.nan

    return RunMetrics(
        ttft_p50=_stat(raw_ttft_ms, 50),
        ttft_p95=ttft_p95,
        ttft_p99=ttft_p99,
        ttft_mean=_stat(raw_ttft_ms, None),
        tpot_p50=_stat(raw_tpot_ms, 50),
        tpot_p95=tpot_p95,
        tpot_p99=tpot_p99,
        tpot_mean=_stat(raw_tpot_ms, None),
        n_requests=n_requests,
        n_warmup_discarded=n_warmup_discarded,
        n_ttft_samples=len(raw_ttft_ms),
        n_tpot_samples=len(raw_tpot_ms),
        valid=valid,
        config=dict(config),
        raw_ttft_ms=raw_ttft_ms,
        raw_tpot_ms=raw_tpot_ms,
    )

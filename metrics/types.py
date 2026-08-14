"""Data types shared across the metrics module.

Pure data holders only — no I/O, no clock reads, no logic beyond simple
serialization. See metrics/README.md for the timing definitions these types
carry (cross-references WEEK1_MEASUREMENT_SPEC.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class ChunkEvent:
    """One parsed SSE chunk, timestamped on receipt.

    recv_time: a monotonic timestamp (time.perf_counter()), never wall-clock.
    is_content: True iff this chunk carries non-empty delta.content — i.e. it
        is a "token chunk" per the streaming contract. False for the role
        chunk, the final finish_reason chunk, and any empty-content chunk.
    content: the extracted delta.content string when is_content is True,
        else None.
    raw: the parsed JSON payload, kept for debugging / schema assertions.
    """

    recv_time: float
    is_content: bool
    content: str | None
    raw: dict


@dataclass
class RequestSample:
    """The measurement result of a single request's stream.

    ttft_ms: time from t0 to the first content chunk, in milliseconds.
        None if the request produced no content chunk at all.
    tpot_samples_ms: gaps between consecutive content chunks, in
        milliseconds. K content chunks yield exactly K-1 samples.
    content_chunk_count: number of content-bearing chunks observed (K).
    error: set when the request produced no content chunk (or another
        recorded failure); None on a clean sample.
    """

    ttft_ms: float | None
    tpot_samples_ms: list[float]
    content_chunk_count: int
    error: str | None = None


@dataclass
class RunMetrics:
    """Aggregate statistics over one benchmark run (post-warmup).

    valid is False when n_requests (measured, post-warmup) is below the
    configured min_samples threshold — in that case ttft_p95/p99 and
    tpot_p95/p99 are NaN and MUST NOT be reported as real tail estimates.
    p50/mean are still populated when at least one sample exists, purely
    for visibility (per AGENT_METRICS_BRIEF.md §5).
    """

    ttft_p50: float
    ttft_p95: float
    ttft_p99: float
    ttft_mean: float

    tpot_p50: float
    tpot_p95: float
    tpot_p99: float
    tpot_mean: float

    n_requests: int
    n_warmup_discarded: int
    n_ttft_samples: int
    n_tpot_samples: int
    valid: bool

    config: dict = field(default_factory=dict)
    raw_ttft_ms: list[float] = field(default_factory=list)
    raw_tpot_ms: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON-serializable record for on-disk run logging (one run = one record)."""

        def _clean(x: float) -> float | None:
            return None if isinstance(x, float) and math.isnan(x) else x

        return {
            "config": self.config,
            "n_requests": self.n_requests,
            "n_warmup_discarded": self.n_warmup_discarded,
            "n_ttft_samples": self.n_ttft_samples,
            "n_tpot_samples": self.n_tpot_samples,
            "valid": self.valid,
            "ttft_p50": _clean(self.ttft_p50),
            "ttft_p95": _clean(self.ttft_p95),
            "ttft_p99": _clean(self.ttft_p99),
            "ttft_mean": _clean(self.ttft_mean),
            "tpot_p50": _clean(self.tpot_p50),
            "tpot_p95": _clean(self.tpot_p95),
            "tpot_p99": _clean(self.tpot_p99),
            "tpot_mean": _clean(self.tpot_mean),
            "raw_ttft_ms": self.raw_ttft_ms,
            "raw_tpot_ms": self.raw_tpot_ms,
        }

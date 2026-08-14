"""LLMRouter metrics module — TTFT/TPOT measurement pipeline.

Pure core (parse.py, compute.py) + thin I/O shell (consume.py). See
metrics/README.md for the split rationale and timing definitions.
"""

from metrics.types import ChunkEvent, RequestSample, RunMetrics
from metrics.parse import parse_sse_line, is_content_chunk, extract_content
from metrics.compute import percentile, request_sample_from_events, aggregate

__all__ = [
    "ChunkEvent",
    "RequestSample",
    "RunMetrics",
    "parse_sse_line",
    "is_content_chunk",
    "extract_content",
    "percentile",
    "request_sample_from_events",
    "aggregate",
]

"""LLMRouter metrics module — TTFT/TPOT measurement pipeline.

Pure core (parse.py, compute.py) + thin I/O shell (consume.py). See
metrics/README.md for the split rationale and timing definitions.
"""

from metrics.types import ChunkEvent, RequestSample, RunMetrics

__all__ = [
    "ChunkEvent",
    "RequestSample",
    "RunMetrics",
]

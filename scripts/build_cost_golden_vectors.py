#!/usr/bin/env python
"""Run the Python request-cost reference over the full pinned corpus,
producing the golden-vector fixture Phase W3-4 uses for exact Rust<->Python
conformance testing (`WEEK3_IMPLEMENTATION_README.md` section 2.10: no
tolerances, no percentile-based acceptance).

Uses `max_tokens=512`, the locked Week 2 output-token policy
(`BASELINE.md`), as the representative case -- this is deliberately the
same value the pinned model/serving identity was already validated against
in `benchmarks/workloads/week2_headline/tokenizer_capacity_report.json`.

Usage:
    .venv/Scripts/python.exe scripts/build_cost_golden_vectors.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from cost_model.reference import load_reference_context  # noqa: E402
from loadgen.corpus import load_corpus  # noqa: E402
from metrics.artifacts import write_json_artifact  # noqa: E402

OUT_PATH = REPO_ROOT / "benchmarks" / "workloads" / "week3_cost" / "golden_vectors.v1.jsonl"

# The locked Week 2 output-token policy (BASELINE.md: "Output policy
# `max_tokens` = 512"). Golden vectors are built at this single value --
# W3-4's edge cases separately cover other max_tokens values.
MAX_TOKENS = 512


def main() -> None:
    ctx = load_reference_context()
    corpus = load_corpus()

    rows = []
    for prompt in corpus.prompts:
        request = {
            "model": ctx.provenance.model_id,
            "messages": [{"role": "user", "content": prompt.text}],
            "max_tokens": MAX_TOKENS,
            "stream": True,
        }
        cost = ctx.compute(request)
        rows.append({
            "prompt_id": prompt.prompt_id,
            "input_tokens": cost.input_tokens,
            "max_output_tokens": cost.max_output_tokens,
            "reserved_tokens": cost.reserved_tokens,
            "estimated_kv_bytes": cost.estimated_kv_bytes,
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # JSONL, not a single JSON artifact (5,000 independent rows) -- byte-stable
    # ascii-safe write, matching metrics/artifacts.py's json_artifact_bytes
    # convention line by line.
    from metrics.artifacts import json_artifact_bytes
    import hashlib

    with OUT_PATH.open("wb") as f:
        for row in rows:
            f.write(json_artifact_bytes(row, indent=None))
            f.write(b"\n")
    sha = hashlib.sha256(OUT_PATH.read_bytes()).hexdigest()

    input_tokens = [r["input_tokens"] for r in rows]
    print(f"corpus: {len(rows):,} prompts")
    print(f"input_tokens: min={min(input_tokens)} max={max(input_tokens)}")
    print(f"written: {OUT_PATH.relative_to(REPO_ROOT)}  sha256={sha[:16]}...")


if __name__ == "__main__":
    main()

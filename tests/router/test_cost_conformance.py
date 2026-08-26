"""Week 3 full-corpus Rust<->Python request-cost conformance
(WEEK3_IMPLEMENTATION_README.md section 2.10: exact equality required over
the full pinned corpus, no tolerances, no percentile-based acceptance).

Drives the real, compiled router (the same session-scoped process every
other router-eval test in this directory uses) with every golden-vector
request from benchmarks/workloads/week3_cost/golden_vectors.v1.jsonl
(scripts/build_cost_golden_vectors.py, the Python reference run over the
full 5,000-row corpus) and asserts the three X-Request-Cost-* response
headers match exactly.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_VECTORS = REPO_ROOT / "benchmarks" / "workloads" / "week3_cost" / "golden_vectors.v1.jsonl"
CORPUS = REPO_ROOT / "corpus" / "baseline_prompts.jsonl"

PINNED_MODEL = "meta-llama/Llama-3.2-3B-Instruct"

pytestmark = [pytest.mark.router, pytest.mark.slow]


def _load_golden() -> list[dict]:
    rows = []
    with GOLDEN_VECTORS.open(encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def _load_corpus_texts() -> dict[int, str]:
    texts = {}
    with CORPUS.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            texts[row["prompt_id"]] = row["text"]
    return texts


def test_full_corpus_conformance(router_base_url):
    golden = _load_golden()
    texts = _load_corpus_texts()
    assert len(golden) == 5000, "golden vectors file does not cover the full corpus"

    mismatches: list[tuple[int, dict, dict]] = []
    missing: list[int] = []

    with httpx.Client(timeout=30.0) as client:
        for row in golden:
            body = {
                "model": PINNED_MODEL,
                "messages": [{"role": "user", "content": texts[row["prompt_id"]]}],
                "max_tokens": row["max_output_tokens"],
                "stream": True,
            }
            with client.stream("POST", f"{router_base_url}/v1/chat/completions", json=body) as resp:
                headers = resp.headers

            cost_headers = (
                "x-request-cost-input-tokens",
                "x-request-cost-reserved-tokens",
                "x-request-cost-estimated-kv-bytes",
            )
            if not all(h in headers for h in cost_headers):
                missing.append(row["prompt_id"])
                continue

            got = {
                "input_tokens": int(headers["x-request-cost-input-tokens"]),
                "reserved_tokens": int(headers["x-request-cost-reserved-tokens"]),
                "estimated_kv_bytes": int(headers["x-request-cost-estimated-kv-bytes"]),
            }
            expected = {
                "input_tokens": row["input_tokens"],
                "reserved_tokens": row["reserved_tokens"],
                "estimated_kv_bytes": row["estimated_kv_bytes"],
            }
            if got != expected:
                mismatches.append((row["prompt_id"], expected, got))

    assert not missing, (
        f"{len(missing)}/{len(golden)} golden-vector requests (all supported by construction) "
        f"received no cost at all: prompt_ids {missing[:10]}"
    )
    assert not mismatches, (
        f"{len(mismatches)}/{len(golden)} prompts diverged between Rust and the Python golden "
        f"vectors (no tolerance permitted). First few: {mismatches[:5]}"
    )

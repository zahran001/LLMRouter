#!/usr/bin/env python
"""Characterize the request-cost distribution over the full pinned corpus
(`WEEK3_IMPLEMENTATION_README.md` section 6 W3-5).

Reads the golden vectors (`scripts/build_cost_golden_vectors.py`'s output,
already the Python reference computed over the full 5,000-row corpus at
the locked max_tokens=512 policy) and reports min/p50/p90/p95/p99/max for
`input_tokens`, `reserved_tokens`, `estimated_kv_bytes`.

Uses `metrics.percentile.percentile_nearest_rank` -- the SAME percentile
convention Week 2's headline evidence uses (an always-observed value, no
interpolation) -- rather than inventing a new one for Week 3.

This is workload characterization, not a routing experiment: it does not
define short/medium/long strata (the README explicitly says not to
silently reuse Week 2's character-based strata as KV-cost strata, and that
any such banding is a separate, later decision).

Usage:
    .venv/Scripts/python.exe scripts/characterize_cost_distribution.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from metrics.artifacts import write_json_artifact  # noqa: E402
from metrics.percentile import percentile_nearest_rank, percentile_provenance  # noqa: E402

GOLDEN_VECTORS = REPO_ROOT / "benchmarks" / "workloads" / "week3_cost" / "golden_vectors.v1.jsonl"
OUT_PATH = REPO_ROOT / "benchmarks" / "workloads" / "week3_cost" / "cost_distribution.v1.json"

FIELDS = ("input_tokens", "reserved_tokens", "estimated_kv_bytes")
# p0/p100 are covered by the explicit min/max keys below; percentile_nearest_rank
# supports them too (rank clamps to 1/n), but min()/max() says the same thing
# more directly.
QUANTILES = (50, 90, 95, 99)


def _load_rows() -> list[dict]:
    rows = []
    with GOLDEN_VECTORS.open(encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def main() -> None:
    rows = _load_rows()
    if not rows:
        raise SystemExit(f"{GOLDEN_VECTORS} is empty -- run scripts/build_cost_golden_vectors.py first")

    distribution = {}
    for field in FIELDS:
        values = [row[field] for row in rows]
        distribution[field] = {
            "min": min(values),
            "max": max(values),
            **{f"p{q}": percentile_nearest_rank(values, q) for q in QUANTILES},
        }

    report = {
        "what": "Week 3 request-cost distribution over the full pinned corpus "
                "(WEEK3_IMPLEMENTATION_README.md section 6 W3-5).",
        "source": {
            "golden_vectors": "benchmarks/workloads/week3_cost/golden_vectors.v1.jsonl",
            "n": len(rows),
            "max_output_tokens_policy": rows[0]["max_output_tokens"],
        },
        "percentile_convention": percentile_provenance(),
        "distribution": distribution,
        "caveat": "Workload characterization only -- deliberately does not define short/medium/"
                  "long KV-cost strata. Week 2's character-based strata "
                  "(tokenizer_capacity_report.json) are NOT reused here as KV-cost strata; any "
                  "such banding is a separate Week 4 decision to be defined and documented on "
                  "its own before being locked.",
    }

    sha = write_json_artifact(OUT_PATH, report)

    print(f"n = {len(rows):,} (full pinned corpus)\n")
    for field in FIELDS:
        d = distribution[field]
        print(f"{field}:")
        print(f"  min={d['min']:,}  p50={d['p50']:,}  p90={d['p90']:,}  p95={d['p95']:,}  "
              f"p99={d['p99']:,}  max={d['max']:,}")
    print(f"\nwritten: {OUT_PATH.relative_to(REPO_ROOT)}  sha256={sha[:16]}...")


if __name__ == "__main__":
    main()

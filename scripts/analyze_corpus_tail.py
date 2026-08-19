#!/usr/bin/env python
"""Corpus length structure and candidate headline strata (Redesign README R1).

What this exists to answer. The first session held the prompt *population*
distribution constant across RPS points and still let the *realized* tail
move: a 120s window at 1 RPS drew ~116 prompts and zero above 10k chars,
the same window at 10 RPS drew ~1316 and fourteen. A p99 over a few hundred
samples is decided by its top few requests, so the two points were not
comparable no matter how carefully the seed was pinned
(WEEK2_GPU_REDESIGN_HANDOFF.md 7).

The redesign fixes that by choosing a canonical prompt multiset whose
composition is fixed by construction rather than by luck (README D2/D3).
Doing that needs three numbers this script produces and does not choose:

    k  how many strata, and where their boundaries sit
    L  the tail boundary -- above which a prompt counts as tail support
    N  how many post-warmup arrivals one run carries

Every number below is a **recommendation input**. The human locks k/L/N at
Hard Stop R3 (README 4/R3); this script's job is to make that read possible,
not to make it.

Outputs (JSON, machine-readable, plus a printed summary):
    benchmarks/calibration/week2_redesign/corpus_tail_analysis.json

Usage:
    .venv/Scripts/python.exe scripts/analyze_corpus_tail.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from loadgen.corpus import load_corpus  # noqa: E402

OUT_DIR = REPO_ROOT / "benchmarks" / "calibration" / "week2_redesign"
OUT_PATH = OUT_DIR / "corpus_tail_analysis.json"

# Quantiles reported for the whole corpus. Dense in the upper tail because
# that is the only region that moves a p99.
QUANTILES = (0, 1, 5, 10, 25, 50, 75, 90, 95, 97.5, 99, 99.5, 99.9, 100)

# Candidate stratum constructions, as quantile edges in percent. These are
# starting points for the human read, NOT a lock (README R1). Each is named
# by its k (number of strata) and by what it is trying to buy.
CANDIDATE_CONSTRUCTIONS = {
    "k3_coarse": {
        "edges_pct": [0, 90, 99, 100],
        "rationale": "Minimal structure: body / shoulder / top-1%. The top stratum is exactly "
                     "the population a p99 reads, so this is the smallest construction that "
                     "controls the quantity that decided the first session.",
    },
    "k4_tail_split": {
        "edges_pct": [0, 50, 90, 99, 100],
        "rationale": "Splits the body at the median so the bulk prompt cost is held fixed too, "
                     "not only the tail.",
    },
    "k6_readme_example": {
        "edges_pct": [0, 50, 90, 95, 99, 99.5, 100],
        "rationale": "The structure the README offers as an exploration starting point. "
                     "Resolves the top 1% into two strata, so the extreme sub-tail cannot "
                     "vary inside a single bucket.",
    },
    "k5_deep_tail": {
        "edges_pct": [0, 50, 90, 99, 99.9, 100],
        "rationale": "Isolates the top 0.1% -- the region where the single extreme prompt that "
                     "flipped the 2-RPS classification lives. Costs the most tail availability.",
    },
}

# Candidate tail boundaries L, as corpus quantiles. L defines what counts as
# 'tail support': the canonical multiset must contain enough prompts above it.
CANDIDATE_L_PCT = (90.0, 95.0, 99.0, 99.5)

# Candidate run sizes, matching the R2 bootstrap grid so the two analyses can
# be read against each other in R3.
CANDIDATE_N = (250, 500, 750, 1000, 1250, 1500, 2000, 2500, 3000, 4000, 5000)


def quantile(lengths: np.ndarray, q_pct: float) -> float:
    return float(np.percentile(lengths, q_pct, method="linear"))


def histogram(lengths: np.ndarray) -> dict:
    """Log-spaced bins. Linear bins over a distribution running 1 -> 44445
    chars put ~99% of the corpus in the first bucket and say nothing about
    the region that matters."""
    lo = max(1, int(lengths.min()))
    hi = int(lengths.max())
    edges = np.unique(np.round(np.logspace(np.log10(lo), np.log10(hi), 25)).astype(int))
    counts, _ = np.histogram(lengths, bins=edges)
    return {
        "bin_edges_chars": [int(e) for e in edges],
        "counts": [int(c) for c in counts],
        "note": "log-spaced bins; edges are inclusive-left, exclusive-right, last bin closed",
    }


def ecdf(lengths: np.ndarray, n_points: int = 60) -> dict:
    """Empirical CDF sampled at evenly spaced ranks (not evenly spaced
    lengths), so the tail keeps resolution."""
    srt = np.sort(lengths)
    idx = np.unique(np.round(np.linspace(0, len(srt) - 1, n_points)).astype(int))
    return {
        "char_len": [int(srt[i]) for i in idx],
        "cumulative_fraction": [float((i + 1) / len(srt)) for i in idx],
    }


def build_construction(name: str, spec: dict, lengths: np.ndarray) -> dict:
    """Resolve a construction's quantile edges into char-length boundaries and
    the count of corpus prompts available in each stratum."""
    edges_pct = spec["edges_pct"]
    edges_chars = [quantile(lengths, p) for p in edges_pct]

    strata = []
    for i in range(len(edges_pct) - 1):
        lo_pct, hi_pct = edges_pct[i], edges_pct[i + 1]
        lo_chars, hi_chars = edges_chars[i], edges_chars[i + 1]
        is_last = i == len(edges_pct) - 2
        if is_last:
            mask = (lengths >= lo_chars) & (lengths <= hi_chars)
        else:
            mask = (lengths >= lo_chars) & (lengths < hi_chars)
        available = int(mask.sum())
        strata.append({
            "index": i,
            "quantile_range_pct": [lo_pct, hi_pct],
            "char_len_range": [lo_chars, hi_chars],
            "population_fraction": (hi_pct - lo_pct) / 100.0,
            "available_prompts": available,
        })

    # Duplicate boundaries are the failure mode that makes a construction
    # unusable: if two quantile edges land on the same char length (a mass
    # point in the distribution), the stratum between them is empty and its
    # 'fixed count' cannot be filled from the corpus at all.
    degenerate = [s["index"] for s in strata if s["available_prompts"] == 0]

    # Proportional allocation is the default because D3 asks for *controlled
    # representative* tail coverage, not tail inflation: each stratum gets its
    # natural share of N, deterministically, instead of however many the RNG
    # happened to draw. Largest-remainder so the parts sum to exactly N.
    def allocate(n: int) -> list[int]:
        exact = [n * s["population_fraction"] for s in strata]
        floors = [int(np.floor(x)) for x in exact]
        remainder = n - sum(floors)
        order = np.argsort([-(x - f) for x, f in zip(exact, floors)])
        for j in range(remainder):
            floors[order[j % len(floors)]] += 1
        return floors

    per_n = {}
    for n in CANDIDATE_N:
        alloc = allocate(n)
        # Selection is WITHOUT replacement inside a stratum: repeating a prompt
        # inside one run invites prefix-cache reuse effects that are not part of
        # the thing being measured (handoff 16.1). That makes per-stratum
        # availability a hard ceiling on N, which is where N_max comes from.
        overdrawn = [
            {
                "stratum": s["index"],
                "needed": a,
                "available": s["available_prompts"],
            }
            for s, a in zip(strata, alloc) if a > s["available_prompts"]
        ]
        per_n[str(n)] = {
            "allocation": alloc,
            "feasible_without_replacement": not overdrawn and not degenerate,
            "overdrawn_strata": overdrawn,
        }

    # The largest N this construction can serve without repeating a prompt.
    feasible_ns = [n for n in CANDIDATE_N if per_n[str(n)]["feasible_without_replacement"]]
    binding = min(
        (
            (s["available_prompts"] / s["population_fraction"], s["index"])
            for s in strata if s["population_fraction"] > 0
        ),
        default=(0.0, None),
    )

    return {
        "name": name,
        "k": len(strata),
        "rationale": spec["rationale"],
        "edges_pct": edges_pct,
        "edges_chars": edges_chars,
        "strata": strata,
        "degenerate_strata": degenerate,
        "allocation_rule": "proportional to population fraction, largest-remainder, "
                           "without replacement within a stratum",
        "per_candidate_N": per_n,
        "max_feasible_N_on_grid": max(feasible_ns) if feasible_ns else None,
        "binding_stratum": {
            "index": binding[1],
            "implied_N_ceiling": int(np.floor(binding[0])) if binding[1] is not None else None,
            "note": "N ceiling implied by the scarcest stratum under proportional, "
                    "without-replacement selection",
        },
    }


def tail_support_table(lengths: np.ndarray) -> list[dict]:
    """For each candidate tail boundary L and each candidate N: how many
    canonical prompts land above L, and how many corpus prompts exist to
    choose them from. This is the R1 half of the joint R3 read."""
    rows = []
    for l_pct in CANDIDATE_L_PCT:
        l_chars = quantile(lengths, l_pct)
        available = int((lengths >= l_chars).sum())
        tail_fraction = (100.0 - l_pct) / 100.0
        for n in CANDIDATE_N:
            in_multiset = int(np.floor(n * tail_fraction))
            rows.append({
                "L_pct": l_pct,
                "L_chars": l_chars,
                "N": n,
                "corpus_prompts_above_L": available,
                "canonical_prompts_above_L": in_multiset,
                "feasible_without_replacement": in_multiset <= available,
                "top_1pct_of_N": n / 100.0,
            })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    corpus = load_corpus(args.corpus) if args.corpus else load_corpus()
    lengths = np.array([p.char_len for p in corpus.prompts], dtype=float)
    corpus_sha = hashlib.sha256(corpus.source_path.read_bytes()).hexdigest()

    prov_path = corpus.source_path.with_name(corpus.source_path.stem + ".provenance.json")
    corpus_prov = json.loads(prov_path.read_text(encoding="utf-8")) if prov_path.exists() else None

    analysis = {
        "what": "Pinned-corpus length structure and candidate headline strata (README R1).",
        "status": "RECOMMENDATION INPUT -- k, L and N are locked by the human at Hard Stop R3",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus": {
            "path": str(corpus.source_path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "sha256": corpus_sha,
            "total_prompts": len(corpus),
            "prompt_len_definition": "char count of the first human turn, stripped "
                                     "(token count is a Week 3 revisit, WEEK2_PLAN.md 3.4)",
            "build_provenance": corpus_prov,
        },
        "length_summary": {
            "min": float(lengths.min()),
            "max": float(lengths.max()),
            "mean": float(lengths.mean()),
            "std": float(lengths.std(ddof=1)),
            "quantiles": {str(q): quantile(lengths, q) for q in QUANTILES},
        },
        "histogram": histogram(lengths),
        "ecdf": ecdf(lengths),
        "counts_above_quantile": {
            str(q): {
                "char_len_threshold": quantile(lengths, q),
                "count": int((lengths >= quantile(lengths, q)).sum()),
            }
            for q in (90, 95, 99, 99.5, 99.9)
        },
        "counts_above_absolute_chars": {
            str(t): int((lengths >= t).sum()) for t in (1000, 2000, 5000, 10000, 20000, 40000)
        },
        "candidate_constructions": [
            build_construction(name, spec, lengths)
            for name, spec in CANDIDATE_CONSTRUCTIONS.items()
        ],
        "candidate_L": list(CANDIDATE_L_PCT),
        "candidate_N": list(CANDIDATE_N),
        "tail_support": tail_support_table(lengths),
        "caveats": [
            "Selection without replacement within a stratum means per-stratum availability "
            "caps N. Allowing repeats would lift the cap but invites prefix-cache reuse "
            "effects inside one run (handoff 16.1), which is not the thing being measured.",
            "prompt_len is char count, not tokens. The tail boundary L is therefore a proxy "
            "for prefill cost; the char/token ratio is not constant across prompts "
            "(WEEK2_PLAN.md 3.4 defers tokens to Week 3).",
            "Proportional allocation preserves the corpus's natural composition exactly. Any "
            "tail-floor variant that raises the top stratum above its natural share changes "
            "the workload's mean prompt cost and is a different experiment, not a bigger one.",
        ],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")

    # ---- printed summary -------------------------------------------------
    q = analysis["length_summary"]["quantiles"]
    print(f"\ncorpus: {analysis['corpus']['path']}  n={len(corpus)}  sha256={corpus_sha[:12]}...")
    print(f"char_len: min={lengths.min():.0f} p50={q['50']:.0f} p90={q['90']:.0f} "
          f"p99={q['99']:.0f} p99.9={q['99.9']:.0f} max={lengths.max():.0f}")
    print(f"          mean={lengths.mean():.0f} std={lengths.std(ddof=1):.0f}  "
          f"(mean sits at the {float((lengths <= lengths.mean()).mean()) * 100:.1f}th percentile "
          "-- the distribution is strongly right-skewed)")

    print("\ncounts above quantile:")
    for qq, rec in analysis["counts_above_quantile"].items():
        print(f"  q{qq:<5} >= {rec['char_len_threshold']:>8.0f} chars   {rec['count']:>4} prompts")

    print("\ncandidate constructions (proportional, without replacement):")
    print(f"{'name':<20} {'k':>2} {'edges (pct)':<34} {'scarcest stratum':>17} {'N ceiling':>10}")
    print("-" * 88)
    for c in analysis["candidate_constructions"]:
        edges = "/".join(str(e) for e in c["edges_pct"])
        b = c["binding_stratum"]
        flag = "  DEGENERATE" if c["degenerate_strata"] else ""
        print(f"{c['name']:<20} {c['k']:>2} {edges:<34} "
              f"{'#' + str(b['index']):>17} {b['implied_N_ceiling']:>10}{flag}")

    print("\ntail support -- canonical prompts above L, per candidate N:")
    header = f"{'L':<10} {'L chars':>9} {'avail':>7} " + "".join(f"{n:>7}" for n in CANDIDATE_N)
    print(header)
    print("-" * len(header))
    for l_pct in CANDIDATE_L_PCT:
        rows = [r for r in analysis["tail_support"] if r["L_pct"] == l_pct]
        r0 = rows[0]
        cells = "".join(
            f"{r['canonical_prompts_above_L']:>7}" if r["feasible_without_replacement"]
            else f"{'!' + str(r['canonical_prompts_above_L']):>7}"
            for r in rows
        )
        print(f"q{l_pct:<9} {r0['L_chars']:>9.0f} {r0['corpus_prompts_above_L']:>7} {cells}")
    print("  (! = needs more prompts above L than the corpus holds)")

    print(f"\nwritten: {args.out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

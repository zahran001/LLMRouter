#!/usr/bin/env python
"""Intrinsic prompt cost vs TTFT, from first-session evidence (Redesign
README R1 support for the tail boundary L; handoff 6 and 7).

R1 asks for candidate strata and a tail boundary L. Quantile edges alone
cannot justify one: `q99` is a fact about the corpus, not about latency. The
number that makes L meaningful is *where along the length axis a prompt
starts costing enough TTFT to matter against a 500ms SLO* -- and the first
session measured exactly that, twice:

  unloaded floor   concurrency 1, 248 prompts, 0 errors -> intrinsic prefill
                   cost with no queueing, no decode contention, nothing to
                   confound it;
  2 RPS / 1.5 RPS  the same prompts under real load, so the same axis can be
                   read with interference present.

So this script does not invent a cost model. It reads the measured relation,
reports it per candidate stratum, and states the one number the human needs
before locking L: how much headroom exists between the unloaded p99 and the
500ms SLO.

It also reports percentile-method sensitivity, because the first session's
own artifacts disagree with each other about what p99 means (see
`percentile_method_sensitivity` in the output).

Everything here is DIAGNOSTIC. The prompts are the first session's realized
draws, not the redesigned canonical workload, and the corpus-wide projection
is an extrapolation from 248 observations -- labelled as such in the output.

Usage:
    .venv/Scripts/python.exe scripts/analyze_prompt_cost.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from loadgen.corpus import load_corpus  # noqa: E402

EVIDENCE = REPO_ROOT / "benchmarks" / "evidence" / "week2" / "first_session"
OUT_PATH = REPO_ROOT / "benchmarks" / "calibration" / "week2_redesign" / "prompt_cost_analysis.json"

SLO_MS = 500.0

# The warmup the first session's point records used. Not a redesign choice --
# it is what these arrays were filtered by, and changing it here would make
# the numbers disagree with the promoted metrics records for no reason.
HISTORICAL_WARMUP_S = 10.0

PERCENTILE_METHODS = ("linear", "lower", "higher", "nearest", "midpoint")

# Candidate tail boundaries, echoing scripts/analyze_corpus_tail.py.
CANDIDATE_L_PCT = (90.0, 95.0, 99.0, 99.5)


def load_unloaded_floor() -> tuple[np.ndarray, np.ndarray]:
    """char_len and TTFT at concurrency 1. This sidecar has its own schema
    (seq/prompt_id/char_len/ttft_ms) because it was written by a one-off
    on-instance script that is not in the repo -- see the caveats."""
    path = EVIDENCE / "unloaded_floor" / "unloaded_floor.samples.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [r for r in rows if r.get("error") is None and r.get("ttft_ms") is not None]
    return (np.array([r["char_len"] for r in rows], dtype=float),
            np.array([r["ttft_ms"] for r in rows], dtype=float))


def load_loaded_point(tag: str) -> tuple[np.ndarray, np.ndarray]:
    """char_len and TTFT for a Stage A point, post-warmup. prompt_len lives in
    the raw log and ttft_ms in the sidecar; they join on request_id (that
    split is deliberate, WEEK2_PLAN.md 3.1)."""
    raw_path = EVIDENCE / "stage_a" / f"{tag}.raw_log.jsonl"
    sam_path = EVIDENCE / "stage_a" / f"{tag}.samples.jsonl"
    lens = {
        r["request_id"]: r["prompt_len"]
        for r in (json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip())
    }
    pairs = []
    for line in sam_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        s = json.loads(line)
        if s["send_time"] < HISTORICAL_WARMUP_S or s.get("ttft_ms") is None or s.get("error"):
            continue
        pairs.append((lens[s["request_id"]], s["ttft_ms"]))
    return (np.array([p[0] for p in pairs], dtype=float),
            np.array([p[1] for p in pairs], dtype=float))


def method_table(values: np.ndarray, p: float = 99.0) -> dict:
    return {m: float(np.percentile(values, p, method=m)) for m in PERCENTILE_METHODS}


def stratum_costs(char_len: np.ndarray, ttft: np.ndarray, edges: list[float]) -> list[dict]:
    out = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        last = i == len(edges) - 2
        mask = (char_len >= lo) & ((char_len <= hi) if last else (char_len < hi))
        n = int(mask.sum())
        row = {"char_len_range": [lo, hi], "n": n}
        if n:
            row.update({
                "ttft_p50_ms": float(np.percentile(ttft[mask], 50)),
                "ttft_max_ms": float(ttft[mask].max()),
                "ttft_mean_ms": float(ttft[mask].mean()),
                "fraction_over_slo": float((ttft[mask] >= SLO_MS).mean()),
            })
        out.append(row)
    return out


def fit_linear(char_len: np.ndarray, ttft: np.ndarray) -> dict:
    """Least-squares TTFT ~ a + b*char_len. Deliberately the simplest model
    that can be checked by eye: prefill cost is roughly linear in prompt
    tokens, and the point of the fit is to project the measured relation onto
    the rest of the corpus, not to be the best possible predictor."""
    b, a = np.polyfit(char_len, ttft, 1)
    pred = a + b * char_len
    ss_res = float(((ttft - pred) ** 2).sum())
    ss_tot = float(((ttft - ttft.mean()) ** 2).sum())
    return {
        "intercept_ms": float(a),
        "slope_ms_per_char": float(b),
        "r_squared": 1.0 - ss_res / ss_tot,
        "pearson_r": float(np.corrcoef(char_len, ttft)[0, 1]),
        "n": int(len(char_len)),
        "residual_std_ms": float(np.std(ttft - pred, ddof=2)),
    }


def cap_sensitivity(char_len: np.ndarray, ttft: np.ndarray, caps: list[float]) -> list[dict]:
    """p99 after excluding every prompt longer than a cap. This is the
    diagnostic that flipped the 2-RPS classification (handoff 7): it measures
    how much of the verdict rests on a handful of extreme prompts."""
    rows = []
    for cap in caps:
        mask = char_len <= cap
        if not mask.any():
            continue
        rows.append({
            "cap_chars": cap,
            "n_kept": int(mask.sum()),
            "n_excluded": int((~mask).sum()),
            "ttft_p99_ms": float(np.percentile(ttft[mask], 99, method="linear")),
            "classification": "OVER" if float(np.percentile(ttft[mask], 99, method="linear")) >= SLO_MS else "UNDER",
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    corpus = load_corpus()
    corpus_lens = np.array([p.char_len for p in corpus.prompts], dtype=float)

    floor_len, floor_ttft = load_unloaded_floor()
    fit = fit_linear(floor_len, floor_ttft)

    # Candidate-L boundaries in char terms, from the pinned corpus.
    l_bounds = {str(p): float(np.percentile(corpus_lens, p)) for p in CANDIDATE_L_PCT}

    # What the measured relation implies for the WHOLE corpus. This is the
    # number that decides whether the headline experiment has room to move:
    # if the projected unloaded p99 already sits at the SLO, the curve has
    # nowhere to travel and the breach RPS collapses toward zero.
    projected = fit["intercept_ms"] + fit["slope_ms_per_char"] * corpus_lens
    projection = {
        "basis": "least-squares fit over the 248 unloaded-floor observations, applied to all "
                 f"{len(corpus_lens)} pinned-corpus prompts",
        "status": "EXTRAPOLATION -- diagnostic only, not a measurement",
        "p50_ms": float(np.percentile(projected, 50)),
        "p90_ms": float(np.percentile(projected, 90)),
        "p99_ms": float(np.percentile(projected, 99)),
        "p99_5_ms": float(np.percentile(projected, 99.5)),
        "p99_9_ms": float(np.percentile(projected, 99.9)),
        "max_ms": float(projected.max()),
        "fraction_over_slo": float((projected >= SLO_MS).mean()),
        "char_len_at_slo": float((SLO_MS - fit["intercept_ms"]) / fit["slope_ms_per_char"]),
        "corpus_percentile_at_slo_length": float(
            (corpus_lens <= (SLO_MS - fit["intercept_ms"]) / fit["slope_ms_per_char"]).mean() * 100.0
        ),
    }

    points = {}
    for tag in ("poisson_rps1.5", "poisson_rps2"):
        cl, tt = load_loaded_point(tag)
        order = np.argsort(-tt)[:10]
        points[tag] = {
            "n": int(len(tt)),
            "ttft_p99_ms_by_method": method_table(tt),
            "top_10_ttft": [
                {"char_len": float(cl[i]), "ttft_ms": float(tt[i])} for i in order
            ],
            "pearson_r_len_vs_ttft": float(np.corrcoef(cl, tt)[0, 1]),
            "cap_sensitivity": cap_sensitivity(
                cl, tt, [float(cl.max()), 16000.0, 14000.0, l_bounds["99.0"], 8000.0, l_bounds["95.0"]]
            ),
            "n_above_L": {k: int((cl >= v).sum()) for k, v in l_bounds.items()},
        }

    analysis = {
        "what": "Measured intrinsic prompt cost vs TTFT, as the empirical basis for the tail "
                "boundary L (README R1).",
        "status": "DIAGNOSTIC / RECOMMENDATION INPUT -- L is locked by the human at Hard Stop R3",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "slo_ms": SLO_MS,
        "historical_warmup_s": HISTORICAL_WARMUP_S,
        "candidate_L_chars": l_bounds,
        "unloaded_floor": {
            "source": "benchmarks/evidence/week2/first_session/unloaded_floor/unloaded_floor.samples.jsonl",
            "n": int(len(floor_ttft)),
            "concurrency": 1,
            "ttft_p99_ms_by_method": method_table(floor_ttft),
            "ttft_max_ms": float(floor_ttft.max()),
            "fit": fit,
            "by_candidate_stratum": stratum_costs(
                floor_len, floor_ttft,
                [0.0, float(np.percentile(corpus_lens, 50)), float(np.percentile(corpus_lens, 90)),
                 l_bounds["95.0"], l_bounds["99.0"], float(corpus_lens.max())],
            ),
        },
        "corpus_wide_projection": projection,
        "loaded_points": points,
        "percentile_method_sensitivity": {
            "why_this_matters": (
                "The promoted unloaded_floor.metrics.json reports p99 = 402.269ms, which is the "
                "nearest-rank value; metrics.compute.percentile (linear interpolation, the method "
                "every Stage A point record uses) gives 388.553ms on the same 248 samples. The "
                "floor was produced by a one-off on-instance script that is not in the repo, so "
                "two percentile conventions are already mixed inside the first session's own "
                "evidence. At the boundary this is not cosmetic: it is worth tens of ms on "
                "exactly the quantity that decides UNDER vs OVER."
            ),
            "unloaded_floor": method_table(floor_ttft),
            "committed_floor_record_p99_ms": json.loads(
                (EVIDENCE / "unloaded_floor" / "unloaded_floor.metrics.json").read_text(encoding="utf-8")
            )["ttft_p99_ms"],
        },
        "caveats": [
            "The unloaded floor's 248 prompts are the 2-RPS schedule's realized draw, not the "
            "redesigned canonical multiset. Its own tail is a sample, so the fit is anchored by "
            "roughly a dozen long prompts.",
            "The corpus-wide projection is a linear extrapolation, and the corpus reaches 44445 "
            "chars while the fit was observed only to 16781. Treat the projected p99 as an "
            "order-of-magnitude read, not a prediction.",
            "char_len is a proxy for prefill token count; the ratio is not constant across "
            "prompts (WEEK2_PLAN.md 3.4 defers tokens to Week 3).",
            "Load adds interference on top of this intrinsic cost; the whole point of the "
            "headline experiment is to measure that addition, so nothing here predicts a "
            "breach RPS.",
        ],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")

    # ---- printed summary -------------------------------------------------
    print(f"\nunloaded floor (concurrency 1, n={len(floor_ttft)}):")
    print(f"  TTFT = {fit['intercept_ms']:.1f}ms + {fit['slope_ms_per_char'] * 1000:.2f}ms per 1000 chars"
          f"   r={fit['pearson_r']:.3f}  R^2={fit['r_squared']:.3f}")
    print(f"  prompt length alone explains {fit['r_squared'] * 100:.0f}% of unloaded TTFT variance")
    print("\n  intrinsic cost by candidate stratum:")
    for s in analysis["unloaded_floor"]["by_candidate_stratum"]:
        lo, hi = s["char_len_range"]
        if not s["n"]:
            print(f"    [{lo:>8.0f},{hi:>8.0f}]  n=  0")
            continue
        print(f"    [{lo:>8.0f},{hi:>8.0f}]  n={s['n']:>3}  p50={s['ttft_p50_ms']:>7.1f}ms  "
              f"max={s['ttft_max_ms']:>7.1f}ms  over-SLO={s['fraction_over_slo'] * 100:>5.1f}%")

    p = analysis["corpus_wide_projection"]
    print(f"\ncorpus-wide projection (EXTRAPOLATION, all {len(corpus_lens)} prompts):")
    print(f"  projected unloaded TTFT  p50={p['p50_ms']:.0f}ms  p99={p['p99_ms']:.0f}ms  "
          f"p99.9={p['p99_9_ms']:.0f}ms  max={p['max_ms']:.0f}ms")
    print(f"  headroom at p99 to the {SLO_MS:.0f}ms SLO: {SLO_MS - p['p99_ms']:.0f}ms "
          f"({(SLO_MS - p['p99_ms']) / SLO_MS * 100:.0f}% of the SLO)")
    print(f"  a prompt reaches {SLO_MS:.0f}ms unloaded at ~{p['char_len_at_slo']:.0f} chars "
          f"= the {p['corpus_percentile_at_slo_length']:.2f}th corpus percentile")

    for tag, rec in points.items():
        print(f"\n{tag} (post-warmup n={rec['n']}, r={rec['pearson_r_len_vs_ttft']:.3f}):")
        m = rec["ttft_p99_ms_by_method"]
        print("  p99 by method: " + "  ".join(f"{k}={v:.1f}" for k, v in m.items()))
        print("  length-cap sensitivity:")
        for row in rec["cap_sensitivity"]:
            print(f"    cap<={row['cap_chars']:>8.0f} chars  drop {row['n_excluded']:>2}  "
                  f"p99={row['ttft_p99_ms']:>7.1f}ms  {row['classification']}")

    print(f"\nwritten: {args.out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""How large must one run be before its p99 TTFT stops being fragile?
(Redesign README R2.)

The rule this replaces is `n >= 100`, which makes a p99 *computable* and says
nothing about whether it is *reliable*. At n=225 the first session's 2-RPS
point produced a p99 whose diagnostic interval straddled the 500ms SLO, so
the point could not be classified at all (handoff 8).

Method. For each candidate run size N, resample the source TTFT array with
replacement to size N, take the p99 of each resample, and read the spread of
those p99 values. That answers "if a run of size N were drawn from this
latency distribution, how much would its p99 move run to run?".

Two source arrays, run independently and never averaged (README R2):

    2 RPS    n=225  the near-boundary, classification-unstable point
    1.5 RPS  n=166  the sparse low-load point

They are NOT interchangeable, and the 1.5-RPS array is not the clean
diagnostic the README expects it to be: it was driven last, against a warm
prefix cache, and its long prompts ran ~5x FASTER than the same prompts at
concurrency 1 (`scripts/analyze_run_order_effects.py`). Its TTFT
distribution is compressed, so it will demand a SMALLER N than it should.
That is precisely why the conservative rule is max(the two) and not a blend.

What this is not. Resampling from n observations cannot invent tail mass the
source never observed: every resample p99 is bounded by the source's own
maximum, and as N grows the resample p99 converges on the source's empirical
p99 rather than on the truth. So this measures **within-distribution
sampling fragility only**, and it is a LOWER BOUND on real run-to-run
variability. Real repeatability comes from independent GPU repeats (D5), not
from here.

Usage:
    .venv/Scripts/python.exe scripts/calibrate_p99_sample_size.py
    .venv/Scripts/python.exe scripts/calibrate_p99_sample_size.py --resamples 20000
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

EVIDENCE = REPO_ROOT / "benchmarks" / "evidence" / "week2" / "first_session"
OUT_PATH = REPO_ROOT / "benchmarks" / "calibration" / "week2_redesign" / "p99_sample_size.json"

SLO_MS = 500.0
HISTORICAL_WARMUP_S = 10.0

# Deliberately extends past 2000 (README R2: "do not stop at 2000 if the
# evidence still looks unstable"). 5000 is the pinned corpus size, i.e. the
# largest canonical multiset selectable without repeating a prompt; the two
# points beyond it exist to show whether stability is reachable AT ALL, which
# is the evidence the N_max / interval-reporting decision needs.
CANDIDATE_N = (250, 500, 750, 1000, 1250, 1500, 2000, 2500, 3000, 4000, 5000, 7500, 10000)

# metrics.compute.percentile uses "linear" and every Stage A point record was
# written with it, so it is the primary. The others are carried because the
# session's own artifacts disagree: the unloaded floor's committed p99 is a
# nearest-rank value, and at the boundary the choice is worth tens of ms.
PRIMARY_METHOD = "linear"
PERCENTILE_METHODS = ("linear", "lower", "higher", "nearest", "midpoint")

MASTER_SEED = 20260818

# Candidate stability criteria. NONE of these is locked -- README R3 is
# explicit that "acceptable" is not the agent's to define. Each is reported
# as "smallest N on the grid that satisfies it", so the human can pick the
# criterion and read N off the table rather than accept a number.
FLIP_THRESHOLDS = (0.10, 0.05, 0.01)
ABS_WIDTH_THRESHOLDS_MS = (200.0, 150.0, 100.0, 50.0)
REL_WIDTH_THRESHOLDS = (0.50, 0.30, 0.20, 0.10)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_source(tag: str) -> dict:
    """The post-warmup TTFT array for one first-session point, with every
    provenance field R2 asks to record before the array is used."""
    sam_path = EVIDENCE / "stage_a" / f"{tag}.samples.jsonl"
    raw_path = EVIDENCE / "stage_a" / f"{tag}.raw_log.jsonl"
    met_path = EVIDENCE / "stage_a" / f"{tag}.metrics.json"

    committed = json.loads(met_path.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in sam_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    post = [r for r in rows if r["send_time"] >= HISTORICAL_WARMUP_S]
    ttft = np.array([r["ttft_ms"] for r in post if r.get("ttft_ms") is not None and not r.get("error")],
                    dtype=float)
    errored = [r for r in post if r.get("error")]

    raw_rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    source = {
        "tag": tag,
        "samples_path": str(sam_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "samples_sha256": sha256_file(sam_path),
        "raw_log_path": str(raw_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "raw_log_sha256": sha256_file(raw_path),
        "metrics_path": str(met_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "metrics_sha256": sha256_file(met_path),
        "nominal_lambda_rps": committed["offered_rps"],
        "materialized_schedule_count": committed["n_scheduled"],
        "issued_total": committed["n_issued_total"],
        "post_warmup_sample_count": len(ttft),
        "warmup_rule": f"time-based, discard send_time < {HISTORICAL_WARMUP_S}s "
                       "(WEEK2_PLAN.md 2.4; the placeholder N, not a resolved one)",
        "timeout_or_error_count": len(errored) + committed["n_errored_total"],
        "shed_count": committed["n_shed_total"],
        "censoring_rate": (len(errored) + committed["n_errored_total"]) / max(1, len(post)),
        "percentile_implementation": "numpy method= (see per-method results); "
                                     f"primary = {PRIMARY_METHOD}, matching metrics.compute.percentile",
        "matches_known_first_session_point": (
            len(ttft) == committed["n_ttft_samples"]
            and abs(float(np.percentile(ttft, 99, method=PRIMARY_METHOD)) - committed["ttft_p99_ms"]) < 1e-6
        ),
        "committed_point_record_p99_ms": committed["ttft_p99_ms"],
        "committed_point_record_tail_valid": committed["tail_valid"],
        "raw_log_rows": len(raw_rows),
        "observed": {
            "min_ms": float(ttft.min()),
            "p50_ms": float(np.percentile(ttft, 50, method=PRIMARY_METHOD)),
            "p95_ms": float(np.percentile(ttft, 95, method=PRIMARY_METHOD)),
            "p99_by_method_ms": {m: float(np.percentile(ttft, 99, method=m)) for m in PERCENTILE_METHODS},
            "max_ms": float(ttft.max()),
            "n_at_or_above_slo": int((ttft >= SLO_MS).sum()),
        },
    }
    return {"meta": source, "ttft": ttft}


def bootstrap_p99(ttft: np.ndarray, n: int, resamples: int, seed: int,
                  methods: tuple[str, ...]) -> dict[str, np.ndarray]:
    """p99 of `resamples` draws of size n, with replacement, per method.

    Chunked over resamples so a 10000x10000 float array is never allocated;
    the RNG stream is a single generator so the chunking does not change the
    draws for a given seed."""
    rng = np.random.default_rng(seed)
    out = {m: np.empty(resamples, dtype=float) for m in methods}
    max_cells = 20_000_000
    chunk = max(1, min(resamples, max_cells // max(1, n)))
    done = 0
    while done < resamples:
        b = min(chunk, resamples - done)
        draws = ttft[rng.integers(0, len(ttft), size=(b, n))]
        for m in methods:
            out[m][done:done + b] = np.percentile(draws, 99, axis=1, method=m)
        done += b
    return out


def summarize(p99s: np.ndarray, point_estimate: float) -> dict:
    lo, hi = np.percentile(p99s, [2.5, 97.5])
    median = float(np.median(p99s))
    frac_over = float((p99s >= SLO_MS).mean())
    point_is_over = point_estimate >= SLO_MS
    return {
        "p99_median_ms": median,
        "p99_mean_ms": float(p99s.mean()),
        "p99_ci95_ms": [float(lo), float(hi)],
        "p99_ci95_width_ms": float(hi - lo),
        "p99_ci95_relative_width": float((hi - lo) / median) if median else None,
        "p99_std_ms": float(p99s.std(ddof=1)),
        "fraction_under_slo": float((p99s < SLO_MS).mean()),
        "fraction_at_or_over_slo": frac_over,
        # "Flip" = a run of this size disagreeing with the source point's own
        # classification. It is the quantity that decides whether a single run
        # can be trusted to classify the point at all.
        "flip_rate": float(1.0 - frac_over) if point_is_over else frac_over,
        "ci_straddles_slo": bool(lo < SLO_MS <= hi),
    }


def smallest_n_meeting(rows: dict, predicate) -> int | None:
    for n in CANDIDATE_N:
        if predicate(rows[str(n)]):
            return n
    return None


def study(source: dict, resamples: int, seed_base: int) -> dict:
    ttft = source["ttft"]
    point_estimate = source["meta"]["observed"]["p99_by_method_ms"][PRIMARY_METHOD]

    per_n = {}
    method_sensitivity = {}
    for i, n in enumerate(CANDIDATE_N):
        seed = seed_base + i
        boots = bootstrap_p99(ttft, n, resamples, seed, PERCENTILE_METHODS)
        primary = summarize(boots[PRIMARY_METHOD], point_estimate)
        primary.update({
            "N": n,
            "resamples": resamples,
            "seed": seed,
            "top_1pct_support": n / 100.0,
        })
        per_n[str(n)] = primary
        method_sensitivity[str(n)] = {
            m: {
                "p99_median_ms": float(np.median(boots[m])),
                "flip_rate": summarize(boots[m], point_estimate)["flip_rate"],
            }
            for m in PERCENTILE_METHODS
        }

    criteria = {
        "flip_rate_at_most": {
            f"{t:.2f}": smallest_n_meeting(per_n, lambda r, t=t: r["flip_rate"] <= t)
            for t in FLIP_THRESHOLDS
        },
        "ci95_width_ms_at_most": {
            f"{t:.0f}": smallest_n_meeting(per_n, lambda r, t=t: r["p99_ci95_width_ms"] <= t)
            for t in ABS_WIDTH_THRESHOLDS_MS
        },
        "ci95_relative_width_at_most": {
            f"{t:.2f}": smallest_n_meeting(per_n, lambda r, t=t: r["p99_ci95_relative_width"] <= t)
            for t in REL_WIDTH_THRESHOLDS
        },
        "ci95_clears_slo_entirely": smallest_n_meeting(per_n, lambda r: not r["ci_straddles_slo"]),
    }

    return {
        "source": source["meta"],
        "point_estimate_ms": point_estimate,
        "point_classification": "OVER" if point_estimate >= SLO_MS else "UNDER",
        "per_candidate_N": per_n,
        "percentile_method_sensitivity": method_sensitivity,
        "candidate_criteria": criteria,
        "criteria_note": (
            "Each entry is the SMALLEST grid N meeting that criterion, or null if no grid N "
            "does. None of these thresholds is locked -- README R3 reserves the definition of "
            "'acceptable' for the human."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--resamples", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=MASTER_SEED)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    sources = {tag: load_source(tag) for tag in ("poisson_rps1.5", "poisson_rps2")}
    studies = {
        tag: study(src, args.resamples, args.seed + 1000 * i)
        for i, (tag, src) in enumerate(sources.items())
    }

    analysis = {
        "what": "p99 TTFT stability vs candidate run size N, from first-session TTFT arrays "
                "(README R2).",
        "status": "RECOMMENDATION INPUT -- N is locked by the human at Hard Stop R3",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {
            "slo_ms": SLO_MS,
            "candidate_N": list(CANDIDATE_N),
            "resamples_per_N": args.resamples,
            "master_seed": args.seed,
            "seed_rule": "seed_base + index of N in candidate_N; seed_base = master_seed + "
                         "1000 * source index",
            "primary_percentile_method": PRIMARY_METHOD,
            "percentile_methods": list(PERCENTILE_METHODS),
            "historical_warmup_s": HISTORICAL_WARMUP_S,
            "resampling": "nonparametric bootstrap, with replacement, from the post-warmup "
                          "TTFT array of one first-session point",
        },
        "studies": studies,
        "combination_rule": {
            "rule": "N_p99_stability_requirement = max(N_requirement per source), per criterion",
            "why_not_averaged": (
                "README R2 forbids averaging the two, and the evidence says why: the two arrays "
                "fail in opposite directions. The 2-RPS array sits on the SLO, so its "
                "requirement is driven by flip rate. The 1.5-RPS array is compressed by prefix-"
                "cache reuse, so its interval is narrow for a reason that has nothing to do "
                "with sample size, and averaging would import that artifact into the lock."
            ),
            "per_criterion": {},
        },
        "known_limitations": [
            "Bootstrap resamples cannot exceed the source's observed maximum TTFT, so this is a "
            "LOWER BOUND on run-to-run variability, not an estimate of it.",
            "Concurrent request latencies are not iid -- queueing correlates neighbouring "
            "requests -- so the nominal 95% coverage is optimistic. The README already calls "
            "this diagnostic-only (handoff 8).",
            "Neither source array is the redesigned canonical workload. Their prompt mixes are "
            "the first session's realized draws, which is the confound the redesign removes.",
            "The 1.5-RPS array is prefix-cache contaminated (scripts/analyze_run_order_effects.py). "
            "It is included because R2 requires both, and because the conservative max() rule "
            "makes its optimism harmless -- not because it is a clean low-load reference.",
        ],
    }

    # Conservative combination, per criterion, computed rather than asserted.
    combo = analysis["combination_rule"]["per_criterion"]
    a, b = studies["poisson_rps1.5"]["candidate_criteria"], studies["poisson_rps2"]["candidate_criteria"]
    for family in ("flip_rate_at_most", "ci95_width_ms_at_most", "ci95_relative_width_at_most"):
        combo[family] = {}
        for k in a[family]:
            va, vb = a[family][k], b[family][k]
            combo[family][k] = None if (va is None or vb is None) else max(va, vb)
    va, vb = a["ci95_clears_slo_entirely"], b["ci95_clears_slo_entirely"]
    combo["ci95_clears_slo_entirely"] = None if (va is None or vb is None) else max(va, vb)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")

    # ---- printed summary -------------------------------------------------
    for tag, st in studies.items():
        m = st["source"]
        print(f"\n=== {tag} ===")
        print(f"  source n={m['post_warmup_sample_count']}  nominal lambda={m['nominal_lambda_rps']} RPS  "
              f"errors={m['timeout_or_error_count']}  censoring={m['censoring_rate'] * 100:.1f}%")
        print(f"  matches the committed point record: {m['matches_known_first_session_point']} "
              f"(record p99 {m['committed_point_record_p99_ms']:.1f}ms)")
        print(f"  observed p99 by method: " +
              "  ".join(f"{k}={v:.1f}" for k, v in m["observed"]["p99_by_method_ms"].items()))
        print(f"  point estimate {st['point_estimate_ms']:.1f}ms -> {st['point_classification']}")
        print(f"\n  {'N':>6} {'top1%':>6} {'p99 med':>9} {'95% interval':>22} {'width':>8} "
              f"{'rel':>6} {'flip':>7} {'straddles':>9}")
        print("  " + "-" * 82)
        for n in CANDIDATE_N:
            r = st["per_candidate_N"][str(n)]
            lo, hi = r["p99_ci95_ms"]
            print(f"  {n:>6} {r['top_1pct_support']:>6.0f} {r['p99_median_ms']:>9.1f} "
                  f"[{lo:>9.1f},{hi:>9.1f}] {r['p99_ci95_width_ms']:>8.1f} "
                  f"{r['p99_ci95_relative_width']:>6.2f} {r['flip_rate'] * 100:>6.1f}% "
                  f"{'YES' if r['ci_straddles_slo'] else 'no':>9}")
        c = st["candidate_criteria"]
        print(f"\n  smallest grid N by candidate criterion:")
        print(f"    flip rate <=  10% / 5% / 1% : {c['flip_rate_at_most']['0.10']} / "
              f"{c['flip_rate_at_most']['0.05']} / {c['flip_rate_at_most']['0.01']}")
        print(f"    CI width <= 200/150/100/50ms: {c['ci95_width_ms_at_most']['200']} / "
              f"{c['ci95_width_ms_at_most']['150']} / {c['ci95_width_ms_at_most']['100']} / "
              f"{c['ci95_width_ms_at_most']['50']}")
        print(f"    CI rel width <= .5/.3/.2/.1 : {c['ci95_relative_width_at_most']['0.50']} / "
              f"{c['ci95_relative_width_at_most']['0.30']} / {c['ci95_relative_width_at_most']['0.20']} / "
              f"{c['ci95_relative_width_at_most']['0.10']}")
        print(f"    CI entirely clear of 500ms  : {c['ci95_clears_slo_entirely']}")

    print("\n=== conservative combination: max(1.5 RPS, 2 RPS) per criterion ===")
    for family, vals in analysis["combination_rule"]["per_criterion"].items():
        if isinstance(vals, dict):
            print(f"  {family}: " + "  ".join(f"{k}->{v}" for k, v in vals.items()))
        else:
            print(f"  {family}: {vals}")

    print(f"\nwritten: {args.out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

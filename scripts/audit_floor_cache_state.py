#!/usr/bin/env python
"""Was the historical unloaded floor measured on a cold cache? (R4 README P1.)

The 402.3ms floor is load-bearing: it is the evidence that 500ms is
achievable for this corpus/model without contention, and therefore that the
project thesis survives. But prefix caching was enabled for the whole first
session, and the floor's 248 prompts had already been served roughly seven
times by the Stage A sweep before the floor ran. So "no contention" was
established; "no cache" was not.

This audit does not rewrite the floor artifact. It classifies how far the
number can be trusted, using three independent lines of evidence:

  1. PROVENANCE  -- run order and prefix-cache configuration from vllm.log.
  2. INTERNAL CONTROL -- 12 prompts were served TWICE inside the floor run
     itself. The second serving is a guaranteed-warm replay under otherwise
     identical conditions, so the pair measures what a cache hit costs here,
     without needing any model of the server.
  3. TAIL COMPOSITION -- whether the samples that actually set the floor's
     p99 are first servings (cold) or second servings (warm).

Line 2 also answers the question line 1 cannot: if a prompt's FIRST serving
inside the floor still costs full cold prefill, then the sweep's exposure to
that prompt had already been evicted, and the floor's first servings are
cold measurements despite the prior exposure.

Usage:
    .venv/Scripts/python.exe scripts/audit_floor_cache_state.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

EVIDENCE = REPO_ROOT / "benchmarks" / "evidence" / "week2" / "first_session"
FLOOR_SAMPLES = EVIDENCE / "unloaded_floor" / "unloaded_floor.samples.jsonl"
FLOOR_METRICS = EVIDENCE / "unloaded_floor" / "unloaded_floor.metrics.json"
VLLM_LOG = EVIDENCE / "session_logs" / "vllm.log"
OUT_PATH = REPO_ROOT / "benchmarks" / "calibration" / "week2_redesign" / "unloaded_floor_cache_audit.json"

# The three verdicts the README defines.
CLEAN = "CLEAN_UNLOADED_FLOOR"
AMBIGUOUS = "CACHE_STATE_AMBIGUOUS_DIAGNOSTIC"
INFLUENCED = "CACHE_INFLUENCED_DIAGNOSTIC"

# A second serving whose TTFT collapses to below this fraction of its first
# serving is behaving like a cache hit rather than a re-prefill.
HIT_RATIO = 0.6

# Long enough that cold prefill is clearly separable from the ~82ms floor:
# below this the two are within noise of each other and the pair says nothing.
DISCRIMINATING_CHARS = 2358.0  # corpus q90

LOG_RE = re.compile(
    r"INFO 08-\d+ (\d\d:\d\d:\d\d).*Running: (\d+) reqs, Waiting: (\d+) reqs.*"
    r"Prefix cache hit rate: ([\d.]+)%"
)


def load_floor() -> list[dict]:
    rows = [json.loads(line) for line in FLOOR_SAMPLES.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    return [r for r in rows if r.get("error") is None and r.get("ttft_ms") is not None]


def within_floor_repeats(rows: list[dict]) -> dict:
    """The internal control: prompts served more than once inside the floor."""
    by_id: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_id[r["prompt_id"]].append(r)

    pairs = []
    for pid, occurrences in by_id.items():
        occurrences = sorted(occurrences, key=lambda r: r["seq"])
        first = occurrences[0]
        for later in occurrences[1:]:
            pairs.append({
                "prompt_id": pid,
                "char_len": first["char_len"],
                "first_seq": first["seq"],
                "first_ttft_ms": first["ttft_ms"],
                "repeat_seq": later["seq"],
                "repeat_ttft_ms": later["ttft_ms"],
                "ratio": later["ttft_ms"] / first["ttft_ms"],
            })

    discriminating = [p for p in pairs if p["char_len"] >= DISCRIMINATING_CHARS]
    return {
        "n_requests": len(rows),
        "n_distinct_prompts": len(by_id),
        "n_repeat_servings": len(pairs),
        "pairs": sorted(pairs, key=lambda p: -p["char_len"]),
        "discriminating_pairs": discriminating,
        "note": (
            "Only pairs above "
            f"{DISCRIMINATING_CHARS:.0f} chars discriminate: below that, cold prefill and a "
            "cache hit both land near the ~82ms short-prompt floor and the pair is uninformative."
        ),
    }


def cold_first_serving_evidence(repeats: dict, fit_intercept: float, fit_slope: float) -> dict:
    """Does a first serving inside the floor still cost cold prefill?

    If yes, the Stage A sweep's exposure to that prompt had been evicted
    before the floor ran -- which is the only way to distinguish 'previously
    served' from 'still cached'."""
    out = []
    for p in repeats["discriminating_pairs"]:
        predicted_cold = fit_intercept + fit_slope * p["char_len"]
        out.append({
            **p,
            "predicted_cold_prefill_ms": predicted_cold,
            "first_serving_vs_predicted_cold": p["first_ttft_ms"] / predicted_cold,
            "repeat_behaves_like_hit": p["ratio"] < HIT_RATIO,
        })
    return {
        "pairs": out,
        "interpretation": (
            "first_serving_vs_predicted_cold near 1.0 means the first serving paid full "
            "prefill despite the sweep having served that prompt earlier, i.e. the earlier "
            "exposure had been evicted. repeat_behaves_like_hit true means the immediate "
            "replay was served from cache."
        ),
    }


def tail_composition(rows: list[dict], repeats: dict, top_k: int = 10) -> dict:
    """Are the samples that set the floor's p99 cold or warm?"""
    repeat_seqs = {p["repeat_seq"] for p in repeats["pairs"]}
    ranked = sorted(rows, key=lambda r: -r["ttft_ms"])[:top_k]
    return {
        "top_k": top_k,
        "samples": [
            {
                "seq": r["seq"],
                "prompt_id": r["prompt_id"],
                "char_len": r["char_len"],
                "ttft_ms": r["ttft_ms"],
                "is_repeat_serving": r["seq"] in repeat_seqs,
            }
            for r in ranked
        ],
        "n_repeat_servings_in_top_k": sum(1 for r in ranked if r["seq"] in repeat_seqs),
    }


def percentiles_excluding_repeats(rows: list[dict], repeats: dict) -> dict:
    repeat_seqs = {p["repeat_seq"] for p in repeats["pairs"]}
    all_ttft = np.array([r["ttft_ms"] for r in rows], dtype=float)
    cold = np.array([r["ttft_ms"] for r in rows if r["seq"] not in repeat_seqs], dtype=float)

    def block(a: np.ndarray) -> dict:
        return {
            "n": int(a.size),
            "p50_ms": float(np.percentile(a, 50, method="linear")),
            "p99_linear_ms": float(np.percentile(a, 99, method="linear")),
            "p99_nearest_rank_ms": float(np.sort(a)[int(np.ceil(0.99 * a.size)) - 1]),
            "max_ms": float(a.max()),
        }

    return {
        "as_recorded": block(all_ttft),
        "first_servings_only": block(cold),
        "note": "The redesigned convention is nearest-rank (L5). Both are shown because the "
                "committed floor record happens to be a nearest-rank value while every Stage A "
                "record is linear.",
    }


def run_order(rows_log: list[dict]) -> dict:
    """Blocks of activity in the vLLM log, so 'the floor ran after the sweep'
    is read off the record rather than assumed."""
    blocks = []
    current: list[dict] = []
    for e in rows_log:
        if e["running"] > 0 or e["waiting"] > 0:
            current.append(e)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)

    return {
        "n_blocks": len(blocks),
        "blocks": [
            {
                "from_time": b[0]["time"],
                "to_time": b[-1]["time"],
                "duration_samples": len(b),
                "peak_running": max(e["running"] for e in b),
                "peak_waiting": max(e["waiting"] for e in b),
                "hit_rate_from_pct": b[0]["prefix_cache_hit_rate_pct"],
                "hit_rate_to_pct": b[-1]["prefix_cache_hit_rate_pct"],
            }
            for b in blocks
        ],
    }


def classify(cold_ev: dict, tail: dict) -> tuple[str, list[str]]:
    reasons = []
    discriminating = cold_ev["pairs"]

    hits = [p for p in discriminating if p["repeat_behaves_like_hit"]]
    cold_firsts = [p for p in discriminating if 0.8 <= p["first_serving_vs_predicted_cold"] <= 1.3]

    if hits:
        reasons.append(
            f"prefix cache was demonstrably live during the floor: {len(hits)} of "
            f"{len(discriminating)} discriminating within-run replays collapsed to cache-hit "
            "speed")
    if cold_firsts:
        reasons.append(
            f"{len(cold_firsts)} of {len(discriminating)} first servings still paid full cold "
            "prefill despite the Stage A sweep having served the same prompt earlier, so that "
            "earlier exposure had been evicted before the floor ran")
    if tail["n_repeat_servings_in_top_k"] == 0:
        reasons.append(
            f"none of the top {tail['top_k']} TTFT samples -- the ones that set the floor's p99 "
            "-- is a within-run repeat serving")

    # The floor ran AFTER prior exposure. That is a documented fact, not an
    # inference, and it is exactly the README's CACHE_INFLUENCED condition.
    # The behavioural evidence above says the exposure had decayed, which is
    # why the verdict carries qualifiers rather than being upgraded: "behaves
    # cold" is not "provably cold", and the README's instruction keys on
    # provability.
    reasons.append(
        "but the floor was measured AFTER the same prompts had been served by the Stage A "
        "sweep, with prefix caching enabled, so a cold cache cannot be PROVEN -- only argued "
        "from behaviour")
    return INFLUENCED, reasons


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    rows = load_floor()
    char_len = np.array([r["char_len"] for r in rows], dtype=float)
    ttft = np.array([r["ttft_ms"] for r in rows], dtype=float)
    slope, intercept = np.polyfit(char_len, ttft, 1)

    log_rows = []
    if VLLM_LOG.exists():
        for m in LOG_RE.finditer(VLLM_LOG.read_text(encoding="utf-8", errors="replace")):
            log_rows.append({
                "time": m.group(1), "running": int(m.group(2)),
                "waiting": int(m.group(3)),
                "prefix_cache_hit_rate_pct": float(m.group(4)),
            })

    repeats = within_floor_repeats(rows)
    cold_ev = cold_first_serving_evidence(repeats, float(intercept), float(slope))
    tail = tail_composition(rows, repeats)
    verdict, reasons = classify(cold_ev, tail)

    committed = json.loads(FLOOR_METRICS.read_text(encoding="utf-8"))

    audit = {
        "what": "Cache-state audit of the first session's unloaded TTFT floor (R4 README P1).",
        "verdict": verdict,
        "verdict_reasons": reasons,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "artifact_not_modified": True,
        "source": {
            "samples": str(FLOOR_SAMPLES.relative_to(REPO_ROOT)).replace("\\", "/"),
            "metrics": str(FLOOR_METRICS.relative_to(REPO_ROOT)).replace("\\", "/"),
            "committed_p99_ms": committed["ttft_p99_ms"],
            "committed_n_requests": committed["n_requests"],
            "committed_n_errors": committed["n_errors"],
            "mode": committed["mode"],
        },
        "server_config": {
            "enable_prefix_caching": True,
            "source": "session_logs/vllm.log EngineCore config line (vLLM v0.27.1)",
        },
        "run_order": run_order(log_rows),
        "cold_prefill_fit": {
            "intercept_ms": float(intercept),
            "slope_ms_per_char": float(slope),
            "note": "fitted on the floor itself, so it is a description of these samples, not "
                    "an independent predictor. Used only to ask whether a given first serving "
                    "looks like full prefill for its length.",
        },
        "internal_control_within_run_repeats": repeats,
        "cold_first_serving_evidence": cold_ev,
        "evidence_strength": {
            "discriminating_pairs": len(cold_ev["pairs"]),
            "caveat": (
                "The internal control rests on a small number of within-run repeats -- the "
                "floor drew 248 requests with replacement from 236 distinct prompts, and only "
                f"those above {DISCRIMINATING_CHARS:.0f} chars discriminate at all. It is "
                "enough to show the cache was live and that at least one prior exposure had "
                "been evicted; it is not enough to characterise eviction across the whole "
                "sample. The verdict does not depend on it: prior exposure is documented, so "
                "the conservative classification holds regardless, and this control only "
                "prevents the floor from being written off entirely."
            ),
        },
        "tail_composition": tail,
        "percentiles": percentiles_excluding_repeats(rows, repeats),
        "how_this_number_may_now_be_described": [
            "ALLOWED: 'the first session's unloaded diagnostic floor, measured with prefix "
            "caching enabled, whose p99 region is composed entirely of first servings'.",
            "NOT ALLOWED: 'the unloaded TTFT floor is 402.3ms' as a definitive, cache-free "
            "measurement. Cache state cannot be proven clean, so the figure stops being "
            "citable as definitive (R4 README P1).",
            "The next GPU session collects a new clean floor with prefix caching disabled "
            "(L6); that measurement supersedes this one for any published claim.",
            "The thesis-level conclusion it supported -- that 500ms is achievable for this "
            "corpus/model without contention -- is WEAKENED, not overturned: a cache-influenced "
            "floor would be biased LOW, so the true cold floor is at or above 402.3ms and could "
            "sit closer to the SLO.",
        ],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")

    print(f"\nverdict: {verdict}\n")
    for r in reasons:
        print(f"  - {r}")

    print(f"\nrun-order blocks in vllm.log ({audit['run_order']['n_blocks']}):")
    for b in audit["run_order"]["blocks"]:
        print(f"  {b['from_time']}-{b['to_time']}  peak_running={b['peak_running']:>4} "
              f"peak_waiting={b['peak_waiting']:>5}  hit {b['hit_rate_from_pct']:>5.1f}% -> "
              f"{b['hit_rate_to_pct']:>5.1f}%")

    print(f"\ninternal control -- {repeats['n_requests']} requests over "
          f"{repeats['n_distinct_prompts']} distinct prompts, "
          f"{repeats['n_repeat_servings']} repeat servings:")
    print(f"  {'pid':>6} {'chars':>7} {'1st ttft':>9} {'repeat':>9} {'ratio':>6} "
          f"{'1st/cold-pred':>14}")
    for p in cold_ev["pairs"]:
        print(f"  {p['prompt_id']:>6} {p['char_len']:>7.0f} {p['first_ttft_ms']:>9.1f} "
              f"{p['repeat_ttft_ms']:>9.1f} {p['ratio']:>6.2f} "
              f"{p['first_serving_vs_predicted_cold']:>14.2f}")

    print(f"\ntop-{tail['top_k']} TTFT samples: "
          f"{tail['n_repeat_servings_in_top_k']} are repeat servings")
    pc = audit["percentiles"]
    print(f"\n  as recorded          n={pc['as_recorded']['n']:>3}  "
          f"p50={pc['as_recorded']['p50_ms']:.1f}ms  "
          f"p99(nearest)={pc['as_recorded']['p99_nearest_rank_ms']:.1f}ms")
    print(f"  first servings only  n={pc['first_servings_only']['n']:>3}  "
          f"p50={pc['first_servings_only']['p50_ms']:.1f}ms  "
          f"p99(nearest)={pc['first_servings_only']['p99_nearest_rank_ms']:.1f}ms")

    print(f"\nwritten: {args.out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

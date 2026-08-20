#!/usr/bin/env python
"""Prefix-cache contamination across first-session points (Redesign README
R2 source validation; unplanned finding).

Why this script exists. R2 is told to use the 1.5-RPS array as "the sparser
clean low-load diagnostic". Reading it against the unloaded floor says it is
not clean, and the reason matters more than the array does:

    prompt 458 (14960 chars)   concurrency 1, no load  ->  523.3ms TTFT
    prompt 458 (14960 chars)   under 1.5 RPS of load   ->  103.9ms TTFT

Adding load cannot make prefill five times faster. Cache reuse can, and the
server ran with `enable_prefix_caching=True` (session_logs/vllm.log). Every
Stage A schedule was built from the same master seed, so the shorter
schedules are strict PREFIXES of the longer ones -- the 1.5-RPS point
replayed prompts that two earlier runs had already loaded into the prefix
cache, and vLLM's reported hit rate climbs from 17.4% to 27.4% across
exactly that run.

So run order silently became an experimental variable. This script measures
how much, by joining each loaded point against the unloaded floor on
prompt_id and reporting the loaded/unloaded TTFT ratio: above 1.0 means load
cost something (physics), below 1.0 means the second run was reading a warm
cache (contamination).

The result bears on the redesign directly, not just on the old data: D2
fixes ONE canonical prompt multiset across every RPS point and repeat, and
D4 forbids restarting vLLM between repeats. Together those guarantee that
every point after the first replays prompts the server has already seen.

Usage:
    .venv/Scripts/python.exe scripts/analyze_run_order_effects.py
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
SCHEDULES = REPO_ROOT / "benchmarks" / "schedules" / "stage_a"
OUT_PATH = REPO_ROOT / "benchmarks" / "calibration" / "week2_redesign" / "run_order_effects.json"

HISTORICAL_WARMUP_S = 10.0
LONG_PROMPT_CHARS = 4566.0  # corpus q95: where intrinsic prefill cost becomes visible

HIT_RATE_RE = re.compile(
    r"INFO 08-\d+ (\d\d:\d\d:\d\d).*Running: (\d+) reqs, Waiting: (\d+) reqs.*"
    r"Prefix cache hit rate: ([\d.]+)%"
)


def floor_by_prompt() -> dict[int, list[float]]:
    path = EVIDENCE / "unloaded_floor" / "unloaded_floor.samples.jsonl"
    out: dict[int, list[float]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("error") is None and r.get("ttft_ms") is not None:
            out[r["prompt_id"]].append(r["ttft_ms"])
    return out


def loaded_rows(tag: str) -> list[tuple[int, float, float]]:
    raw_path = EVIDENCE / "stage_a" / f"{tag}.raw_log.jsonl"
    sam_path = EVIDENCE / "stage_a" / f"{tag}.samples.jsonl"
    raw = {
        r["request_id"]: r
        for r in (json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip())
    }
    rows = []
    for line in sam_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        s = json.loads(line)
        if s["send_time"] < HISTORICAL_WARMUP_S or s.get("ttft_ms") is None or s.get("error"):
            continue
        r = raw[s["request_id"]]
        rows.append((r["prompt_id"], float(r["prompt_len"]), float(s["ttft_ms"])))
    return rows


def schedule_nesting() -> dict:
    """Are the Stage A prompt streams nested? If they are, every point after
    the first is replaying an earlier point's prompts."""
    streams = {}
    for p in sorted(SCHEDULES.glob("*.schedule.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        streams[p.stem.replace(".schedule", "")] = (
            [e["prompt_id"] for e in d["entries"]],
            d["provenance"]["master_seed"],
        )
    longest = max(streams.values(), key=lambda v: len(v[0]))[0]
    return {
        "master_seeds": sorted({seed for _ids, seed in streams.values()}),
        "all_streams_nested": all(
            ids == longest[: len(ids)] for ids, _s in streams.values() if len(ids) <= len(longest)
        ),
        "stream_lengths": {name: len(ids) for name, (ids, _s) in streams.items()},
        "note": "One master seed for every point means one corpus_rng draw sequence, so a "
                "shorter schedule is a strict prefix of a longer one. That was intended as "
                "matching (WEEK2_PLAN.md 2.2) and is also what makes prefix-cache reuse "
                "track run order.",
    }


def hit_rate_timeline() -> list[dict]:
    log = EVIDENCE / "session_logs" / "vllm.log"
    if not log.exists():
        return []
    out = []
    for m in HIT_RATE_RE.finditer(log.read_text(encoding="utf-8", errors="replace")):
        out.append({
            "time": m.group(1),
            "running": int(m.group(2)),
            "waiting": int(m.group(3)),
            "prefix_cache_hit_rate_pct": float(m.group(4)),
        })
    return out


def compare(tag: str, floor: dict[int, list[float]]) -> dict:
    rows = [r for r in loaded_rows(tag) if r[0] in floor]
    ratios = [(pid, cl, tt, tt / float(np.median(floor[pid]))) for pid, cl, tt in rows]
    long_ratios = [r for r in ratios if r[1] >= LONG_PROMPT_CHARS]

    def summarize(rs):
        if not rs:
            return None
        vals = np.array([r[3] for r in rs], dtype=float)
        return {
            "n": len(rs),
            "median_ratio": float(np.median(vals)),
            "min_ratio": float(vals.min()),
            "max_ratio": float(vals.max()),
            "fraction_faster_than_unloaded": float((vals < 1.0).mean()),
        }

    return {
        "tag": tag,
        "n_joined": len(rows),
        "all_prompts": summarize(ratios),
        "long_prompts_only": summarize(long_ratios),
        "long_prompt_detail": [
            {
                "prompt_id": pid,
                "char_len": cl,
                "unloaded_ttft_ms": float(np.median(floor[pid])),
                "loaded_ttft_ms": tt,
                "ratio": ratio,
            }
            for pid, cl, tt, ratio in sorted(long_ratios, key=lambda r: -r[1])
        ],
        "verdict": _verdict(summarize(long_ratios)),
    }


def _verdict(summary: dict | None) -> str:
    if not summary:
        return "no long prompts in common with the unloaded floor -- inconclusive"
    if summary["median_ratio"] < 0.9:
        return (
            "CONTAMINATED: long prompts served FASTER under load than at concurrency 1. "
            "Load cannot reduce prefill cost, so this point read a warm prefix cache left "
            "by an earlier run. Its p99 is not a clean low-load measurement."
        )
    if summary["median_ratio"] > 1.05:
        return (
            "CONSISTENT: long prompts cost more under load than at concurrency 1, which is "
            "the direction load can move them."
        )
    return "AMBIGUOUS: loaded and unloaded costs are within noise of each other"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    floor = floor_by_prompt()
    timeline = hit_rate_timeline()
    comparisons = [compare(tag, floor) for tag in ("poisson_rps1.5", "poisson_rps2")]

    analysis = {
        "what": "Run-order / prefix-cache contamination in the first GPU session.",
        "status": "FINDING -- affects the validity of the 1.5-RPS R2 source array and the "
                  "feasibility of README D2+D4 as written",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "server_config": {
            "enable_prefix_caching": True,
            "enable_chunked_prefill": True,
            "source": "session_logs/vllm.log, EngineCore config line (vLLM v0.27.1)",
            "note": "Both are vLLM defaults and neither was set by the runbook. Prefix caching "
                    "was therefore never a decision -- it was inherited.",
        },
        "schedule_nesting": schedule_nesting(),
        "method": (
            "Join each loaded point's post-warmup requests against the unloaded floor "
            "(concurrency 1, same prompts) on prompt_id, and take loaded/unloaded TTFT per "
            "prompt. Restricted to prompts >= "
            f"{LONG_PROMPT_CHARS:.0f} chars (corpus q95), where prefill cost is large enough "
            "to see."
        ),
        "comparisons": comparisons,
        "prefix_cache_hit_rate_summary": _timeline_summary(timeline),
        "prefix_cache_hit_rate_timeline": timeline,
        "implications": [
            "The 1.5-RPS point's p99 of 113.6ms is a warm-cache artifact of being driven last, "
            "not evidence that 1.5 RPS is comfortably under the SLO. The handoff's 'clearly "
            "under' read for that point does not survive this join.",
            "README D2 fixes one canonical prompt multiset across every RPS point and every "
            "repeat; D4 forbids restarting vLLM between repeats. Together they guarantee that "
            "every point and repeat after the first replays prompts the server has already "
            "cached -- a drift aligned with run order, which is exactly the class of confound "
            "the redesign exists to remove.",
            "Prefix cache hit rate is currently not recorded per point. Whatever policy is "
            "chosen, it should become a recorded per-point covariate so a contaminated point "
            "is visible in its own artifact rather than reconstructed from a server log.",
        ],
        "options_for_the_human": [
            {
                "option": "A -- disable prefix caching for headline runs",
                "effect": "Removes the confound at the source; every request pays full prefill.",
                "cost": "Changes the served configuration from the first session's, and moves "
                        "the measured baseline away from how vLLM is normally deployed. The "
                        "500ms SLO and the breach location would both shift.",
            },
            {
                "option": "B -- keep prefix caching, randomize point order across repeats",
                "effect": "Cache advantage no longer aligns with lambda, so it becomes noise "
                          "across repeats instead of a monotone trend along the x-axis.",
                "cost": "Needs more repeats to average out, and does not remove the advantage "
                        "within a repeat.",
            },
            {
                "option": "C -- keep prefix caching, record hit rate per point and gate on it",
                "effect": "Contamination becomes measurable and a point whose hit rate differs "
                          "materially from its neighbours can be flagged or re-driven.",
                "cost": "Needs a hit-rate scrape from /metrics per point, and a threshold that "
                        "is itself a calibration.",
            },
            {
                "option": "D -- drain-and-flush between points/repeats",
                "effect": "Restores a comparable cache state per point without restarting vLLM.",
                "cost": "Requires a supported cache-reset path; D4's 'no restart' rule exists to "
                        "avoid re-paying CUDA-graph/init variance, and a flush must not "
                        "reintroduce it.",
            },
        ],
        "caveats": [
            "The ratio uses the unloaded floor as the reference, and the floor itself ran after "
            "the main sweep with a ~16% hit rate. It is therefore not a fully cold reference; "
            "if anything that makes the 1.5-RPS contamination an UNDERSTATEMENT.",
            "Hit rate is reported engine-wide, not per request, so a point's rate mixes its own "
            "requests with whatever preceded them.",
            "No absolute timestamps exist in the raw logs; run ordering is inferred from the "
            "vLLM log timeline plus each point's schedule duration.",
        ],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")

    nest = analysis["schedule_nesting"]
    print(f"\nStage A schedules: master seed(s) {nest['master_seeds']}, "
          f"all prompt streams nested = {nest['all_streams_nested']}")
    print("  -> every point replays the prompts of every shorter point")

    for c in comparisons:
        lp = c["long_prompts_only"]
        print(f"\n{c['tag']}: {c['n_joined']} requests joinable to the unloaded floor")
        if lp:
            print(f"  prompts >= {LONG_PROMPT_CHARS:.0f} chars: n={lp['n']}  "
                  f"median loaded/unloaded ratio = {lp['median_ratio']:.2f}  "
                  f"(range {lp['min_ratio']:.2f}-{lp['max_ratio']:.2f})")
            print(f"  {lp['fraction_faster_than_unloaded'] * 100:.0f}% of them were FASTER than "
                  "the same prompt at concurrency 1")
        print(f"  verdict: {c['verdict']}")
        for d in c["long_prompt_detail"][:5]:
            print(f"    prompt {d['prompt_id']:>5} ({d['char_len']:>6.0f} chars): "
                  f"unloaded {d['unloaded_ttft_ms']:>7.1f}ms -> loaded {d['loaded_ttft_ms']:>7.1f}ms "
                  f"({d['ratio']:.2f}x)")

    s = analysis["prefix_cache_hit_rate_summary"]
    if s:
        print(f"\nprefix cache hit rate over the session: {s['first_pct']:.1f}% -> {s['last_pct']:.1f}% "
              f"({s['n_samples']} log lines)")

    print(f"\nwritten: {args.out.relative_to(REPO_ROOT)}")


def _timeline_summary(timeline: list[dict]) -> dict | None:
    """Session-wide hit rate, plus the LAST contiguous block of active traffic.

    The last block is the interesting one: it is the 1.5-RPS point, driven
    after everything else, and its own climb is the contamination happening in
    real time rather than a session-wide average that mixes six other points
    into it."""
    if not timeline:
        return None

    last_block: list[dict] = []
    for entry in reversed(timeline):
        if entry["running"] > 0 or entry["waiting"] > 0:
            last_block.insert(0, entry)
        elif last_block:
            break

    return {
        "n_samples": len(timeline),
        "first_time": timeline[0]["time"],
        "last_time": timeline[-1]["time"],
        "first_pct": timeline[0]["prefix_cache_hit_rate_pct"],
        "last_pct": timeline[-1]["prefix_cache_hit_rate_pct"],
        "max_pct": max(t["prefix_cache_hit_rate_pct"] for t in timeline),
        "final_active_block": {
            "from_time": last_block[0]["time"],
            "to_time": last_block[-1]["time"],
            "from_pct": last_block[0]["prefix_cache_hit_rate_pct"],
            "to_pct": last_block[-1]["prefix_cache_hit_rate_pct"],
            "peak_running": max(t["running"] for t in last_block),
            "note": "low peak concurrency identifies this as the last low-RPS point, "
                    "driven after the sweep and after the unloaded floor",
        } if last_block else None,
    }


if __name__ == "__main__":
    main()

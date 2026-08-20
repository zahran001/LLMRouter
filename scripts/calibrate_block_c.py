#!/usr/bin/env python
"""Block C calibration reads (WEEK2_EXECUTION.md Block C; WEEK2_PLAN.md §2.4,
§3.3, §8). Generates the DATA for the human to read three [CALIBRATE] values
off of -- this script does not choose the values itself (that's Hard Stop 3).

Three sweeps, all against the mock's slow config (500ms TTFT/100ms TPOT --
the config the concurrency cap must be calibrated against per §3.3):

1. shed_onset: for a few candidate concurrency caps, offered RPS vs shed
   count -- read the client's healthy ceiling off the RPS where shedding
   onsets for a given cap (§4 V3's calibration output).
2. natural_concurrency: same RPS sweep, cap effectively uncapped -- the raw
   peak_concurrency() needed to sustain each offered RPS against slow
   responses, independent of any candidate cap. Lets the human sanity-check
   any candidate cap algebraically (shed onset for cap=C is where this curve
   crosses C) without re-running per candidate.
3. low_load_tracking: offered-vs-achieved RPS divergence at low RPS
   (uncapped), to inform the ±5% [CALIBRATE] band (§2.5) -- divergence here
   would indicate a loadgen bug, not saturation, since load is far below
   anything that could saturate a single client.

Usage:
    .venv/Scripts/python.exe scripts/calibrate_block_c.py
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from pathlib import Path

import uvicorn

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loadgen.corpus import load_corpus
from loadgen.log import RunLogger, read_log
from loadgen.schedule import build_steady_schedule
from loadgen.scheduler import OpenLoopScheduler
from mock.app import app as mock_app
from tests.loadgen._assertions import peak_concurrency

SEED = 20260817
DURATION_S = 8.0
UNCAPPED = 100_000


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_mock() -> tuple[str, uvicorn.Server, threading.Thread]:
    port = _free_port()
    config = uvicorn.Config(mock_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    return f"http://127.0.0.1:{port}", server, thread


async def _run_point(base_url, corpus, rps, duration_s, cap, config, log_path):
    schedule = build_steady_schedule(rps, duration_s, SEED, corpus)
    scheduler = OpenLoopScheduler(
        schedule=schedule, corpus=corpus, base_url=base_url,
        logger=RunLogger(log_path), concurrency_cap=cap,
        query_params={"config": config, "num_tokens": 5}, capture_samples=False,
    )
    result = await scheduler.run()
    scheduler.logger.close()
    rows = read_log(log_path)
    return {
        "offered_rps": rps,
        "cap": cap,
        "n_scheduled": result.n_scheduled,
        "n_sent": result.n_sent,
        "n_shed": result.n_shed,
        "n_errored": result.n_errored,
        "achieved_rps": result.achieved_rps,
        "peak_concurrency": peak_concurrency(rows),
    }


async def main_async() -> dict:
    base_url, server, thread = _start_mock()
    corpus = load_corpus()
    # Raw per-sweep logs are working output, not evidence -- they go to the
    # ignored scratch subtree (benchmarks/README.md). Only the distilled
    # calibration_reads.json below is committed.
    out_dir = Path(__file__).resolve().parent.parent / "benchmarks" / "scratch" / "block_c"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        rps_sweep = [5, 10, 20, 30, 50, 75, 100, 150, 200, 300]
        candidate_caps = [50, 100, 200]

        print("=== 1/3: shed_onset (candidate caps x RPS sweep, slow config) ===", file=sys.stderr)
        shed_onset = []
        for cap in candidate_caps:
            for rps in rps_sweep:
                point = await _run_point(
                    base_url, corpus, rps, DURATION_S, cap, "slow",
                    out_dir / f"shed_onset_cap{cap}_rps{rps}.raw_log.jsonl",
                )
                shed_onset.append(point)
                print(f"  cap={cap:4d} rps={rps:4d} -> shed={point['n_shed']:3d} "
                      f"peak_conc={point['peak_concurrency']:3d} achieved_rps={point['achieved_rps']:.2f}",
                      file=sys.stderr)

        print("=== 2/3: natural_concurrency (uncapped, same RPS sweep, slow config) ===", file=sys.stderr)
        natural_concurrency = []
        for rps in rps_sweep:
            point = await _run_point(
                base_url, corpus, rps, DURATION_S, UNCAPPED, "slow",
                out_dir / f"natural_rps{rps}.raw_log.jsonl",
            )
            natural_concurrency.append(point)
            print(f"  rps={rps:4d} -> peak_conc={point['peak_concurrency']:4d} "
                  f"achieved_rps={point['achieved_rps']:.2f}", file=sys.stderr)

        print("=== 3/3: low_load_tracking (uncapped, low RPS, slow config) ===", file=sys.stderr)
        low_load_tracking = []
        for rps in [0.5, 1, 2, 5]:
            point = await _run_point(
                base_url, corpus, rps, 30.0, UNCAPPED, "slow",
                out_dir / f"lowload_rps{rps}.raw_log.jsonl",
            )
            divergence_pct = 100.0 * (point["achieved_rps"] - rps) / rps
            point["divergence_pct"] = divergence_pct
            low_load_tracking.append(point)
            print(f"  rps={rps} -> achieved_rps={point['achieved_rps']:.3f} "
                  f"divergence={divergence_pct:+.2f}%", file=sys.stderr)

    finally:
        server.should_exit = True
        thread.join(timeout=5.0)

    return {
        "seed": SEED,
        "duration_s_main_sweeps": DURATION_S,
        "candidate_caps": candidate_caps,
        "rps_sweep": rps_sweep,
        "shed_onset": shed_onset,
        "natural_concurrency": natural_concurrency,
        "low_load_tracking": low_load_tracking,
    }


def main() -> None:
    result = asyncio.run(main_async())

    out_path = (
        Path(__file__).resolve().parent.parent
        / "benchmarks" / "calibration" / "block_c" / "calibration_reads.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(f"\nWrote {out_path}", file=sys.stderr)

    print("\n=== Shed onset per candidate cap (first RPS with n_shed > 0) ===")
    for cap in result["candidate_caps"]:
        points = [p for p in result["shed_onset"] if p["cap"] == cap]
        onset = next((p["offered_rps"] for p in points if p["n_shed"] > 0), None)
        print(f"cap={cap:4d}: onset={'none in sweep range' if onset is None else onset}")

    print("\n=== Natural concurrency vs offered RPS (uncapped) ===")
    for p in result["natural_concurrency"]:
        print(f"rps={p['offered_rps']:4d}  peak_concurrency={p['peak_concurrency']:4d}")

    print("\n=== Low-load offered-vs-achieved tracking (uncapped) ===")
    for p in result["low_load_tracking"]:
        print(f"rps={p['offered_rps']:>4}  achieved={p['achieved_rps']:.3f}  divergence={p['divergence_pct']:+.2f}%")


if __name__ == "__main__":
    main()

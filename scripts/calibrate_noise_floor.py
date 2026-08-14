#!/usr/bin/env python
"""Calibration task (METRICS_TEST_SUITE.md, "Calibration task" section).

Run ONE stable mock config N times (each a full, independent run: warmup +
>= min_samples measured requests), record p50 TTFT per run, and report the
run-to-run spread. This spread is the measurement noise floor: the 15ms
constant in tests/tolerances.py (TOLERANCE_FLOOR_MS, marked [CALIBRATE]) is
supposed to sit just above it, not be guessed.

This script does NOT modify tests/tolerances.py for you -- that's a
deliberate choice (see AGENT_METRICS_BRIEF.md task notes): review the
printed spread yourself before changing a correctness-critical constant.

Usage:
    .venv/Scripts/python.exe scripts/calibrate_noise_floor.py
    .venv/Scripts/python.exe scripts/calibrate_noise_floor.py --config fast --runs 200

Starts its own throwaway copy of the mock server (same as tests/conftest.py)
so this is runnable standalone, with no server to start by hand.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import statistics
import sys
import threading
import time
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metrics.compute import aggregate
from mock.app import app as mock_app
from mock.configs import CONFIGS
from tests.helpers import drive_requests


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


async def _run_once(base_url: str, config_name: str, warmup: int, min_samples: int, num_tokens: int) -> float | None:
    cfg = CONFIGS[config_name]
    samples = await drive_requests(base_url, config_name, n=warmup + min_samples, num_tokens=num_tokens, concurrency=20)
    result = aggregate(samples, warmup=warmup, min_samples=min_samples, config={"name": config_name, "ttft_ms": cfg.ttft_ms})
    return result.ttft_p50 if result.valid else None


async def main_async(args: argparse.Namespace) -> dict:
    base_url, server, thread = _start_mock()
    try:
        p50s: list[float] = []
        for i in range(args.runs):
            p50 = await _run_once(base_url, args.config, args.warmup, args.min_samples, args.num_tokens)
            if p50 is None:
                print(f"run {i + 1}/{args.runs}: INVALID (below min_samples) -- skipped", file=sys.stderr)
                continue
            p50s.append(p50)
            if (i + 1) % max(1, args.runs // 20) == 0 or i == 0:
                print(f"run {i + 1}/{args.runs}: p50 TTFT = {p50:.2f}ms", file=sys.stderr)
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)

    cfg = CONFIGS[args.config]
    spread = {
        "config": args.config,
        "configured_ttft_ms": cfg.ttft_ms,
        "runs": len(p50s),
        "requests_per_run": args.warmup + args.min_samples,
        "num_tokens": args.num_tokens,
        "p50_mean": statistics.mean(p50s),
        "p50_stdev": statistics.pstdev(p50s) if len(p50s) > 1 else 0.0,
        "p50_min": min(p50s),
        "p50_max": max(p50s),
        "p50_range": max(p50s) - min(p50s),
        "raw_p50s_ms": p50s,
    }
    return spread


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="fast", choices=sorted(CONFIGS))
    parser.add_argument("--runs", type=int, default=200, help="spec default: 200")
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--min-samples", type=int, default=100, dest="min_samples")
    parser.add_argument("--num-tokens", type=int, default=5, dest="num_tokens")
    parser.add_argument("--out", default=None, help="path to write the JSON result (default: benchmarks/noise_floor_<config>.json)")
    args = parser.parse_args()

    spread = asyncio.run(main_async(args))

    print()
    print(f"config={spread['config']} (configured ttft_ms={spread['configured_ttft_ms']})")
    print(f"valid runs: {spread['runs']}")
    print(f"p50 TTFT across runs: mean={spread['p50_mean']:.2f}ms  stdev={spread['p50_stdev']:.2f}ms  "
          f"min={spread['p50_min']:.2f}ms  max={spread['p50_max']:.2f}ms  range={spread['p50_range']:.2f}ms")
    print()
    print("Set TOLERANCE_FLOOR_MS in tests/tolerances.py just above this observed spread")
    print("(e.g. a few ms above p50_range/2, or above 3x stdev) -- do not copy a number")
    print("blindly, look at the distribution. Then document the measured floor in")
    print("BENCHMARKS.md per WEEK1_MEASUREMENT_SPEC.md #4.")

    out_path = Path(args.out) if args.out else Path(__file__).resolve().parent.parent / "benchmarks" / f"noise_floor_{args.config}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(spread, indent=2))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()

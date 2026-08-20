#!/usr/bin/env python
"""Loadgen scheduler spin-margin A/B (WEEK2_PLAN.md §8; WEEK2_EXECUTION.md
Block C; docs/WEEK2_PRE_GPU_AUDIT.md B2).

The open question this closes: `loadgen/scheduler.py:SPIN_MARGIN_S` was tuned
on the Windows dev box, where bare `asyncio.sleep` can wake a few ms EARLY and
violate V5's "send_time >= scheduled_offset -- late allowed, early impossible"
contract. Whether Linux needs that busy-wait at all was never measured, and
§8 forbids shipping the Windows value onto the Linux vLLM runs unverified.

This is the same CLASS of A/B Block 0 ran for the mock's own spin
(`mock/timing.py`, see MOCK_TRUST_BOUNDARY.md), applied to the scheduler:
same machine, same workload, same schedule construction, same seed, same
client, same repetition count -- ONE variable, the spin margin.

  Arm A: spin margin = 0ms   (bare asyncio.sleep, no busy-wait)
  Arm B: spin margin = 5ms   (the Windows-tuned incumbent)

Measured from the loadgen's OWN scheduling instrument (§3.3's "per-send
scheduling lag is logged... the ground-truth instrument for open-loop
fidelity") -- not from response latency, which is the mock's business and is
outside the mock's trusted role anyway (MOCK_TRUST_BOUNDARY.md).

Run on a dedicated CPU-only Linux e2 VM, NOT CI and NOT the Windows dev box:
a shared runner measures the neighbour's contention, and the whole question is
platform-specific. GPU-free.

Usage:
    python scripts/calibrate_scheduler_spin.py                     # full A/B
    python scripts/calibrate_scheduler_spin.py --smoke             # fast shakeout
    python scripts/calibrate_scheduler_spin.py --out <path.json>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import socket
import statistics
import sys
import threading
import time
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loadgen.corpus import load_corpus
from loadgen.log import RunLogger
from loadgen.schedule import build_poisson_schedule
from loadgen.scheduler import OpenLoopScheduler
from mock import timing as mock_timing
from mock.app import app as mock_app

# Held identical across arms -- the point of the exercise.
SEED = 20260818
# Stage A's ceiling is 80 RPS (scripts/generate_stage_a_schedules.py), and 20
# sits in the middle of the coarse sweep. Both are required by the task; they
# also bracket the range where a scheduler that cannot keep up would first
# show it.
RPS_POINTS = [20.0, 80.0]
# 0ms first so a crash mid-run leaves the *incumbent* unmeasured rather than
# the candidate.
SPIN_ARMS_S = [0.0, 0.005]
DURATION_S = 30.0
REPEATS = 5
# The cap must not bite: a shed request never gets a send_time, so it would
# silently drop out of the lag population being compared. 3000 is the
# baseline value and is far above what 80 RPS against this mock produces.
CONCURRENCY_CAP = 3000
# Slow config (~500ms TTFT / 100ms TPOT) -- the regime where in-flight
# streams actually accumulate, same reasoning as §3.3's cap calibration and
# §4 V2. A fast mock drains immediately and would understate the load the
# scheduler runs under.
MOCK_CONFIG = "slow"
NUM_TOKENS = 5

OUT_DEFAULT = (
    Path(__file__).resolve().parent.parent
    / "benchmarks" / "calibration" / "scheduler_spin" / "scheduler_spin_linux_ab.json"
)


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
    deadline = time.monotonic() + 15.0
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("mock server did not start")
        time.sleep(0.01)
    return f"http://127.0.0.1:{port}", server, thread


def _pct(values: list[float], p: float) -> float:
    """Percentile without importing metrics.compute -- this script measures
    the SCHEDULER, and borrowing the response-latency percentile helper would
    blur which instrument produced which number."""
    if not values:
        return float("nan")
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    r = (p / 100.0) * (len(xs) - 1)
    lo = int(r)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (r - lo) * (xs[hi] - xs[lo])


async def _one_run(base_url: str, corpus, rps: float, spin_margin_s: float,
                   duration_s: float, log_path: Path) -> dict:
    """One (rps, spin) run. Schedule construction is identical across arms --
    same builder, same seed, same corpus -- so the arms drive byte-identical
    workloads and only the sleep behaviour differs."""
    schedule = build_poisson_schedule(rps, duration_s, SEED, corpus)
    logger = RunLogger(log_path)
    scheduler = OpenLoopScheduler(
        schedule=schedule,
        corpus=corpus,
        base_url=base_url,
        logger=logger,
        concurrency_cap=CONCURRENCY_CAP,
        query_params={"config": MOCK_CONFIG, "num_tokens": NUM_TOKENS},
        capture_samples=False,  # scheduling lag only; TTFT is not the question
        spin_margin_s=spin_margin_s,
    )
    result = await scheduler.run()
    logger.close()
    log_path.unlink(missing_ok=True)  # the lag lives in `result`; the log is scratch

    lag_ms = [x * 1000.0 for x in result.per_send_lag_s]
    return {
        "offered_rps": rps,
        "achieved_rps": result.achieved_rps,
        "divergence_pct": 100.0 * (result.achieved_rps - rps) / rps if rps else 0.0,
        "n_scheduled": result.n_scheduled,
        "n_sent": result.n_sent,
        "n_shed": result.n_shed,
        "n_errored": result.n_errored,
        "lag_ms": {
            "p50": _pct(lag_ms, 50),
            "p95": _pct(lag_ms, 95),
            "p99": _pct(lag_ms, 99),
            "max": max(lag_ms) if lag_ms else float("nan"),
            "min": min(lag_ms) if lag_ms else float("nan"),
            "mean": statistics.mean(lag_ms) if lag_ms else float("nan"),
        },
        # V5's contract: early is impossible. A negative lag means a send
        # fired BEFORE its scheduled offset, which is the correctness failure
        # the spin exists to prevent -- so it is counted, not just summarized.
        "n_negative_lag": sum(1 for x in lag_ms if x < 0.0),
        "most_negative_lag_ms": min(lag_ms) if lag_ms else float("nan"),
    }


def _summarize(runs: list[dict]) -> dict:
    """Aggregate REPEATS runs of one (rps, spin) cell. Percentiles are
    averaged across runs and the max is the worst single observation -- a
    per-run p99 hides a single catastrophic run, and the max is exactly the
    thing V5 cares about."""
    def avg(path: str) -> float:
        return statistics.mean(r["lag_ms"][path] for r in runs)

    return {
        "runs": len(runs),
        "lag_ms": {
            "p50": avg("p50"),
            "p95": avg("p95"),
            "p99": avg("p99"),
            "max": max(r["lag_ms"]["max"] for r in runs),
            "mean": avg("mean"),
        },
        "achieved_rps": statistics.mean(r["achieved_rps"] for r in runs),
        "divergence_pct": statistics.mean(r["divergence_pct"] for r in runs),
        "worst_divergence_pct": max((r["divergence_pct"] for r in runs), key=abs),
        "n_shed_total": sum(r["n_shed"] for r in runs),
        "n_errored_total": sum(r["n_errored"] for r in runs),
        "n_negative_lag_total": sum(r["n_negative_lag"] for r in runs),
        "most_negative_lag_ms": min(r["most_negative_lag_ms"] for r in runs),
        "per_run": runs,
    }


async def main_async(args: argparse.Namespace) -> None:
    corpus = load_corpus()
    # TOPOLOGY MATTERS MORE THAN IT LOOKS. With the mock in a thread of this
    # process, the mock's own request handling and the scheduler's send loop
    # share one GIL, and at 80 RPS the mock's ~560 SSE writes/sec saturate the
    # single core -- so measured "scheduling lag" is really "how long the
    # event loop was busy serving the mock". That is a harness artifact, not a
    # property of the scheduler: the real GPU run drives vLLM in a *separate
    # process* (separate venv, over loopback), with no shared interpreter.
    # Pass --mock-url to point at an externally-started mock and reproduce the
    # real topology.
    if args.mock_url:
        base_url, server, thread = args.mock_url.rstrip("/"), None, None
        print(f"driving external mock at {base_url} (separate process -- real topology)",
              file=sys.stderr)
    else:
        base_url, server, thread = _start_mock()
        print("driving IN-PROCESS mock (shares this interpreter's GIL -- fine at low RPS, "
              "saturates at Stage A's ceiling; prefer --mock-url)", file=sys.stderr)
    scratch = Path(args.scratch_dir)
    scratch.mkdir(parents=True, exist_ok=True)

    duration_s = 5.0 if args.smoke else args.duration_s
    repeats = 1 if args.smoke else args.repeats
    rps_points = [20.0] if args.smoke else RPS_POINTS

    cells: dict[str, dict] = {}
    try:
        for rps in rps_points:
            for spin in SPIN_ARMS_S:
                key = f"rps{rps:g}_spin{spin * 1000:g}ms"
                runs = []
                for i in range(repeats):
                    print(f"  {key} run {i + 1}/{repeats} ...", file=sys.stderr, flush=True)
                    runs.append(await _one_run(
                        base_url, corpus, rps, spin, duration_s,
                        scratch / f"{key}_{i}.raw_log.jsonl",
                    ))
                cells[key] = _summarize(runs)
                s = cells[key]
                print(
                    f"  {key}: lag p50={s['lag_ms']['p50']:.2f}ms p95={s['lag_ms']['p95']:.2f}ms "
                    f"p99={s['lag_ms']['p99']:.2f}ms max={s['lag_ms']['max']:.2f}ms "
                    f"achieved={s['achieved_rps']:.2f} div={s['divergence_pct']:+.2f}% "
                    f"neg_lag={s['n_negative_lag_total']}",
                    file=sys.stderr, flush=True,
                )
    finally:
        if server is not None:
            server.should_exit = True
            thread.join(timeout=10.0)

    record = {
        "purpose": (
            "Loadgen scheduler spin-margin A/B (WEEK2_PLAN.md §8, WEEK2_EXECUTION.md Block C). "
            "Arm A = 0ms (bare asyncio.sleep), Arm B = 5ms (Windows-tuned incumbent). One "
            "variable; everything else held identical."
        ),
        "host": {
            "platform": sys.platform,
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "cpu_count": __import__("os").cpu_count(),
            "hostname": socket.gethostname(),
        },
        "method": {
            "seed": SEED,
            "arrival_process": "poisson",
            "rps_points": rps_points,
            "spin_arms_s": SPIN_ARMS_S,
            "duration_s": duration_s,
            "repeats": repeats,
            "concurrency_cap": CONCURRENCY_CAP,
            "mock_config": MOCK_CONFIG,
            "num_tokens": NUM_TOKENS,
            "instrument": "loadgen scheduling lag (send_time - (t_start + scheduled_offset))",
            "smoke": bool(args.smoke),
            # Recorded because it materially changes the absolute lag numbers:
            # the mock shares this process (and its GIL) with the driver.
            "mock_spin_margin_s": mock_timing.SPIN_MARGIN_S,
            "mock_topology": "external-process" if args.mock_url else "in-process-thread",
        },
        "cells": cells,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"\nwrote {out}", file=sys.stderr)

    # The comparison table, printed so the human reads the number off the
    # same output the artifact holds (Hard Stop 3 discipline: the script
    # generates the data, the human reads the value).
    print()
    print(f"{'RPS':>6} {'spin':>7} {'p50':>9} {'p95':>9} {'p99':>9} {'max':>9} "
          f"{'offered':>8} {'achieved':>9} {'div%':>8} {'early':>6}")
    print("-" * 96)
    for rps in rps_points:
        for spin in SPIN_ARMS_S:
            s = cells[f"rps{rps:g}_spin{spin * 1000:g}ms"]
            lm = s["lag_ms"]
            print(f"{rps:>6g} {spin * 1000:>6g}ms {lm['p50']:>9.3f} {lm['p95']:>9.3f} "
                  f"{lm['p99']:>9.3f} {lm['max']:>9.3f} {rps:>8g} {s['achieved_rps']:>9.3f} "
                  f"{s['divergence_pct']:>+8.2f} {s['n_negative_lag_total']:>6d}")
    print("\n(lag in ms; 'early' = sends that fired BEFORE their scheduled offset, "
          "which V5 forbids -- must be 0)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(OUT_DEFAULT))
    parser.add_argument("--scratch-dir", default=str(
        Path(__file__).resolve().parent.parent / "benchmarks" / "scratch" / "scheduler_spin"))
    parser.add_argument("--duration-s", type=float, default=DURATION_S)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--smoke", action="store_true",
                        help="1 repeat x 5s at 20 RPS only -- shakeout, NOT a calibration")
    parser.add_argument(
        "--mock-url", default=None, dest="mock_url",
        help="drive an already-running mock at this base URL instead of starting one in a "
             "thread of this process. STRONGLY PREFERRED at Stage A rates: an in-process mock "
             "shares this interpreter's GIL with the scheduler, so its request handling shows "
             "up as scheduling lag. The real GPU run drives vLLM in a separate process")
    parser.add_argument(
        "--mock-spin-margin-s", type=float, default=None, dest="mock_spin_margin_s",
        help="override mock.timing.SPIN_MARGIN_S for this run. IMPORTANT CONFOUND: the mock "
             "runs in a thread of THIS process, so its own busy-wait competes with the "
             "scheduler for the GIL -- at 80 RPS x 5 sleeps/request that is seconds of "
             "spinning per second, and it inflates measured scheduling lag for BOTH arms. "
             "Block 0 already established the mock's spin is unnecessary on Linux "
             "(MOCK_TRUST_BOUNDARY.md), so pass 0 for the uncontaminated reading. The real "
             "GPU run has no such coupling: the driver and vLLM are separate processes",
    )
    args = parser.parse_args()

    if args.mock_spin_margin_s is not None:
        mock_timing.SPIN_MARGIN_S = args.mock_spin_margin_s
        print(f"mock.timing.SPIN_MARGIN_S overridden to {args.mock_spin_margin_s}s "
              "(removes the mock's GIL-contending busy-wait from this measurement)",
              file=sys.stderr)

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()

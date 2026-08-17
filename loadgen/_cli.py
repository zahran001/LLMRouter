"""Shared CLI plumbing for loadgen/steady.py, loadgen/poisson.py,
loadgen/adversarial.py -- argument parsing + the build-schedule -> drive
sequence common to all three (WEEK2_EXECUTION.md Block A).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

from loadgen.corpus import DEFAULT_CORPUS_PATH, load_corpus
from loadgen.log import RunLogger
from loadgen.schedule import Schedule, build_poisson_schedule, build_steady_schedule
from loadgen.scheduler import OpenLoopScheduler

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEDULE_DIR = REPO_ROOT / "benchmarks" / "schedules"
DEFAULT_LOG_DIR = REPO_ROOT / "benchmarks" / "runs"


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--rps", type=float, required=True, help="target offered RPS")
    parser.add_argument("--duration", type=float, required=True, dest="duration_s",
                         help="total schedule duration in seconds (warmup + measurement window, one continuous schedule -- §2.4)")
    parser.add_argument("--seed", type=int, required=True, help="master seed for arrival_rng/corpus_rng derivation")
    parser.add_argument("--base-url", default="http://127.0.0.1:9001", help="mock or vLLM base URL")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS_PATH))
    parser.add_argument("--concurrency-cap", type=int, required=True, dest="concurrency_cap",
                         help="cap on open (not-yet-drained) streaming responses -- over-cap sends shed, never block (§3.3)")
    parser.add_argument("--model", default="mock")
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--no-capture-samples", action="store_true",
                         help="skip per-chunk TTFT/TPOT capture (metrics.consume_stream) -- request-pattern-only run")
    # Mock-specific pass-throughs; a real-vLLM run would leave these at
    # defaults and use --extra-body instead.
    parser.add_argument("--mock-config", default=None, dest="mock_config",
                         help="mock's ?config= query param (fast/slow/bursty/high-variance); omit for real vLLM")
    parser.add_argument("--num-tokens", type=int, default=None, dest="num_tokens",
                         help="mock's ?num_tokens= query param; omit for real vLLM (use --extra-body max_tokens instead)")
    parser.add_argument("--extra-body", default=None, help="JSON object merged into the request body (e.g. real-vLLM max_tokens)")
    parser.add_argument("--tag", default=None, help="label embedded in output filenames; default derived from rps/seed")
    parser.add_argument("--schedule-dir", default=str(DEFAULT_SCHEDULE_DIR))
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    parser.add_argument("--schedule-in", default=None, dest="schedule_in",
                         help="re-drive a previously committed frozen schedule instead of generating a new one (replay, §5)")


def _tag(args: argparse.Namespace, arrival_process: str) -> str:
    if args.tag:
        return args.tag
    return f"{arrival_process}_rps{args.rps:g}_seed{args.seed}"


def build_or_load_schedule(args: argparse.Namespace, arrival_process: str, long_context: bool = False) -> tuple[Schedule, "Corpus"]:
    corpus = load_corpus(args.corpus)

    if args.schedule_in:
        schedule = Schedule.load(args.schedule_in)
        schedule.validate_corpus_version(corpus)  # raises on drift -- §5's reproducibility contract
        print(f"replaying frozen schedule {args.schedule_in} ({len(schedule.entries)} entries)", file=sys.stderr)
        return schedule, corpus

    builder = build_poisson_schedule if arrival_process == "poisson" else build_steady_schedule
    schedule = builder(args.rps, args.duration_s, args.seed, corpus, long_context=long_context)
    print(f"materialized {arrival_process} schedule: {len(schedule.entries)} entries over {args.duration_s}s", file=sys.stderr)
    return schedule, corpus


def save_schedule(schedule: Schedule, args: argparse.Namespace, arrival_process: str) -> Path:
    schedule_dir = Path(args.schedule_dir)
    path = schedule_dir / f"{_tag(args, arrival_process)}.schedule.json"
    schedule.save(path)
    print(f"schedule written to {path} (before any sending begins)", file=sys.stderr)
    return path


def build_request_kwargs(args: argparse.Namespace) -> dict:
    query_params = {}
    if args.mock_config is not None:
        query_params["config"] = args.mock_config
    if args.num_tokens is not None:
        query_params["num_tokens"] = args.num_tokens
    extra_body = json.loads(args.extra_body) if args.extra_body else None
    return {"query_params": query_params, "extra_body": extra_body}


async def run_and_report(schedule: Schedule, corpus, args: argparse.Namespace, arrival_process: str) -> dict:
    log_dir = Path(args.log_dir)
    log_path = log_dir / f"{_tag(args, arrival_process)}.raw_log.jsonl"

    scheduler = OpenLoopScheduler(
        schedule=schedule,
        corpus=corpus,
        base_url=args.base_url,
        logger=RunLogger(log_path),
        concurrency_cap=args.concurrency_cap,
        model=args.model,
        timeout_s=args.timeout_s,
        capture_samples=not args.no_capture_samples,
        **build_request_kwargs(args),
    )

    t0 = time.time()
    result = await scheduler.run()
    scheduler.logger.close()

    lag = result.per_send_lag_s
    offered_rps = args.rps
    divergence_pct = (
        100.0 * (result.achieved_rps - offered_rps) / offered_rps if offered_rps else 0.0
    )
    summary = {
        "arrival_process": arrival_process,
        "offered_rps": offered_rps,
        "achieved_rps": result.achieved_rps,
        "divergence_pct": divergence_pct,
        "n_scheduled": result.n_scheduled,
        "n_sent": result.n_sent,
        "n_shed": result.n_shed,
        "n_errored": result.n_errored,
        "window_s": result.window_s,
        "wall_clock_drain_s": result.wall_clock_drain_s,
        "wall_clock_s": time.time() - t0,
        "scheduling_lag_s": {
            "mean": statistics.mean(lag) if lag else None,
            "p50": statistics.median(lag) if lag else None,
            "max": max(lag) if lag else None,
        },
        "raw_log_path": str(log_path),
    }
    print(json.dumps(summary, indent=2))
    return summary


def main_for(arrival_process: str, long_context: bool = False) -> None:
    parser = argparse.ArgumentParser(description=f"loadgen/{arrival_process}.py -- open-loop {arrival_process} arrival generator")
    add_common_args(parser)
    args = parser.parse_args()

    schedule, corpus = build_or_load_schedule(args, arrival_process, long_context=long_context)
    if not args.schedule_in:
        save_schedule(schedule, args, arrival_process)

    asyncio.run(run_and_report(schedule, corpus, args, arrival_process))

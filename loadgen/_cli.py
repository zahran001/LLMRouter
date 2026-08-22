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
from loadgen.log import RunLogger, SampleLogger, read_log, read_samples
from loadgen.schedule import Schedule, build_poisson_schedule, build_steady_schedule
from loadgen.scheduler import (
    LINUX_SPIN_MARGIN_S,
    SPIN_MARGIN_ENV,
    WINDOWS_SPIN_MARGIN_S,
    OpenLoopScheduler,
    default_spin_margin_s,
)
from metrics.point import DEFAULT_BAND_PCT, MIN_TAIL_SAMPLES, point_metrics

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEDULE_DIR = REPO_ROOT / "benchmarks" / "schedules"
DEFAULT_LOG_DIR = REPO_ROOT / "benchmarks" / "runs"

# The session #1 placeholder the committed Stage A schedules were sized
# against (scripts/generate_stage_a_schedules.py: WARMUP_N_PLACEHOLDER_S).
#
# SCOPE: this module drives `loadgen-schedule-v1` schedules only -- the Stage A
# artifacts and the secondary natural-random points. Session #2's frozen
# exact-N schedules carry their own `warmup_boundary_s` (60s) and are driven
# through `loadgen/redesign_point.py`, which reads the boundary off the
# schedule and never consults this constant.
#
# The re-filter that used to be documented here -- resolve the real warmup
# afterwards by re-running compute_point_metrics over the committed sidecars
# -- was valid under the fixed-duration design and is forbidden for the
# redesigned headline (lock 4A): past the frozen boundary it discards
# canonical arrivals and silently leaves fewer than N measured samples.
# `metrics/headline_point.py` refuses it outright.
DEFAULT_WARMUP_N_S = 10.0

# Resolved 2026-08-17 (WEEK2_PLAN.md §3.3, §8) -- no longer [CALIBRATE].
# Above every concurrency level Block C's uncapped sweep produced (peak 2380
# simultaneous streams at 300 RPS; 651 at 100 RPS), and by Little's Law it
# cannot bite at session #1 Stage A's 80 RPS ceiling until mean response time exceeds
# 37.5s. A default rather than a required flag so the eight hand-run Stage A
# points cannot disagree with each other by a typo; every point record still
# logs the cap it actually ran with (provenance.concurrency_cap).
#
# PRECONDITION on Linux: `ulimit -n 65535` before driving. The default soft
# limit of 1024 is below this cap, so the process would hit EMFILE first and
# those land as `errored`, not `shed` -- corrupting achieved RPS instead of
# tripping the shed check.
BASELINE_CONCURRENCY_CAP = 3000


def add_common_args(parser: argparse.ArgumentParser) -> None:
    # Generation inputs, not replay inputs. Required to BUILD a schedule;
    # meaningless when one is being re-driven, because the frozen artifact
    # already records what it was built with. Passing hand-extracted copies
    # alongside `--schedule-in` only creates a second source of truth that can
    # disagree with the first -- so they are optional here and validated in
    # `build_or_load_schedule` against what was actually asked for.
    parser.add_argument("--rps", type=float, default=None, help="target offered RPS (generation)")
    parser.add_argument("--duration", type=float, default=None, dest="duration_s",
                         help="total schedule duration in seconds (warmup + measurement window, one continuous schedule -- §2.4). Generation only")
    parser.add_argument("--seed", type=int, default=None, help="master seed for arrival_rng/corpus_rng derivation (generation only)")
    parser.add_argument("--base-url", default="http://127.0.0.1:9001", help="mock or vLLM base URL")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS_PATH))
    parser.add_argument("--concurrency-cap", type=int, default=BASELINE_CONCURRENCY_CAP, dest="concurrency_cap",
                         help=f"cap on open (not-yet-drained) streaming responses -- over-cap sends shed, never "
                              f"block (§3.3). Default {BASELINE_CONCURRENCY_CAP} is the resolved baseline value; "
                              f"a point that sheds at all is cap-shaped, not server-shaped")
    parser.add_argument("--model", default="mock")
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--spin-margin-s", type=float, default=None, dest="spin_margin_s",
                         help=f"scheduler busy-wait margin in seconds; omit for this platform's "
                              f"calibrated default (currently {default_spin_margin_s()}s here -- "
                              f"Windows {WINDOWS_SPIN_MARGIN_S}s / Linux {LINUX_SPIN_MARGIN_S}s, see "
                              f"BENCHMARKS.md). Env {SPIN_MARGIN_ENV} also overrides")
    parser.add_argument("--no-capture-samples", action="store_true",
                         help="skip per-chunk TTFT/TPOT capture (metrics.consume_stream) -- request-pattern-only "
                              "run. NOTE: this also disables the sample sidecar and the per-point metrics record, "
                              "i.e. the run produces NO TTFT. Never use it for a baseline sweep point (§6.3)")
    parser.add_argument("--warmup-n", type=float, default=DEFAULT_WARMUP_N_S, dest="warmup_n_s",
                         help=f"seconds discarded from the front of the window, by send timestamp (§2.4). "
                              f"loadgen-schedule-v1 ONLY -- the legacy session #1 semantics. It is "
                              f"invalid for the session #2 exact-N headline, where the boundary is "
                              f"frozen into the schedule and filtering past it discards canonical "
                              f"arrivals (lock 4A); metrics/headline_point.py refuses it")
    parser.add_argument("--min-samples", type=int, default=MIN_TAIL_SAMPLES, dest="min_samples",
                         help="achieved post-warmup sample floor below which tail percentiles are not reportable (§2.4)")
    parser.add_argument("--band-pct", type=float, default=DEFAULT_BAND_PCT, dest="band_pct",
                         help="offered-vs-achieved divergence band in %% (§2.5); beyond it the point is flagged "
                              "and plotted at achieved RPS (Option Y)")
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
    # A replay may have no seed to name itself with -- the seed belongs to the
    # generation that produced the frozen file, not to this run of it.
    suffix = f"_seed{args.seed}" if args.seed is not None else "_replay"
    return f"{arrival_process}_rps{args.rps:g}{suffix}"


def build_or_load_schedule(args: argparse.Namespace, arrival_process: str, long_context: bool = False) -> tuple[Schedule, "Corpus"]:
    corpus = load_corpus(args.corpus)

    if args.schedule_in:
        schedule = Schedule.load(args.schedule_in)
        schedule.validate_corpus_version(corpus)  # raises on drift -- §5's reproducibility contract

        # The frozen schedule is the source of truth for what was offered.
        # Anything the caller did not supply is filled from its provenance
        # rather than defaulted, and anything the caller DID supply must agree
        # -- a silent mismatch would put one number in the point record and a
        # different one in the artifact it claims to describe.
        prov = schedule.provenance
        for flag, attr, key in (("--rps", "rps", "target_rps"),
                                ("--duration", "duration_s", "duration_s")):
            frozen = prov.get(key)
            supplied = getattr(args, attr)
            if supplied is None:
                if frozen is None:
                    raise SystemExit(
                        f"{args.schedule_in} has no provenance.{key} and {flag} was not given; "
                        "the point record cannot state what was offered.")
                setattr(args, attr, float(frozen))
            elif frozen is not None and abs(float(supplied) - float(frozen)) > 1e-9:
                raise SystemExit(
                    f"{flag}={supplied} contradicts the frozen schedule's {key}={frozen}. "
                    "A replay does not get to restate what was offered; drop the flag.")

        print(f"replaying frozen schedule {args.schedule_in} ({len(schedule.entries)} entries)", file=sys.stderr)
        return schedule, corpus

    missing = [flag for flag, attr in (("--rps", "rps"), ("--duration", "duration_s"),
                                       ("--seed", "seed")) if getattr(args, attr) is None]
    if missing:
        raise SystemExit(
            f"generating a schedule requires {', '.join(missing)}. (They are optional only "
            "with --schedule-in, where the frozen artifact already carries them.)")

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
    tag = _tag(args, arrival_process)
    log_path = log_dir / f"{tag}.raw_log.jsonl"
    samples_path = log_dir / f"{tag}.samples.jsonl"
    metrics_path = log_dir / f"{tag}.metrics.json"

    capture_samples = not args.no_capture_samples
    sample_logger = SampleLogger(samples_path) if capture_samples else None

    scheduler = OpenLoopScheduler(
        schedule=schedule,
        corpus=corpus,
        base_url=args.base_url,
        logger=RunLogger(log_path),
        sample_logger=sample_logger,
        concurrency_cap=args.concurrency_cap,
        model=args.model,
        timeout_s=args.timeout_s,
        capture_samples=capture_samples,
        spin_margin_s=args.spin_margin_s,
        **build_request_kwargs(args),
    )

    t0 = time.time()
    result = await scheduler.run()
    scheduler.logger.close()
    if sample_logger is not None:
        sample_logger.close()

    lag = result.per_send_lag_s
    offered_rps = args.rps
    divergence_pct = (
        100.0 * (result.achieved_rps - offered_rps) / offered_rps if offered_rps else 0.0
    )
    summary = {
        "arrival_process": arrival_process,
        "offered_rps": offered_rps,
        # Full-schedule achieved RPS (warmup included), the number the V2/V3
        # mock validations were built against. The per-point record below
        # carries the §2.5 gate's number instead -- sends within the
        # post-warmup measurement window only. They differ once a warmup is
        # being discarded; both are reported rather than one silently
        # replacing the other.
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

    if capture_samples:
        summary["samples_path"] = str(samples_path)
        summary["metrics_path"] = str(metrics_path)
        summary["point"] = write_point_metrics(
            log_path, samples_path, metrics_path, schedule, args, arrival_process
        )
    else:
        summary["point"] = None
        summary["warning"] = (
            "--no-capture-samples: no TTFT/TPOT recorded, no per-point metrics written. "
            "This run cannot contribute to the breach number."
        )

    print(json.dumps(summary, indent=2))
    return summary


def write_point_metrics(
    log_path: Path,
    samples_path: Path,
    metrics_path: Path,
    schedule: Schedule,
    args: argparse.Namespace,
    arrival_process: str,
) -> dict:
    """Compute and durably write the point's metrics record (§6.3: "written
    immediately after the point's window closes").

    Deliberately reads back the two files rather than using the scheduler's
    in-memory samples: that makes this call provably identical to Block F's
    offline recompute (scripts/compute_point_metrics.py), and it fails loudly
    here -- on the meter, where it can still be fixed -- if the durable
    artifacts are somehow not sufficient to produce the number.
    """
    record = point_metrics(
        raw_rows=read_log(log_path),
        sample_rows=read_samples(samples_path),
        offered_rps=args.rps,
        duration_s=schedule.provenance["duration_s"],
        warmup_n_s=args.warmup_n_s,
        min_samples=args.min_samples,
        band_pct=args.band_pct,
        provenance={
            "arrival_process": arrival_process,
            "schedule_provenance": schedule.provenance,
            "concurrency_cap": args.concurrency_cap,
            # The scheduler timing knob the point actually ran with, recorded
            # per point so a Linux sweep can never be mistaken for one driven
            # with the Windows-tuned margin (WEEK2_PLAN.md §8).
            "spin_margin_s": (
                default_spin_margin_s() if args.spin_margin_s is None else args.spin_margin_s
            ),
            "platform": sys.platform,
            "base_url": args.base_url,
            "model": args.model,
            "raw_log_path": str(log_path),
            "samples_path": str(samples_path),
            "warmup_n_is_placeholder": args.warmup_n_s == DEFAULT_WARMUP_N_S,
        },
    )
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    # Hard Stop 5 reads this line off the terminal to decide whether the
    # breach is bracketed, so it goes to stderr where it can't be lost in a
    # redirected stdout capture of the JSON summary.
    if record["tail_valid"] and record["ttft_p99_ms"] is not None:
        print(
            f"[point] offered={record['offered_rps']}rps achieved={record['achieved_rps']:.2f}rps "
            f"p99 TTFT={record['ttft_p99_ms']:.1f}ms "
            f"({'BREACH' if record['breach_500ms'] else 'under'} 500ms"
            f"{', SEVERE >2s' if record['severe_2s'] else ''}) "
            f"n={record['n_samples_window']} -> {metrics_path}",
            file=sys.stderr,
        )
    elif record["tail_valid"]:
        # Enough requests, but not one of them yielded a content chunk --
        # the point is loud, not quiet, and must not read as "no breach".
        print(
            f"[point] offered={record['offered_rps']}rps achieved={record['achieved_rps']:.2f}rps "
            f"NO TTFT: {record['n_samples_window']} post-warmup requests produced zero content "
            f"chunks between them -- check the upstream, this point measured nothing "
            f"-> {metrics_path}",
            file=sys.stderr,
        )
    else:
        print(
            f"[point] offered={record['offered_rps']}rps achieved={record['achieved_rps']:.2f}rps "
            f"TAIL-INVALID: only {record['n_samples_window']} post-warmup samples "
            f"(< {record['min_samples']}) -- p99 NOT reportable for this point (§2.4) "
            f"-> {metrics_path}",
            file=sys.stderr,
        )
    if record["flagged"]:
        print(
            f"[point] FLAGGED: achieved diverges {record['divergence_pct']:+.1f}% from offered "
            f"(band +/-{record['band_pct']}%) -- point plots at achieved RPS (Option Y, §2.5)",
            file=sys.stderr,
        )
    return record


def main_for(arrival_process: str, long_context: bool = False) -> None:
    parser = argparse.ArgumentParser(description=f"loadgen/{arrival_process}.py -- open-loop {arrival_process} arrival generator")
    add_common_args(parser)
    args = parser.parse_args()

    schedule, corpus = build_or_load_schedule(args, arrival_process, long_context=long_context)
    if not args.schedule_in:
        save_schedule(schedule, args, arrival_process)

    asyncio.run(run_and_report(schedule, corpus, args, arrival_process))

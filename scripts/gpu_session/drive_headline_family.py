#!/usr/bin/env python
"""Drive the frozen headline repeat family on the instance (R4 README R9).

Runs **on the L4**, from the repo clone, against vLLM on loopback. This is the
piece that turns `loadgen/repeat_runner.py` from a tested library into the
thing that actually sequences a metered session.

## Why the drain probe reads the SERVER, not the client

`OpenLoopScheduler.run()` already awaits every spawned send task before it
returns, so a client-side in-flight count is *always* zero by the time a point
finishes. Wiring the gate to that would produce a check that can never fail --
green forever, proving nothing, which is exactly the failure mode the
negative-control discipline exists to catch.

The quantity that actually matters is whether the **server** is still working.
vLLM reports it directly:

    vllm:num_requests_running   currently decoding
    vllm:num_requests_waiting   queued

Those can be non-zero after the client has closed every stream -- an abandoned
request keeps occupying the scheduler, and the next repeat would then queue
behind it. So the probe scrapes `/metrics` and the gate refuses on that.

## What it refuses to do

- start while the server has requests running or waiting (`RepeatOverlapError`);
- run at all unless a prefix-cache verdict artifact exists and says DISABLED --
  L6's gate belongs in the driver, not only in the human remembering to run it;
- drive schedules whose canonical membership disagrees, or whose post-warmup
  count is not exactly `N`.

Each point writes its own raw log, sidecar and redesigned point record before
the next one starts. Classification happens offline, afterwards, from those
files (`metrics/classification.py`).

Usage (on the instance):
    python scripts/gpu_session/drive_headline_family.py \
        --schedule-dir benchmarks/schedules/week2_redesign/headline \
        --lambdas 1.5 2 2.5 --repeats 1 2 3 \
        --out-dir ~/llmrouter-artifacts/headline
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402

from loadgen.corpus import load_corpus  # noqa: E402
from loadgen.headline_schedule import load_headline_schedule  # noqa: E402
from loadgen.log import RunLogger, SampleLogger, read_log, read_samples  # noqa: E402
from loadgen.prefix_cache import DISABLED  # noqa: E402
from loadgen.repeat_runner import RepeatPlan, RepeatRunner  # noqa: E402
from loadgen.scheduler import OpenLoopScheduler  # noqa: E402
from metrics.artifacts import write_json_artifact  # noqa: E402
from metrics.headline_point import headline_point_metrics  # noqa: E402

DEFAULT_SCHEDULE_DIR = REPO_ROOT / "benchmarks" / "schedules" / "week2_redesign" / "headline"
BASELINE_CONCURRENCY_CAP = 3000

RUNNING_RE = re.compile(r"^vllm:num_requests_running\{[^}]*\}\s+([\d.eE+-]+)", re.M)
WAITING_RE = re.compile(r"^vllm:num_requests_waiting\{[^}]*\}\s+([\d.eE+-]+)", re.M)


class ServerInflightProbe:
    """In-flight requests as the SERVER sees them.

    Fails closed: if `/metrics` cannot be read or the counters are absent, this
    raises rather than returning 0. A probe that cannot see the server must not
    be able to certify that the server is idle.
    """

    def __init__(self, base_url: str, timeout_s: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.client = httpx.Client(timeout=timeout_s)

    def __call__(self) -> int:
        text = self.client.get(f"{self.base_url}/metrics").text
        running, waiting = RUNNING_RE.search(text), WAITING_RE.search(text)
        if running is None and waiting is None:
            raise RuntimeError(
                f"{self.base_url}/metrics exposes neither vllm:num_requests_running nor "
                "vllm:num_requests_waiting. The drain gate cannot verify the server is idle, "
                "and a gate that silently reports 0 would be worse than no gate.")
        return int(float(running.group(1)) if running else 0) + \
            int(float(waiting.group(1)) if waiting else 0)

    def close(self) -> None:
        self.client.close()


def require_prefix_cache_disabled(verdict_path: Path) -> dict:
    """L6, enforced by the driver rather than by memory."""
    if not verdict_path.exists():
        raise SystemExit(
            f"REFUSED: no prefix-cache verdict at {verdict_path}.\n"
            "Run scripts/gpu_session/verify_prefix_cache_disabled.py first. Exact prompt "
            "replay is this experiment's central control; a live cache changes the cost it "
            "controls as a function of run order (WEEK2_PLAN.md 10.8).")
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    if verdict.get("verdict") != DISABLED:
        raise SystemExit(
            f"REFUSED: prefix-cache verdict is {verdict.get('verdict')!r}, not {DISABLED}.\n"
            "Relaunch vLLM with DISABLE_PREFIX_CACHING=1 and re-verify.")
    return verdict


def discover(schedule_dir: Path, repeat_ids: list[int], lambdas: list[float]) -> dict:
    """Load the frozen schedules for the requested (repeat, λ) grid.

    Every consistency check here is about the *family*, not one schedule: a
    single schedule can be perfectly valid while the set it belongs to is not
    a matched family.
    """
    found: dict[tuple[int, float], tuple[Path, object]] = {}
    for path in sorted(schedule_dir.glob("*.schedule.json")):
        schedule = load_headline_schedule(path)
        prov = schedule.provenance
        key = (prov["repeat_id"], prov["nominal_lambda_rps"])
        if key[0] in repeat_ids and any(abs(key[1] - lam) < 1e-9 for lam in lambdas):
            found[key] = (path, schedule)

    missing = [(r, lam) for r in repeat_ids for lam in lambdas
               if not any(k[0] == r and abs(k[1] - lam) < 1e-9 for k in found)]
    if missing:
        raise SystemExit(f"missing schedules for {missing} under {schedule_dir}")

    memberships = {s.provenance["canonical_prompt_membership_id"] for _p, s in found.values()}
    if len(memberships) != 1:
        raise SystemExit(
            f"the selected schedules span {len(memberships)} canonical memberships. Repeats "
            "must share membership exactly, or they are not comparable.")

    for (repeat_id, lam), (path, schedule) in sorted(found.items()):
        prov = schedule.provenance
        if prov["materialized_post_warmup_count"] != prov["post_warmup_target_count"]:
            raise SystemExit(
                f"{path.name}: {prov['materialized_post_warmup_count']} post-warmup arrivals, "
                f"expected exactly {prov['post_warmup_target_count']}. The exact-N contract is "
                "broken in the frozen artifact; regenerate rather than driving it.")

    return found


def drive_point(schedule, corpus, args, out_dir: Path, tag: str) -> dict:
    """One λ point: drive the complete frozen schedule, then record it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"{tag}.raw_log.jsonl"
    samples_path = out_dir / f"{tag}.samples.jsonl"
    metrics_path = out_dir / f"{tag}.metrics.json"

    extra_body = json.loads(args.extra_body) if args.extra_body else {}
    sample_logger = SampleLogger(samples_path)
    scheduler = OpenLoopScheduler(
        schedule=schedule,
        corpus=corpus,
        base_url=args.base_url,
        logger=RunLogger(raw_path),
        sample_logger=sample_logger,
        concurrency_cap=args.concurrency_cap,
        model=args.model,
        timeout_s=args.timeout_s,
        capture_samples=True,
        extra_body=extra_body,
    )

    started = time.time()
    result = asyncio.run(scheduler.run())
    scheduler.logger.close()
    sample_logger.close()

    prov = schedule.provenance
    record = headline_point_metrics(
        raw_rows=read_log(raw_path),
        sample_rows=read_samples(samples_path),
        schedule_provenance=prov,
        warmup_n_s=args.warmup_n_s if args.warmup_n_s is not None else prov["warmup_boundary_s"],
        provenance={
            "tag": tag,
            "schedule_path": str(schedule_path_of(schedule, args)),
            "raw_log_path": str(raw_path),
            "samples_path": str(samples_path),
            "base_url": args.base_url,
            "model": args.model,
            "concurrency_cap": args.concurrency_cap,
            "timeout_s": args.timeout_s,
            "wall_clock_s": time.time() - started,
            "wall_clock_drain_s": result.wall_clock_drain_s,
            "n_scheduled_driven": result.n_scheduled,
            "n_sent": result.n_sent,
            "n_shed": result.n_shed,
            "n_errored": result.n_errored,
        },
    )
    write_json_artifact(metrics_path, record)

    print(f"    issued {result.n_sent + result.n_errored}/{result.n_scheduled} "
          f"(shed {result.n_shed}, errored {result.n_errored})  "
          f"state={record['point_state']}  "
          f"p99={record['ttft_p99_ms'] if record['ttft_p99_ms'] is None else round(record['ttft_p99_ms'], 1)}ms  "
          f"censoring={record['ttft_censoring_rate']:.1%}")

    if result.n_shed:
        print("    WARNING: the concurrency cap bit. This point is cap-shaped, not "
              "server-shaped (WEEK2_PLAN.md 3.3).")
    if not record["schedule_delivery_ok"]:
        print(f"    WARNING: driver delivered {record['schedule_delivery_divergence_pct']:+.1f}% "
              "against the materialized schedule -- this repeat is excluded from "
              "classification.")
    return record


def schedule_path_of(schedule, args) -> Path:
    prov = schedule.provenance
    rps = f"{prov['nominal_lambda_rps']:g}"
    return Path(args.schedule_dir) / f"headline_r{prov['repeat_id']}_rps{rps}.schedule.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--schedule-dir", type=Path, default=DEFAULT_SCHEDULE_DIR)
    parser.add_argument("--repeats", type=int, nargs="+", default=[1, 2, 3],
                        help="repeat ids to drive, in order")
    parser.add_argument("--lambdas", type=float, nargs="+", required=True,
                        help="nominal lambda points, driven in this order within each repeat")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--model", default="meta-llama/Llama-3.2-3B-Instruct")
    parser.add_argument("--concurrency-cap", type=int, default=BASELINE_CONCURRENCY_CAP)
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--extra-body", default=None)
    parser.add_argument("--warmup-n-s", type=float, default=None,
                        help="metrics-side warmup; defaults to each schedule's frozen boundary. "
                             "Cannot exceed it -- that would discard canonical arrivals.")
    parser.add_argument("--prefix-cache-verdict", type=Path,
                        default=REPO_ROOT / "benchmarks" / "runs" / "preflight"
                        / "prefix_cache_verdict.json")
    parser.add_argument("--drain-timeout-s", type=float, default=300.0)
    args = parser.parse_args()

    verdict = require_prefix_cache_disabled(args.prefix_cache_verdict)
    print(f"prefix cache: {verdict['verdict']} (min replay ratio {verdict['min_ratio']:.2f})")

    schedules = discover(args.schedule_dir, args.repeats, args.lambdas)
    membership = next(iter(schedules.values()))[1].provenance["canonical_prompt_membership_id"]
    corpus = load_corpus()

    print(f"canonical membership {membership[:16]}...")
    print(f"driving {len(args.repeats)} repeat(s) x {len(args.lambdas)} lambda point(s), "
          "repeat-major")

    probe = ServerInflightProbe(args.base_url)
    records: list[dict] = []

    def run_point(plan: RepeatPlan, nominal_lambda: float) -> dict:
        path, schedule = schedules[(plan.repeat_id, nominal_lambda)]
        tag = path.name[: -len(".schedule.json")]
        print(f"\n  repeat {plan.repeat_id}  lambda {nominal_lambda:g}  {tag}")
        record = drive_point(schedule, corpus, args, args.out_dir, tag)
        records.append(record)
        return record

    plans = []
    for repeat_id in args.repeats:
        _p, schedule = schedules[(repeat_id, args.lambdas[0])]
        prov = schedule.provenance
        plans.append(RepeatPlan(
            repeat_id=repeat_id,
            arrival_seed=prov["arrival_seed"],
            assignment_seed=prov["assignment_seed"],
            lambda_points=list(args.lambdas),
            canonical_membership_id=membership,
        ))

    try:
        runner = RepeatRunner(run_point=run_point, inflight_probe=probe,
                              drain_timeout_s=args.drain_timeout_s)
        report = runner.run(plans)
    finally:
        probe.close()

    summary = report.to_dict()
    summary.update({
        "what": "Headline repeat family drive report (R4 README R9).",
        "driven_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "canonical_prompt_membership_id": membership,
        "prefix_cache_verdict": verdict["verdict"],
        "base_url": args.base_url,
        "model": args.model,
        "point_states": {r["provenance"]["tag"]: r["point_state"] for r in records},
    })
    report_path = args.out_dir / "family_report.json"
    write_json_artifact(report_path, summary)

    print(f"\n{len(records)} point(s) driven. States:")
    for tag, state in summary["point_states"].items():
        print(f"  {tag:<32} {state}")
    print(f"\nreport: {report_path}")
    print("\nClassification happens OFFLINE from these per-point records "
          "(metrics/classification.py). Pull the artifacts before teardown.")


if __name__ == "__main__":
    main()

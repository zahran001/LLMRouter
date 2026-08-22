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
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402

from loadgen.corpus import load_corpus  # noqa: E402
from loadgen.headline_schedule import load_headline_schedule  # noqa: E402
from loadgen.prefix_cache import (  # noqa: E402
    require_prefix_cache_disabled,
    server_process_epoch,
)
from loadgen.redesign_point import (  # noqa: E402
    BASELINE_CONCURRENCY_CAP,
    HEADLINE_EVIDENCE,
    RedesignScheduleError,
    drive_redesign_point,
    report_point,
    require_exact_n,
)
from loadgen.repeat_runner import RepeatPlan, RepeatRunner  # noqa: E402
from metrics.artifacts import write_json_artifact  # noqa: E402

DEFAULT_SCHEDULE_DIR = REPO_ROOT / "benchmarks" / "schedules" / "week2_redesign" / "headline"

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
        try:
            require_exact_n(path.name, schedule.provenance)
        except RedesignScheduleError as exc:
            raise SystemExit(str(exc)) from exc

    return found


def drive_point(schedule, corpus, args, out_dir: Path, tag: str) -> dict:
    """One λ point: drive the complete frozen schedule, then record it.

    The mechanics live in `loadgen/redesign_point.py`, shared with Tier A. All
    this layer adds is the evidence class: a headline point is the only kind
    that may define the breach.
    """
    record = drive_redesign_point(
        schedule,
        corpus,
        out_dir=out_dir,
        tag=tag,
        evidence_class=HEADLINE_EVIDENCE,
        base_url=args.base_url,
        model=args.model,
        schedule_path=schedule_path_of(schedule, args),
        concurrency_cap=args.concurrency_cap,
        timeout_s=args.timeout_s,
        extra_body=args.extra_body,
        warmup_n_s=args.warmup_n_s,
        process_epoch=args.process_epoch,
    )
    report_point(record)
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
                        help="metrics-side warmup. Defaults to each schedule's frozen boundary "
                             "and must EQUAL it: membership comes from the schedule, so any "
                             "other value changes nothing while the record claims it did. "
                             "Post-hoc re-filtering is not a valid resolution (lock 4A).")
    parser.add_argument("--prefix-cache-verdict", type=Path,
                        default=REPO_ROOT / "benchmarks" / "runs" / "preflight"
                        / "prefix_cache_verdict.json")
    parser.add_argument("--drain-timeout-s", type=float, default=300.0)
    parser.add_argument("--process-epoch", default=None,
                        help="override the server process epoch; by default it is read from "
                             "the server's own process_start_time_seconds, so a restart "
                             "mid-family is detected rather than asserted away")
    args = parser.parse_args()

    verdict = require_prefix_cache_disabled(args.prefix_cache_verdict)
    print(f"prefix cache: {verdict['verdict']} (min replay ratio {verdict['min_ratio']:.2f})")

    args.process_epoch = server_process_epoch(args.base_url, args.process_epoch)
    print(f"process epoch: {args.process_epoch}")

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

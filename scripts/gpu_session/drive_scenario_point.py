#!/usr/bin/env python
"""Drive one frozen session #2 exact-N schedule on the instance — scout,
sustained-scout, or steady (`WEEK2_GPU_SESSION_2_PLAN.md` §3 and §8, locks
5A and 6A).

Runs **on the L4**, from the repo clone, against vLLM on loopback — the same
place and the same way Tier B runs.

## This is Tier B's driver with Tier B's authority removed

Everything about interpreting the frozen schedule is shared with the headline
family through `loadgen/redesign_point.py`: the warmup boundary, the expected
post-warmup N, the delivery-fidelity denominator, the censoring gate, the
membership and corpus identity, and the nearest-rank percentile. A scout
sweep exists to hand Tier B a bracket, and a bracket measured under different
semantics is not one Tier B can use.

What is *not* shared is what the result may be used for. The scout family is
N=500 at one repeat, against its own separately-namespaced workload
(`week2_scout`, membership `e9470f8f…`). Its per-run classification flip rate
is ~34% — ample for locating a knee, useless as a verdict. So the record is
stamped `evidence_class: scout_diagnostic`, and `metrics/classification.py`
refuses to aggregate it into a headline family.

## One driver, three scenarios, none with authority

Tier A scout, its sustained-scout replacement, and the steady reference are
all `headline-schedule-v2` exact-N schedules, so they are read by the same
contract as the headline family and differ from it only in what the record
may be used for. The scenario is checked against the artifact by
`scenario_contract.py` before anything is sent: a headline schedule handed to
`--scenario scout` is refused on membership, which is the only field that
separates the two; a headline schedule handed to `--scenario sustained-scout`
is refused on `workload_class`, the only field separating that pair (they
share both scheme and membership).

## Why this drives one point rather than a family

Tier A is four sequential points with a human reading the result between the
sweep and Tier B, and lock 5A's fallback (λ=0.5, λ=16) fires per-end rather
than per-family. A family runner would have to encode a bracket-search policy
that the runbook deliberately keeps in the human's hands.

The drain gate is Tier B's, not this one's: it exists so repeats of the same
λ cannot overlap in one vLLM process. Scout points are single repeats driven
one command at a time, so there is nothing to serialize against here — but
the prefix-cache verdict IS required, because a live cache would move the
crossing this sweep is trying to locate, and the bracket would then point
Tier B at the wrong three λ.

Usage (on the instance):
    python scripts/gpu_session/drive_scout_point.py \
        --schedule benchmarks/schedules/week2_redesign/scout/headline_r1_rps1.schedule.json \
        --out-dir ~/llmrouter-artifacts/scout
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from loadgen.corpus import load_corpus  # noqa: E402
from loadgen.headline_schedule import load_headline_schedule  # noqa: E402
from loadgen.prefix_cache import (  # noqa: E402
    require_prefix_cache_disabled,
    server_process_epoch,
)
from loadgen.redesign_point import (  # noqa: E402
    BASELINE_CONCURRENCY_CAP,
    RedesignScheduleError,
    drive_redesign_point,
    report_point,
)
from metrics.artifacts import write_json_artifact  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scenario_contract import CONTRACTS, ScenarioMismatch, validate  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=["scout", "sustained-scout", "steady"],
                        default="scout",
                        help="which session #2 exact-N scenario this schedule belongs to; "
                             "checked against the artifact, never inferred from its path")
    parser.add_argument("--schedule", type=Path, required=True,
                        help="repo-relative or absolute path to ONE frozen v2 schedule")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--model", default="meta-llama/Llama-3.2-3B-Instruct")
    parser.add_argument("--concurrency-cap", type=int, default=BASELINE_CONCURRENCY_CAP)
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--extra-body", default=None)
    parser.add_argument("--warmup-n-s", type=float, default=None,
                        help="metrics-side warmup. Defaults to the schedule's frozen boundary "
                             "and must EQUAL it: membership comes from the schedule, so any "
                             "other value changes nothing while the record claims it did. "
                             "Post-hoc re-filtering is not a valid resolution (lock 4A).")
    parser.add_argument("--process-epoch", default=None,
                        help="identifier for the vLLM process this ran against")
    parser.add_argument("--prefix-cache-verdict", type=Path,
                        default=REPO_ROOT / "benchmarks" / "runs" / "preflight"
                        / "prefix_cache_verdict.json")
    args = parser.parse_args()

    verdict = require_prefix_cache_disabled(args.prefix_cache_verdict)
    print(f"prefix cache: {verdict['verdict']} (min replay ratio {verdict['min_ratio']:.2f})")

    args.process_epoch = server_process_epoch(args.base_url, args.process_epoch)
    print(f"process epoch: {args.process_epoch}")

    contract = CONTRACTS[args.scenario]
    try:
        validate(args.scenario, args.schedule)
    except ScenarioMismatch as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc

    # `load_headline_schedule` refuses anything that is not
    # `headline-schedule-v2`, so a legacy v1 artifact cannot be driven here by
    # accident -- it would be read with the wrong warmup semantics.
    schedule = load_headline_schedule(args.schedule)
    prov = schedule.provenance
    tag = args.schedule.name[: -len(".schedule.json")]

    print(f"{args.scenario} point {tag}  (DIAGNOSTIC -- never headline evidence)")
    print(f"  role         {contract.role}")
    print(f"  membership   {prov['canonical_prompt_membership_id'][:16]}...")
    print(f"  nominal      {prov['nominal_lambda_rps']:g} rps")
    print(f"  warmup       {prov['warmup_boundary_s']:g}s (frozen into the schedule)")
    print(f"  post-warmup  N = {prov['post_warmup_target_count']}")

    corpus = load_corpus()
    try:
        record = drive_redesign_point(
            schedule,
            corpus,
            out_dir=args.out_dir,
            tag=tag,
            evidence_class=contract.evidence_class,
            base_url=args.base_url,
            model=args.model,
            schedule_path=args.schedule,
            concurrency_cap=args.concurrency_cap,
            timeout_s=args.timeout_s,
            extra_body=args.extra_body,
            warmup_n_s=args.warmup_n_s,
            process_epoch=args.process_epoch,
        )
    except RedesignScheduleError as exc:
        raise SystemExit(str(exc)) from exc

    report_point(record)

    summary = {
        "what": f"Session #2 {args.scenario} point drive report "
                "(WEEK2_GPU_SESSION_2_PLAN.md 3/8).",
        "driven_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scenario": args.scenario,
        "tag": tag,
        "evidence_class": record["evidence_class"],
        "may_define_headline_breach": record["may_define_headline_breach"],
        "canonical_prompt_membership_id": record["canonical_prompt_membership_id"],
        "nominal_lambda_rps": record["nominal_lambda_rps"],
        "warmup_boundary_s": record["warmup_boundary_s"],
        "post_warmup_target_count": record["post_warmup_target_count"],
        "exact_n_honoured": record["exact_n_honoured"],
        "schedule_delivery_ok": record["schedule_delivery_ok"],
        "n_shed_total": record["n_shed_total"],
        "ttft_censoring_rate": record["ttft_censoring_rate"],
        "point_state": record["point_state"],
        "prefix_cache_verdict": verdict["verdict"],
    }
    write_json_artifact(args.out_dir / f"{tag}.scout_report.json", summary)

    print("\n  Tier A gates:")
    print(f"    exact_n_honoured      {record['exact_n_honoured']}")
    print(f"    schedule_delivery_ok  {record['schedule_delivery_ok']}")
    print(f"    shed                  {record['n_shed_total']}")
    print(f"    censoring             {record['ttft_censoring_rate']:.1%}")
    print("\n  DIAGNOSTIC. This point locates the crossing region. It may not produce an")
    print("  UNDER/OVER headline claim and never enters the classification "
          "(repeat_policy.json, scout.evidence_class).")


if __name__ == "__main__":
    main()

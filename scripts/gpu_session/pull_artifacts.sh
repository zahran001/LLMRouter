#!/usr/bin/env bash
#
# pull_artifacts.sh -- LOCAL. Copy the session's durable artifacts off the
# instance and verify they are complete, BEFORE teardown
# (WEEK2_PLAN.md 6.3/6.4, WEEK2_GPU_SESSION_2_PLAN.md).
#
# Running the loadgen on the instance means the artifacts are born on a disk
# that gets deleted with it. This is the step that makes them survive, and
# the verification exists so "I pulled them" and "I have a usable sweep" are
# the same statement -- checked while the instance is still up and a missing
# point can still be re-driven.
#
# Uses an ABSOLUTE remote path: PuTTY's pscp does not reliably expand ~ in
# remote paths and fails with "unable to open ~/dest" (GPU_SESSION_NOTES.md).

set -euo pipefail

INSTANCE_NAME="${INSTANCE_NAME:-llmrouter-vllm-l4-week2}"
ZONE="${ZONE:-us-central1-a}"
# Required, not defaulted. It used to fall back to session #1's `stage_a`, so a
# bare invocation pulled a session #1 directory and reported it complete --
# while the session #2 points it was meant to fetch stayed on an instance that
# is about to be deleted.
if [ -z "${SESSION_TAG:-}" ]; then
  echo "FATAL: SESSION_TAG is required. Session #2 writes one directory per stage:" >&2
  echo "    floor  scout  headline  secondary  steady  adversarial" >&2
  echo "  e.g. SESSION_TAG=headline bash scripts/gpu_session/pull_artifacts.sh" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST_DIR="${DEST_DIR:-$REPO_ROOT/benchmarks/runs/$SESSION_TAG}"

remote_home() {
  gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" --command="pwd" | tr -d '\r' | tail -1
}

HOME_REMOTE="$(remote_home)"
SRC_DIR="$HOME_REMOTE/llmrouter-artifacts/$SESSION_TAG"

echo "pulling $INSTANCE_NAME:$SRC_DIR"
echo "     -> $DEST_DIR"
mkdir -p "$DEST_DIR"

gcloud compute scp --recurse \
  --zone="$ZONE" \
  "$INSTANCE_NAME:$SRC_DIR" \
  "$(dirname "$DEST_DIR")"

echo
echo "=== completeness check ==="
# A point is only usable if all three artifacts arrived: the raw log (sends,
# sheds, errors), the sidecar (the breach metric itself), and the point
# record. A sidecar that did not make it is a point that cannot produce a
# p99 -- which is the exact failure this whole pipeline exists to prevent,
# so it is checked rather than assumed.
python - "$DEST_DIR" "$REPO_ROOT" <<'PYEOF'
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[2])
from metrics.artifacts import discover_tags

dest = Path(sys.argv[1])
# Suffix-stripping, NOT name.split(".")[0]: the old rule read
# `poisson_rps1.5.raw_log.jsonl` as the point `poisson_rps1` and reported a
# healthy fractional point as incomplete (handoff 11). Stage B is fractional.
tags = discover_tags(dest)
if not tags:
    print(f"NOTHING PULLED: no *.raw_log.jsonl under {dest}")
    raise SystemExit(1)

problems = 0
print(f"{'point':<28} {'raw':>8} {'samples':>8} {'metrics':>8}  status")
print("-" * 78)
for tag in tags:
    raw = dest / f"{tag}.raw_log.jsonl"
    samples = dest / f"{tag}.samples.jsonl"
    metrics = dest / f"{tag}.metrics.json"

    n_raw = sum(1 for _ in raw.open(encoding="utf-8")) if raw.exists() else 0
    n_samples = sum(1 for _ in samples.open(encoding="utf-8")) if samples.exists() else 0

    notes = []
    if not samples.exists() or n_samples == 0:
        notes.append("NO SAMPLES -- no TTFT, point unusable")
        problems += 1
    if not metrics.exists():
        notes.append("no metrics.json (recompute offline)")
    else:
        try:
            rec = json.loads(metrics.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            notes.append(f"metrics.json unreadable: {exc}")
            problems += 1
        else:
            # Three record shapes reach this gate, and they do NOT share
            # field names. Reading the legacy names off a session #2 record
            # printed "under" for a breaching point (because `breach_500ms`
            # was absent and therefore falsy) and "TAIL-INVALID" for every
            # valid one (because `tail_valid` was absent too) -- wrong in both
            # fields, on the meter, at the moment §11 asks a human to read it.
            version = rec.get("record_version")
            if version == "headline-point-v1":
                shape = "session2"
            elif version == "floor-point-v1":
                shape = "floor"
            else:
                shape = "legacy"
            notes.append(shape)

            if shape == "session2":
                if not rec.get("exact_n_honoured", False):
                    notes.append("EXACT-N BROKEN")
                    problems += 1
                if not rec.get("schedule_delivery_ok", False):
                    notes.append(
                        f"DELIVERY {rec.get('schedule_delivery_divergence_pct', 0):+.1f}% "
                        "-- excluded from classification")
                    problems += 1
                notes.append(f"N={rec.get('percentile_population_n')}")
                notes.append(f"[{rec.get('evidence_class', '?')}]")
            elif shape == "floor":
                if not rec.get("membership_complete", False):
                    notes.append(f"INCOMPLETE FLOOR -- {rec.get('n_missing_prompts')} prompts "
                                 "never served")
                    problems += 1
                notes.append(f"served={rec.get('reconciled_measurement_n')}"
                             f"/{rec.get('expected_measurement_n')}")
            else:
                if not rec.get("tail_valid"):
                    notes.append(f"TAIL-INVALID (n={rec.get('n_samples_window')})")
                if rec.get("flagged"):
                    notes.append(f"flagged {rec.get('divergence_pct', 0):+.1f}%")

            censoring = rec.get("ttft_censoring_rate")
            if censoring:
                notes.append(f"censoring={censoring:.1%}")

            if rec.get("n_shed_total"):
                notes.append(f"SHED={rec['n_shed_total']} -- cap bit, point is cap-shaped")
                problems += 1
            if rec.get("n_errored_total"):
                notes.append(f"errored={rec['n_errored_total']}")

            p99 = rec.get("ttft_p99_ms")
            state = rec.get("point_state")
            if p99 is None:
                notes.append(f"NO p99{f' ({state})' if state else ''}")
            elif shape == "legacy":
                notes.append(f"p99={p99:.0f}ms {'BREACH' if rec.get('breach_500ms') else 'under'}")
            else:
                # `point_state` is the authority for a session #2 record; the
                # threshold lives in the reader, not here.
                notes.append(f"p99={p99:.0f}ms {state or ''}".rstrip())

    print(f"{tag:<28} {n_raw:>8} {n_samples:>8} {'yes' if metrics.exists() else 'NO':>8}  "
          + "; ".join(notes))

print()
if problems:
    print(f"{problems} problem(s) above. The instance is still up -- re-drive those points now,")
    print("while re-driving is cheap, rather than discovering it after teardown.")
    raise SystemExit(1)
print(f"{len(tags)} point(s) pulled and complete.")
print("Next: bash scripts/gpu_session/teardown_week2.sh   (owns the Week 2 instance name;")
print("      bare scripts/teardown.sh would target Week 1's name and silently no-op)")
# Deliberately NOT compute_point_metrics --warmup-n: that is session #1's
# post-hoc warmup re-filter, which lock 4A forbids for the redesigned headline
# (repeat_policy.json: post_hoc_warmup_refilter false). It also asked the
# operator to supply a "<resolved N>" that no longer exists as a concept --
# the boundary is frozen into the schedule.
print("Then, OFFLINE and after teardown: classify from these per-point records via")
print("      metrics/classification.py (WEEK2_GPU_SESSION_2_PLAN.md 13). No percentile is")
print("      computed on the meter and no verdict is rendered during the session.")
PYEOF

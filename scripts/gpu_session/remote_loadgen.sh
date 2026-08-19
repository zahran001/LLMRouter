#!/bin/bash
#
# remote_loadgen.sh -- REMOTE script. Runs ON the L4 instance, from the repo
# clone that run_on_instance.sh puts there. Not invoked by hand: the local
# wrapper calls it as one simple ssh --command (docs/GPU_SESSION_NOTES.md --
# chained/nested-quote --command strings intermittently fail with exit 128
# and no output through the Windows gcloud -> plink chain).
#
# WHY THE LOADGEN RUNS HERE AND NOT ON THE LAPTOP (WEEK2_PLAN.md 2.5, 3.3):
# driving through the SSH tunnel would fold WAN round-trip into every TTFT
# and multiplex up to 3000 concurrent streams through a single TCP
# connection -- at Stage A's upper points that measures the tunnel, not the
# replica, and it does so in the direction that inflates the breach metric.
# On-instance the loadgen talks to 127.0.0.1:8000 over loopback.
#
# Deliberately ASCII-only: this file gets executed by bash on the instance,
# and GPU_SESSION_NOTES.md records a BOM/encoding failure mode for scripts
# authored on Windows and run on Linux.

set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/LLMRouter}"
VENV_DIR="${VENV_DIR:-$HOME/loadgen-env}"
ARTIFACT_ROOT="${ARTIFACT_ROOT:-$HOME/llmrouter-artifacts}"
VLLM_URL="${VLLM_URL:-http://127.0.0.1:8000}"

# 3000 concurrent streams needs ~3000 sockets; Ubuntu's default soft limit
# is 1024, below the cap (WEEK2_PLAN.md 3.3). Under it the process hits
# EMFILE before the cap can engage, and those land as `errored` -- a send
# really attempted -- rather than `shed`, corrupting achieved RPS instead of
# tripping the shed check. Raising the soft limit toward the hard limit
# needs no root.
FD_LIMIT="${FD_LIMIT:-65535}"

usage() {
  cat <<'EOF'
usage: remote_loadgen.sh <command> [args]

  setup                     apt deps + venv + pip install -r requirements.txt
  env-check                 report python/deps/ulimit/GPU/vLLM-health/commit
  verify-cache              REFUSE the session if prefix caching is live (L6)
  run <schedule.json> <tag> drive one committed schedule against local vLLM
                            (session #1 format; still the way to drive a
                            single scout or secondary point)
  headline <tag> <lambdas>  drive the frozen headline repeat family through
                            the drain-gated runner (session #2, R9)
  list-artifacts            list what is currently under the artifact root
EOF
}

py() { "$VENV_DIR/bin/python" "$@"; }

cmd_setup() {
  if [ ! -d "$REPO_DIR" ]; then
    echo "FATAL: $REPO_DIR does not exist -- run 'bootstrap' from the local wrapper first" >&2
    exit 1
  fi
  # The common-cu* DLVM image ships drivers but no pip/venv
  # (GPU_SESSION_NOTES.md, "Image and package choice").
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-pip python3-venv
  # Separate venv from ~/vllm-env on purpose: vLLM pins torch/numpy hard, and
  # the driver must not be able to perturb the server's environment.
  [ -d "$VENV_DIR" ] || python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install -q -U pip
  "$VENV_DIR/bin/pip" install -q -r "$REPO_DIR/requirements.txt"
  mkdir -p "$ARTIFACT_ROOT"
  echo "setup OK: venv=$VENV_DIR repo=$REPO_DIR artifacts=$ARTIFACT_ROOT"
}

cmd_env_check() {
  echo "=== commit driving this session ==="
  git -C "$REPO_DIR" --no-pager log -1 --format='%H %s'
  git -C "$REPO_DIR" status --porcelain | head -5
  if [ -n "$(git -C "$REPO_DIR" status --porcelain)" ]; then
    echo "WARNING: the instance's clone is DIRTY -- the sweep would not be reproducible from a commit" >&2
  fi

  echo
  echo "=== python + deps ==="
  py -c 'import sys, numpy, httpx; print("python", sys.version.split()[0], "numpy", numpy.__version__, "httpx", httpx.__version__)'
  ( cd "$REPO_DIR" && py -c 'import loadgen.scheduler, metrics.point; print("loadgen + metrics import OK")' )

  echo
  echo "=== file descriptors (needs to clear the 3000 concurrency cap) ==="
  echo "soft=$(ulimit -Sn) hard=$(ulimit -Hn)"
  ulimit -n "$FD_LIMIT" 2>/dev/null || true
  echo "after raise attempt: soft=$(ulimit -Sn) (target $FD_LIMIT)"
  if [ "$(ulimit -Sn)" -lt 4000 ]; then
    echo "WARNING: soft fd limit below the 3000 cap + headroom -- EMFILE would masquerade as errored sends" >&2
  fi

  echo
  echo "=== GPU ==="
  nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader || echo "nvidia-smi unavailable"

  echo
  echo "=== vLLM health at $VLLM_URL ==="
  curl -sS -o /dev/null -w 'health HTTP %{http_code} in %{time_total}s\n' "$VLLM_URL/health" \
    || echo "FATAL: vLLM not reachable on loopback -- is setup_and_launch_vllm.sh still running?" >&2

  echo
  echo "=== corpus present (schedules validate their own sha256 at replay) ==="
  ls -la "$REPO_DIR/corpus/baseline_prompts.jsonl"
}

cmd_run() {
  local schedule="$1"
  local tag="$2"
  shift 2

  [ -f "$schedule" ] || { echo "FATAL: no such schedule: $schedule" >&2; exit 1; }

  # Raise the fd limit in THIS shell, before the driver starts. Verified, not
  # assumed -- a silent failure here is the EMFILE-as-errored trap above.
  ulimit -n "$FD_LIMIT" 2>/dev/null || true
  local soft
  soft="$(ulimit -Sn)"
  if [ "$soft" -lt 4000 ]; then
    echo "FATAL: fd soft limit is $soft, below the concurrency cap + headroom." >&2
    echo "Refusing to drive a point that would report EMFILE failures as 'errored' sends." >&2
    exit 1
  fi

  # Offered RPS / duration / seed come from the schedule's OWN provenance,
  # never from the filename or a hand-typed flag -- the point record's
  # offered_rps must match what was actually materialized (WEEK2_PLAN.md 2.5).
  local rps duration seed
  rps="$(py -c 'import json,sys; print(json.load(open(sys.argv[1]))["provenance"]["target_rps"])' "$schedule")"
  duration="$(py -c 'import json,sys; print(json.load(open(sys.argv[1]))["provenance"]["duration_s"])' "$schedule")"
  seed="$(py -c 'import json,sys; print(json.load(open(sys.argv[1]))["provenance"]["master_seed"])' "$schedule")"

  local out_dir="$ARTIFACT_ROOT/$tag"
  mkdir -p "$out_dir"

  echo "point: rps=$rps duration=${duration}s seed=$seed fd_soft=$soft"
  echo "  schedule: $schedule"
  echo "  out:      $out_dir"

  cd "$REPO_DIR"
  # --schedule-in re-drives the committed artifact and validates the corpus
  # sha256 against the schedule's provenance (WEEK2_PLAN.md 5); it raises on
  # drift rather than silently driving a different workload.
  py -m loadgen.poisson \
    --schedule-in "$schedule" \
    --rps "$rps" \
    --duration "$duration" \
    --seed "$seed" \
    --base-url "$VLLM_URL" \
    --model "${LOADGEN_MODEL:-meta-llama/Llama-3.2-3B-Instruct}" \
    --log-dir "$out_dir" \
    --schedule-dir "$out_dir" \
    --tag "$(basename "$schedule" .schedule.json)" \
    ${EXTRA_BODY:+--extra-body "$EXTRA_BODY"} \
    "$@"
}

cmd_verify_cache() {
  # L6: the CLI flag is not evidence. This probes the running server.
  cd "$REPO_DIR"
  mkdir -p "$REPO_DIR/benchmarks/runs/preflight"
  py scripts/gpu_session/verify_prefix_cache_disabled.py \
    --base-url "$VLLM_URL" \
    --model "${LOADGEN_MODEL:-meta-llama/Llama-3.2-3B-Instruct}" \
    --out "$REPO_DIR/benchmarks/runs/preflight/prefix_cache_verdict.json"
}

cmd_headline() {
  local tag="$1"
  shift
  [ -n "$tag" ] || { echo "usage: remote_loadgen.sh headline <tag> <lambda> [lambda...]" >&2; exit 1; }
  [ "$#" -gt 0 ] || { echo "FATAL: give at least one lambda point" >&2; exit 1; }

  # Same fd guard as cmd_run: EMFILE would land as `errored` sends and
  # corrupt the censoring rate rather than tripping the shed check.
  ulimit -n "$FD_LIMIT" 2>/dev/null || true
  local soft
  soft="$(ulimit -Sn)"
  if [ "$soft" -lt 4000 ]; then
    echo "FATAL: fd soft limit is $soft, below the concurrency cap + headroom." >&2
    exit 1
  fi

  local out_dir="$ARTIFACT_ROOT/$tag"
  mkdir -p "$out_dir"

  # Nothing about the workload is passed here: lambda selects which frozen
  # schedules to drive, and every other parameter comes from their own
  # provenance. The driver refuses if the prefix-cache verdict is missing or
  # not DISABLED, and if the schedules do not share one canonical membership.
  cd "$REPO_DIR"
  py scripts/gpu_session/drive_headline_family.py \
    --schedule-dir "$REPO_DIR/benchmarks/schedules/week2_redesign/headline" \
    --lambdas "$@" \
    --out-dir "$out_dir" \
    --base-url "$VLLM_URL" \
    --model "${LOADGEN_MODEL:-meta-llama/Llama-3.2-3B-Instruct}" \
    --prefix-cache-verdict "$REPO_DIR/benchmarks/runs/preflight/prefix_cache_verdict.json" \
    ${REPEAT_IDS:+--repeats $REPEAT_IDS} \
    ${EXTRA_BODY:+--extra-body "$EXTRA_BODY"}
}

cmd_list_artifacts() {
  find "$ARTIFACT_ROOT" -type f \( -name '*.raw_log.jsonl' -o -name '*.samples.jsonl' -o -name '*.metrics.json' \) \
    -printf '%10s  %p\n' 2>/dev/null | sort -k2 || echo "(nothing yet under $ARTIFACT_ROOT)"
}

case "${1:-}" in
  setup)          shift; cmd_setup "$@" ;;
  env-check)      shift; cmd_env_check "$@" ;;
  verify-cache)   shift; cmd_verify_cache "$@" ;;
  run)            shift; cmd_run "$@" ;;
  headline)       shift; cmd_headline "$@" ;;
  list-artifacts) shift; cmd_list_artifacts "$@" ;;
  *)              usage; exit 1 ;;
esac

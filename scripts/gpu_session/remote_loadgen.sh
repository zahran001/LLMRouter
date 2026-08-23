#!/bin/bash
#
# remote_loadgen.sh -- REMOTE script. Runs ON the L4 instance, from the repo
# clone that run_on_instance.sh puts there. Not invoked by hand: the local
# wrapper calls it as one simple ssh --command (GPU_SESSION_NOTES.md --
# chained/nested-quote --command strings intermittently fail with exit 128
# and no output through the Windows gcloud -> plink chain).
#
# WHY THE LOADGEN RUNS HERE AND NOT ON THE LAPTOP (WEEK2_PLAN.md 2.5, 3.3):
# driving through the SSH tunnel would fold WAN round-trip into every TTFT
# and multiplex up to 3000 concurrent streams through a single TCP
# connection -- at session #1 Stage A's upper points that measures the tunnel, not the
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
  floor <tag>               drive the unloaded intrinsic floor: every canonical
                            prompt once, sequentially, concurrency 1, no
                            arrival process. DIAGNOSTIC
  scout <schedule.json> <tag>
                            drive ONE frozen Tier A scout schedule
                            (headline-schedule-v2) through the session #2
                            measurement path. DIAGNOSTIC -- the record is
                            stamped scout_diagnostic and can never enter the
                            headline classification
  steady <schedule.json> <tag>
                            drive ONE frozen steady-reference schedule (v2
                            exact-N). DIAGNOSTIC
  secondary <schedule.json> <tag>
                            drive ONE frozen natural-random secondary schedule
                            (v1). DIAGNOSTIC
  adversarial <schedule.json> <tag>
                            drive ONE frozen adversarial long-context schedule
                            (v1). DIAGNOSTIC -- runs LAST
  run <schedule.json> <tag> drive one LEGACY (loadgen-schedule-v1) committed
                            schedule -- the secondary natural-random points.
                            REFUSES a v2 schedule and names `scout` instead
  headline <tag> <lambdas>  drive the frozen headline repeat family through
                            the drain-gated runner (session #2, R9)
  list-artifacts            list what is currently under the artifact root
EOF
}

py() {
  # The instance is Linux, so `bin/python` is the real path and the one that
  # runs on the meter. The Windows layout is accepted too, and only so the
  # dispatch below can be exercised by the test suite on the dev box -- there
  # is deliberately NO fallback to a bare `python`: a missing venv must fail
  # loudly rather than silently drive a point with whatever interpreter and
  # dependency set happened to be on PATH.
  if [ -x "$VENV_DIR/bin/python" ]; then
    "$VENV_DIR/bin/python" "$@"
  else
    "$VENV_DIR/Scripts/python.exe" "$@"
  fi
}

schedule_workload_class() {
  # Which scenario generated this artifact. Read from provenance for the same
  # reason the scheme is: the directory a file sits in is not authority.
  py -c 'import json,sys; print(json.load(open(sys.argv[1]))["provenance"].get("workload_class",""))' "$1"
}

schedule_scheme() {
  # Which format is this frozen artifact? The two generations declare
  # themselves, so the dispatch reads the schedule rather than inferring from
  # a directory name -- `benchmarks/schedules/week2_redesign/scout/` holds
  # files named `headline_r1_rps*.schedule.json`, and guessing from the path
  # is exactly how a scout point ends up read as a headline one.
  #
  # `.get()` rather than `[]`: an artifact that declares no scheme is not a
  # crash, it is an unknown format, and the caller decides what to do about
  # that.
  py -c 'import json,sys; print(json.load(open(sys.argv[1]))["provenance"].get("schedule_scheme_version",""))' "$1"
}

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
  echo "=== corpus present (every driver hashes it at replay and refuses on drift) ==="
  ls -la "$REPO_DIR/corpus/baseline_prompts.jsonl"
}

cmd_legacy_replay() {
  # The shared v1 replay body. Reached two ways: `run` (no scenario check, for
  # session #1 artifacts) and the named `secondary` / `adversarial` commands,
  # which validate the artifact's role first.
  local schedule="$1"
  local tag="$2"
  shift 2

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

  local out_dir="$ARTIFACT_ROOT/$tag"
  mkdir -p "$out_dir"

  echo "point: schedule=$(basename "$schedule") fd_soft=$soft"
  echo "  out:      $out_dir"

  cd "$REPO_DIR"
  # --schedule-in re-drives the committed artifact and validates the corpus
  # sha256 against the schedule's provenance (WEEK2_PLAN.md 5); it raises on
  # drift rather than silently driving a different workload.
  #
  # No --rps/--duration/--seed: those are schedule-GENERATION inputs, and this
  # is a replay. The frozen artifact already carries what was offered, and
  # passing hand-extracted copies alongside it only creates a second source of
  # truth that can disagree with the first.
  py -m loadgen.poisson \
    --schedule-in "$schedule" \
    --base-url "$VLLM_URL" \
    --model "${LOADGEN_MODEL:-meta-llama/Llama-3.2-3B-Instruct}" \
    --log-dir "$out_dir" \
    --schedule-dir "$out_dir" \
    --tag "$(basename "$schedule" .schedule.json)" \
    ${EXTRA_BODY:+--extra-body "$EXTRA_BODY"} \
    "$@"
}

cmd_run() {
  local schedule="$1"
  local tag="$2"
  shift 2

  [ -f "$schedule" ] || { echo "FATAL: no such schedule: $schedule" >&2; exit 1; }

  # Format dispatch FIRST, before any resource guard: driving the wrong reader
  # is a correctness failure, and it should be refused for that reason rather
  # than incidentally surviving because the fd check happened to pass.
  #
  # A v2 schedule read by the legacy runner is the defect this exists to
  # prevent: `metrics/point.py` does not know what `warmup_boundary_s` is, so
  # it would apply the legacy 10s placeholder to a schedule whose boundary is
  # frozen at 60s, and emit a record carrying neither `exact_n_honoured` nor
  # `schedule_delivery_ok`. Every number in it would look plausible.
  local scheme
  scheme="$(schedule_scheme "$schedule")"
  if [ "$scheme" = "headline-schedule-v2" ]; then
    echo "FATAL: $schedule is a Session #2 schedule ($scheme)." >&2
    echo "'run' drives the LEGACY v1 format and would read it with the wrong warmup" >&2
    echo "semantics. Drive it through the session #2 path instead:" >&2
    echo "    remote_loadgen.sh scout $schedule <tag>" >&2
    exit 1
  fi

  # `run` performs NO scenario check, so it must not be reachable for an
  # artifact that HAS a named scenario command. Both session #2 v1 families are
  # `loadgen-schedule-v1`, so the scheme gate above cannot tell them apart --
  # without this, `run <adversarial schedule>` under SESSION_TAG=secondary
  # drives happily and files the result under a scenario it never measured.
  local wclass
  wclass="$(schedule_workload_class "$schedule")"
  case "$wclass" in
    secondary_natural_random|adversarial_long_context)
      local named="secondary"
      [ "$wclass" = "adversarial_long_context" ] && named="adversarial"
      echo "FATAL: $schedule was generated as '$wclass', which has its own command." >&2
      echo "'run' applies no scenario check at all. Use the named command, which" >&2
      echo "validates the artifact's role before driving it:" >&2
      echo "    remote_loadgen.sh $named $schedule <tag>" >&2
      exit 1 ;;
  esac

  cmd_legacy_replay "$schedule" "$tag" "$@"
}

cmd_floor() {
  local tag="${1:-floor}"
  shift 2>/dev/null || true

  # No fd guard: the floor holds exactly one stream open at a time by
  # construction, so the EMFILE trap the loaded points need cannot apply here.
  # Asserting a 65535 limit anyway would be cargo-culted rather than earned.
  local out_dir="$ARTIFACT_ROOT/$tag"
  mkdir -p "$out_dir"

  echo "unloaded floor: canonical membership, concurrency 1, sequential"
  echo "  out:      $out_dir"

  cd "$REPO_DIR"
  py scripts/gpu_session/drive_unloaded_floor.py \
    --out-dir "$out_dir" \
    --tag "$tag" \
    --base-url "$VLLM_URL" \
    --model "${LOADGEN_MODEL:-meta-llama/Llama-3.2-3B-Instruct}" \
    --prefix-cache-verdict "$REPO_DIR/benchmarks/runs/preflight/prefix_cache_verdict.json" \
    ${PROCESS_EPOCH:+--process-epoch "$PROCESS_EPOCH"} \
    ${EXTRA_BODY:+--extra-body "$EXTRA_BODY"} \
    "$@"
}

# --- session #2 exact-N scenarios (v2): scout and steady ---------------------
cmd_v2_scenario() {
  local scenario="$1"
  local schedule="$2"
  local tag="${3:-$scenario}"
  shift 3 2>/dev/null || shift $#

  [ -f "$schedule" ] || { echo "FATAL: no such schedule: $schedule" >&2; exit 1; }

  # Format dispatch first, for the same reason as in cmd_run.
  local scheme
  scheme="$(schedule_scheme "$schedule")"
  if [ "$scheme" != "headline-schedule-v2" ]; then
    echo "FATAL: $schedule declares scheme '$scheme', not headline-schedule-v2." >&2
    echo "The session #2 measurement path reads a frozen exact-N schedule; a legacy" >&2
    echo "v1 artifact has no warmup boundary to read. Use 'run' for those." >&2
    exit 1
  fi

  # Same fd guard as every other driving command: EMFILE would land as
  # `errored` sends and corrupt the censoring rate rather than tripping the
  # shed check.
  ulimit -n "$FD_LIMIT" 2>/dev/null || true
  local soft
  soft="$(ulimit -Sn)"
  if [ "$soft" -lt 4000 ]; then
    echo "FATAL: fd soft limit is $soft, below the concurrency cap + headroom." >&2
    echo "Refusing to drive a point that would report EMFILE failures as 'errored' sends." >&2
    exit 1
  fi

  local out_dir="$ARTIFACT_ROOT/$tag"
  mkdir -p "$out_dir"

  echo "$scenario point: schedule=$(basename "$schedule") fd_soft=$soft"
  echo "  out:      $out_dir"

  # Nothing about the workload is passed: offered RPS, warmup boundary,
  # expected N, membership and corpus identity all come from the frozen
  # schedule's own provenance -- the same source Tier B reads.
  cd "$REPO_DIR"
  py scripts/gpu_session/drive_scenario_point.py \
    --scenario "$scenario" \
    --schedule "$schedule" \
    --out-dir "$out_dir" \
    --base-url "$VLLM_URL" \
    --model "${LOADGEN_MODEL:-meta-llama/Llama-3.2-3B-Instruct}" \
    --prefix-cache-verdict "$REPO_DIR/benchmarks/runs/preflight/prefix_cache_verdict.json" \
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

# --- legacy v1 scenarios: natural-random secondary and adversarial -----------
cmd_v1_scenario() {
  local scenario="$1"
  local schedule="$2"
  local tag="${3:-$scenario}"

  [ -f "$schedule" ] || { echo "FATAL: no such schedule: $schedule" >&2; exit 1; }

  # The scenario is checked against the ARTIFACT before anything is driven.
  # `run` only distinguishes v1 from v2; this also refuses a natural-random
  # schedule handed to `adversarial` and vice versa, which `run` cannot tell
  # apart because both are v1.
  cd "$REPO_DIR"
  py scripts/gpu_session/check_scenario.py --scenario "$scenario" --schedule "$schedule"

  # Deliberately NOT via cmd_run: `run` now refuses artifacts that have a
  # named scenario, which is exactly these. The replay body is shared.
  cmd_legacy_replay "$schedule" "$tag"
}

cmd_list_artifacts() {
  find "$ARTIFACT_ROOT" -type f \( -name '*.raw_log.jsonl' -o -name '*.samples.jsonl' -o -name '*.metrics.json' \) \
    -printf '%10s  %p\n' 2>/dev/null | sort -k2 || echo "(nothing yet under $ARTIFACT_ROOT)"
}

case "${1:-}" in
  setup)          shift; cmd_setup "$@" ;;
  env-check)      shift; cmd_env_check "$@" ;;
  verify-cache)   shift; cmd_verify_cache "$@" ;;
  floor)          shift; cmd_floor "$@" ;;
  scout)          shift; cmd_v2_scenario scout "$@" ;;
  sustained-scout) shift; cmd_v2_scenario sustained-scout "$@" ;;
  steady)         shift; cmd_v2_scenario steady "$@" ;;
  secondary)      shift; cmd_v1_scenario secondary "$@" ;;
  adversarial)    shift; cmd_v1_scenario adversarial "$@" ;;
  run)            shift; cmd_run "$@" ;;
  headline)       shift; cmd_headline "$@" ;;
  list-artifacts) shift; cmd_list_artifacts "$@" ;;
  *)              usage; exit 1 ;;
esac

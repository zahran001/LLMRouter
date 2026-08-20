#!/usr/bin/env bash
#
# run_on_instance.sh -- LOCAL wrapper. Drives the loadgen ON the L4 instance
# instead of through the SSH tunnel (WEEK2_EXECUTION.md Block E,
# WEEK2_GPU_SESSION_2_PLAN.md).
#
# Why on-instance: the tunnel would fold WAN round-trip into every TTFT and
# multiplex up to 3000 concurrent streams through one TCP connection. At
# Stage A's upper points that characterizes the tunnel rather than the
# replica, and it biases the breach metric upward -- i.e. toward declaring a
# breach that is the client's. On-instance the driver talks to
# 127.0.0.1:8000 over loopback. tunnel.sh stays useful for poking /health or
# curling by hand; it is no longer the measurement path.
#
# Every ssh --command below is ONE simple command with no chaining and no
# nested quotes -- GPU_SESSION_NOTES.md records chained/quoted --command
# strings intermittently failing with exit 128 and zero output through the
# Windows gcloud -> plink chain. All the real work lives in the remote-side
# script (remote_loadgen.sh), which travels in the repo clone.
#
# Human-run, like every other script in this directory: the agent does not
# stand up, drive, or tear down the instance (WEEK2_EXECUTION.md Block E).

set -euo pipefail

INSTANCE_NAME="${INSTANCE_NAME:-llmrouter-vllm-l4-week2}"
ZONE="${ZONE:-us-central1-a}"
REPO_URL="${REPO_URL:-https://github.com/zahran001/LLMRouter.git}"
SESSION_TAG="${SESSION_TAG:-stage_a}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE_A_DIR="benchmarks/schedules/stage_a"

usage() {
  cat <<'EOF'
usage: run_on_instance.sh <command> [args]

  bootstrap          clone/fetch the repo on the instance at THIS commit, then setup
  check              run the remote env-check (deps, fd limit, GPU, vLLM health)
  verify-cache       REFUSE the session if prefix caching is live (L6) -- run
                     this BEFORE any headline point
  run <schedule>     drive one schedule, repo-relative path. The way to drive a
                     Tier A scout or a secondary point
                     (e.g. benchmarks/schedules/week2_redesign/scout/headline_r1_rps2.schedule.json)
  headline <lambda>... drive the frozen headline repeat family through the
                     drain-gated runner (session #2, R9). Repeat-major.
  stage-a            SESSION #1 ONLY -- drives the superseded fixed-duration
                     Stage A sweep. See the warning it prints.
  shell              open an interactive ssh session on the instance

env: INSTANCE_NAME ZONE REPO_URL SESSION_TAG EXTRA_BODY LOADGEN_MODEL REPEAT_IDS
EOF
}

ssh_cmd() {
  # One simple command, per GPU_SESSION_NOTES.md.
  gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" --command="$1"
}

remote_home() {
  # Discovered rather than guessed: the remote username is whatever gcloud
  # maps the local one to, and pscp will not expand ~ in remote paths
  # (GPU_SESSION_NOTES.md), so everything downstream needs this absolute.
  ssh_cmd "pwd" | tr -d '\r' | tail -1
}

require_reproducible_head() {
  # The whole point of pinning to a commit is that BASELINE.md can say which
  # code drove the sweep. A dirty tree or an unpushed HEAD breaks that, and
  # it breaks it silently -- the instance would happily clone some older
  # state and every artifact would look fine.
  if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
    echo "FATAL: working tree is dirty. Commit (or stash) before driving a metered session --" >&2
    echo "the sweep must be traceable to one commit." >&2
    git -C "$REPO_ROOT" status --short >&2
    exit 1
  fi
  local sha
  sha="$(git -C "$REPO_ROOT" rev-parse HEAD)"
  if [ -z "$(git -C "$REPO_ROOT" branch -r --contains "$sha" 2>/dev/null)" ]; then
    echo "FATAL: HEAD ($sha) is not on any remote branch. The instance clones from" >&2
    echo "$REPO_URL, so it cannot see this commit. Push first:" >&2
    echo "    git push -u origin $(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)" >&2
    exit 1
  fi
  echo "$sha"
}

cmd_bootstrap() {
  local sha home repo
  sha="$(require_reproducible_head)"
  home="$(remote_home)"
  repo="$home/LLMRouter"
  echo "pinning instance to commit $sha"

  # Each of these is one simple command. Clone is idempotent-ish: if the dir
  # exists we just fetch.
  if ssh_cmd "test -d $repo/.git" 2>/dev/null; then
    echo "repo already present, fetching..."
    ssh_cmd "git -C $repo fetch --all --tags --prune"
  else
    ssh_cmd "git clone $REPO_URL $repo"
  fi
  # Detached HEAD at the exact commit -- not a branch name, which could move
  # under the session.
  ssh_cmd "git -C $repo checkout --force $sha"
  ssh_cmd "bash $repo/scripts/gpu_session/remote_loadgen.sh setup"

  echo
  echo "bootstrap complete. Next: run_on_instance.sh check"
}

cmd_check() {
  local home
  home="$(remote_home)"
  ssh_cmd "bash $home/LLMRouter/scripts/gpu_session/remote_loadgen.sh env-check"
}

cmd_run() {
  local schedule="${1:-}"
  [ -n "$schedule" ] || { echo "usage: run_on_instance.sh run <repo-relative schedule path>" >&2; exit 1; }
  [ -f "$REPO_ROOT/$schedule" ] || { echo "FATAL: $schedule not found locally -- is it committed?" >&2; exit 1; }

  local home
  home="$(remote_home)"
  local remote_repo="$home/LLMRouter"
  # EXTRA_BODY / LOADGEN_MODEL are passed as a leading env assignment rather
  # than interpolated into the loadgen flags, keeping the --command simple.
  local env_prefix=""
  [ -n "${EXTRA_BODY:-}" ] && env_prefix="EXTRA_BODY='$EXTRA_BODY' "
  [ -n "${LOADGEN_MODEL:-}" ] && env_prefix="${env_prefix}LOADGEN_MODEL='$LOADGEN_MODEL' "

  ssh_cmd "${env_prefix}bash $remote_repo/scripts/gpu_session/remote_loadgen.sh run $remote_repo/$schedule $SESSION_TAG"
}

cmd_verify_cache() {
  local home
  home="$(remote_home)"
  ssh_cmd "bash $home/LLMRouter/scripts/gpu_session/remote_loadgen.sh verify-cache"
}

cmd_headline() {
  [ "$#" -gt 0 ] || {
    echo "usage: run_on_instance.sh headline <lambda> [lambda...]" >&2
    echo "  e.g. run_on_instance.sh headline 1.5 2 2.5" >&2
    echo "  env: REPEAT_IDS='1 2 3' (default), SESSION_TAG (default headline)" >&2
    exit 1
  }
  # Guard the same locally-checkable thing the driver guards remotely: the
  # schedules have to be committed, or the instance's clone will not have
  # them and the failure surfaces as a confusing "missing schedules" list.
  local first_missing=""
  for lam in "$@"; do
    local probe="benchmarks/schedules/week2_redesign/headline/headline_r1_rps${lam}.schedule.json"
    [ -f "$REPO_ROOT/$probe" ] || first_missing="$probe"
  done
  [ -z "$first_missing" ] || {
    echo "FATAL: $first_missing not found locally -- generate and COMMIT the headline family" >&2
    echo "first (scripts/generate_headline_schedules.py). The instance clones from git." >&2
    exit 1
  }

  local home
  home="$(remote_home)"
  local tag="${SESSION_TAG:-headline}"
  # REPEAT_IDS travels as an env assignment rather than an interpolated flag,
  # keeping the --command one simple string (GPU_SESSION_NOTES.md).
  local env_prefix=""
  [ -n "${REPEAT_IDS:-}" ] && env_prefix="REPEAT_IDS='$REPEAT_IDS' "
  [ -n "${EXTRA_BODY:-}" ] && env_prefix="${env_prefix}EXTRA_BODY='$EXTRA_BODY' "
  [ -n "${LOADGEN_MODEL:-}" ] && env_prefix="${env_prefix}LOADGEN_MODEL='$LOADGEN_MODEL' "

  echo "Headline family: lambdas [$*], repeats [${REPEAT_IDS:-1 2 3}], tag '$tag'."
  echo "Repeat-major ordering, drain-gated between every point. The driver refuses to"
  echo "start unless the prefix-cache verdict says DISABLED -- run 'verify-cache' first."
  echo
  ssh_cmd "${env_prefix}bash $home/LLMRouter/scripts/gpu_session/remote_loadgen.sh headline $tag $*"

  echo
  echo "Pull the artifacts BEFORE teardown:"
  echo "    SESSION_TAG=$tag bash scripts/gpu_session/pull_artifacts.sh"
}

cmd_stage_a() {
  # SESSION #1 ONLY. The fixed-duration Stage A design this drives was
  # superseded on 2026-08-19 (WEEK2_PLAN.md 10.1/10.2): a fixed 120s window
  # makes request count a function of lambda, so each point realizes a
  # different prompt tail -- the confound that cost the first session its
  # breach number. Kept because those schedules are still the historical
  # workload for replaying session #1, not because it is the way to run
  # session #2.
  cat >&2 <<'WARN'
WARNING: `stage-a` drives the SUPERSEDED fixed-duration Stage A sweep.

  Session #2's headline curve uses the exact-N canonical family instead:
      run_on_instance.sh verify-cache
      run_on_instance.sh headline 1.5 2 2.5

  Continue only if you are deliberately replaying session #1's workload.
WARN
  read -r -p "Type 'replay-session-1' to continue: " confirm
  [ "$confirm" = "replay-session-1" ] || { echo "aborted." >&2; exit 1; }

  # Ascending RPS deliberately: the low anchor characterizes the unloaded
  # TTFT floor before any queueing exists (WEEK2_PLAN.md 2.6), and if the
  # session dies partway the points you kept are the cheap informative ones.
  local rps_points=(2 5 10 20 30 40 60 80)
  echo "Stage A: ${#rps_points[@]} points, ascending. Each writes durably as it goes;"
  echo "read the [point] line after each one -- Hard Stop 5 is bracketing, not completeness."
  echo
  for rps in "${rps_points[@]}"; do
    local schedule="$STAGE_A_DIR/poisson_rps${rps}.schedule.json"
    echo "=================== Stage A point: ${rps} RPS ==================="
    cmd_run "$schedule"
    echo
  done
  echo "Stage A sweep issued. Pull the artifacts BEFORE teardown:"
  echo "    bash scripts/gpu_session/pull_artifacts.sh"
  echo "then tear down with the Week 2 wrapper (never bare scripts/teardown.sh):"
  echo "    bash scripts/gpu_session/teardown_week2.sh"
}

cmd_shell() {
  gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE"
}

case "${1:-}" in
  bootstrap)    shift; cmd_bootstrap "$@" ;;
  check)        shift; cmd_check "$@" ;;
  verify-cache) shift; cmd_verify_cache "$@" ;;
  run)          shift; cmd_run "$@" ;;
  headline)     shift; cmd_headline "$@" ;;
  stage-a)      shift; cmd_stage_a "$@" ;;
  shell)        shift; cmd_shell "$@" ;;
  *)            usage; exit 1 ;;
esac

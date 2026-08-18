#!/usr/bin/env bash
#
# teardown_week2.sh -- the ONLY teardown path a Week 2 runbook step should
# invoke. LOCAL, human-run.
#
# WHY THIS WRAPPER EXISTS (WEEK2_PLAN.md 6.1, docs/WEEK2_PRE_GPU_AUDIT.md B1):
# scripts/teardown.sh is a generic deletion primitive shared with Week 1, and
# its default INSTANCE_NAME is Week 1's `llmrouter-vllm-l4`. Week 2 creates
# `llmrouter-vllm-l4-week2` (create_instance.sh, deliberately distinct). Run
# bare, the generic script therefore describes an instance that does not
# exist, prints "nothing to tear down" and exits 0 -- while the Week 2 L4
# keeps billing. That is verbatim the failure mode 6.1 names: "A silent no-op
# teardown is how a forgotten L4 runs all weekend."
#
# This wrapper owns the Week 2 target so no call site has to remember an env
# prefix, and it VERIFIES the deletion afterwards: 6.4 requires confirming the
# instance is actually gone, not trusting the delete command's exit code.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# What create_instance.sh ACTUALLY created, if it left a record. This closes
# the zone axis of the very bug this wrapper exists for: owning the instance
# NAME is not enough if a capacity stockout moves the session to another zone
# (hit for real 2026-08-18 -- us-central1-a had no g2-standard-8+L4). Teardown
# pointed at the wrong zone prints "nothing to tear down" and exits 0 while the
# meter runs.
SESSION_FILE="${SESSION_FILE:-$REPO_ROOT/.gpu_session_target}"
if [ -f "$SESSION_FILE" ]; then
  # The recorded names are deliberately SESSION_-prefixed: sourcing this must
  # not be able to clobber an explicit INSTANCE_NAME=/ZONE= the operator typed.
  # shellcheck disable=SC1090
  . "$SESSION_FILE"
fi

# Week 2's target, owned here. Precedence, most specific first:
#   explicit env  >  what was actually created  >  the Week 2 default.
INSTANCE_NAME="${INSTANCE_NAME:-${SESSION_INSTANCE_NAME:-llmrouter-vllm-l4-week2}}"
ZONE="${ZONE:-${SESSION_ZONE:-us-central1-a}}"

exists() {
  gcloud compute instances describe "$INSTANCE_NAME" --zone="$ZONE" &>/dev/null
}

echo "=== Week 2 teardown ==="
echo "  instance: $INSTANCE_NAME"
echo "  zone:     $ZONE"
echo "  project:  $(gcloud config get-value project 2>/dev/null || echo '<unset>')"
echo

if [ "${DRY_RUN:-0}" = "1" ]; then
  # Resolution check only -- proves this wrapper targets the right thing
  # without touching anything. Used by the pre-flight evidence step.
  if exists; then
    echo "DRY RUN: instance '$INSTANCE_NAME' EXISTS in '$ZONE' and WOULD be deleted."
  else
    echo "DRY RUN: no instance named '$INSTANCE_NAME' in zone '$ZONE' -- nothing would be deleted."
  fi
  exit 0
fi

# Delegate the actual deletion to the generic primitive, with the Week 2
# target passed explicitly. The primitive stays generic; this wrapper is the
# only thing that knows Week 2's name.
INSTANCE_NAME="$INSTANCE_NAME" ZONE="$ZONE" bash "$REPO_ROOT/scripts/teardown.sh"

# 6.4: "Verify the instance is actually deleted -- do not trust the script's
# exit code alone." Deletion is asynchronous enough that an immediate describe
# can still succeed, so poll briefly rather than checking once.
echo
echo "=== verifying deletion (not trusting the delete's exit code) ==="
for attempt in $(seq 1 12); do
  if ! exists; then
    echo "VERIFIED: '$INSTANCE_NAME' no longer exists in '$ZONE'. Meter stopped."
    # The session record described a live instance; it no longer does. Leaving
    # it would point a later teardown at an instance that is already gone.
    rm -f "$SESSION_FILE"
    echo "Console cross-check (6.4 asks for a human eyeball too):"
    echo "  https://console.cloud.google.com/compute/instances?project=$(gcloud config get-value project 2>/dev/null)"
    exit 0
  fi
  echo "  attempt $attempt/12: still present, waiting 5s..."
  sleep 5
done

echo >&2
echo "FATAL: '$INSTANCE_NAME' STILL EXISTS in '$ZONE' after the delete completed." >&2
echo "The meter may still be running. Delete it by hand NOW and check the console:" >&2
echo "  gcloud compute instances delete $INSTANCE_NAME --zone=$ZONE" >&2
exit 1

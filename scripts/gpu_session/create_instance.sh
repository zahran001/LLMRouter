#!/usr/bin/env bash
#
# create_instance.sh -- stand up the Week 2 GPU instance (WEEK2_PLAN.md §6,
# WEEK2_EXECUTION.md Block E). Human-run only -- the agent does not stand up,
# drive, or tear down this instance (WEEK2_EXECUTION.md Block E preamble).
#
# Recipe confirmed working in the Week 1 faithfulness check
# (docs/GPU_SESSION_NOTES.md): common-cuXXX DLVM image (drivers preinstalled,
# no docker/pip), gN-standard-* machine type bundles the L4.

set -euo pipefail

INSTANCE_NAME="${INSTANCE_NAME:-llmrouter-vllm-l4-week2}"
ZONE="${ZONE:-us-central1-a}"
MACHINE_TYPE="${MACHINE_TYPE:-g2-standard-8}"
IMAGE_FAMILY="${IMAGE_FAMILY:-common-cu129-ubuntu-2204-nvidia-580}"
IMAGE_PROJECT="${IMAGE_PROJECT:-deeplearning-platform-release}"

# WEEK2_PLAN.md 6.2 step 1 and WEEK2_EXECUTION.md Block E both specify
# "1x L4 SPOT". Requested explicitly rather than left to the default, which
# is on-demand at roughly 2-3x the price -- the runbook said spot, so the
# script must actually ask for spot (docs/WEEK2_PRE_GPU_AUDIT.md S8).
#
# --provisioning-model=SPOT requires a non-MIGRATE maintenance policy, and a
# GPU instance cannot live-migrate anyway, so TERMINATE is both mandatory
# here and correct. --no-restart-on-failure keeps a preempted instance from
# silently coming back and restarting the meter unattended.
PROVISIONING_MODEL="${PROVISIONING_MODEL:-SPOT}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "Creating $INSTANCE_NAME in $ZONE"
echo "  machine:      $MACHINE_TYPE"
echo "  image:        $IMAGE_PROJECT/$IMAGE_FAMILY"
echo "  provisioning: $PROVISIONING_MODEL"
echo
gcloud compute instances create "$INSTANCE_NAME" \
  --zone="$ZONE" \
  --machine-type="$MACHINE_TYPE" \
  --image-family="$IMAGE_FAMILY" \
  --image-project="$IMAGE_PROJECT" \
  --provisioning-model="$PROVISIONING_MODEL" \
  --maintenance-policy=TERMINATE \
  --no-restart-on-failure

# Read the resolved model back from the API rather than trusting the flag
# went through: a silently on-demand L4 is a budget finding, and spot
# capacity can be refused.
echo
echo "=== resolved provisioning (read back, not assumed) ==="
gcloud compute instances describe "$INSTANCE_NAME" --zone="$ZONE" \
  --format="value(scheduling.provisioningModel,scheduling.preemptible,scheduling.onHostMaintenance,status)"

# Record what was ACTUALLY created, so teardown cannot target the wrong thing.
# The wrapper's defaults are only correct while a session lands in the default
# ZONE -- and a single-zone capacity stockout is routine, hit for real on
# 2026-08-18 when us-central1-a had no g2-standard-8+L4 to give. The moment a
# session moves to -b or -c, a default teardown describes an instance that does
# not exist, prints "nothing to tear down" and exits 0 while the L4 keeps
# billing. That is WEEK2_PLAN.md 6.1's money leak with the instance NAME fixed
# and the ZONE still open.
#
# Gitignored on purpose: this is local session state, and `run_on_instance.sh
# bootstrap` refuses a dirty tree, so creating an instance must not dirty it.
SESSION_FILE="${SESSION_FILE:-$REPO_ROOT/.gpu_session_target}"
cat > "$SESSION_FILE" <<SESSION_EOF
# Written by create_instance.sh; read by teardown_week2.sh. Local session
# state, not evidence -- safe to delete once the instance is gone.
SESSION_INSTANCE_NAME=$INSTANCE_NAME
SESSION_ZONE=$ZONE
SESSION_CREATED_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
SESSION_EOF
echo
echo "session target recorded -> $SESSION_FILE"
echo "  teardown_week2.sh will read this, so it targets $INSTANCE_NAME in $ZONE"
echo "  even though its built-in default zone is us-central1-a."

echo
echo "Instance created. Next: scripts/gpu_session/setup_and_launch_vllm.sh (scp + ssh --command)."
echo "Distinct name from Week 1's (llmrouter-vllm-l4); tear down with"
echo "scripts/gpu_session/teardown_week2.sh, never bare scripts/teardown.sh."
echo
echo "SPOT NOTE: a spot L4 can be preempted mid-sweep. Every point writes durably as it"
echo "completes (6.3), so a preemption costs the in-flight point, not the whole sweep."

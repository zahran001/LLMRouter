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

echo
echo "Instance created. Next: scripts/gpu_session/setup_and_launch_vllm.sh (scp + ssh --command)."
echo "Distinct name from Week 1's (llmrouter-vllm-l4); tear down with"
echo "scripts/gpu_session/teardown_week2.sh, never bare scripts/teardown.sh."
echo
echo "SPOT NOTE: a spot L4 can be preempted mid-sweep. Every point writes durably as it"
echo "completes (6.3), so a preemption costs the in-flight point, not the whole sweep."

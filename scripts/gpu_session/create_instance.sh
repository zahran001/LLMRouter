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

echo "Creating $INSTANCE_NAME in $ZONE ($MACHINE_TYPE, image $IMAGE_PROJECT/$IMAGE_FAMILY)..."
gcloud compute instances create "$INSTANCE_NAME" \
  --zone="$ZONE" \
  --machine-type="$MACHINE_TYPE" \
  --image-family="$IMAGE_FAMILY" \
  --image-project="$IMAGE_PROJECT"

echo
echo "Instance created. Next: scripts/gpu_session/setup_and_launch_vllm.sh (scp + ssh --command)."
echo "Distinct name from Week 1's (llmrouter-vllm-l4) so teardown.sh can't ever target the wrong session."

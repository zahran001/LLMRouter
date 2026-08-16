#!/usr/bin/env bash
#
# teardown.sh
#
# Deletes the benchmark GPU instance so nothing keeps billing after a
# session. Run this immediately after the golden fixture is captured.

set -euo pipefail

INSTANCE_NAME="${INSTANCE_NAME:-llmrouter-vllm-l4}"
ZONE="${ZONE:-us-central1-a}"

if ! gcloud compute instances describe "$INSTANCE_NAME" --zone="$ZONE" &>/dev/null; then
  echo "No instance named '$INSTANCE_NAME' in zone '$ZONE' — nothing to tear down."
  exit 0
fi

echo "Deleting instance '$INSTANCE_NAME' in zone '$ZONE'..."
gcloud compute instances delete "$INSTANCE_NAME" --zone="$ZONE" --quiet

echo "Delete requested. Verify in the console that it's gone:"
echo "  https://console.cloud.google.com/compute/instances?project=$(gcloud config get-value project 2>/dev/null)"

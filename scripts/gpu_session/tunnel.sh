#!/usr/bin/env bash
#
# tunnel.sh -- SSH tunnel to the vLLM port, so the loadgen (and router) can
# reach it at http://127.0.0.1:8000 without opening a firewall rule
# (docs/GPU_SESSION_NOTES.md: nothing to remember to clean up, dead the
# moment this process exits). Run in its own terminal; leave it running for
# the duration of the session.
#
# --ssh-flag (not the documented `--` passthrough) is required on Windows --
# gcloud's batch wrapper doesn't reliably pass `--` through to plink.

set -euo pipefail

INSTANCE_NAME="${INSTANCE_NAME:-llmrouter-vllm-l4-week2}"
ZONE="${ZONE:-us-central1-a}"
PORT="${PORT:-8000}"

gcloud compute ssh "$INSTANCE_NAME" \
  --zone="$ZONE" \
  --ssh-flag="-L ${PORT}:localhost:${PORT}" \
  --ssh-flag="-N"

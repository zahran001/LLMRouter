#!/bin/bash
#
# setup_and_launch_vllm.sh -- REMOTE script. scp this to the instance, then
# run it via `gcloud compute ssh INSTANCE --command="bash setup_and_launch_vllm.sh"`
# (docs/GPU_SESSION_NOTES.md: keep --command to one simple command; do the
# real work in a scripted file instead of a complex inline string).
#
# Encodes the three flashinfer workarounds hit during the Week 1
# faithfulness check (docs/GPU_SESSION_NOTES.md, "vLLM 0.27.1 + this
# environment: three real crashes"). All three are almost certainly still
# needed -- confirmed by a quick check at session start (see below) before
# assuming otherwise.
#
# EAGER MODE is a knob -- see ENFORCE_EAGER below. --enforce-eager is the
# PROVEN-working config from Week 1, but Week 1's own note flags it as "the
# right setting for a single-request faithfulness check, not a perf run":
# it disables CUDA graph capture, which a sustained-load measurement wants
# back. WEEK2_GPU_IMPLEMENTATION_README.md 3.2 therefore attempts non-eager
# FIRST and forbids an automatic fallback -- a non-eager failure is evidence
# to surface, not something to paper over.
#
# The knob exists so that fallback is an env var rather than an edit. Editing
# a script mid-session would dirty the tree and then block `run_on_instance.sh
# bootstrap`, which refuses a dirty or unpushed HEAD -- i.e. the recovery path
# would otherwise have cost a new benchmark revision on the meter.

set -euo pipefail

MODEL="${MODEL:-meta-llama/Llama-3.2-3B-Instruct}"
PORT="${PORT:-8000}"
# Longest pinned corpus prompt is 44445 chars (corpus/baseline_prompts.provenance.json).
# char->token estimate uses 3 chars/token (conservative -- lower than the
# ~4 chars/token English-text rule of thumb, so this errs toward MORE
# estimated tokens, not fewer) => ceil(44445/3) = 14815 prompt tokens.
# Add headroom for output tokens (not yet locked -- placeholder 512) plus a
# ~15% safety margin on the char->token heuristic itself (WEEK2_PLAN.md
# §3.4: prompt_len is char count for now, token count is a Week 3 revisit --
# this is a deliberately conservative stand-in, not a real tokenizer count).
# (14815 + 512) * 1.15 ~= 17626 -> rounded up to a clean value.
MAX_MODEL_LEN="${MAX_MODEL_LEN:-20000}"

if [ ! -d ~/vllm-env ]; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-pip python3-venv
  python3 -m venv ~/vllm-env
fi

~/vllm-env/bin/pip install -q -U vllm

# Workaround 2 (GPU_SESSION_NOTES.md item 2): uninstall the broken package
# outright rather than rely on --enforce-eager alone to avoid every import path.
~/vllm-env/bin/pip uninstall -y flashinfer flashinfer-python || true

# 1 (default) = --enforce-eager, Week 1's proven config and the fallback.
# 0 = the README 3.2 first attempt, CUDA graph capture left on.
# Defaulting to 1 keeps the known-good path the one you get by accident.
ENFORCE_EAGER="${ENFORCE_EAGER:-1}"
eager_flag=()
if [ "$ENFORCE_EAGER" = "1" ]; then
  eager_flag=(--enforce-eager)
fi

# Echo the RESOLVED mode, not the requested one: every benchmark point in a
# Week 2 baseline has to run the same mode, and this line is the record of
# which one this server actually came up in.
echo "Launching vLLM: model=$MODEL max_model_len=$MAX_MODEL_LEN port=$PORT enforce_eager=$ENFORCE_EAGER"
VLLM_USE_FLASHINFER_SAMPLER=0 ~/vllm-env/bin/vllm serve "$MODEL" \
  --port "$PORT" \
  "${eager_flag[@]}" \
  --max-model-len "$MAX_MODEL_LEN"

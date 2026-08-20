#!/bin/bash
#
# setup_and_launch_vllm.sh -- REMOTE script. scp this to the instance, then
# run it via `gcloud compute ssh INSTANCE --command="bash setup_and_launch_vllm.sh"`
# (GPU_SESSION_NOTES.md: keep --command to one simple command; do the
# real work in a scripted file instead of a complex inline string).
#
# Encodes the three flashinfer workarounds hit during the Week 1
# faithfulness check (GPU_SESSION_NOTES.md, "vLLM 0.27.1 + this
# environment: three real crashes"). All three are almost certainly still
# needed -- confirmed by a quick check at session start (see below) before
# assuming otherwise.
#
# EAGER MODE is a knob -- see ENFORCE_EAGER below. --enforce-eager is the
# PROVEN-working config from Week 1, but Week 1's own note flags it as "the
# right setting for a single-request faithfulness check, not a perf run":
# it disables CUDA graph capture, which a sustained-load measurement wants
# back. Session #1's runbook 3.2 therefore attempted non-eager
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
# 20000 is now backed by an EXACT tokenizer measurement over the frozen
# canonical workload, not the char->token estimate this line used to carry
# (benchmarks/workloads/week2_headline/tokenizer_capacity_report.json,
# R4 README R4B):
#
#   max input   10,482 tokens  (prompt_id 790, 44,445 chars, chars/token 4.25)
#   + output       512 tokens  (locked policy)
#   + margin     1,099 tokens  (10%, floor 512)
#   = required  12,093 tokens   <=  20000   PASS
#
# The old estimate assumed 3 chars/token uniformly and happened to be safe.
# It needed replacing because the canonical construction GUARANTEES the
# corpus's longest prompts appear at every point of every repeat -- in the
# first session that prompt was never drawn at all.
MAX_MODEL_LEN="${MAX_MODEL_LEN:-20000}"

# --- Prefix caching: OFF for the controlled headline (R4 README L6) ---------
#
# vLLM enables prefix caching by default, and the first session inherited that
# without ever deciding it. Exact prompt replay is the experimental control
# the redesign introduces, so a cache that recognizes those replays changes
# the very cost being controlled -- and does it as a function of run order,
# making later points and later repeats systematically cheaper. Measured on
# the first session's own data: a 14,960-char prompt cost 523.3ms cold and
# 103.9ms on a warm replay.
#
# 1 (default) = --no-enable-prefix-caching, the controlled headline config.
# 0 = leave vLLM's default on. ONLY for a deliberate, declared configuration
#     experiment -- never for a headline or Week 4+ routing comparison.
DISABLE_PREFIX_CACHING="${DISABLE_PREFIX_CACHING:-1}"
prefix_cache_flag=()
if [ "$DISABLE_PREFIX_CACHING" = "1" ]; then
  prefix_cache_flag=(--no-enable-prefix-caching)
fi

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
echo "Launching vLLM: model=$MODEL max_model_len=$MAX_MODEL_LEN port=$PORT" \
     "enforce_eager=$ENFORCE_EAGER disable_prefix_caching=$DISABLE_PREFIX_CACHING"
echo
echo "The CLI flag is NOT the evidence. Before driving any headline point, run:"
echo "    python scripts/gpu_session/verify_prefix_cache_disabled.py"
echo "which probes the EFFECTIVE runtime behaviour and refuses the run if caching is live."
echo
VLLM_USE_FLASHINFER_SAMPLER=0 ~/vllm-env/bin/vllm serve "$MODEL" \
  --port "$PORT" \
  "${eager_flag[@]}" \
  "${prefix_cache_flag[@]}" \
  --max-model-len "$MAX_MODEL_LEN"

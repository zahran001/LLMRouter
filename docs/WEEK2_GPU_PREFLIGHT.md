# Week 2 GPU Session Pre-Flight (Hard Stop 4)

Evidence checklist for `WEEK2_EXECUTION.md` Hard Stop 4, ahead of the real
$150-budget GPU session (Block E, human-run only). Mirrors `WEEK2_PLAN.md`
§6.1's pre-flight list. Every item below either has evidence attached or is
explicitly flagged for your confirmation — nothing here was self-certified
past what I can actually verify.

---

## 1. §4 hard gate — all five mock validations green, controls confirmed biting

Re-affirms Hard Stop 2. Status: **confirmed** (2026-08-16 review, `ec1063f`
+ carry-forwards recorded `a0c4b97`). `pytest tests/loadgen -v` — 23/23
green (19 original + 4 replay, `c5813c9`), stable across repeated runs.

## 2. Quota + billing

Checked directly via `gcloud` just now, not assumed from Block 0:

```
$ gcloud compute regions describe us-central1 --format=json | jq '.quotas[] | select(.metric | contains("L4"))'
{'limit': 1.0, 'metric': 'NVIDIA_L4_GPUS', 'usage': 0.0}
{'limit': 1.0, 'metric': 'PREEMPTIBLE_NVIDIA_L4_GPUS', 'usage': 0.0}
{'limit': 1.0, 'metric': 'COMMITTED_NVIDIA_L4_GPUS', 'usage': 0.0}

$ gcloud compute project-info describe --format=json | jq '.quotas[] | select(.metric == "GPUS_ALL_REGIONS")'
{'limit': 1.0, 'metric': 'GPUS_ALL_REGIONS', 'usage': 0.0}

$ gcloud billing projects describe <project> --format="value(billingEnabled,billingAccountName)"
True	billingAccounts/<REDACTED>
```

1 L4 quota live in `us-central1`, project-wide `GPUS_ALL_REGIONS` quota
also 1 (both currently unused — 0 in flight), billing enabled, same account
Block 0's e2 VM ran on.

**Budget alerts ($50/$100/$150) — could not verify, needs your
confirmation.** The Billing Budget API isn't enabled on this project, so
`gcloud billing budgets list` can't see existing alerts (or their absence).
I did not enable that API or create any budget myself — that's an account-
level financial setting, yours to configure, not something to do
unilaterally on your behalf.

## 3. Launch staged

`scripts/gpu_session/`:
- `create_instance.sh` — `g2-standard-8`, `common-cu129-ubuntu-2204-nvidia-580`
  (`deeplearning-platform-release`), instance name defaults to
  `llmrouter-vllm-l4-week2` (deliberately distinct from Week 1's
  `llmrouter-vllm-l4`, so teardown can never target the wrong instance).
- `setup_and_launch_vllm.sh` — remote script (scp + `ssh --command="bash ..."`,
  per `docs/GPU_SESSION_NOTES.md`'s guidance against complex inline
  `--command` strings). Encodes all three flashinfer workarounds from the
  Week 1 faithfulness check (uninstall `flashinfer`/`flashinfer-python`,
  `VLLM_USE_FLASHINFER_SAMPLER=0`, `--enforce-eager`).
- `tunnel.sh` — SSH port-forward, `--ssh-flag` (not `--`, which doesn't
  reliably pass through gcloud's Windows batch wrapper).

**Open item, staged not decided:** `--enforce-eager` is kept because it's
the Week 1 *proven*-working config, but Week 1's own note flags it as right
for a single-request faithfulness check, not necessarily a perf run
(disables CUDA graph capture). Try without it first at session start if you
want that perf back; the script's default is the safe fallback if it
crashes the same way Week 1's did. This is exactly what Block E step 2
("confirm config-only swap holds... any required code change is a finding,
STOP") is for — not something to resolve here.

## 4. `--max-model-len` sizing

**Staged value: 20000.** Computation (`scripts/gpu_session/setup_and_launch_vllm.sh`
header comment has the same math):
- Longest pinned corpus prompt: 44445 chars (`corpus/baseline_prompts.provenance.json`).
- char→token estimate: 3 chars/token (deliberately conservative — below the
  ~4 chars/token English-text rule of thumb, so this overestimates tokens
  rather than under). `ceil(44445/3) = 14815`.
- `+512` placeholder output-token headroom (the real output-token count for
  the Stage A/B sweep isn't locked yet either) `= 15327`.
- `×1.15` margin on the char-based heuristic itself (per WEEK2_PLAN.md §3.4,
  `prompt_len` is char count for now — token count is a Week 3 revisit, so
  this whole estimate is a stand-in, not a real tokenizer count)
  `≈ 17626` → rounded up to **20000**.

KV-cache sanity check: at ~112KB/token (backed out from
`docs/GPU_SESSION_NOTES.md`'s observed ~14.0GiB at `max_model_len=131072`),
20000 tokens ≈ 2.2GB KV cache — comfortable alongside a ~6GB (fp16) 3B model
on a 24GB L4. This is a **per-sequence** limit, not a concurrency budget —
total KV-cache VRAM needed under real sustained concurrent load is a
separate question tied to the concurrency-cap value Hard Stop 3 deferred
until Stage A's real RPS range is known. Not blocking (vLLM queues rather
than crashes when it runs low on KV blocks), but worth watching for
unexpected queuing/timeouts at Hard Stop 5 if the sweep pushes high
concurrency.

## 5. Teardown staged, dry-run verified

```
$ INSTANCE_NAME=llmrouter-vllm-l4-week2 ZONE=us-central1-a bash scripts/teardown.sh
No instance named 'llmrouter-vllm-l4-week2' in zone 'us-central1-a' — nothing to tear down.
```

Confirms `teardown.sh` (unchanged from Week 1, already parameterized via
env vars) correctly targets the Week 2 instance name/zone and exits clean
when nothing exists yet — exactly the state before Block E starts.

## 6. Stage A schedules pre-generated and committed

`scripts/generate_stage_a_schedules.py` → `benchmarks/schedules/stage_a/`
(committed `b4a43d1`): 8 Poisson schedules, RPS = [2, 5, 10,
20, 30, 40, 60, 80] (§6.2's example anchor + wide-step points), one
continuous `duration_s=130s` each (`WARMUP_N_PLACEHOLDER=10s` — [CALIBRATE],
deferred to Block F per Hard Stop 3 — `+ Y=120s`, confirmed Hard Stop 3),
all drawing from the **same** `BASELINE_SEED=20260817` per §2.2's
"every RPS point draws from the same seeded ShareGPT sample" requirement
(holds the prompt-length contribution constant across the sweep — only
offered RPS moves).

**Note on the deferred warmup N:** if Block F's real GPU-derived N differs
from the 10s placeholder, these schedules do not need regenerating — the
warmup filter discards by timestamp on the metrics side (§2.4), not by
truncating the schedule. Only if the real N turns out *larger* than the
schedule can absorb without shrinking the post-warmup window below Y=120s
would regeneration be needed — worth a quick sanity check once Block F
resolves N, not expected to bite at these placeholder magnitudes.

---

## Summary

| Item | Status |
|---|---|
| §4 gate (Hard Stop 2) | ✅ confirmed |
| L4/GPUS_ALL_REGIONS quota | ✅ verified live, 0 in use |
| Billing enabled | ✅ verified |
| Budget alerts | ⚠️ **needs your confirmation** — could not verify |
| Launch staged | ✅ `scripts/gpu_session/*.sh` |
| `--enforce-eager` on/off | ⚠️ **your call at session start** — staged safe default |
| `--max-model-len` | ✅ computed (20000), your confirmation welcome |
| Teardown dry-run | ✅ verified against Week 2 instance name |
| Stage A schedules | ✅ generated, committing now |

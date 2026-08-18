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

**Budget alerts — verified 2026-08-17** (you enabled the Billing Budget API;
re-checked directly, not taken on trust):

```
$ gcloud billing budgets list --billing-account=<REDACTED>
warn-at-150   $150   thresholds 0.5 / 0.9 / 1.0 CURRENT_SPEND   projects/<REDACTED>
Warn-at-10    $10    thresholds 0.5 / 0.9 / 1.0 CURRENT_SPEND   (all projects)
```

`warn-at-150`'s project filter matches this project's number, confirmed
against `gcloud projects describe`. Account and project identifiers are
redacted here deliberately — this is a public repo, and the evidence a
reviewer needs is *that* the check was run and what it returned, not which
account it was run against. Re-run the two commands above to see the live
values.

Three things to know about what these actually give you, none of them
blocking:

1. **The thresholds are $75 / $135 / $150, not the $50 / $100 / $150 §6.1
   named.** Same shape — escalating warnings with the hard line at $150 —
   and the $150 stop is exactly covered. Recording the difference rather
   than calling the item green against a number it doesn't match; your call
   whether to adjust.
2. **The $10 budget is the one that will actually fire.** A g2-standard-8 +
   L4 spot runs roughly $0.40–0.50/hr, so a single session lands in the
   $5–15 range and `warn-at-150`'s first threshold ($75) is unlikely to be
   reached at all. `Warn-at-10`'s $5 threshold is the real "the meter is
   running" signal.
3. **Both are `MONTH` period against calendar-month spend**, so August's
   earlier Block 0 e2 VM spend already counts toward them, and **alerts are
   email-only and lag** (GCP budget evaluation is not real-time).
   `notificationsRule` is empty on both, meaning default IAM recipients —
   billing admins/users on the account — get the email. **These are a
   tripwire, not a stop:** nothing here halts an instance. Verified teardown
   (§5) remains the actual control.

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
  reliably pass through gcloud's Windows batch wrapper). **No longer the
  measurement path** — the loadgen drives on-instance over loopback (§9).
  Kept for hand-checking `/health` and one-off curls.

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

## 6. TTFT actually reaches disk (added 2026-08-17 — was a hard blocker)

**This item was not on §6.1's list and should have been.** Found while
re-checking Block E readiness: the loadgen captured per-request TTFT/TPOT
into an in-memory dict (`OpenLoopScheduler._samples`) and
`loadgen/_cli.py:run_and_report` printed a summary of counts and scheduling
lag without it. The samples were never serialized. The raw log cannot
stand in — `close_time` bounds the whole stream, and §3.1's six fields
contain no first-token time.

Consequence had this gone unfixed: every Stage A point would have burned
GPU time and produced a durable log with **no TTFT in it**. Hard Stop 5
("is the breach bracketed — one point clearly <500ms p99 TTFT, one clearly
over") would have been unanswerable on the meter, and Block F would have
had nothing to compute the baseline number from. It would not have failed
loudly; each point would have looked like a clean run.

**Fix (this commit).** Three durable artifacts per point, not one:

- `<tag>.raw_log.jsonl` — unchanged, §3.1's locked 6 fields.
- `<tag>.samples.jsonl` — new sidecar, one row per *issued* request:
  `request_id`, `send_time` (same t_start-relative basis as the raw log),
  `ttft_ms`, `tpot_samples_ms`, `content_chunk_count`, `error`. Written
  the instant the sample exists, inside the request handler — §6.3's
  durable-on-produce rule, applied within a point.
- `<tag>.metrics.json` — the point record, written when the window closes:
  p50/p95/p99 TTFT+TPOT, achieved RPS, the §2.5 divergence gate, the §2.4
  tail-validity gate, and the §2.6 breach verdict.

A **separate file** rather than extra raw-log columns, deliberately: §3.1's
schema is locked, and §6.3 needs per-request TTFT-vs-wall-clock data it
cannot carry. The two join on `request_id` offline.

The point record is computed by reading the two files back
(`metrics/point.py:point_metrics`), so the live on-meter number and Block
F's offline recompute (`scripts/compute_point_metrics.py`) are the same
function over the same bytes — verified: recomputing an end-to-end mock run
at the same N reproduced the live record with zero differing fields.

**Two things this closes that were otherwise open:**
- Hard Stop 5 is now readable live — each point prints
  `p99 TTFT=…ms (BREACH|under 500ms)` to stderr as its window closes.
- The deferred warmup N is a pure offline re-derivation: the filter is
  metrics-side and time-based (§2.4), so Block F's real N means re-running
  `scripts/compute_point_metrics.py --warmup-n <N>` over the committed
  sidecars. **No GPU re-run.** Verified by recomputing the same run at a
  different N and watching the window, achieved RPS and p99 all move.

**The wording conflict this surfaced — now closed.** Block F used to say
"compute per-point p50/p95/p99 TTFT + TPOT **from the raw logs**", which
§3.1's locked 6-field schema cannot support; surfaced at the time rather
than silently reconciled (`WEEK2_EXECUTION.md:13`). Resolved on your call
(2026-08-17) in the direction that leaves the lock intact: §3.1 now carries
a **companion sidecar** bullet stating the six fields are complete and
closed as written and the sidecar sits beside them — including *why* the
raw log alone cannot carry TTFT, so a fresh-context read finds the reason
instead of re-flagging the contradiction. Block F now reads "from the raw
log + samples sidecar."

**Tests:** `tests/loadgen/test_sample_persistence.py`, 12 cases. Controls
confirmed to bite, not just to pass:
- dropped sample-write → sidecar reconciliation goes RED (`missing=`);
- flush removed from the writer → the durable-on-produce test goes RED
  ("still empty 2s into a 3s run"), then green again when restored;
- warmup filter fed a 9000ms pre-warmup transient → p99 stays at 100ms
  with the filter, jumps above 1000ms without it.

These are my reds, produced on demand. **Hard Stop 2's standard says you
confirm them personally** — `pytest tests/loadgen/test_sample_persistence.py`
is green (35/35 for the full loadgen suite), but the reds are the proof.

**One operational note:** `benchmarks/runs/` is gitignored. If the session's
sidecars are to be reproducible evidence for `BASELINE.md`, they need
force-adding like the Stage A schedules were.

## 7. Stage A schedules pre-generated and committed

`scripts/generate_stage_a_schedules.py` → `benchmarks/schedules/stage_a/`
(committed `4d381fe`): 8 Poisson schedules, RPS = [2, 5, 10,
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

## 8. Concurrency cap = 3000, and the one precondition it carries

Resolved 2026-08-17, closing the Hard Stop 3 deferral. Constant:
`loadgen/_cli.py: BASELINE_CONCURRENCY_CAP`, now the `--concurrency-cap`
default rather than a required flag — eight hand-run Stage A points should
not be able to disagree with each other by a typo, and every point record
still logs the cap it actually ran with (`provenance.concurrency_cap`).

Why 3000 clears the bar (full provenance in `WEEK2_PLAN.md` §3.3): it is
above **every** concurrency level Block C's uncapped sweep produced — peak
2380 simultaneous open streams at 300 offered RPS, 651 at 100 RPS, the
closest comparable rate to Stage A's 80 RPS ceiling. Equivalently, at 80 RPS
the cap cannot bite until *mean* end-to-end response time exceeds 37.5s,
which is far past the point where a 500ms p99 TTFT breach is still an
interesting measurement.

**Verify per point rather than assuming.** §3.3's requirement is that the
cap never sheds within the characterized range — if it does, the cap and not
the server shaped the result. Every point record carries `n_shed_total`, and
`scripts/compute_point_metrics.py` flags any point with `shed > 0` in its
table. Treat a non-zero shed count at any swept point as a finding.

**Precondition — raise `ulimit -n` before driving from Linux.** 3000
concurrent streams means ~3000 open sockets in the driving process, and
Linux's default soft limit is 1024. Below the cap, the process hits `EMFILE`
before the cap can ever engage — and those failures are recorded as
`errored` (a send that was really attempted), **not** `shed`. That is the bad
direction: it corrupts achieved RPS and the error count instead of tripping
the shed check above. Run `ulimit -n 65535` in the driving shell first.
Applies whether you drive from the L4 instance or another Linux host; see
also the open question of driving through the SSH tunnel at high concurrency.

## 9. The loadgen drives from the instance, and it is scripted

**Decision (2026-08-17): on-instance, not through the tunnel.** Driving from
the laptop over `tunnel.sh` would fold WAN round-trip into every TTFT and
multiplex up to 3000 concurrent streams through a single TCP connection. At
Stage A's upper points that characterizes the *tunnel* rather than the
replica — and it biases in the worst direction, inflating the breach metric
so the sweep could report a breach that belongs to the client. On-instance
the driver reaches vLLM at `127.0.0.1:8000` over loopback.

`tunnel.sh` is not retired; it is just no longer the measurement path. Keep
it for poking `/health` or curling a request by hand.

The operational cost of on-instance (clone, deps, launch, get the artifacts
back off a disk that dies with the instance) is staged into scripts so none
of it is improvised on the meter:

- **`scripts/gpu_session/run_on_instance.sh`** (local wrapper) —
  `bootstrap` | `check` | `run <schedule>` | `stage-a` | `shell`.
- **`scripts/gpu_session/remote_loadgen.sh`** (runs *on* the instance, from
  the clone) — `setup` | `env-check` | `run` | `list-artifacts`.
- **`scripts/gpu_session/pull_artifacts.sh`** (local) — scp the artifacts
  back and verify them **before teardown**.

Session order: `create_instance.sh` → `setup_and_launch_vllm.sh` →
`run_on_instance.sh bootstrap` → `check` → `stage-a` →
`pull_artifacts.sh` → `teardown.sh`.

**Three guards worth knowing about, because each blocks rather than warns:**

1. **`bootstrap` refuses a dirty tree or an unpushed HEAD.** The instance
   clones from GitHub and checks out the exact SHA in detached HEAD — not a
   branch name, which could move under the session. Without this the
   instance would silently clone some older state and every artifact would
   still look fine. *Verified: it currently refuses, listing the offending
   files, before issuing a single `gcloud` call.* **This means the branch
   must be pushed before the session** — `week2/loadgen-baseline` is not on
   `origin` yet.
2. **`run` refuses to drive a point if the fd soft limit is under 4000.**
   `remote_loadgen.sh` raises it to 65535 in the shell that runs the driver
   and then re-reads it rather than assuming the raise took. This is §8's
   `ulimit` precondition made non-optional: under the limit, EMFILE
   failures would land as `errored` instead of `shed` and corrupt achieved
   RPS instead of tripping the shed check.
3. **`pull_artifacts.sh` exits non-zero on an incomplete sweep** — a point
   missing its sidecar (no TTFT, therefore unusable), an unreadable
   `metrics.json`, or any point with `shed > 0`. It runs while the instance
   is **still up**, so a bad point can be re-driven for a few cents instead
   of being discovered after teardown. *Verified against synthetic points:
   it correctly flagged a missing sidecar, a shed-bitten point, and a
   tail-invalid point, and exited 0 on a clean set.*

Offered RPS, duration and seed come from each schedule's **own provenance**,
never from the filename or a typed flag, so a point record's `offered_rps`
cannot disagree with what was materialized. The loadgen venv on the
instance (`~/loadgen-env`) is deliberately separate from `~/vllm-env` —
vLLM pins torch/numpy hard and the driver must not be able to perturb the
server's environment.

**Still your call at session start:** the output-token policy. The driver
passes `--extra-body` through via `EXTRA_BODY`, defaulting to unset (vLLM
generates to EOS, so output length varies per prompt). §2.2 holds the
prompt-length contribution constant across the sweep; whether output length
should also be pinned (e.g. `{"max_tokens": 512}`) is an open knob, in the
same class as `--enforce-eager` and not resolved here.

---

## Summary

| Item | Status |
|---|---|
| §4 gate (Hard Stop 2) | ✅ confirmed |
| L4/GPUS_ALL_REGIONS quota | ✅ verified live, 0 in use |
| Billing enabled | ✅ verified |
| Budget alerts | ✅ verified live 2026-08-17 — $150 budget @ 50/90/100% + a $10 canary; thresholds land at $75/$135/$150 rather than $50/$100/$150 (§2) |
| Launch staged | ✅ `scripts/gpu_session/*.sh` |
| `--enforce-eager` on/off | ⚠️ **your call at session start** — staged safe default |
| `--max-model-len` | ✅ computed (20000), your confirmation welcome |
| Teardown dry-run | ✅ verified against Week 2 instance name |
| TTFT reaches disk | ✅ fixed 2026-08-17 (§6) — **was a hard blocker**; controls confirmed biting, your Hard Stop 2-class read still owed |
| Stage A schedules | ✅ generated, committed `4d381fe` |
| Concurrency cap value | ✅ **resolved 3000** 2026-08-17 — above Block C's uncapped peak (2380); provenance in `WEEK2_PLAN.md` §3.3 |
| `ulimit -n` on the driving host | ✅ enforced in `remote_loadgen.sh` — raises to 65535 and refuses to drive below 4000 (§8, §9) |
| Loadgen drives on-instance | ✅ scripted — `run_on_instance.sh` / `remote_loadgen.sh` / `pull_artifacts.sh` (§9) |
| Branch pushed to `origin` | ⚠️ **required before the session** — `bootstrap` pins the instance to a SHA and refuses an unpushed HEAD (§9) |
| Output-token policy (`EXTRA_BODY`) | ⚠️ **your call at session start** — unset means generate-to-EOS (§9) |

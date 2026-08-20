# Week 2 GPU Session Pre-Flight (Hard Stop 4)

> **STATUS: SUPERSEDED — DO NOT EXECUTE**
>
> Role: the Hard Stop **4** pre-flight checklist for session #1, including its `GPU SESSION READY` verdict. Session #2's checklist is `docs/WEEK2_GPU_SESSION_2_PREFLIGHT.md`.
>
> Procedures in this document were valid before the Week 2 GPU redesign and
> **must not** drive GPU session #2.
> Current execution instructions: `docs/WEEK2_GPU_SESSION_2_PLAN.md`.
> Index: `docs/WEEK2_DOC_INDEX.md`.

Evidence checklist for `WEEK2_EXECUTION.md` Hard Stop 4, ahead of the real
$150-budget GPU session (Block E, human-run only). Mirrors `WEEK2_PLAN.md`
§6.1's pre-flight list. Every item below either has evidence attached or is
explicitly flagged for your confirmation — nothing here was self-certified
past what I can actually verify.

---

## 1. §4 hard gate — all five mock validations green, controls confirmed biting

Re-affirms Hard Stop 2. Status: **confirmed** (2026-08-16 review, `ec1063f`
+ carry-forwards recorded `a0c4b97`). `pytest tests/loadgen -v` — **63/63
green** as of 2026-08-18, stable across repeated runs.

*The count has grown as the gate was extended, and the earlier figures are
kept here as history rather than overwritten: 19 at the original Hard Stop 2
review, 23 with replay (`c5813c9`), 35 with the TTFT-persistence set (§6), and
63 now that the schedule-generator CLI (§10) and scheduler-spin configuration
(§11) are covered. Any doc still quoting one of the older numbers is stale, not
describing a different suite.*

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

1. **The thresholds are $10 / $75 / $135 / $150 — and that is now the
   authoritative policy** (resolved 2026-08-18; `WEEK2_PLAN.md` §6.1,
   `WEEK2_EXECUTION.md` Hard Stop 4). *Historically §6.1 named
   $50 / $100 / $150 and this item recorded the mismatch rather than
   claiming green against a number it didn't match; the decision went the
   other way — the docs were changed to match the live ladder, because the
   live ladder is the better one (see 2).* The $150 hard line, the only rung
   that actually bounds spend, was never in question.
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
  `VLLM_USE_FLASHINFER_SAMPLER=0`, `--enforce-eager`). Eager mode is an
  `ENFORCE_EAGER` env knob — see the resolved item below.
- `tunnel.sh` — SSH port-forward, `--ssh-flag` (not `--`, which doesn't
  reliably pass through gcloud's Windows batch wrapper). **No longer the
  measurement path** — the loadgen drives on-instance over loopback (§9).
  Kept for hand-checking `/health` and one-off curls.

**Resolved 2026-08-18 — `ENFORCE_EAGER` is now a knob.** `--enforce-eager`
is the Week 1 *proven*-working config, but Week 1's own note flags it as right
for a single-request faithfulness check, not necessarily a perf run (it
disables CUDA graph capture). `WEEK2_GPU_IMPLEMENTATION_README.md` §3.2
therefore attempts **non-eager first** and forbids an automatic fallback.

That was not executable as this item was originally written: the flag was
hard-coded in the launch line, while `MODEL`/`PORT`/`MAX_MODEL_LEN` beside it
were all `${VAR:-default}` knobs. Following §3.2 would have meant either a
source edit or hand-launching the server — and an edit *mid-session* is worse
than it looks, because it dirties the tree and `run_on_instance.sh bootstrap`
refuses a dirty or unpushed HEAD, so the fallback path would have cost a new
benchmark revision on the meter.

Now: `ENFORCE_EAGER=0` for §3.2's first attempt, unset/`1` for the proven
fallback. **The default is still eager**, so the known-good path is the one
you get by accident. The launch line echoes the *resolved* mode, which is the
record that every point in one baseline ran the same way. Verified in all
three modes (unset / `1` / `0`); non-eager drops the flag cleanly rather than
passing an empty argument.

Block E step 2 ("confirm config-only swap holds... any required code change
is a finding, STOP") still governs what happens if non-eager *fails* — that
is evidence to surface, not something to paper over.

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

**Use `scripts/gpu_session/teardown_week2.sh`. Never bare `scripts/teardown.sh`.**

`teardown.sh` is the *generic* deletion primitive and still defaults to Week 1's
`llmrouter-vllm-l4`. Run bare against a Week 2 session it describes an instance
that does not exist, prints "nothing to tear down" and exits **0** — while the
Week 2 L4 keeps billing. That is §6.1's named failure mode ("a silent no-op
teardown is how a forgotten L4 runs all weekend"), and the earlier version of
this section hid it: the dry-run below was originally recorded with an explicit
`INSTANCE_NAME=` prefix, so the item read green while every runbook path around
it invoked the bare form.

*Historical note, kept deliberately — the original evidence line for this item was:*

```
$ INSTANCE_NAME=llmrouter-vllm-l4-week2 ZONE=us-central1-a bash scripts/teardown.sh
No instance named 'llmrouter-vllm-l4-week2' in zone 'us-central1-a' — nothing to tear down.
```

*Correct as typed, and it is why the item was recorded green; misleading as a
checklist item, because nothing else in the runbook typed that prefix.*

The wrapper owns Week 2's target, prints it before deleting, and **verifies the
instance is gone afterwards** rather than trusting the delete's exit code (§6.4):

```
$ DRY_RUN=1 bash scripts/gpu_session/teardown_week2.sh
=== Week 2 teardown ===
  instance: llmrouter-vllm-l4-week2
  zone:     us-central1-a
  project:  <REDACTED>

DRY RUN: no instance named 'llmrouter-vllm-l4-week2' in zone 'us-central1-a' -- nothing would be deleted.
```

Correct target, correct zone, clean exit with nothing standing — exactly the
state before Block E starts. Target resolution is also pinned by
`tests/gpu_session/test_teardown_target.py`, which fails if the wrapper and
`create_instance.sh` ever drift apart or if any Week 2 runbook path starts
recommending the bare primitive again.

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

**Tests:** `tests/loadgen/test_sample_persistence.py`, 13 cases. Controls
confirmed to bite, not just to pass:
- dropped sample-write → sidecar reconciliation goes RED (`missing=`);
- flush removed from the writer → the durable-on-produce test goes RED
  ("still empty 2s into a 3s run"), then green again when restored;
- warmup filter fed a 9000ms pre-warmup transient → p99 stays at 100ms
  with the filter, jumps above 1000ms without it.

These were my reds, produced on demand. **Hard Stop 2-class read: confirmed by
you, 2026-08-18.** The four reds re-verified at that review:

- a dropped sidecar row → `sidecar rows (4) != issued requests (5) -- missing=[2]`;
- a shed request wrongly carrying a sample → `unexpected=[99]` (a shed request
  never opened a stream and cannot have one);
- a sidecar/raw-log `send_time` disagreement → caught, because it would desync
  the time-based warmup filter that the whole deferred-N plan rests on;
- the warmup filter holding p99 TTFT at **100.0ms** where disabling it gives
  **9000.0ms** over the same rows.

`pytest tests/loadgen/test_sample_persistence.py` → 13 passed; full loadgen
suite 63/63. Per Hard Stop 2's standard the reds are the proof, not the green —
and they were confirmed personally rather than accepted as my summary.

**One operational note:** `benchmarks/runs/` is still gitignored — that is where
a point lands as it is produced. Promoting a point to evidence is a deliberate
copy into `benchmarks/evidence/week2/`, which **is** tracked, so its sidecar and
raw log then commit with a **plain `git add`** (`benchmarks/README.md`).
Force-adding is no longer the mechanism, and deliberately so: a `-f` leaves no
trace in history that a promotion decision was ever made.

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
`pull_artifacts.sh` → `teardown_week2.sh` (§5 — the Week 2 wrapper, never the
bare generic primitive).

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

## 10. Stage B schedules are a command, not a source edit

`scripts/generate_schedules.py` takes the RPS points as arguments, in either
style, both routing through the same implementation:

```
$ python scripts/generate_schedules.py --rps 32 34 36 38 --out-dir benchmarks/schedules/stage_b
$ python scripts/generate_schedules.py --rps-start 32 --rps-stop 38 --rps-step 2 --out-dir benchmarks/schedules/stage_b
```

Verified byte-identical output between the two modes, and
`generate_stage_a_schedules.py` is now a thin wrapper over the same function —
regenerating Stage A reproduces the eight committed artifacts **byte for byte**,
so going generic did not perturb a frozen input.

Why this is a pre-flight item at all: Stage B's bracket is only known
mid-session, and the previous generator hard-coded its RPS list. Producing Stage
B would have meant editing tracked source *on the meter* — and
`run_on_instance.sh bootstrap` pins the instance to a commit and refuses a dirty
tree, so that edit would either block the session or cost the "which code drove
this sweep" answer `BASELINE.md` owes. Covered by
`tests/loadgen/test_schedule_cli.py` (18 cases, including that every workload
lock — RNG scheme, corpus pinning, provenance, replay round-trip — survives).

## 11. Loadgen scheduler spin margin — Linux-calibrated

`loadgen/scheduler.py:SPIN_MARGIN_S` was Windows-tuned at 5ms, and `WEEK2_PLAN.md`
§8 forbade shipping it onto the Linux vLLM runs unverified. Resolved 2026-08-18
by an A/B on a dedicated CPU-only `e2-standard-4` (`us-central1-a`), 0ms vs 5ms,
at 20 and 80 RPS, 5 runs per cell — same machine, seed, schedule, client and
repetition count, one variable.

The margin is now **per platform, from measurement**: `WINDOWS_SPIN_MARGIN_S` /
`LINUX_SPIN_MARGIN_S`, resolvable per host via `--spin-margin-s` or
`LOADGEN_SPIN_MARGIN_S` (no source edit, so `bootstrap`'s dirty-tree guard is not
in tension with re-tuning). Every point record now carries
`provenance.spin_margin_s` and `provenance.platform`, so a Linux sweep can never
be silently mistaken for one driven with the Windows value.

Evidence: `benchmarks/calibration/scheduler_spin/`; reading and decision in
`BENCHMARKS.md`. Harness: `scripts/calibrate_scheduler_spin.py`. Configuration
behaviour is pinned by `tests/loadgen/test_scheduler_spin_config.py`, including
that `_sleep_until` never returns early at **either** margin — the V5 property
the spin exists to protect.

**Two methodology traps this run hit, recorded because they generalise:**

1. **The in-process mock's own busy-wait contends for the GIL.** The harness
   runs the mock in a thread of the driving process, so `mock/timing.py`'s 20ms
   spin — 5 sleeps per request at 80 RPS — burns seconds of CPU per second and
   inflates measured scheduling lag for *both* arms. Block 0 already established
   that spin is unnecessary on Linux, so the calibration run passes
   `--mock-spin-margin-s 0`. The real GPU run has no such coupling: driver and
   vLLM are separate processes in separate venvs.
2. **The `ulimit -n` precondition applies to the calibration too.** The first
   attempt at 80 RPS hit `OSError: [Errno 24] Too many open files` — §8's exact
   failure mode, from the same default soft limit of 1024, in a script that had
   not raised it. `remote_loadgen.sh` enforces the raise for the GPU run; the
   calibration runner now does too. Any harness that drives at Stage A rates
   needs it, not just the session path.

## Summary

| Item | Status |
|---|---|
| §4 gate (Hard Stop 2) | ✅ confirmed |
| L4/GPUS_ALL_REGIONS quota | ✅ verified live, 0 in use |
| Billing enabled | ✅ verified |
| Budget alerts | ✅ verified live 2026-08-17; policy resolved 2026-08-18 as **$10 canary / $75 / $135 / $150 hard line** — docs now match the live ladder (§2) |
| Launch staged | ✅ `scripts/gpu_session/*.sh` |
| `--enforce-eager` on/off | ✅ **`ENFORCE_EAGER` knob** (2026-08-18, §3) — defaults eager (proven); `0` is README §3.2's non-eager first attempt, so the fallback is an env var not an edit |
| `--max-model-len` | ✅ computed (20000), your confirmation welcome |
| Teardown dry-run | ✅ verified against Week 2 instance name |
| TTFT reaches disk | ✅ fixed 2026-08-17 (§6) — **was a hard blocker**; controls confirmed biting, Hard Stop 2-class read **confirmed by you 2026-08-18** |
| Stage A schedules | ✅ generated, committed `4d381fe` |
| Concurrency cap value | ✅ **resolved 3000** 2026-08-17 — above Block C's uncapped peak (2380); provenance in `WEEK2_PLAN.md` §3.3 |
| `ulimit -n` on the driving host | ✅ enforced in `remote_loadgen.sh` — raises to 65535 and refuses to drive below 4000 (§8, §9) |
| Loadgen drives on-instance | ✅ scripted — `run_on_instance.sh` / `remote_loadgen.sh` / `pull_artifacts.sh` (§9) |
| Branch pushed to `origin` | ✅ `week2/loadgen-baseline` is on `origin`; `bootstrap` pins the instance to that SHA and refuses an unpushed HEAD (§9). Re-confirm after any new commit — the guard is per-commit, not per-branch |
| Output-token policy (`EXTRA_BODY`) | ⚠️ **your call at session start** — unset means generate-to-EOS (§9) |

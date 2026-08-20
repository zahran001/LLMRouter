> **STATUS: HISTORICAL — DO NOT EXECUTE**
>
> Role: the pre-session-#1 remediation brief. Already executed; the record is `docs/WEEK2_REMEDIATION_REPORT.md`.
>
> This document records an earlier Week 2 state. It is preserved for
> provenance, and nothing in it may drive GPU session #2.
> Current entry point: `docs/WEEK2_DOC_INDEX.md`.

You are implementing the final Week 2 pre-GPU remediation for LLMRouter.

This is **not a redesign task**. The experiment architecture and Week 2 decisions are locked. Implement the decisions below, update affected tests/docs, run the required gates, and stop before any GPU action.

Do **not** stand up, drive, or tear down a GPU instance.

## Authoritative sources

Use, in precedence order:

1. `WEEK2_PLAN.md` — what was decided and why.
2. `WEEK2_EXECUTION.md` — execution order, hard stops, and definitions of done.
3. `WEEK2_PRE_GPU_AUDIT.md` — current remediation tracker/evidence.
4. `docs/WEEK2_GPU_PREFLIGHT.md`
5. `MOCK_TRUST_BOUNDARY.md`
6. Week 1 measurement/router specs where referenced.

If two authoritative docs still conflict on the same axis after the explicitly locked decisions below, **surface the conflict rather than silently reconciling it**.

---

# LOCKED HUMAN DECISIONS

These are settled. Do not ask to revisit them.

### D1 — Week 2 teardown ownership

Keep `scripts/teardown.sh` as a generic deletion primitive.

Add a Week 2-specific wrapper under `scripts/gpu_session/` that owns:

- instance: `llmrouter-vllm-l4-week2`
- default zone: the existing Week 2 target zone

Every Week 2 runbook/call site must invoke the Week 2 wrapper rather than bare `scripts/teardown.sh`.

The wrapper must clearly print the resolved instance and zone before deletion and verify afterward that the instance no longer exists.

A successful delete command alone is not sufficient evidence.

### D2 — Linux loadgen scheduler spin calibration

The existing `loadgen/scheduler.py:SPIN_MARGIN_S = 5ms` is Windows-tuned and may not be shipped onto the Linux vLLM benchmark without calibration.

Run an A/B on a dedicated CPU-only Linux GCP e2 VM:

- Arm A: scheduler spin margin = `0ms`
- Arm B: scheduler spin margin = `5ms`

Use the same machine, workload, schedule construction, seed, client, and repetitions between arms.

No GPU.

At minimum test:

- 20 RPS
- 80 RPS

Measure from the loadgen's own scheduling instrument:

- scheduling lag p50
- p95
- p99
- max
- offered RPS
- achieved RPS
- offered-vs-achieved divergence

Use the result to choose the Linux default.

Do not invent a new arbitrary calibration threshold merely to choose a winner. The relevant question is whether spin-disabled Linux operation satisfies the existing loadgen fidelity requirements with adequate headroom through the 80-RPS Stage A ceiling.

Make scheduler spin configurable rather than leaving an environment-specific hidden constant if practical.

If the evidence supports a platform-specific default, encode it explicitly, e.g. Windows vs Linux behavior, and document its provenance.

Persist the raw/calculated calibration evidence under the committed calibration/evidence structure.

Create and tear down the e2 VM as part of this task. Verify it is deleted.

### D3 — Offered-vs-achieved band

Resolve the Week 2 divergence band at:

**±5%.**

Calibration provenance:

- 0.5 RPS → 0.0%
- 1 RPS → 0.0%
- 2 RPS → 0.0%
- 5 RPS → −0.67%

Retain ±5% rather than tightening it to the measured maximum. The intent is to leave realistic scheduler/client headroom while still detecting material driver under-delivery.

Update the authoritative plan/calibration records so this is no longer `[CALIBRATE]`.

Do not change the semantic behavior of Option Y:
- clean point → plotted at offered RPS
- flagged point → retained and plotted at achieved RPS
- both values logged

### D4 — Stage B schedule generator

Remove the need to edit source code during the metered session.

Create/rework a generic schedule-generation CLI supporting BOTH:

#### Explicit point mode

Example:

```bash
python scripts/generate_schedules.py \
  --rps 32 34 36 38
```

#### Range mode

Example:

```bash
python scripts/generate_schedules.py \
  --rps-start 30 \
  --rps-stop 40 \
  --rps-step 2
```

Both modes must route through the same underlying schedule-generation implementation.

Preserve all existing workload locks:

- same frozen materialized schedule format
- same RNG scheme/version
- same arrival/corpus RNG independence
- prompt assignment during materialization
- same pinned corpus
- same provenance fields
- same duration behavior
- same replay compatibility

Do not duplicate schedule-generation logic.

Existing Stage A generation should either use this generic path or be a thin wrapper around it.

Add tests for:
- explicit-points parsing
- range parsing
- invalid/mutually-conflicting argument combinations
- generated provenance
- replay compatibility if the genericization touches schedule format

The GPU-session tooling should be able to generate Stage B schedules after a bracket is observed **without modifying tracked source files**.

### D5 — Budget alert policy

The authoritative Week 2 policy becomes:

- `$10` canary
- `$75` warning
- `$135` near-cap warning
- `$150` hard budget line

Update documentation/preflight references that still say `$50 / $100 / $150`.

Do not attempt to create or modify billing alerts unless the existing repo tooling explicitly supports and expects that operation as part of this CPU-only task. The primary requirement here is to make the recorded decision and preflight source of truth internally consistent.

### D6 — benchmark evidence Git policy

Adopt an explicit split:

**Version-controlled:**
- frozen benchmark inputs/schedules
- calibration evidence
- accepted/final evidence supporting published benchmark claims

**Ignored:**
- scratch
- exploratory runs
- failed/retry runs unless deliberately promoted as evidence
- temporary benchmark outputs

Implement a structure along the lines of:

```text
benchmarks/
  schedules/
  calibration/
  evidence/
    week2/
  scratch/
```

You may adapt names to the repo's existing organization, but preserve the semantic distinction.

Update `.gitignore` so the intended evidence/calibration subtrees are naturally trackable without requiring `git add -f`, while scratch/generated noise remains ignored.

Do NOT blindly unignore all benchmark output.

Document the promotion rule:

> Only accepted artifacts that support `BASELINE.md` or calibration provenance are committed; exploratory/debug/retry artifacts remain scratch.

---

# ADDITIONAL REQUIRED REMEDIATION

These decisions were already settled by the existing design and do not require human re-approval.

## R1 — Fix the Week 1 mock/vLLM faithfulness regression

Current failing test:

`tests/faithfulness/test_real_fixture.py::test_real_stream_key_set_matches_mock`

Real vLLM fixture contains four keys the mock role chunk omits:

- `choices[0].delta.content`
- `choices[0].logprobs`
- `prompt_token_ids`
- `prompt_text`

Fix the mock to match the captured real-vLLM fixture's shape/types.

Do NOT weaken or delete the key-set assertion.

Do NOT change the parser contract.

Preserve the existing behavior that empty role-chunk `delta.content` is not classified as a content/token chunk.

After the fix, prove:

- mock schema passes
- real fixture schema passes
- recursive key-set diff is clean
- existing parser remains a no-op on the real stream
- router eval remains green

## R2 — Explicitly request Spot provisioning

The Week 2 GPU runbook specifies Spot, but the audit found `create_instance.sh` does not explicitly request it.

Update Week 2 instance creation to explicitly request the appropriate GCP Spot provisioning model.

Keep all existing Week 2 machine/GPU/model/resource settings unchanged unless a syntactic requirement of Spot provisioning forces a corresponding flag.

Have the script print/verify the resolved provisioning model where practical.

This task must NOT actually create the GPU instance.

## R3 — Mark measurement window Y resolved

Resolve:

**Y = 120 seconds**

Provenance:

- lowest Stage A offered RPS = 2
- `2 RPS × 120s = 240` scheduled measurement-window requests before considering any under-delivery
- this comfortably clears the ≥100 achieved-sample validity floor under normal tracking

Update `WEEK2_PLAN.md` §8 and any stale calibration references so Y is no longer presented as unresolved.

Do not change runtime behavior if it is already 120s.

## R4 — Normalize V2 negative-control assertion style

V2 already has strong measured evidence, but make its test structure match the other negative controls.

Extract/use a shared assertion helper for fast-vs-slow achieved-RPS invariance.

Required structure:

1. real open-loop implementation passes the helper
2. deliberately closed-loop implementation is fed to the SAME helper under `pytest.raises(AssertionError)`

Preserve the existing measured semantics; do not weaken the current threshold to make the control pass.

## R5 — adversarial CLI/docstring drift

The audit found `loadgen/adversarial.py` documents `--long-context-percentile 90` but that CLI option does not exist.

Determine which of these is consistent with the locked implementation:

- if percentile is intentionally fixed by the Week 2 design, remove/fix the misleading docstring;
- if the implementation already has a legitimate configurable value elsewhere and the missing flag is clearly accidental, wire it through without changing the default workload.

Do not introduce a new experiment knob merely because the docstring mentions one.

## R6 — documentation consistency cleanup

Update stale documentation identified by the audit after the code changes are complete.

At minimum address:

- `STATUS.md` stale test counts/state
- `WEEK2_PLAN.md` preamble saying §3–§7 are not locked
- stale branch-on-origin warning in `docs/WEEK2_GPU_PREFLIGHT.md`
- stale loadgen test counts
- Window Y calibration status
- concurrency-cap cross-reference typo
- teardown instructions/call sites
- budget thresholds
- new benchmark evidence policy
- Linux scheduler-spin calibration result

Do not rewrite history or remove useful provenance.

Where an old value was truly a historical state, preserve it as historical context rather than pretending it never existed.

---

# DO NOT CHANGE

The following remain locked:

- headline baseline = Poisson
- steady = reference
- adversarial = separate scenario
- p99 TTFT = breach metric
- 500ms = headline SLO
- 2s = secondary severe-degradation line
- concurrency cap = 3000
- cap must not shape characterized points
- raw log six-field schema
- samples sidecar separation
- `prompt_len` = char count in Week 2
- token-count prompt length deferred to Week 3
- frozen schedule is replay source of truth
- schedule + pinned corpus = workload identity
- warmup is time-based
- warmup N remains unresolved until Stage A GPU transient data
- agent never starts the GPU session

Do not opportunistically refactor unrelated code.

---

# IMPLEMENTATION ORDER

Use this sequence:

1. Inspect current repo/HEAD and confirm the audit findings still apply.
2. Implement Week 2 teardown wrapper + update call sites.
3. Build the Linux scheduler-spin calibration harness/configurability.
4. Run the 0ms-vs-5ms A/B on a dedicated e2 Linux VM.
5. Persist evidence, choose/implement Linux scheduler behavior, tear the VM down.
6. Resolve/document ±5% offered-vs-achieved band.
7. Implement generic Stage A/Stage B schedule-generation CLI.
8. Fix mock/vLLM faithfulness mismatch.
9. Explicitly configure Spot in Week 2 creation script.
10. Implement benchmark evidence/scratch Git policy.
11. Normalize V2 negative-control helper.
12. Fix adversarial docstring/CLI drift.
13. Mark Y=120s resolved.
14. Update preflight/status/plan documentation.
15. Run all gates below.
16. Produce a final evidence report and STOP.

---

# REQUIRED TEST / VALIDATION GATES

Run the repo's authoritative equivalents if command names have changed.

At minimum:

```bash
.venv/Scripts/python -m pytest tests/loadgen -v
```

Expected: all loadgen tests green, including all negative controls.

Run the V2/control output visibly enough to preserve the fast/slow divergence evidence.

Then:

```bash
PYTHON=.venv/Scripts/python bash scripts/router_eval.sh
```

Expected: router gate green including its negative controls.

Then:

```bash
.venv/Scripts/python -m pytest tests
```

Goal: clean full suite.

If the full-suite mock timing integration test still flakes only under suite-wide contention, investigate enough to distinguish:
- actual regression
- known untrusted concurrent mock timing/machine-load effect

Do not widen timing tolerances merely to make the suite green.

If it remains an environment-only known issue, report it explicitly with standalone-vs-full-suite evidence rather than silently changing the measurement contract.

Also run tests for:
- generic schedule CLI
- replay after schedule-generator changes
- teardown target resolution/dry-run
- benchmark Git-ignore policy
- scheduler-spin configuration/platform behavior

---

# PRE-GPU FINAL VERIFICATION

Do NOT create the GPU.

Produce evidence that:

### Teardown
- Week 2 wrapper resolves `llmrouter-vllm-l4-week2`
- correct zone is shown
- no Week 2 runbook path recommends bare generic teardown
- post-delete verification exists

### Scheduler
- Linux A/B artifact exists
- result and decision are documented
- Linux GPU run will not unknowingly use an unverified Windows-tuned value
- 80-RPS behavior is within the existing client-fidelity requirements

### Calibrations
- cap = 3000 resolved
- band = ±5% resolved
- Y = 120s resolved
- mock Linux spin resolved
- loadgen Linux spin resolved
- warmup N explicitly remains POST-GPU BY DESIGN

### Stage B
Demonstrate, without editing source files, generation of a hypothetical fine bracket such as:

```text
32, 34, 36, 38 RPS
```

using:
1. explicit-point syntax
2. range syntax

Do not commit those hypothetical schedules as real benchmark evidence unless they belong in a test fixture/temp directory.

### Spot
Show the exact command/script path now requests Spot.

### Evidence storage
Show:
- which paths are committed evidence
- which paths are scratch/ignored
- `git check-ignore` / equivalent proving both sides behave as intended

### Git reproducibility
The final repo state intended for GPU bootstrap must be clean, committed, and pushed.

Do not push unless the existing workflow/user authorization already permits normal branch pushes; otherwise stop with the exact commit-ready state and report that push remains human-owned.

---

# FINAL REPORT

Produce a concise report containing:

## Changes made
For each remediation item:
- file(s)
- what changed
- why

## Calibration result
Linux scheduler A/B table:

| RPS | Spin | lag p50 | p95 | p99 | max | offered | achieved | divergence |
|---|---:|---:|---:|---:|---:|---:|---:|---:|

Then state the resulting Linux spin decision and provenance.

## Tests
Exact commands and pass/fail counts.

## Remaining issues
Classify as only:

- BLOCKER
- SHOULD FIX
- POST-GPU BY DESIGN
- DOCUMENTATION/HISTORICAL

## Hard-stop verdict

| Gate | Verdict | Evidence |
|---|---|---|
| Hard Stop 1 — open-loop architecture | PASS / FAIL | ... |
| Hard Stop 2 — negative controls bite | PASS / FAIL | ... |
| Hard Stop 3 — calibrations | PASS / FAIL | ... |
| Hard Stop 4 — pre-GPU readiness | PASS / FAIL | ... |

Warmup N must not cause Hard Stop 3 to fail; it is intentionally resolved from Stage A GPU transient data.

End with exactly:

> **GPU SESSION READY: YES**

or

> **GPU SESSION READY: NO — blockers: ...**

Then stop. Do not start Block E.
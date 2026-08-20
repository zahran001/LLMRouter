# Week 2 Pre-GPU Documentation Cleanup — Implementation README

> **STATUS: HISTORICAL — DO NOT EXECUTE**
>
> Role: the brief for the pre-GPU documentation cleanup. Already executed; the evidence is `docs/WEEK2_GPU_SESSION_2_PREFLIGHT.md`.
>
> This document records an earlier Week 2 state. It is preserved for
> provenance, and nothing in it may drive GPU session #2.
> Current entry point: `docs/WEEK2_DOC_INDEX.md`.

## Purpose

Week 2's redesigned benchmark implementation is complete through R11 and is halted at **Hard Stop R-PREGPU**.

Before starting GPU session #2, perform one final repository cleanup whose purpose is:

> **Make it impossible for a fresh agent or human operator to mistake a historical Week 2 document for current execution instructions.**

This is not cosmetic documentation work.

The Week 2 experiment has changed materially since the original plan:

- fixed-duration headline runs were superseded by exact-N schedules,
- natural random sampling was superseded by a controlled canonical headline workload,
- `n >= 100` was superseded by calibrated `N=4000` + independent repeats,
- post-hoc warmup re-filtering is no longer valid for the redesigned headline,
- offered-vs-achieved semantics changed,
- p99 is explicitly nearest-rank,
- timeout censoring has explicit validity states,
- prefix caching is disabled for the controlled headline,
- the first GPU session and its apparent breach/floor are diagnostic evidence only.

The code now enforces these redesign decisions.

The remaining risk is **instruction drift**: an old README/runbook may still contain commands or procedures that were correct when written but are invalid for GPU session #2.

This cleanup creates an explicit documentation authority system and makes stale execution guidance testable.

---

# 1. Scope

This task is **GPU-free**.

Do not:

- create an L4 instance,
- run GPU benchmarks,
- modify historical evidence bytes,
- rewrite historical schedules,
- reinterpret session #1 as publishable baseline evidence,
- change R4–R11 benchmark architecture,
- reopen already locked load-generator decisions.

This task may modify:

- active Week 2 planning documents,
- execution/runbook documents,
- documentation headers,
- documentation indexes,
- documentation tests,
- machine-readable repeat/session policy,
- current status/preflight files.

Historical documents remain preserved.

---

# 2. Human decisions already LOCKED

The following are no longer proposed.

## D-CLEAN-1 — repeat classification

**LOCKED: 1A**

Each headline λ receives three independent GPU repeats.

Final classification requires agreement.

```text
UNDER + UNDER + UNDER → UNDER

OVER + OVER + OVER → OVER

2–1 split → UNCERTAIN
```

Do not implement majority voting.

---

## D-CLEAN-2 — N=5000 escalation

**LOCKED: 2B**

For GPU session #2:

```text
N = 4000
```

is the authorized headline evidence size.

```text
N = 5000
```

is **NOT AUTHORIZED**.

If `N=4000` cannot resolve the crossing under the locked repeat policy:

```text
report a breach interval
```

Do not increase N on the meter.

---

## D-CLEAN-3 — Spot preemption / process epochs

**LOCKED: 3A**

Headline repeats from different vLLM process epochs must not be combined into one final classification family.

If Tier B is interrupted:

```text
epoch A:
repeat 1
repeat 2
PREEMPTED
```

a new process may not contribute only `repeat 3`.

Instead:

```text
epoch A → preserved diagnostic evidence

epoch B →
repeat 1
repeat 2
repeat 3
→ final family
```

---

## D-CLEAN-4 — warmup boundary

**LOCKED: 4A**

The redesigned headline schedules freeze a **60-second warmup boundary**.

Tier A must establish that the relevant transient has stabilized by that boundary.

If not:

```text
STOP
pull artifacts
regenerate schedules with a larger frozen boundary
rerun required GPU-free checks
return to pre-GPU approval
```

Do **not** resolve a larger warmup afterward by re-filtering headline sidecars.

Post-hoc warmup re-filtering was valid under the old fixed-duration experiment and is **superseded for the redesigned exact-N headline**.

---

## D-CLEAN-5 — scout expansion

**LOCKED: 5A**

Initial diagnostic scout:

```text
λ = 1, 2, 4, 8
```

Pre-authorized fallback:

```text
if λ=1 is already OVER:
    add λ=0.5

if λ=8 is still UNDER:
    add λ=16
```

If the authorized fallback still fails to establish a useful bracket:

```text
STOP
return to human review
```

Do not invent additional λ values on the meter.

---

## D-CLEAN-6 — Week 2 secondary scope

**LOCKED: 6A**

Week 2 is not closed until the intended secondary scenarios are accounted for:

1. controlled Poisson headline,
2. natural-random secondary,
3. steady-arrival reference,
4. adversarial scenario.

The controlled Poisson workload alone defines the headline breach.

The other scenarios may support interpretation but may never redefine it.

Adversarial remains last in execution order.

---

# 3. Add Hard Stop R-DOC

Introduce a new blocking gate:

```text
R4–R11 complete
      ↓
documentation cleanup
      ↓
HARD STOP R-DOC
      ↓
final regression / benchmark SHA
      ↓
HARD STOP R-PREGPU
      ↓
GPU session #2
```

## Purpose of R-DOC

R-DOC answers:

> Can a fresh-context agent enter the repository and unambiguously determine which documents govern GPU session #2 without relying on conversation history?

R-DOC is a **human-verdict gate**.

The agent produces evidence.

The human decides PASS / FAIL.

---

# 4. Create one Week 2 authority index

Add:

```text
docs/WEEK2_DOC_INDEX.md
```

This becomes the single index for all Week 2 process documents.

Every relevant document must be classified into exactly one primary state:

```text
AUTHORITATIVE
EXECUTABLE
EVIDENCE
HISTORICAL
SUPERSEDED
```

Recommended semantics:

| State | Meaning |
|---|---|
| `AUTHORITATIVE` | Defines current experiment decisions |
| `EXECUTABLE` | May be followed during the current GPU workflow |
| `EVIDENCE` | Supports decisions; never defines current execution by itself |
| `HISTORICAL` | Preserved record of an earlier project state |
| `SUPERSEDED` | Contains instructions/decisions that are no longer current |

The index must show the current execution chain prominently:

```text
START
  │
  ▼
README.md
  │
  ▼
STATUS.md
  │
  ▼
docs/WEEK2_DOC_INDEX.md
  │
  ├── Experimental authority
  │      WEEK2_PLAN.md
  │
  ├── Ordering / hard stops
  │      WEEK2_EXECUTION.md
  │
  ├── Current GPU mechanics
  │      docs/WEEK2_GPU_SESSION_2_PLAN.md
  │
  └── Machine-readable repeat policy
         benchmarks/workloads/week2_headline/repeat_policy.json
```

A reader should not need to infer this hierarchy from filenames.

---

# 5. Lock document responsibilities

## `README.md`

Purpose:

> What the project is.

It may point to `STATUS.md`.

It must not become a Week 2 runbook.

---

## `STATUS.md`

Purpose:

> Where the project currently is.

It should say:

```text
Week 2 — redesigned baseline
R4–R11 implemented
Hard Stop R-DOC / R-PREGPU pending
GPU session #2 not yet run
```

It should also preserve the explicit session #1 **do-not-cite** list.

Avoid duplicating the detailed benchmark design here.

---

## `WEEK2_PLAN.md`

Primary state:

```text
AUTHORITATIVE
```

Purpose:

> What is measured, what is locked, and why.

It is authoritative for:

- controlled headline semantics,
- workload definition,
- p99 definition,
- censoring rules,
- N / N ceiling semantics,
- prefix-cache policy,
- repeat meaning,
- secondary scenarios,
- supersession provenance.

Do not use it as the primary shell-command runbook.

---

## `WEEK2_EXECUTION.md`

Primary state:

```text
AUTHORITATIVE / EXECUTION-GATING
```

Purpose:

> Execution order, hard stops, definitions of done.

It must include:

```text
R0 → R11
R-DOC
R-PREGPU
GPU session #2
Week 2 closeout
```

It must not contain active instructions that conflict with exact-N session #2 semantics.

Any old Block F wording about resolving warmup by post-hoc re-filtering redesigned headline data must be removed from the active path or clearly marked historical.

---

## `docs/WEEK2_GPU_SESSION_2_PLAN.md`

Primary state:

```text
EXECUTABLE
```

Purpose:

> The only current GPU session runbook.

This file should be self-contained enough that the operator does not need to jump through historical READMEs while the GPU meter is running.

It may link outward for rationale.

It may not invent new experimental policy.

---

## `repeat_policy.json`

Purpose:

> Machine-readable encoding of the final repeat/evidence policy.

Change:

```text
status = PROPOSED
```

to the repository's equivalent of:

```text
status = LOCKED
```

Encode the newly approved policies, including:

```text
repeats = 3
agreement_required = true
majority_vote = false

N = 4000

escalation.N5000.authorized = false

cross_process_epoch_combination = false

unresolved_boundary = interval
```

Use existing schema/style where possible rather than inventing redundant fields.

Tests should verify these values where practical.

---

# 6. Add status banners to Week 2 documents

Every Week 2 process document that could reasonably be discovered and followed must declare its state near the top.

## Current executable example

```text
STATUS: EXECUTABLE — GPU SESSION #2

Current document authority:
- experiment semantics: WEEK2_PLAN.md
- execution/gating: WEEK2_EXECUTION.md
- GPU commands: this document

If these appear to conflict:
HALT and surface the conflict.
Do not reconcile silently.
```

## Historical example

```text
STATUS: HISTORICAL — DO NOT EXECUTE

This document records an earlier Week 2 state.
It is preserved for provenance.

Current entry point:
docs/WEEK2_DOC_INDEX.md
```

## Superseded example

```text
STATUS: SUPERSEDED — DO NOT EXECUTE

Some procedures in this document were valid before the Week 2 GPU redesign
and must not drive GPU session #2.

Current execution instructions:
docs/WEEK2_GPU_SESSION_2_PLAN.md
```

Do not rely on directory names alone to communicate authority.

---

# 7. Classify existing Week 2 documents

At minimum inspect:

```text
WEEK2_PLAN.md
WEEK2_EXECUTION.md
STATUS.md

docs/WEEK2_GPU_PREFLIGHT.md
docs/WEEK2_PRE_GPU_AUDIT.md
docs/WEEK2_REMEDIATION_REPORT.md
docs/WEEK2_GPU_SESSION_FINDINGS.md
docs/WEEK2_GPU_SESSION_2_PLAN.md

WEEK2_R3_CLOSEOUT_AND_R4_IMPLEMENTATION_README.md
docs/WEEK2_R4_EVIDENCE_PACKAGE.md

any other WEEK2*.md
any GPU-session README/runbook
```

Do not assume the list above is exhaustive.

Discover all relevant files from the repository.

For each document, record in `WEEK2_DOC_INDEX.md`:

- path,
- state,
- role,
- whether executable,
- successor/current replacement if superseded.

---

# 8. Separate evidence from instructions

Evidence documents include items such as:

```text
WEEK2_GPU_SESSION_FINDINGS.md
WEEK2_R4_EVIDENCE_PACKAGE.md
WEEK2_PRE_GPU_AUDIT.md
WEEK2_REMEDIATION_REPORT.md
R3 evidence packages
calibration reports
```

Their job is:

> Why do we believe this?

Their job is **not**:

> What shell command should I execute next?

If an evidence package currently contains executable-looking instructions, leave them as historical context but add a header making clear that the package does not govern current execution.

The GPU-session runbook may reference evidence documents for rationale.

The dependency must never point the other way.

---

# 9. Repository-wide stale-assumption audit

Search the entire repository, not just `.md` files, for assumptions associated with earlier Week 2 states.

At minimum search for variants of:

```text
120s
120 seconds
Y = 120
fixed duration
measurement window

n >= 100
n≥100
100-sample
tail-valid

warmup-n
re-filter
refilter
flatten point
post-hoc warmup

1.5 RPS
1.5 / 2 / 5
old bracket
breach = 2

402.3
unloaded floor

linear percentile
numpy percentile
np.percentile

prefix caching
enable_prefix_caching

plot at achieved
offered-vs-achieved

same seeded ShareGPT
natural random
with replacement
no stratification

Stage A
Stage B
GPU SESSION READY
```

Do not blindly replace hits.

Classify every relevant occurrence as:

```text
CURRENT_CORRECT
HISTORICAL_EXPLICIT
STALE
```

### `CURRENT_CORRECT`

The statement matches current session #2 semantics.

No action needed.

### `HISTORICAL_EXPLICIT`

The old value is intentionally preserved and clearly framed as historical/superseded evidence.

No semantic rewrite needed.

### `STALE`

The statement could cause current execution or interpretation to drift.

Update it.

The audit report must show **zero unexplained stale hits** before R-DOC can pass.

---

# 10. Special stale assumption: warmup

Treat this as load-bearing.

Historical rule:

```text
measure first
resolve warmup later
re-filter sidecars
```

Current redesigned headline rule:

```text
freeze 60s boundary into exact-N schedule
validate boundary during Tier A

if 60s insufficient:
STOP
regenerate schedules
```

Do not allow active session #2 documentation to preserve the historical behavior.

Historical documents may retain it only if clearly marked superseded.

---

# 11. Special stale assumption: session #1 results

The following may remain in evidence/history but must never be reachable as current claims:

```text
breach RPS = 2
1.5 RPS = clean UNDER anchor
402.3ms = definitive unloaded floor
10/20/30 RPS survivor p99 = ordinary latency
n >= 100 = sufficient p99 evidence
```

Current documents should direct readers to:

```text
docs/WEEK2_GPU_SESSION_FINDINGS.md
```

for the permanent interpretation of session #1.

---

# 12. Make GPU session #2 self-contained

`docs/WEEK2_GPU_SESSION_2_PLAN.md` should contain the operational facts needed while the meter is running.

At minimum:

## Benchmark identity

```text
benchmark commit SHA
canonical workload version / membership id
schedule version
repeat-policy version
metrics version
percentile method
```

## Server configuration

```text
model
vLLM version
max_model_len = 20000
output max_tokens = 512
prefix caching = disabled
enforce-eager policy
network topology
```

## Client configuration

```text
on-instance loadgen
concurrency cap = 3000
Linux spin = 0ms
fd limit
```

## Tier A

```text
new clean floor
scout λ = 1/2/4/8
N = 500 diagnostic only
fallback 0.5 / 16
warmup-transient validation
```

## Hard Stop GPU-1

Must answer:

```text
is the crossing neighborhood bracketed?
is 60s warmup sufficient?
```

## Tier B

```text
3 λ
×
3 repeats
×
N=4000
repeat-major
same vLLM process epoch
```

## Point/repeat validity

```text
UNDER
OVER
UNCERTAIN
CENSORED

>5% censoring → suppress ordinary p99

2–1 repeat split → UNCERTAIN
```

## Preemption

Explicit process-epoch rule.

## Secondary runs

```text
natural-random
steady
adversarial last
```

## Artifact gate

What must exist before teardown.

## Teardown

Week 2 teardown wrapper + deletion verification.

This must be the one file an operator can keep open during the metered session.

---

# 13. Add a no-improvisation matrix

Include the following or equivalent in the session #2 runbook.

| Condition | Authorized response |
|---|---|
| λ=1 already OVER | Add λ=0.5 scout |
| λ=8 still UNDER | Add λ=16 scout |
| Authorized scout still fails to bracket | STOP |
| Transient not stable by 60s | STOP + regenerate schedules |
| Prefix-cache verification fails | STOP |
| Shed > 0 | Point invalid / investigate |
| Driver fails materialized-schedule fidelity | Point invalid / investigate |
| Censoring >5% | `CENSORED`; no ordinary p99 |
| Censoring 0–5% near boundary | review required |
| 2–1 repeat split | `UNCERTAIN` |
| N=4000 unresolved | report interval |
| Desire to increase N to 5000 | NOT AUTHORIZED |
| Spot preemption during Tier B | do not combine process epochs |
| Code change required | STOP; new benchmark SHA + preflight |
| Historical README conflicts with session #2 plan | STOP; surface conflict |

No other mid-session policy changes are authorized.

---

# 14. Documentation tests

Add a focused documentation-governance test suite, for example:

```text
tests/redesign/test_week2_doc_state.py
```

Use the repository's existing testing conventions.

At minimum test:

### T-DOC-1 — every Week 2 process document has a state

Fail if a relevant Week 2 document has no declared classification.

---

### T-DOC-2 — superseded runbooks are visibly non-executable

Any historical/superseded document containing runbook-like GPU commands must include:

```text
DO NOT EXECUTE
```

and point to:

```text
docs/WEEK2_DOC_INDEX.md
```

or the current session #2 plan.

---

### T-DOC-3 — only one current GPU runbook

The repository should have exactly one document classified as the active Week 2 GPU-session runbook:

```text
docs/WEEK2_GPU_SESSION_2_PLAN.md
```

---

### T-DOC-4 — active docs reject stale headline semantics

Current executable/authoritative docs must not assert:

```text
headline fixed window = 120s
n >= 100 is sufficient
post-hoc warmup re-filtering is valid
prefix caching enabled
majority vote resolves repeats
N=5000 is authorized
old 1.5/2/5 bracket is authoritative
402.3ms is definitive floor
```

Historical sections are allowed only when explicitly marked.

---

### T-DOC-5 — repeat policy matches human locks

Verify machine-readable policy reflects:

```text
3 repeats
unanimous agreement
2–1 = UNCERTAIN
N=4000
N=5000 unauthorized
cross-process combination forbidden
interval fallback
```

---

### T-DOC-6 — current execution chain is valid

Verify all files referenced by `WEEK2_DOC_INDEX.md` as current authority exist.

---

# 15. Negative controls for documentation governance

Follow the project's existing principle:

> A green check that has never gone red proves little.

Demonstrate that the new controls bite.

At minimum:

### C-DOC-1

Temporarily remove `DO NOT EXECUTE` from a superseded GPU runbook.

Expected:

```text
documentation test RED
```

Restore.

Expected:

```text
GREEN
```

---

### C-DOC-2

Temporarily change active session policy to:

```text
N=5000 authorized
```

Expected:

```text
repeat-policy/doc consistency test RED
```

Restore.

---

### C-DOC-3

Inject an active statement such as:

```text
resolve warmup after the run with --warmup-n
```

Expected:

```text
stale-semantics test RED
```

Restore.

---

### C-DOC-4

Mark two GPU runbooks as `EXECUTABLE`.

Expected:

```text
single-current-runbook test RED
```

Restore.

Record the red→green evidence in the cleanup report.

---

# 16. Fresh-context integration check

This is a required human-facing control.

After cleanup, run a fresh-context review whose only starting point is the repository root.

Prompt the reviewer/agent with the equivalent of:

> You have no prior Week 2 conversation context. Starting only from the root README, determine:
>
> 1. the current Week 2 state,
> 2. which documents are authoritative,
> 3. which document you would execute for the next GPU run,
> 4. the current N/repeat/warmup/preemption policies,
> 5. which documents are historical and must not be executed.

Expected answer must converge on:

```text
README.md
→ STATUS.md
→ WEEK2_DOC_INDEX.md

authority:
WEEK2_PLAN.md
WEEK2_EXECUTION.md

GPU execution:
docs/WEEK2_GPU_SESSION_2_PLAN.md

machine policy:
repeat_policy.json
```

If the reviewer chooses an old preflight/runbook or cannot identify the hierarchy unambiguously:

```text
R-DOC = FAIL
```

Fix the repository rather than coaching the reviewer.

---

# 17. Final pre-GPU evidence report

After the cleanup, produce:

```text
docs/WEEK2_GPU_SESSION_2_PREFLIGHT.md
```

This is a **short evidence checklist**, not another design document.

Include:

## Repository identity

```text
branch
commit SHA
origin status
working tree clean
```

## Documentation governance

```text
documents classified
current GPU runbooks = 1
stale-assumption scan = PASS
documentation tests = PASS
documentation controls = red→green
fresh-context test = PASS
```

## Human locks

```text
1A
2B
3A
4A
5A
6A
```

## Benchmark

```text
canonical workload verified
N = 4000
N=5000 unauthorized
60s frozen warmup
prefix caching disabled
nearest-rank p99
capacity proof PASS
max_model_len = 20000
```

## Regression

Record the new exact numbers after cleanup:

```text
non-router
router
redesign
controls
```

Do not copy the pre-cleanup counts blindly.

## Historical compatibility

```text
24/24 promoted hashes verify
R2 source records unchanged
historical schedules unchanged
canonical workload verifies
```

## Cloud state

```text
no GPU currently running
quota/billing/preflight state
teardown target verified
```

Finish with:

```text
HARD STOP R-DOC: READY FOR HUMAN VERDICT
HARD STOP R-PREGPU: READY ONLY AFTER R-DOC PASS
```

Do not self-authorize the GPU.

---

# 18. Required regression after cleanup

Run the complete relevant suite.

At minimum:

```text
full non-router suite
router tier
redesign suite
documentation-governance suite
negative-control demonstrations
legacy artifact verification
canonical workload verification
capacity proof
schedule verification
```

The pre-cleanup evidence was:

```text
non-router: 288 passed
router: 25 passed
redesign: 165 passed
controls: 13/13 red→green + live-server control
```

The cleanup must not reduce existing coverage or silently remove controls.

Any new totals must be recorded, not substituted into historical evidence packages.

---

# 19. Commit discipline

Do not mix the documentation cleanup with unrelated project work.

Recommended sequence:

```text
implement cleanup
      ↓
run stale scan
      ↓
run doc tests + controls
      ↓
run full regression
      ↓
fresh-context integration test
      ↓
produce preflight report
      ↓
human reviews R-DOC
```

After R-DOC passes:

```text
commit
push
verify origin
record exact SHA
```

That SHA becomes the candidate:

```text
WEEK2_BENCHMARK_SHA
```

Re-run the final preflight from that clean SHA.

Any code/document change after the benchmark SHA is approved requires:

```text
new commit
new SHA
re-run affected preflight
```

Do not benchmark a dirty tree.

---

# 20. Definition of Done — cleanup

This cleanup is complete only when all are true:

- [ ] `docs/WEEK2_DOC_INDEX.md` exists.
- [ ] Every Week 2 process document is classified.
- [ ] Exactly one current GPU session runbook exists.
- [ ] Historical executable-looking docs say `DO NOT EXECUTE`.
- [ ] Historical evidence remains preserved.
- [ ] Locks `1A / 2B / 3A / 4A / 5A / 6A` are committed into current authority.
- [ ] `repeat_policy.json` is no longer `PROPOSED`.
- [ ] N=5000 is explicitly unauthorized.
- [ ] Cross-process repeat mixing is explicitly forbidden.
- [ ] 60s warmup is represented as a frozen boundary requiring Tier-A validation.
- [ ] Post-hoc headline warmup re-filtering is absent from active instructions.
- [ ] Scout fallback `0.5 / 16` is pre-authorized.
- [ ] Natural-random, steady and adversarial remain in Week 2 scope.
- [ ] Repo-wide stale-assumption scan has zero unexplained stale hits.
- [ ] Documentation tests pass.
- [ ] Documentation negative controls have demonstrably gone red then green.
- [ ] Existing R4–R11 regression remains green.
- [ ] Historical hashes/artifacts remain unchanged.
- [ ] Fresh-context documentation test passes.
- [ ] Final session #2 preflight report exists.
- [ ] No GPU instance was created during this work.
- [ ] Human renders explicit **R-DOC PASS**.
- [ ] Changes are committed and pushed.
- [ ] Exact benchmark SHA is recorded.
- [ ] Human renders explicit **R-PREGPU PASS** before GPU creation.

---

# 21. Hard Stop R-DOC — agent output

At completion, halt and present only the evidence needed for review:

## Documentation map

```text
current authoritative docs
current executable docs
historical/superseded docs
```

## Stale-assumption audit

```text
hits inspected
current-correct
historical-explicit
stale corrected
unexplained = 0
```

## Policy confirmation

```text
1A PASS
2B PASS
3A PASS
4A PASS
5A PASS
6A PASS
```

## Tests

```text
documentation suite
full regression
control red→green evidence
legacy compatibility
```

## Fresh-context result

Show what document path the fresh-context reviewer selected.

## Git/cloud state

```text
working tree status
commit state
GPU instances = none
```

Then stop.

Do not begin GPU session #2.

---

# 22. Guiding principle

Week 2 now has a large amount of valuable historical evidence.

The goal is **not** to simplify the repository by deleting that history.

The goal is to make authority explicit:

```text
history stays
evidence stays
rationale stays

but only one execution path is live
```

The cleanup succeeds when an agent can learn from every previous Week 2 state without being able to accidentally execute one.
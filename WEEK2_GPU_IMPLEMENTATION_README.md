# Week 2 GPU Phase — Implementation README

> **STATUS: SUPERSEDED — DO NOT EXECUTE**
>
> Role: the GPU session **#1** runbook (Stage A/B sweep, post-hoc warmup resolution, teardown). Its Stage A/B design was falsified by the session it ran.
>
> Procedures in this document were valid before the Week 2 GPU redesign and
> **must not** drive GPU session #2.
> Current execution instructions: `docs/WEEK2_GPU_SESSION_2_PLAN.md`.
> Index: `docs/WEEK2_DOC_INDEX.md`.

## Purpose

This README is the execution handoff for wrapping up **Week 2: load generation & baseline**.

The design work and pre-GPU remediation are complete. The remaining work is:

1. freeze the exact benchmark revision,
2. run the real-vLLM GPU experiment,
3. bracket and fine-resolve the 500ms p99 TTFT breach,
4. preserve and verify all benchmark artifacts,
5. tear down the GPU,
6. resolve warmup `N` offline,
7. produce `BASELINE.md`,
8. close Week 2.

This document is procedural. Do **not** redesign already-locked Week 2 decisions.

Authoritative sources still take precedence:

1. `WEEK2_PLAN.md` — locked decisions and provenance.
2. `WEEK2_EXECUTION.md` — execution order and hard stops.
3. `docs/WEEK2_GPU_PREFLIGHT.md` — Hard Stop 4 evidence and GPU runbook.
4. `docs/WEEK2_REMEDIATION_REPORT.md` — remediation record.
5. `STATUS.md` — current phase/state.

If this README appears to conflict with an authoritative source on a locked decision, **stop and surface the conflict to the user. Do not silently reconcile it.**

---

# 1. Current state

Pre-GPU remediation is complete.

The remediation report records:

- Hard Stop 1 — open-loop architecture: **PASS**
- Hard Stop 2 — negative controls: **PASS**
- Hard Stop 3 — calibrations: **PASS**
- Hard Stop 4 — pre-GPU readiness: **PASS**
- GPU session ready: **YES**
- no GPU instance was created during remediation

The user has also explicitly confirmed the outstanding TTFT-persistence negative-control read.

Therefore, do **not** reopen the pre-GPU audit unless new evidence shows a regression.

---

# 2. Locked experiment values

Use these values unless the user explicitly changes a session-start choice before benchmark collection begins.

| Setting | Value |
|---|---|
| Headline metric | p99 TTFT |
| Breach threshold | 500ms |
| Secondary reference | 2s |
| Headline arrival process | seeded Poisson |
| Steady traffic | secondary reference |
| Stage A RPS | 2, 5, 10, 20, 30, 40, 60, 80 |
| Measurement window `Y` | 120s |
| Warmup `N` | 10s placeholder during collection; final value resolved offline |
| Offered-vs-achieved band | ±5% |
| Concurrency cap | 3000 |
| Linux scheduler spin | 0ms |
| Driver location | same GCP VM as vLLM |
| Driver network path | `127.0.0.1:8000` loopback |
| Linux fd target | `ulimit -n 65535` |
| Stage B generator | `scripts/generate_schedules.py` |
| GPU provisioning | Spot |
| Week 2 teardown | `scripts/gpu_session/teardown_week2.sh` |

The mock is **not** trusted for concurrent latency or saturation behavior. Do not use mock saturation to predict real-vLLM Stage A behavior.

---

# 3. Session-start defaults

## 3.1 Output-token policy

Default recommendation:

```json
{"max_tokens": 512}
```

Interpretation:

- this is a **ceiling**, not a forced output length;
- normal EOS may terminate earlier;
- use the same output policy across Stage A, Stage B, and steady reference;
- do not silently vary output-token policy between comparable points.

## 3.2 `--enforce-eager`

Default policy:

1. First attempt vLLM **without `--enforce-eager`**.
2. Before collecting benchmark data, verify:
   - vLLM becomes healthy,
   - one sanity request succeeds,
   - no code change is required.
3. If non-eager works, use non-eager for the entire Week 2 baseline.
4. If non-eager fails, **do not automatically fall back**.
5. Surface the failure evidence and prompt the user for approval to restart with `--enforce-eager`.
6. If approved, restart once using the known-working eager configuration.
7. Never mix eager and non-eager benchmark points in one baseline.

---

# 4. Approval protocol

The user is **not** running with `--dangerously-skip-permissions`.

Whenever this README marks a step as **USER APPROVAL REQUIRED**, the agent must:

1. summarize the evidence needed for the decision,
2. state the exact action it proposes to take,
3. explicitly ask the user to approve or reject it,
4. stop at that point,
5. do not continue until approval is received.

Use a concise prompt such as:

> **Approval required:** I am ready to create the Week 2 Spot L4 using benchmark SHA `<sha>`. Preflight checks are green. Approve GPU creation?

Do not treat silence, previous approval for a different gate, or your own confidence as approval.

Approval is scoped to the action named in the prompt.

---

# 5. Phase E-1 — Freeze the benchmark revision

The GPU run does **not** require the Week 2 branch to be merged to `main`.

The benchmark must use one exact, clean, pushed commit SHA.

## Agent tasks

1. Inspect the current repository state.
2. Confirm that all code required for the Week 2 GPU experiment exists in one branch/history.
3. Confirm no unrelated uncommitted changes are required for the experiment.
4. Confirm the working tree is clean.
5. Confirm the benchmark commit is pushed to `origin`.
6. Record:
   - branch name,
   - commit SHA,
   - remote state.

Do not merge or rebase merely to prepare for benchmarking.

Once the benchmark SHA is declared, any code change creates a new benchmark revision and must be surfaced.

## USER APPROVAL REQUIRED — benchmark SHA

Present:

- branch,
- exact SHA,
- confirmation that it is pushed,
- confirmation that the working tree is clean,
- short summary of what the SHA contains.

Prompt the user:

> **Approval required:** Approve `<sha>` as the frozen Week 2 benchmark revision?

Do not create the GPU before this is approved.

---

# 6. Phase E0 — GPU creation and startup

## USER APPROVAL REQUIRED — GPU creation

Before creating the instance, confirm:

- benchmark SHA approved,
- Spot configuration staged,
- target instance/zone staged,
- Week 2 teardown wrapper available,
- Stage A schedules available,
- output policy fixed,
- eager policy fixed,
- no known blocker is open.

Then prompt:

> **Approval required:** Preflight is green and benchmark SHA `<sha>` is frozen. Approve creation of the Week 2 Spot L4 instance?

Do not create the GPU before approval.

## After approval

Follow the existing GPU-session scripts/runbook.

Expected properties:

- Week 2 instance target,
- Spot provisioning,
- expected L4 machine configuration,
- exact approved SHA checked out in detached HEAD,
- separate vLLM and loadgen environments,
- load generator running on-instance,
- vLLM reachable over `127.0.0.1:8000`,
- fd limit raised and verified,
- Linux scheduler spin = 0ms.

The loadgen talks to vLLM over **loopback**. This means both processes run on the same GCP VM and communicate through localhost; traffic does not travel through the GPU itself and does not traverse the WAN/SSH tunnel.

---

# 7. Phase E0.1 — vLLM configuration canary

Attempt the preferred non-eager configuration first.

Before benchmark collection:

1. launch vLLM without `--enforce-eager`,
2. wait for health,
3. send one non-benchmark sanity request,
4. verify the response path works,
5. verify the mock→vLLM swap still requires configuration only.

If it succeeds:

- record non-eager as the session configuration,
- continue.

If it fails:

- capture the relevant startup/runtime error,
- do not patch source,
- do not silently add `--enforce-eager`.

## USER APPROVAL REQUIRED — eager fallback

Prompt:

> **Approval required:** Non-eager vLLM failed before benchmark collection with `<brief failure>`. The known-working fallback is `--enforce-eager`. Approve restarting vLLM in eager mode for the entire Week 2 baseline?

If rejected, stop the experiment and preserve the evidence.

If approved, restart once in eager mode and keep that mode fixed for every benchmark point.

If any **source-code change** is required to make vLLM work, stop and tell the user. A code change on-meter is a finding, not a routine fix.

---

# 8. Phase E1 — Stage A coarse sweep

Drive the committed Stage A Poisson schedules:

```text
2, 5, 10, 20, 30, 40, 60, 80 RPS
```

Do not redesign the Stage A range before data requires it.

For each completed point, immediately verify and report:

- offered RPS,
- achieved RPS,
- divergence percentage,
- p99 TTFT,
- p99 TPOT,
- post-warmup sample count,
- tail-validity result,
- shed count,
- errored request count,
- raw-log presence,
- sample-sidecar presence,
- metrics-record presence.

Maintain a running table:

| Offered | Achieved | Divergence | Samples | p99 TTFT | Shed | Errors | Valid | vs 500ms |
|---:|---:|---:|---:|---:|---:|---:|---|---|

## Validity rules

- `n_shed_total` should be `0`.
- Any `shed > 0` is a finding.
- Missing TTFT sidecar makes the point unusable.
- Offered-vs-achieved divergence beyond ±5% is flagged.
- Flagged points are kept and use achieved RPS under Option Y.
- Tail-invalid points are not used as valid p99 estimates.
- Do not hide errors or invalid points.

---

# 9. HARD STOP 5 — Stage A bracket

The agent may identify a **candidate** bracket but may not declare the experiment bracketed on its own.

A candidate bracket requires:

- one valid point clearly below 500ms p99 TTFT,
- one valid point clearly at/above 500ms p99 TTFT.

## USER APPROVAL REQUIRED — Stage A bracket

When a candidate exists, stop and present:

- lower point,
- upper point,
- p99 TTFT for both,
- achieved/offered validity for both,
- sample validity,
- shed/errors,
- proposed Stage B resolution.

Prompt:

> **Approval required:** Stage A appears bracketed between `<low>` RPS and `<high>` RPS. Approve this bracket and generation of the proposed Stage B fine sweep?

Do not generate/run Stage B until approved.

---

# 10. Stage A exceptional paths

## Case A — entire Stage A is below 500ms

Propose additional higher RPS points.

## USER APPROVAL REQUIRED — upward extension

Prompt:

> **Approval required:** Stage A did not cross 500ms through 80 RPS. I propose extending the coarse sweep to `<points>`. Approve these additional metered points?

Do not run them without approval.

## Case B — first meaningful point is already above 500ms

Propose lower points.

## USER APPROVAL REQUIRED — downward extension

Prompt:

> **Approval required:** The breach is already present at the lowest meaningful Stage A point. I propose adding lower points `<points>` to establish an under-SLO anchor. Approve?

## Case C — unexpected measurement behavior

Examples:

- material achieved-RPS collapse,
- non-zero shedding,
- repeated request errors,
- missing sidecars,
- corrupt metrics,
- server instability,
- configuration drift,
- unexpected source-code requirement.

Do not improvise a new experiment.

Recommend the escape hatch:

1. preserve/pull artifacts,
2. stop collection,
3. tear down,
4. analyze offline.

## USER APPROVAL REQUIRED — escape hatch / continuation

Present the evidence and ask whether to:

- retry a clearly identified failed point,
- continue,
- or terminate the GPU session and analyze offline.

Do not make that metered-session judgment silently.

---

# 11. Phase E2 — Stage B fine sweep

After the user approves the Stage A bracket:

1. generate fine-grained RPS points **between the approved bracket endpoints**,
2. use `scripts/generate_schedules.py`,
3. do not edit tracked source,
4. preserve all workload locks,
5. verify schedule provenance before running.

Keep fixed:

- benchmark SHA,
- model,
- vLLM configuration,
- eager/non-eager mode,
- `max_tokens`,
- corpus,
- RNG scheme,
- warmup placeholder,
- measurement window,
- concurrency cap,
- Linux spin setting.

The agent may generate and run the **approved** Stage B schedule set without asking for approval point-by-point.

If the fine sweep reveals that the approved bracket was invalid or insufficient, stop and return to the user rather than extending silently.

---

# 12. Phase E3 — steady reference

After the Poisson breach is fine-resolved:

- run the planned steady reference,
- keep the same comparable configuration,
- treat it as secondary context,
- do not redefine the headline breach using steady traffic.

No additional approval is needed if this is the already-approved locked Week 2 sequence.

---

# 13. Phase E4 — adversarial scenario

Run adversarial **last**.

Reason:

- it intentionally stresses the replica,
- it may leave the server/cache/scheduler in a degraded state,
- baseline and steady data must already be durable first.

Do not use adversarial traffic to redefine the headline Week 2 breach.

No additional approval is needed if this is the already-approved locked Week 2 sequence.

---

# 14. Artifact protection before teardown

Before recommending teardown:

1. pull all run artifacts locally,
2. verify each expected point has:
   - frozen schedule/provenance,
   - raw log,
   - TTFT/TPOT samples sidecar,
   - point metrics,
3. reconcile request counts,
4. flag missing sidecars,
5. flag any `shed > 0`,
6. flag unreadable metrics,
7. confirm local copies exist.

Report:

```text
ARTIFACT SET COMPLETE: YES
```

or:

```text
ARTIFACT SET COMPLETE: NO
Missing/invalid:
- ...
```

If the artifact set is incomplete, identify exactly what can still be recovered or re-run while the instance exists.

Do not recommend teardown while required evidence only exists on the ephemeral VM.

---

# 15. USER APPROVAL REQUIRED — teardown

Once the artifact set is complete, prompt:

> **Approval required:** All required Week 2 GPU artifacts are verified locally. Approve teardown of `llmrouter-vllm-l4-week2` using `scripts/gpu_session/teardown_week2.sh`?

Only after approval:

- run the Week 2 teardown wrapper,
- never use bare `scripts/teardown.sh`,
- verify deletion rather than trusting the delete command's exit code.

Report the final cloud state.

The metered session is closed only when the instance is confirmed absent.

---

# 16. Block F — offline analysis

After teardown, GPU spend is over.

The agent now owns the mechanical analysis.

## 16.1 Generate the warmup transient

From the durable per-request samples, produce the Stage A TTFT-vs-wall-clock transient needed to determine where startup/load-transition effects flatten.

Do not silently assign the final warmup `N`.

## USER APPROVAL REQUIRED — warmup `N`

Present:

- transient plot,
- candidate flatten point,
- short explanation of why it appears stable,
- any ambiguity.

Prompt:

> **Approval required:** The Stage A transient appears to flatten at approximately `<N>` seconds. Approve `warmup N = <N>s` for the final Week 2 recomputation?

Do not finalize the baseline until the user approves a value.

Changing `N` does **not** require another GPU run.

Apply the approved value by metrics-side re-filtering over the committed sidecars.

---

# 17. Final recomputation

Using the approved warmup `N`, recompute all accepted points from durable artifacts.

Apply:

- final warmup filter,
- ≥100 achieved-sample validity rule,
- ±5% offered-vs-achieved gate,
- Option Y x-axis handling,
- shed/error flags,
- 500ms headline threshold,
- 2s secondary reference.

Resolve:

> **Breach RPS = the lowest valid fine-sweep RPS whose full-window p99 TTFT is ≥500ms.**

Do not report interpolation as measured fact.

If the fine sweep only resolves the crossing to a certain step size, state that resolution explicitly.

---

# 18. `BASELINE.md`

Produce the Week 2 deliverable containing:

- the statement:
  - **“At X RPS, naive single-replica serving breaches the 500ms p99 TTFT SLO.”**
- Poisson headline curve,
- steady reference,
- 500ms SLO line,
- 2s severe-degradation line,
- unloaded TTFT floor,
- realized prompt-length histogram,
- final warmup `N` + provenance,
- offered-vs-achieved behavior,
- invalid/flagged-point handling,
- output-token policy,
- eager/non-eager setting,
- vLLM/model configuration,
- benchmark SHA,
- corpus provenance,
- frozen-schedule provenance,
- artifact references sufficient to reproduce the result.

Include the locked prompt-tail interpretation:

> Prompt-length variation is held fixed across the sweep, so the prompt-length contribution sets part of the curve's floor while movement as offered RPS increases is attributed to load.

---

# 19. Week 2 closeout

After `BASELINE.md` is complete:

1. verify the baseline can be reproduced from the preserved artifacts,
2. update `STATUS.md` to mark Week 2 complete,
3. record the final benchmark SHA and accepted evidence paths,
4. review the Week 2 PR(s),
5. merge the required Week 2 work to `main` only after the benchmark result is preserved,
6. archive/move completed process documents if that matches the repo's existing convention,
7. do not begin Week 3 implementation as part of this handoff.

If merging introduces changes beyond the benchmark SHA, preserve the benchmark SHA explicitly as the revision that produced the Week 2 baseline.

---

# 20. Definition of done

Week 2 is complete only when all of the following are true:

- [ ] exact benchmark SHA frozen and recorded
- [ ] GPU configuration recorded
- [ ] Stage A produced a valid 500ms bracket
- [ ] Stage B fine-resolved the crossing
- [ ] steady reference completed
- [ ] adversarial scenario completed
- [ ] required artifacts verified locally
- [ ] GPU instance verified deleted
- [ ] warmup `N` approved from GPU transient data
- [ ] final metrics recomputed offline
- [ ] `BASELINE.md` states the measured breach RPS
- [ ] evidence/provenance is sufficient for deterministic workload replay
- [ ] `STATUS.md` marks Week 2 closed
- [ ] Week 2 code is ready to merge/merged without losing the benchmark SHA provenance

---

# Agent operating rule

Use this rule throughout the phase:

> **If the next action is mechanical and already authorized by the locked experiment, execute it and report evidence. If it spends/continues metered GPU time under a new decision, changes the experiment, crosses a hard stop, selects a calibration value, or destroys the GPU environment, prompt the user for explicit approval and stop until approved.**

During the GPU session:

> **Measure, validate, record, and surface decisions — do not redesign on the meter.**

# Week 2 — Final Pre-GPU Remediation Plan

> **STATUS: EVIDENCE — DOES NOT GOVERN GPU EXECUTION**
>
> Role: the final GPU-free remediation brief (Phases A–G) and its change
> ledger. It records what this pass was required to close and what actually
> landed. It decides no experiment semantics and is **not** a GPU runbook —
> current GPU commands live in `WEEK2_GPU_SESSION_2_PLAN.md`.
> Index: `WEEK2_DOC_INDEX.md`.

> **Goal:** close the remaining Session #2 execution and classification gaps, re-freeze the repository under one new benchmark SHA, and reach a state where the Week 2 GPU run can start without further design work.
>
> **Scope:** this is the final GPU-free remediation pass. Do not create a GPU instance while executing this plan.
>
> **Review model:** no human hard-stop reviews are required in this pass. Use independent subagents for targeted review of each completed workstream, then run one final cross-cutting review before commit/push.

---

## 0. Starting state

The Tier A remediation already established the right architecture:

- Session #2 scout and headline runs share a redesign-aware execution/metrics path.
- Frozen schedules are authoritative; replay no longer depends on legacy `master_seed`.
- Scout/headline evidence authority is explicit through `evidence_class`.
- Prefix-cache-disabled verification is required before scout execution.
- Existing benchmark/corpus artifacts were not modified.

The remaining work is to close:

1. headline classification fail-open behavior;
2. exact-N percentile membership semantics;
3. unloaded-floor execution;
4. frozen steady/adversarial execution;
5. end-to-end session contract coverage;
6. documentation/preflight refresh and final repository freeze.

---

# Phase A — Make headline classification fail closed

## Required change

`metrics/classification.py` must accept a point for Session #2 headline classification **only** when the record explicitly proves that it is valid headline evidence.

At minimum require:

- `evidence_class == "headline_evidence"`
- `may_define_headline_breach == true`
- canonical headline membership id
- expected Session #2 headline schedule scheme/version
- `n_per_run == 4000` / expected headline N
- required delivery / exact-N / censoring gates clean
- repeat-policy compatibility where the classifier has access to it

Missing or unknown provenance must **not** default to headline evidence.

### Required rejection behavior

Reject:

- `scout_diagnostic`
- missing `evidence_class`
- unknown `evidence_class`
- Session #1 / legacy records
- scout membership passed through the headline driver
- mismatched schedule scheme/version
- mismatched expected N

Historical evidence remains readable through diagnostic/legacy analysis code, but it must not be eligible for Session #2 headline classification.

## Required tests

Add controls proving:

1. valid Session #2 headline record is accepted;
2. scout record is rejected;
3. missing `evidence_class` is rejected;
4. legacy Session #1 record is rejected;
5. scout schedule cannot become headline evidence merely by being passed through a headline entry point;
6. incorrect headline membership is rejected.

## Subagent review

Assign an independent reviewer to inspect only:

- `metrics/classification.py`
- evidence-stamping logic
- headline/scout workload identity checks
- relevant tests

Reviewer question:

> Can any non-headline, legacy, missing-provenance, or scout artifact still enter the Session #2 final classification family?

Do not proceed until the subagent reports **no fail-open path**.

---

# Phase B — Make exact-N percentile membership schedule-based

## Required invariant

The requests used to compute p99 must be determined by the **frozen schedule membership**, not by when the request happened to be sent.

For a frozen boundary `warmup_boundary_s`:

```text
measurement_member(request) :=
    scheduled_offset >= warmup_boundary_s
```

Actual `send_time` is delivery-fidelity evidence only.

A warmup request scheduled before the boundary remains a warmup request even if scheduling lag causes its actual send to occur after the boundary.

A measurement request scheduled after the boundary remains part of the canonical measurement population even if it is delivered late; if delivery becomes unacceptable, invalidate the point rather than silently dropping the request.

## Required accounting

Make the runtime record expose enough information to verify the invariant. Prefer explicit fields such as:

- `expected_measurement_n`
- `reconciled_measurement_n`
- `percentile_population_n`
- `exact_n_honoured`
- `schedule_delivery_ok`

Exact names may follow existing conventions, but the three populations must be inspectable.

For the current workloads:

- scout percentile population = exactly **500**
- headline percentile population = exactly **4000**

## Required tests

Add a synthetic boundary test:

- 10 requests are scheduled just before the warmup boundary;
- all 10 are intentionally delivered after the boundary;
- the 10 warmup requests have extreme TTFT values;
- N canonical post-warmup requests have normal TTFT values.

Prove:

- wall-clock sends after boundary may exceed N;
- percentile population remains exactly N;
- late warmup requests do not affect p99;
- delivery diagnostics still see the lag.

Add the reverse control:

- a canonical measurement request is delivered very late;
- it remains in canonical membership;
- bad delivery causes the appropriate validity gate to fail instead of shrinking N.

## Subagent review

Assign an independent reviewer to inspect:

- `loadgen/redesign_point.py`
- `metrics/headline_point.py`
- request-id joins/filtering
- schedule provenance/membership logic
- exact-N and delivery tests

Reviewer question:

> Can actual send timing change which request IDs enter the p99 estimator?

Required answer: **No.**

---

# Phase C — Add the canonical unloaded-floor execution path

## Required command

Add a dedicated Session #2 command:

```bash
bash scripts/gpu_session/run_on_instance.sh floor
```

Do not route the unloaded floor through a Poisson/steady RPS schedule merely for convenience.

## Floor semantics

The floor must execute:

- canonical headline workload membership
- all **4,000** canonical prompts
- concurrency = **1**
- prefix caching verified disabled
- same model/server configuration as Session #2
- stop measurement at first content token where already specified by the Session #2 plan
- no headline queueing interpretation; this is an unloaded intrinsic-floor measurement

## Required artifacts

Produce durable floor artifacts using the normal Session #2 artifact discipline, e.g.:

- `floor.raw_log.jsonl`
- `floor.samples.jsonl`
- `floor.metrics.json`

Record at minimum:

- benchmark SHA
- canonical membership id
- corpus hash
- N = 4000
- concurrency = 1
- prefix-cache verdict reference
- process epoch
- resolved server configuration

## Tests

Add a GPU-free/mock smoke test proving:

- command exists;
- canonical membership is used;
- N = 4000 is enforced;
- concurrency = 1 is enforced;
- required artifacts are produced;
- prefix-cache gate is required.

## Subagent review

Reviewer question:

> Does the floor measure the same canonical workload as the headline experiment without accidentally introducing an arrival-process or alternate-membership dependency?

---

# Phase D — Freeze steady and adversarial Session #2 inputs

## Required artifacts

Commit the missing Session #2 schedule/input families under the redesign namespace:

```text
benchmarks/schedules/week2_redesign/
    scout/
    headline/
    secondary_natural/
    secondary_steady/
    adversarial/
```

Do not generate the steady or adversarial workload live on the GPU instance.

The GPU session must only drive frozen committed inputs.

## Steady requirements

Freeze the steady-arrival reference with:

- explicit scenario namespace
- committed schedule files
- frozen warmup boundary
- expected post-warmup N
- membership/corpus identity
- arrival-process provenance
- schedule/RNG scheme provenance as applicable

Use the already-decided steady points from the Session #2 plan/runbook. If the current authoritative documents do not specify exact steady λ values, surface that as a **design conflict** rather than inventing them.

## Adversarial requirements

Freeze the adversarial scenario with:

- explicit adversarial namespace
- fixed long-context selection semantics
- committed workload/schedule artifact
- frozen warmup and N
- explicit arrival/pacing semantics
- membership/corpus identity
- provenance for selection rule/version and seeds

Do not turn adversarial into a length sweep.

## Runtime

Add explicit commands such as:

```bash
bash scripts/gpu_session/run_on_instance.sh steady ...
bash scripts/gpu_session/run_on_instance.sh adversarial ...
```

or an equivalent scenario-aware dispatcher.

The runtime must reject mismatched scenario/schedule types rather than infer roles from filenames or directories.

## Tests

Prove:

- every committed steady/adversarial artifact validates;
- wrong scenario command refuses the artifact;
- generated artifacts are deterministic/reproducible under their defined scheme;
- all schedule/input hashes are represented in manifests;
- no live schedule generation is needed during the GPU session.

## Subagent review

Reviewer question:

> Can every secondary scenario in the Session #2 runbook be executed from a frozen committed input with no on-meter generation or semantic choice?

---

# Phase E — Add a full Session #2 execution-contract test

Create one GPU-free contract test that validates the runbook as an executable system, not just individual functions.

## Required stages

The test must verify that each required stage has:

- a real command;
- a valid input;
- the expected schedule/workload role;
- required output artifacts;
- correct evidence authority.

Cover:

1. prefix-cache verification gate;
2. unloaded floor;
3. Tier A scout;
4. Tier B headline family;
5. natural-random secondary;
6. steady secondary;
7. adversarial;
8. artifact pull/completeness path;
9. teardown command target/dry-run.

## Required cross-role controls

Prove at least:

- v2 scout schedule rejected by legacy `run`;
- legacy/v1 schedule rejected by `scout`;
- scout input rejected by headline authority;
- headline input cannot be stamped as scout and later classify;
- steady/adversarial scenario inputs cannot be misrouted;
- missing prefix-cache verdict blocks every scenario that requires it.

This is the final guard against a repeat of the original failure where the documentation named a valid-looking command that had never been exercised against the actual Session #2 artifact.

## Subagent review

Use a reviewer that did not implement Phases A–D.

Reviewer task:

> Starting only from `WEEK2_GPU_SESSION_2_PLAN.md`, follow every documented Session #2 command and verify that the code and committed artifacts can execute the whole session without inventing a value, generating a workload live, or entering a legacy measurement path.

---

# Phase F — Clean stale semantics and refresh active documentation

Update only active documentation/help/comments affected by the implementation.

At minimum verify:

- `WEEK2_GPU_SESSION_2_PLAN.md`
- `WEEK2_PLAN.md`
- `WEEK2_EXECUTION.md`
- `WEEK2_GPU_SESSION_2_PREFLIGHT.md` / current preflight document
- `STATUS.md`
- `scripts/README.md`
- active `.py` / `.sh` help/comments

Remove or explicitly mark stale semantics including:

- post-hoc warmup re-filter as a valid Session #2 resolution;
- legacy `master_seed` replay assumptions;
- superseded `stage-a` execution instructions;
- old test counts;
- old benchmark SHA.

Extend the active-state stale-semantic scan beyond Markdown to active Python/shell help/comments if not already covered.

Do not rewrite historical evidence or archived documents merely to make the scan green; exclude historical/fixture material explicitly where appropriate.

---

# Phase G — Regression, independent review, and freeze

## 1. Run all GPU-free verification

At minimum:

```text
full non-router suite
router suite
redesign suite
documentation suite
gpu_session suite
redesign negative controls
documentation negative controls
promoted evidence hash verification
schedule/input manifest verification
```

Also run the new full Session #2 execution-contract test independently.

No GPU instance may be created.

## 2. Independent final subagent review

Use a fresh reviewer with the following brief:

> Audit the final tree for any remaining path by which:
> - scout/legacy evidence can enter headline classification;
> - actual send time can alter exact-N percentile membership;
> - any Session #2 stage lacks an executable command/input;
> - any runbook command routes through legacy Session #1 semantics;
> - any workload must be generated or decided while the GPU meter is running;
> - any active documentation contradicts the final code.

Require a file/line reference for every issue found.

Resolve all findings and rerun affected tests.

## 3. Freeze

When green:

1. commit all remediation changes;
2. push the commit;
3. record the new benchmark SHA;
4. verify the working tree is clean;
5. verify the pushed remote contains HEAD;
6. regenerate/update only manifests or documentation that are supposed to bind the new SHA;
7. rerun hash verification after the final commit;
8. confirm cloud state still has no GPU instance.

At this point the repository is the frozen input to the GPU session.

---

# Final go/no-go checklist

The GPU run may start only when all are true:

- [ ] Session #2 headline classifier fails closed.
- [ ] Scout/legacy/missing-provenance artifacts cannot classify.
- [ ] Headline workload identity is independently verified.
- [ ] Exact-N p99 membership is based on frozen scheduled request IDs.
- [ ] Late warmup sends cannot enter the percentile population.
- [ ] Scout percentile population is exactly 500.
- [ ] Headline percentile population is exactly 4000.
- [ ] Delivery lag affects validity, not workload membership.
- [ ] Dedicated unloaded-floor command exists and is tested.
- [ ] Steady inputs are frozen, committed, and runnable.
- [ ] Adversarial inputs are frozen, committed, and runnable.
- [ ] Every Session #2 runbook stage has a tested executable path.
- [ ] No Session #2 stage routes through legacy measurement semantics.
- [ ] Prefix-cache-disabled gate remains structural.
- [ ] All regression and negative-control suites are green.
- [ ] All benchmark/corpus/schedule manifests verify.
- [ ] Final independent subagent audit reports no blocker.
- [ ] Tree is clean and HEAD is pushed.
- [ ] New benchmark SHA is recorded in active preflight/runbook state.
- [ ] No GPU instance exists yet.

---

# Change Ledger — fill in as work lands

Every implementation step must be appended here with concrete code references so the final GPU-session handoff can be audited quickly.

| ID | Change | Why | Code reference(s) | Tests / evidence | Status |
|---|---|---|---|---|---|
| A1 | Headline classifier fails closed | Prevent scout/legacy/missing provenance from defining breach | `metrics/classification.py:187` `HeadlineEvidenceSpec`, `:226` `_headline_evidence_only` | `test_headline_evidence_gate.py` — 25 controls | **DONE** |
| A2 | Headline workload identity enforcement | Driver role alone must not confer headline authority | `metrics/classification.py:226`; expectation read from frozen artifacts via `HeadlineEvidenceSpec.from_frozen` | `test_control_the_scout_workload_cannot_become_headline_evidence_by_being_stamped` | **DONE** |
| A3 | Validity gates required *present*, not defaulted | `record.get(gate, True)` read an uncomputed gate as a passing one | `metrics/classification.py:226`, and direct indexing in `classify_point` | `test_control_an_absent_validity_gate_is_rejected_not_assumed_passing` | **DONE** |
| A4 | Tail-review gate derived, not trusted | `.get("tail_censoring_warning")` → `None` → falsy let a boundary point finalize with 3% censoring and no review | `metrics/classification.py:396` | `test_control_an_unstamped_tail_warning_cannot_finalize_a_boundary_point` | **DONE** *(review finding)* |
| A5 | λ key cross-checked against the record | `resolve_breach` reported the interval at the caller's dict key; no loader builds that dict | `metrics/classification.py:471` | `test_control_a_mis_keyed_lambda_is_refused_by_resolve_breach` | **DONE** *(review finding)* |
| A6 | Producer default is least-privilege | `evidence_class` defaulted to `HEADLINE_EVIDENCE`; silence granted authority | `metrics/headline_point.py` — default is now `SCOUT_DIAGNOSTIC` | `test_evidence_class_changes_authority_and_nothing_else` | **DONE** *(review finding)* |
| A7 | Lock 3A made enforceable | No record carried a process epoch and `vllm_restarted_between_repeats` was a hardcoded `False` | `metrics/classification.py:333`, `loadgen/repeat_runner.py:87`, `drive_headline_family.py` `server_process_epoch()` | `test_control_repeats_from_two_process_epochs_are_refused`, `test_control_a_restart_between_repeats_is_reported_not_asserted_away` | **DONE** *(review finding)* |
| B1 | Schedule-based percentile membership | Preserve exact-N estimator population | `metrics/headline_point.py:116` `measurement_membership`; caller passes frozen offsets from `loadgen/redesign_point.py` | `test_exact_n_membership.py` — 15 controls | **DONE** |
| B2 | Separate delivery-fidelity accounting | Late sends invalidate delivery, not membership | `metrics/headline_point.py` — `expected_/reconciled_/percentile_population_n`, `late_warmup_sends`, `max_send_lag_s` | `test_the_lag_is_still_visible_as_a_diagnostic`; real λ=16 scout drive reconciles 500/500 at 0.0% with `late_warmup_sends > 0` | **DONE** |
| B3 | Shed canonical requests counted as censored | Excluding them subtracted them from the denominator: 4% shed read as 0.0% censoring | `metrics/headline_point.py:340` | `test_control_shed_canonical_requests_count_as_censored` | **DONE** *(review finding)* |
| B4 | Warmup value must equal the frozen boundary | A smaller value selected nothing while the record claimed it applied | `metrics/headline_point.py` — both-direction guard | `test_control_a_warmup_value_below_the_frozen_boundary_is_refused` | **DONE** *(review finding)* |
| C1 | Dedicated unloaded-floor driver | Make runbook step 3 executable | `scripts/gpu_session/drive_unloaded_floor.py`, `metrics/floor_point.py:51` | `test_unloaded_floor.py` — 10 controls | **DONE** |
| D1 | Frozen steady inputs | Remove on-meter schedule generation | `scripts/generate_secondary_scenarios.py`; `benchmarks/schedules/week2_redesign/secondary_steady/` — 5 schedules | `SECONDARY_SCENARIOS_MANIFEST.json`; `--verify` reproduces byte-for-byte | **DONE** |
| D2 | Frozen adversarial inputs | Remove on-meter scenario generation | same generator; `adversarial/adversarial_rps2.schedule.json` | `test_the_adversarial_draw_really_comes_from_the_long_context_tail` | **DONE** |
| D3 | Scenario-aware runtime dispatch | Enforce scenario/input compatibility from provenance, never from path | `scripts/gpu_session/scenario_contract.py:86`, `check_scenario.py`, `drive_scenario_point.py` | `test_secondary_scenarios.py` — 8 misrouting controls incl. scout↔headline | **DONE** |
| E1 | Full Session #2 contract test | Exercise actual runbook seams end to end | — | `test_session2_contract.py` — 34 controls | **DONE** |
| F1 | Active stale-semantic cleanup | Prevent old semantics from guiding execution | `tests/redesign/test_week2_doc_state.py` — `ACTIVE_CODE`, `scan_text(..., code=True)` | `test_active_code_does_not_assert_stale_headline_semantics`, plus its non-vacuity control | **DONE** |
| F2 | Scan reads code comments at all | `#` was parsed as a Markdown heading, so in `.py`/`.sh` every comment was a heading and none were scanned — green and inert | `tests/redesign/test_week2_doc_state.py` `iter_units(..., code=)` | `test_control_the_code_scan_catches_the_defect_it_was_built_from` | **DONE** *(caught by its own control)* |
| G1 | Final benchmark SHA / preflight refresh | Freeze exact code that drives GPU | `STATUS.md`, `WEEK2_GPU_SESSION_2_PREFLIGHT.md` superseded-numbers section, `WEEK2_GPU_SESSION_2_PLAN.md` §1/§2/§8/§11 | clean tree + origin verification | **PENDING COMMIT** |

### Design decisions surfaced rather than invented

Phase D §261 required surfacing a design conflict instead of filling it in.
`WEEK2_PLAN.md` §2.1 constrains the *shape* of the steady and adversarial
scenarios and names a λ for neither; no other authoritative document does. Both
operating points were put to the human and decided **2026-08-21**:

| Scenario | Decision | Recorded rationale |
|---|---|---|
| Steady | λ ∈ {1.5, 2, 2.5, 3, 4}, session #2 exact-N mechanics (N=500, 60s frozen boundary) | Same operating points as the headline curve, so the only difference is Poisson vs fixed intervals — an arrival-process comparison rather than a second experiment. A 2/3/4 subset saves little and weakens the comparison |
| Adversarial | One point, λ=2, 600s | The purpose is to show what a long-context-heavy workload does, not to build a second breach curve. λ=5 would likely collapse into a trivial saturation/censoring result; λ=2 sits in the expected headline neighbourhood, where the q90 selection already supplies the pressure |

Both are recorded in `WEEK2_GPU_SESSION_2_PLAN.md` §8 and in the generator's
module docstring, so the reasoning travels with the artifacts.

## Final implementation summary

Before starting the GPU, replace this section with:

- **Commit / benchmark SHA:** `<sha>`
- **Files changed:** `<count>`
- **Benchmark inputs changed:** `<yes/no; list only intentional new steady/adversarial artifacts>`
- **Canonical headline membership:** `<id>`
- **Canonical scout membership:** `<id>`
- **Regression result:** `<summary>`
- **Negative controls:** `<summary>`
- **Independent subagent audit:** `<PASS / findings resolved>`
- **Remaining known blockers:** `none`
- **GPU session status:** `READY`

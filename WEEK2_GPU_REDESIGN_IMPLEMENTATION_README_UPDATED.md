# Week 2 GPU Baseline Redesign — Agent Implementation README

> **STATUS: HISTORICAL — DO NOT EXECUTE**
>
> Role: the R0–R3 implementation brief. Already executed; the evidence is `docs/WEEK2_R4_EVIDENCE_PACKAGE.md`.
>
> This document records an earlier Week 2 state. It is preserved for
> provenance, and nothing in it may drive GPU session #2.
> Current entry point: `docs/WEEK2_DOC_INDEX.md`.

**Revision:** post-review update incorporating closed-loop stop-condition, sub-5% censoring, dual-source bootstrap, bounded-UNCERTAIN, and regression/legacy-compatibility guards.

## Purpose

This document is the implementation handoff for the Week 2 GPU baseline redesign.

The first GPU session did **not** invalidate the load generator, replay model, GPU plumbing, or the 500ms p99 TTFT objective. It exposed a narrower experimental-design problem:

> The original fixed-duration + independently sampled natural-ShareGPT design did not hold the **realized prompt tail** or the **p99 evidence quality** constant enough to support a defensible breach-RPS claim.

The redesign therefore changes the **statistical/workload layer**, not the underlying open-loop architecture.

The agent should implement the redesign in two stages:

1. **Offline redesign + calibration tooling** — no GPU spend.
2. **Schedule/runtime/metrics changes after human sign-off on the calibrated workload values.**

Do **not** start, create, drive, or tear down a GPU instance as part of this task.

---

## 1. Authority and precedence

Read these before changing code:

1. `WEEK2_GPU_REDESIGN_HANDOFF.md` — why the first GPU design failed and what evidence is still trustworthy.
2. `WEEK2_PLAN.md` — authoritative on existing Week 2 decisions and provenance.
3. `WEEK2_EXECUTION.md` — authoritative on execution order, gates, and human hard stops.
4. `docs/WEEK2_GPU_PREFLIGHT.md` — existing GPU-session operational constraints.
5. `docs/WEEK2_REMEDIATION_REPORT.md` — pre-GPU fixes already completed.
6. `STATUS.md` — current phase/state.
7. `MOCK_TRUST_BOUNDARY.md` — mock remains a request-pattern oracle, not a concurrent-latency source.

If this README appears to conflict with one of those documents on an already-locked non-redesign decision, **halt and surface the conflict**. Do not silently reconcile it.

This README intentionally supersedes only the statistical/workload assumptions falsified by the first GPU session.

---

## 2. Redesign decisions — LOCKED

### D1 — Two workloads, two jobs

**Headline curve:** controlled matched ShareGPT workload.

Purpose:

> Measure the RPS at which p99 TTFT breaches 500ms **for this documented controlled workload**, with prompt-cost composition held fixed.

**Secondary curve:** natural-random ShareGPT traffic.

Purpose:

> Validate that the same general knee/breach behavior survives under unconstrained natural traffic.

Do not collapse these into one workload. The headline is for causal cleanliness; the secondary is for realism.

---

### D2 — Same prompt multiset across RPS points; re-permute across repeats

For the headline workload:

- Freeze one canonical **prompt multiset**.
- Every RPS point uses the same prompt membership.
- Within one repeat, every RPS point uses the same seeded prompt order/assignment lineage so the RPS comparison is matched.
- Across independent repeats:
  - keep the same prompt membership,
  - generate a new seeded prompt permutation/assignment,
  - generate a new independently seeded Poisson arrival schedule.

Therefore:

```text
across RPS points:
  prompt membership = fixed
  prompt ordering/assignment lineage = fixed for that repeat
  arrival rate λ = changes

across repeats:
  prompt membership = fixed
  prompt ordering/assignment = re-seeded
  Poisson arrival realization = re-seeded
```

Do not treat deterministic permutation alone as repeatability evidence. It is only one component of an independent repeat.

**Scope of the canonical multiset:** the frozen canonical membership of size `N` applies to the **post-warmup headline measurement arrivals**. Time-based warmup traffic is excluded from `N`; it must still come from the pinned corpus, use explicitly derived/provenance-recorded RNG state, and remain fully pre-materialized/open-loop. Do not let warmup request count differences caused by different λ alter the canonical post-warmup membership.

---

### D3 — Controlled representative tail for the headline

The headline workload does **not** use an unconstrained natural draw and does **not** merely hope the rare tail appears in the right count.

Instead:

- derive prompt-length strata from the pinned ShareGPT corpus,
- choose a fixed representative prompt membership from those strata,
- ensure the chosen tail has enough absolute support for the p99 experiment,
- freeze the resulting prompt IDs.

This is **controlled representative tail coverage**, not arbitrary tail inflation.

The natural-random secondary run is where natural proportions are allowed to fluctuate normally.

The exact values below are **not locked yet**:

- `k` = stratum definition/count,
- `L` = tail boundary/support definition,
- `N` = requests per independent run / canonical multiset size.

These must come from the offline calibration in §5.

---

### D4 — Independent repeat semantics

One independent headline repeat must use:

- the same canonical prompt multiset,
- a new arrival RNG seed,
- a new prompt-assignment/permutation RNG seed,
- a fully drained server before the next repeat begins,
- its own time-based warmup discard,
- its own run artifacts.

**Do not restart vLLM between repeats.**

The repeatability estimate is intended to measure arrival/queue interaction variability, not cold-process/CUDA-graph/cache initialization variability.

Required transition:

```text
repeat A
  -> stop scheduling
  -> drain all in-flight requests
  -> begin repeat B
  -> apply repeat B's own warmup filter
  -> measure repeat B
```

---

### D5 — Bootstrap sizes a run; independent repeats determine the verdict

The statistical responsibilities are separated:

**Offline bootstrap/resampling:**

- free,
- uses already-collected first-session near-boundary TTFT data,
- determines how large one run must be before its p99 stops being unacceptably fragile,
- helps choose `N`.

**Independent GPU repeats:**

- provide real run-to-run repeatability evidence,
- determine the final headline point classification.

Do not use slices of one continuous run as independent repeats.

Do not present request-level bootstrap coverage as proof of true run-to-run independence.

---

### D6 — Material TTFT censoring invalidates ordinary p99

Use four point states:

```text
UNDER
OVER
UNCERTAIN
CENSORED
```

Censoring rule:

- TTFT-censoring / timeout rate `> 5%` -> `CENSORED`.
- A `CENSORED` point must **not** report an ordinary p99 TTFT as a valid latency percentile.
- Always report timeout/error rate.
- `<= 5%` means **eligible for p99 evaluation**, not automatically tail-valid.
- Any non-zero censoring at a point that could determine the UNDER/OVER boundary must carry an explicit tail-censoring review/sensitivity record before it can contribute a final point verdict. If that review is absent or cannot establish a defensible verdict, the point remains `UNCERTAIN` rather than being silently blessed by the 5% gate.

**Provenance for the 5% hard gate.** The first-session evidence separates clean low-RPS points (0% censoring) from clearly censored saturation points (33%+), so `>5%` is retained as the automatic material-censoring threshold. This threshold is **not** a claim that 4.9% censoring is harmless for p99: censored requests are tail events, and near the SLO boundary even sub-5% censoring can matter.

Do not use zero-tolerance unless later evidence shows low-rate censoring materially biases the tail enough to justify superseding this lock.

Keep non-timeout validity failures separate in provenance/diagnostics; do not overload the four statistical states with every tooling failure.

---

### D7 — RPS semantics

The headline x-axis is **nominal Poisson λ**.

Record three distinct quantities:

```text
nominal_lambda_rps
materialized_schedule_rps
actual_send_rps
```

Interpret them as:

- `nominal_lambda_rps` — experimental workload parameter / chart x-axis,
- `materialized_schedule_rps` — finite realization of the frozen Poisson schedule,
- `actual_send_rps` — what the driver actually sent.

Scheduler fidelity compares:

```text
actual sends
vs
materialized scheduled sends
```

It does **not** compare actual sends against exactly `lambda * duration`.

Finite-Poisson count variance is metadata, not driver under-delivery.

---

## 3. Existing decisions that remain locked

Do not reopen these unless implementation reveals a direct contradiction:

- p99 TTFT is the headline metric,
- 500ms is the headline SLO,
- 2s remains a secondary severe-degradation line,
- Poisson arrivals define the headline workload,
- steady arrivals remain a secondary reference,
- adversarial remains a separate scenario,
- open-loop scheduling,
- absolute-time scheduling,
- fire-and-forget send-task spawn,
- independent arrival/corpus RNG principles,
- frozen materialized schedule as replay source of truth,
- pinned ShareGPT corpus,
- raw log + TTFT/TPOT sidecar durability model,
- concurrency cap = 3000,
- cap must not shape the characterized breach region,
- Linux loadgen scheduler spin = 0ms,
- loadgen runs on-instance over loopback,
- `ulimit -n 65535` protection,
- exact benchmark SHA pinning,
- GPU session remains human-owned,
- mock concurrent latency remains untrusted,
- all published latency comes from real vLLM/GPU.

The old `120s fixed measurement window` and `n >= 100` tail-validity rule are **reopened by provenance** because their justification depended on the statistical design the first GPU session falsified.

Do not keep either merely because it was previously marked locked.

---

## 3.1 Regression contract — MUST remain true

The redesign must not regress the infrastructure that the first session already proved. Treat these as compatibility invariants, not optional cleanup.

### Runtime / architecture invariants

- The scheduler remains genuinely **open-loop**: response completion never gates future schedule issuance.
- Absolute-time targets, fire-and-forget send tasks, scheduling-lag logging, and fail-fast shedding remain intact.
- The concurrency cap remains **3000** and must not shape the headline breach region.
- Linux scheduler spin remains **0ms** unless a new calibration explicitly supersedes it.
- Load generation remains on-instance over loopback with the existing fd-limit guard.
- vLLM is **not restarted between independent repeats**; repeat separation is drain + own warmup.
- GPU lifecycle remains human-owned; no new code path may automatically create or tear down the GPU instance.

### Artifact / replay invariants

- Existing first-session raw logs, samples sidecars, metrics artifacts, and frozen schedules are historical evidence and must **never be rewritten in place**.
- If the redesigned schedule/provenance schema changes, increment its format/version and make readers explicitly support the legacy format or fail with a clear version error.
- Existing frozen schedules must remain replayable under their original workload identity contract: frozen schedule + pinned corpus hash.
- Raw-log six-field semantics remain unchanged; redesign metadata belongs in additive provenance/metrics fields or a versioned companion artifact, not by silently mutating historical field meaning.
- First-session artifacts must remain offline-readable by the analysis tooling used to perform R2.

### Measurement invariants

- TTFT/TPOT definitions and SSE parser behavior remain unchanged.
- 500ms p99 TTFT remains the headline SLO; 2s remains secondary.
- Concurrent mock latency remains outside the trusted set; no redesign test may promote mock latency into baseline evidence.
- Survivor-only p99 at materially censored points remains forbidden.

### Regression test gate

Before the next GPU preflight, the agent must show:

1. the pre-existing loadgen/router/faithfulness regression suites still pass (except already-documented environment-only flakes),
2. all redesign tests/negative controls pass **and their bad variants bite**,
3. at least one legacy first-session schedule/artifact fixture is parsed/replayed successfully by the updated code,
4. a deliberately response-dependent `N` stop implementation fails a negative control,
5. historical artifact hashes are unchanged.

A redesign implementation that makes the new tests green while breaking any of these invariants is **not complete**.

---

## 4. What the agent must implement now — GPU-free

The immediate task is to produce the evidence needed to lock `k`, `L`, and `N`, plus the code paths needed to execute the redesigned workload later.

### Block R0 — Preserve first-session evidence

If not already promoted:

1. Locate the complete first GPU session artifact set copied locally before teardown.
2. Preserve it as **diagnostic / failed-experiment evidence**, not baseline evidence.
3. Ensure both the **1.5-RPS** and **2-RPS** first-session `samples.jsonl` / TTFT arrays used in R2 are durable and discoverable.
4. Do not rewrite raw first-session artifacts.
5. Record hashes when promoting/copying.
6. Capture a small immutable legacy-fixture manifest (paths + hashes + format/version) for at least one first-session schedule, raw log, sidecar, and metrics record; later regression tests must prove updated readers do not change their historical interpretation.

Also fix/confirm the already-known fractional-RPS artifact-name parser issue before new fractional Stage B points are generated.

**Do not invent paths.** Discover the actual artifact locations in the repository/local session copy and record what was found.

---

### Block R1 — Corpus histogram and candidate headline strata

Input:

- pinned ShareGPT baseline corpus artifact,
- its existing provenance/hash.

Produce a machine-readable corpus analysis containing at minimum:

- total prompt count,
- prompt-length quantiles,
- histogram / empirical CDF,
- counts above relevant upper-tail quantiles,
- candidate stratum boundaries,
- count available in each candidate stratum.

The analysis should make the rare tail explicit. Do not choose arbitrary human-friendly buckets unless the corpus distribution supports them.

Candidate quantile structure may be explored, for example:

```text
0-50%
50-90%
90-95%
95-99%
99-99.5%
99.5-100%
```

but this is an analysis starting point, **not a lock**.

For each candidate `(k, L)` construction, report:

- stratum definitions,
- candidate fixed counts per stratum,
- number of prompts available to choose from,
- number of canonical prompts above the proposed tail boundary,
- whether the construction gives sufficient absolute tail support for candidate `N` values.

Do not select the final prompt IDs yet unless the human has approved the `(k, L, N)` construction.

---

### Block R2 — Offline p99 sample-size calibration from existing GPU data

Use **both** usable low-RPS first-session TTFT arrays:

- **1.5 RPS** — the sparser clean low-load diagnostic,
- **2 RPS** — the observed near-threshold / classification-unstable diagnostic.

Do **not** assume the final redesigned crossing lies below 2 RPS, and do not claim that either old prompt realization exactly represents the final canonical workload. The two arrays are conservative run-sizing diagnostics with different failure pressures; the candidate `N` must satisfy the more conservative result.

For **each** source array, first verify and record:

- source artifact path,
- artifact hash,
- nominal RPS and materialized count,
- sample count,
- warmup rule used for the source array,
- timeout/error count,
- percentile implementation used in the diagnostic,
- whether the source samples correspond to the known first-session point.

Then run the **same** reproducible resampling/bootstrap study independently over both arrays and over the same candidate sample sizes.

At minimum explore a useful range such as:

```text
N = 250, 500, 750, 1000, 1250, 1500, 2000, ...
```

Extend as needed; do not stop at 2000 if the evidence still looks unstable.

For each candidate `N`, report at minimum:

- number of resamples,
- p99 center/median,
- p99 spread / interval,
- interval width,
- fraction of resamples classified `< 500ms`,
- fraction classified `>= 500ms`,
- probability/frequency of classification flip relative to 500ms,
- top-1% support (`N * 0.01`),
- sensitivity to percentile interpolation/implementation if that materially changes the result.

The implementation must make random seeds explicit and persist the analysis configuration.

Derive a requirement from each source independently:

```text
N_requirement_1p5
N_requirement_2p0

N_p99_stability_requirement = max(the two)
```

If the two diagnostics disagree materially, surface the reason rather than averaging them away.

Important interpretation rule:

> This bootstrap is a **run-sizing diagnostic**, not the final repeatability proof.

Do not claim iid guarantees the data cannot support, and do not present either first-session prompt realization as the redesigned workload itself.

---

### Block R3 — Joint `k / L / N` calibration report

Combine R1 and R2.

The final candidate `N` must satisfy **both** jobs:

1. enough controlled prompt-tail support in the canonical multiset,
2. enough TTFT p99 support that one run is no longer unacceptably fragile around 500ms.

Conceptually:

```text
N_prompt_tail_requirement
N_p99_stability_requirement

N_candidate = max(the two)
```

Do not silently choose what “acceptable” means if it is not already explicitly encoded in the authoritative docs.

Instead, produce a compact decision table for the human showing the best candidate constructions and their tradeoffs.

Example structure:

| Candidate | k / L construction | N | prompts above L | top-1% TTFT support | bootstrap width | 500ms flip rate | estimated duration @ 1.5 RPS | note |
|---|---|---:|---:|---:|---:|---:|---:|---|

The human owns the final lock of `k`, `L`, and `N`, plus the **maximum evidence ceiling** used to prevent an unbounded large-`N` GPU escalation.

### HARD STOP R3 — Human locks `k`, `L`, `N`, and the evidence ceiling

At this stop the agent must halt and present:

- corpus histogram evidence,
- candidate strata,
- bootstrap/resampling results from **both 1.5 and 2 RPS**,
- candidate `k/L/N` table,
- estimated GPU runtime implications at the low-single-digit RPS region,
- at least one proposed **maximum feasible `N` / maximum evidence budget** beyond which the GPU session must stop escalating evidence and report an interval instead of chasing a point estimate.

The human locks:

```text
k
L
N
N_max (or an equivalent explicit maximum evidence budget)
```

Do not self-certify these workload/budget numbers.

---

## 5. Implementation after `k`, `L`, `N` are human-locked

Proceed only after explicit human sign-off.

### Block R4 — Build and freeze canonical headline workload

Implement a deterministic canonical-workload builder.

Requirements:

- source only from the pinned ShareGPT corpus,
- select the approved fixed prompt multiset according to locked `k/L/N`,
- record exact prompt IDs,
- record char-length histogram and quantiles,
- record corpus hash/version,
- record selection algorithm/version,
- record selection seed if selection contains randomness,
- emit a dedicated provenance artifact,
- deterministic regeneration must reproduce the same canonical membership byte-for-byte or fail loudly.

Do not fetch live ShareGPT.

Do not change the corpus itself.

---

### Block R5 — Redesign schedule generation for matched points + repeats

Extend the schedule generator so it can generate a repeat family.

Required identity model:

```text
headline workload family
  canonical_prompt_membership_id
  repeat_id
  nominal_lambda_rps
  arrival_seed
  assignment_seed
```

For each repeat:

1. create one deterministic seeded permutation of the locked canonical **post-warmup** prompt multiset,
2. for each RPS point in that repeat, map the same ordered canonical sequence onto the `N` post-warmup scheduled arrivals,
3. generate a new Poisson arrival schedule at that point's nominal `lambda`,
4. generate the time-based warmup portion from pinned-corpus traffic using explicit derived RNG provenance; warmup traffic is not part of the canonical `N`,
5. materialize the exact full schedule before sending,
6. freeze all provenance needed for replay.

Across repeats:

- canonical membership stays identical,
- arrival seed changes,
- assignment/permutation seed changes.

If the redesigned schedule artifact needs fields that legacy schedules do not have, emit a **new explicit schedule/provenance format version**. Never retrofit/rewrite the committed legacy schedule bytes.

Tests must prove:

- same repeat seed + same λ -> byte-identical schedule,
- different repeat seed -> different Poisson timing and assignment order,
- prompt membership is identical across all repeats,
- within a repeat, RPS points use the intended matched prompt order/assignment lineage,
- replay still validates corpus hash/version,
- fractional RPS filenames/artifacts are parsed correctly.

---

### Block R6 — Replace fixed-duration semantics without introducing a closed-loop stop condition

The redesigned headline run is no longer fundamentally defined by a fixed 120s measurement window.

`N` is a **schedule-generation constraint**, never a live runtime stopping condition.

#### Offline schedule materialization

For each `(repeat_id, nominal_lambda_rps)`:

1. materialize Poisson arrivals from the repeat's frozen arrival seed,
2. include the full time-based warmup portion,
3. continue materializing until the schedule contains **exactly `N` scheduled arrivals whose offsets are at or beyond the warmup boundary**,
4. stop materialization at that precomputed point,
5. assign the repeat's already-frozen canonical prompt order to those exactly `N` post-warmup arrivals,
6. freeze the entire schedule and its realized duration **before execution begins**.

Therefore:

```text
N = exact number of scheduled post-warmup arrivals
materialized schedule duration = stochastic outcome of the Poisson realization
```

Do **not** use `N / lambda` as the exact runtime duration; it is only an expectation and would reintroduce finite-Poisson sample-count variation into the quantity `N` was calibrated to control.

#### Runtime execution

Runtime must:

```text
load the frozen schedule
-> drive every scheduled arrival
-> stop only when schedule issuance is exhausted
-> drain/record outcomes according to the existing open-loop lifecycle
```

The following must **never** extend, shorten, or otherwise alter schedule issuance:

- request completions,
- TTFT observations,
- number of successful responses,
- errors/timeouts,
- censoring rate,
- current p99,
- whether `N` successful samples have been observed.

This is a regression-critical invariant: **server response behavior may change measurement validity, but it can never change the offered workload.**

Record:

- nominal λ,
- warmup boundary,
- materialized schedule count,
- materialized post-warmup scheduled count (must equal `N`),
- materialized schedule duration,
- post-warmup target count `N`,
- actual post-warmup attempted/sent count,
- actual send rate.

The old `Y=120s` value may remain useful for secondary/legacy comparisons, but it must not silently remain the headline validity basis.

---

### Block R7 — Fix offered-vs-achieved fidelity semantics

Update point metrics so Poisson finite-count variance is not mislabeled as driver divergence.

Required fields:

```text
nominal_lambda_rps
materialized_schedule_count
materialized_schedule_duration_s
materialized_schedule_rps
actual_sent_count
actual_send_rps
schedule_delivery_divergence_pct
nominal_realization_delta_pct
```

Where:

```text
schedule_delivery_divergence_pct
  = actual sent vs materialized scheduled sends

nominal_realization_delta_pct
  = materialized finite-Poisson realization vs nominal lambda
```

The first is a driver-fidelity signal.

The second is descriptive stochastic metadata.

Do not use nominal-realization delta to fail the driver.

Keep existing per-send scheduling-lag instrumentation.

---

### Block R8 — Implement censoring-aware point validity

Update metrics so timeout censoring cannot produce a misleading ordinary p99.

Required hard gate:

```text
if ttft_censoring_rate > 0.05:
    state = CENSORED
    publish ordinary p99 = false
else:
    point is eligible for p99 evaluation
    # eligibility is not the same as tail-validity
```

For `0 < ttft_censoring_rate <= 0.05`, persist an explicit tail-censoring warning. If the point could determine the final UNDER/OVER boundary, R10 must require a recorded tail-censoring review/sensitivity verdict before the point can contribute a final classification. Without that record, the aggregate verdict remains `UNCERTAIN`.

Persist:

- issued count,
- TTFT-observed count,
- timeout/censored count,
- censoring rate,
- error categories,
- `tail_censoring_warning`,
- `tail_censoring_review_status` when applicable,
- p99 only when the hard gate allows it,
- point state,
- reason/provenance.

Tests must include at least:

- 0% censoring -> p99 eligible, no warning,
- just below 5% -> p99 eligible **with tail warning**, not automatically final-valid,
- exactly 5% -> p99 eligible **with tail warning**, not automatically final-valid,
- just above 5% -> `CENSORED`, ordinary p99 suppressed,
- high censoring (e.g. 33%+) -> `CENSORED`, ordinary p99 suppressed,
- a boundary-determining sub-5% censored point with no review -> aggregate classification cannot finalize as UNDER/OVER.

Do not silently drop timed-out requests and compute p99 over survivors as if the sample were complete.

---

### Block R9 — Independent-repeat orchestration

Implement a repeat runner/runbook that enforces:

```text
run repeat
-> stop scheduling
-> wait until all in-flight requests close/error
-> verify in-flight = 0
-> start next repeat
-> apply next repeat's own warmup filter
```

No vLLM restart.

The runner must refuse to start the next repeat while in-flight requests remain.

Each repeat gets separate artifacts and provenance.

Do not aggregate repeat artifacts into one pseudo-run before the per-repeat metrics are preserved.

---

### Block R10 — Repeat-level classification plumbing + bounded uncertainty

The final headline classification is determined from independent repeats, not bootstrap slices.

Implement the mechanism generically so it consumes the human-approved repeat/stability policy rather than baking in an arbitrary repeat count or spread threshold.

At minimum support these point states:

```text
UNDER
OVER
UNCERTAIN
CENSORED
```

Rules:

- a repeat that is censored/invalid for measurement reasons must not be silently pooled with valid repeats,
- a boundary-determining repeat/point with sub-5% censoring but no completed tail-censoring review cannot silently finalize UNDER/OVER,
- per-repeat values and provenance must remain available even when an aggregate verdict exists.

#### Persistent-UNCERTAIN escape hatch

The implementation/runbook must obey the R3 human-locked evidence ceiling (`N_max` or equivalent maximum evidence budget).

If a candidate crossing remains `UNCERTAIN` after the authorized evidence ceiling is reached:

1. **do not** keep increasing `N` or adding unplanned GPU work,
2. retain the unresolved point(s) as `UNCERTAIN`,
3. find the highest defensible `UNDER` λ and the lowest defensible `OVER` λ,
4. report the breach as an interval rather than manufacturing a point estimate:

```text
breach interval = (highest UNDER λ, lowest OVER λ]
```

If no valid UNDER/OVER bracket exists, report that the breach was not resolved within the authorized experiment range/budget.

Persist the per-repeat values and the exact evidence-ceiling condition that caused interval reporting.

---

### Block R11 — Natural-random secondary workload

Keep a secondary natural-random ShareGPT experiment.

Purpose:

> realism validation only; it does not define the headline breach RPS.

Requirements:

- pinned corpus,
- normal natural-random prompt draws,
- independent seeds,
- same server/output policy as headline,
- same censoring rules,
- clearly separate artifact namespace and chart labeling,
- do not mix its p99 points into the matched-workload headline classification.

The secondary should answer whether the knee/general breach behavior survives natural traffic, not reproduce the exact headline crossing.

---

## 6. Tests / negative controls required before any new GPU session

The redesign needs teeth, not only green tests.

Add tests/controls for at least:

### Canonical workload

- same configuration -> identical canonical membership,
- corpus hash mismatch -> refusal,
- changing locked stratum config -> changed workload identity,
- tail-support accounting matches the frozen prompt IDs.

### Repeat identity

- same repeat seed -> identical schedule family,
- different repeat seed -> different arrival realization,
- different repeat seed -> different prompt assignment/permutation,
- membership remains exactly identical.

### Matched RPS points

- within one repeat, prompt membership/order contract is preserved across RPS points,
- only arrival timing/rate changes.

### Evidence-count / open-loop stop semantics

- schedule generation produces exactly locked `N` post-warmup **scheduled** arrivals,
- runtime drives the complete frozen schedule even if requests complete slowly, time out, or error,
- fast-server and slow-server variants issue the same frozen schedule/count,
- a deliberately broken implementation that stops after `N` completions must fail the control,
- changing response latency must not change schedule duration/count after materialization.

### RPS semantics

- materialized Poisson count below `lambda * time` does **not** trip driver-fidelity failure,
- deliberately dropping scheduled sends **does** trip driver-fidelity failure.

### Censoring

- survivor-only p99 path must fail a negative control where >5% timeouts are injected,
- p99 suppressed for censored points.

### Repeat orchestration

- deliberately start the next repeat with in-flight requests -> runner refuses,
- cleanly drained previous repeat -> next repeat allowed.

### Fractional RPS

- names such as `rps1.5` survive artifact discovery/completeness checks without truncation.

### Legacy compatibility / no-regression

- legacy first-session schedules still parse/replay under their original version,
- first-session raw log + sidecar still recompute with unchanged historical semantics,
- new provenance fields do not alter legacy hashes or require rewriting old artifacts,
- schedule-format version mismatch fails loudly rather than being silently coerced.

---

## 7. Documentation changes required

Do not silently overwrite the original Week 2 rationale. Record the redesign as a falsification-driven change.

Update, with provenance:

### `WEEK2_PLAN.md`

Amend the sections covering:

- prompt distribution,
- fixed duration,
- `n >= 100` tail validity,
- offered-vs-achieved semantics,
- breach-point validity under timeouts.

Explicitly state what first-session evidence falsified the old rationale.

### `WEEK2_EXECUTION.md`

Add the offline redesign/calibration hard stop before another GPU session.

The GPU must not start until `k/L/N`, repeat policy, and censoring-aware metrics are implemented and human-approved.

### `STATUS.md`

State that Week 2 remains in progress and the first GPU session produced diagnostic evidence, not a final breach RPS.

### Recommended new permanent record

Create:

```text
docs/WEEK2_GPU_SESSION_FINDINGS.md
```

Record:

- first-session setup,
- trusted findings,
- invalid conclusions,
- prompt-tail confound,
- p99 sample-size instability,
- timeout censoring,
- finite-Poisson semantics issue,
- fractional-RPS bug,
- redesign decisions D1-D7,
- explicit statement: **no final breach RPS was produced by the first session**.

---

## 8. What not to do

Do **not**:

- start another GPU session before the offline calibration and implementation gates pass,
- choose `N=1000`, `1500`, `2000`, etc. because it sounds large,
- run until `N` completions/successful TTFT samples have been observed; `N` is fixed in the frozen schedule before execution,
- treat three slices of one run as three independent repeats,
- treat prompt-order permutation alone as repeatability evidence,
- re-draw prompt membership across headline repeats,
- rely on natural-random tail realization for the headline,
- oversell request-level bootstrap as true run-to-run confidence,
- restart vLLM between repeats,
- compute an ordinary p99 from a point with >5% TTFT censoring,
- treat `<=5%` censoring as automatically harmless at a boundary-determining p99 point,
- compare actual sends directly against `lambda * duration` and call finite-Poisson variance client under-delivery,
- change the open-loop scheduler architecture,
- rewrite or silently migrate historical first-session schedules/artifacts in place,
- change the pinned corpus content,
- change the 500ms headline SLO,
- publish the first session's `2 RPS` result as the breach RPS,
- publish the 10/20/30-RPS ~60s survivor percentiles as ordinary latency measurements,
- keep escalating `N` beyond the human-locked evidence ceiling instead of reporting an interval-valued breach.

---

## 9. Agent execution order

```text
R0  Preserve / locate first-session diagnostic evidence
        ↓
R1  Corpus histogram + candidate strata
        ↓
R2  Existing 1.5 + 2-RPS TTFT bootstrap / N study
        ↓
R3  Joint k/L/N + evidence-ceiling candidate report
        ↓
HARD STOP — human locks k/L/N + N_max/evidence ceiling
        ↓
R4  Freeze canonical workload
        ↓
R5  Matched repeat-family schedule generation
        ↓
R6  Pre-materialized exact-N headline schedule semantics
        ↓
R7  Nominal λ vs materialized vs actual-send metrics
        ↓
R8  Censoring-aware validity
        ↓
R9  Drain-separated independent-repeat orchestration
        ↓
R10 Repeat-level classification + bounded-UNCERTAIN fallback
        ↓
R11 Natural-random secondary workload
        ↓
Tests + negative controls
        ↓
Update authoritative docs with provenance
        ↓
Pre-GPU audit / human hard stop
        ↓
ONLY THEN: human-owned second GPU session
```

---

## 10. Definition of done for this implementation task

Before asking for another GPU session, all of the following must be true:

- [ ] first-session diagnostic artifacts are preserved and the 1.5-RPS + 2-RPS TTFT sources are identified by hash,
- [ ] corpus histogram and upper-tail structure are reproducibly computed,
- [ ] bootstrap/resampling study reports p99 stability vs candidate `N` independently for 1.5 and 2 RPS,
- [ ] human has locked `k`, `L`, `N`, and `N_max` (or equivalent maximum evidence budget) from the evidence,
- [ ] canonical headline prompt multiset is frozen and reproducible,
- [ ] same membership is used across all headline RPS points and repeats,
- [ ] repeat-specific prompt order/assignment and Poisson timing are independently seeded,
- [ ] repeat boundaries enforce drain + own warmup without vLLM restart,
- [ ] headline validity no longer depends on `n >= 100`,
- [ ] headline validity no longer depends on a fixed 120s window unless re-justified by the new evidence policy,
- [ ] `N` is enforced only during offline schedule materialization; no response-dependent live stop condition exists,
- [ ] every headline schedule contains exactly `N` post-warmup scheduled arrivals and runtime always drives the full frozen schedule,
- [ ] nominal λ, materialized schedule rate, and actual send rate are separately recorded,
- [ ] driver fidelity is checked against the materialized schedule,
- [ ] >5% TTFT censoring yields `CENSORED` and suppresses ordinary p99,
- [ ] 0-5% censoring is treated as eligible-but-not-automatically-tail-valid, with boundary-point review plumbing,
- [ ] persistent `UNCERTAIN` at the human-locked evidence ceiling reports a breach interval instead of triggering unbounded GPU escalation,
- [ ] fractional-RPS artifact handling is fixed,
- [ ] all redesign tests and negative controls bite,
- [ ] pre-existing regression suites remain green except documented environment-only flakes,
- [ ] legacy first-session schedules/artifacts remain readable/replayable and historical artifact hashes remain unchanged,
- [ ] natural-random secondary workload remains separate from the headline,
- [ ] authoritative Week 2 docs carry provenance for every superseded lock,
- [ ] no code path stands up a GPU automatically.

---

## 11. Expected output at the next human checkpoint

The first checkpoint should **not** be "implementation complete."

It should be a compact evidence package containing:

1. the corpus tail histogram,
2. candidate `k/L` constructions,
3. the 1.5-RPS and 2-RPS bootstrap/resampling curves/tables across candidate `N`, shown separately and conservatively combined,
4. a joint candidate table with runtime implications,
5. a recommendation for `k`, `L`, `N`, and `N_max` / maximum evidence budget, clearly labeled as recommendations rather than self-approved,
6. regression evidence showing legacy artifacts remain readable and historical hashes unchanged,
7. any conflict discovered with the authoritative Week 2 docs.

Then halt for human sign-off.

The guiding principle is:

> **The next GPU session executes a pre-locked experiment. It must not be used to discover the experiment design.**

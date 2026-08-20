# Week 2 GPU Redesign — R3 Closeout and R4→Pre-GPU Agent Instructions

> **STATUS: HISTORICAL — DO NOT EXECUTE**
>
> Role: the R4→R11 implementation brief. Already executed; the evidence is `docs/WEEK2_R4_EVIDENCE_PACKAGE.md`.
>
> This document records an earlier Week 2 state. It is preserved for
> provenance, and nothing in it may drive GPU session #2.
> Current entry point: `docs/WEEK2_DOC_INDEX.md`.

**Purpose:** continue Week 2 from the completed R0–R3 redesign calibration without reopening already-proven infrastructure or spending GPU time prematurely.

**Current state:** R0–R3 are complete. Hard Stop R3 produced the evidence package at:

```text
benchmarks/calibration/week2_redesign/R3_EVIDENCE_PACKAGE.md
```

No GPU was used for R0–R3. No canonical workload has been frozen yet. No R4+ redesign runtime/metrics wiring has been implemented yet. Historical schedules/corpus bytes remain unchanged.

This README begins **at Hard Stop R3**. It is not a replacement for the original redesign README; it is the continuation/closeout instruction that incorporates the evidence R3 produced.

---

## 0. Non-negotiable operating rule

Do **not** start, create, drive, or tear down a GPU instance as part of this instruction.

The next GPU session remains human-owned and is gated on:

1. R3 provenance closeout,
2. canonical-workload construction,
3. prefix-cache neutralization,
4. percentile-definition lock in code/docs,
5. exact tokenizer-based context sizing,
6. schedule/metrics/repeat implementation,
7. regression + negative-control evidence,
8. a new pre-GPU audit and explicit human approval.

If an authoritative document conflicts with this README on an unrelated previously-locked infrastructure decision, **halt and surface the conflict**. Do not silently reconcile it.

---

# 1. R3 evidence that changes the experiment

Treat the following as findings, not optional commentary.

## F1 — `n >= 100` is falsified as a p99-quality rule

R2 measured, separately:

| Diagnostic source | Original n | flip rate at N=250 | first N with flip <=5% | first N with flip <=1% |
|---|---:|---:|---:|---:|
| 1.5 RPS | 166 | 0% | 250 | 250 |
| 2 RPS | 225 | 51.8% | 4,000 | 7,500 |

The 2-RPS historical distribution flips its own `<500ms` / `>=500ms` classification in roughly half of N=250 resamples. The old `n >= 100` rule is therefore not merely conservative/loose; it is inadequate for the observed near-boundary tail.

The 1.5-RPS result is retained as historical diagnostic evidence but must **not** be treated as a clean low-load sizing source after F2 below.

---

## F2 — the historical 1.5-RPS point is prefix-cache confounded

vLLM ran with prefix caching enabled by default, and the first-session schedules shared a master-seed lineage that made shorter schedules prefixes of longer ones. Run order therefore changed prompt cost.

Observed example:

```text
prompt 458 (14,960 chars)
  concurrency-1 floor: 523.3ms TTFT
  1.5-RPS run:         103.9ms TTFT
```

The 1.5-RPS point was driven late, after the server had already seen many repeated prefixes. Load cannot plausibly make prefill ~5x faster; cache state is the missing variable.

Consequences:

- Do **not** describe first-session 1.5 RPS as a clean UNDER point.
- Do **not** use the historical 1.5-RPS result to claim the redesigned crossing is below/above 2 RPS.
- Preserve its bootstrap output because R2 was correctly run as specified, but mark it **cache-confounded diagnostic only**.
- The 2-RPS source remains the conservative driver of `N` sizing.
- The old 1.5/2/5-RPS sequence is **not an authoritative final bracket** for the redesigned experiment.

---

## F3 — percentile convention can flip the verdict

The same historical 2-RPS samples produce materially different p99 values under different conventions:

```text
linear   -> 524.6ms -> OVER
lower    -> 434.8ms -> UNDER
nearest  -> 552.9ms -> OVER
midpoint -> 493.9ms -> UNDER
```

Therefore the percentile definition is part of the measurement specification. It must not be inherited from a library default or whichever analysis script happens to run.

---

## F4 — `N=7,500` is statistically attractive but structurally unavailable without prompt reuse

The pinned corpus contains 5,000 prompts. The first candidate reaching the stricter <=1% historical flip diagnostic is approximately N=7,500, above the no-reuse corpus ceiling.

Therefore interval-valued breach reporting is a **live possible result**, not merely a theoretical fallback.

---

# 2. R3 closeout locks to implement

Apply the following redesign locks for the controlled headline experiment.

## L1 — prompt strata

```text
k = k6_readme_example
```

Use the six-stratum construction documented in the R3 evidence package. Do not silently redefine the strata while implementing R4.

If the exact boundary table is not directly discoverable from the evidence package, halt and surface it rather than reconstructing it from memory.

---

## L2 — controlled tail boundary

```text
L = corpus q99 = 11,471 chars
```

This is the headline workload's explicit tail-support boundary.

Rationale to preserve in provenance:

- q99 is a genuinely sparse corpus tail;
- prompts in this region already consume a large fraction of the 500ms TTFT budget unloaded;
- the headline workload must fix representative tail support rather than allow finite random draws to decide whether those prompts appear.

This is **controlled representative tail coverage**, not arbitrary synthetic tail inflation.

The natural-random secondary workload remains responsible for natural proportion/luck-of-the-draw realism.

---

## L3 — initial per-run evidence size

```text
N = 4,000 post-warmup scheduled headline arrivals per independent run
```

Interpretation:

- N is the first tested candidate that satisfies the <=5% historical bootstrap classification-flip diagnostic on the conservative 2-RPS source.
- N is a **run-sizing calibration**, not proof of final repeatability.
- Independent GPU repeats determine the final UNDER/OVER/UNCERTAIN verdict.
- At N=4,000, the empirical top 1% has roughly 40 observations rather than ~1–2.

Do not replace N=4,000 with 2,500 merely to reduce runtime unless a human explicitly supersedes this lock with provenance.

---

## L4 — hard evidence ceiling

```text
N_max = 5,000
```

Meaning:

- no headline measured run may exceed 5,000 unique canonical prompt IDs by silently repeating prompts;
- do not manufacture N=7,500 by duplicating corpus prompts;
- if the authorized repeat/evidence policy remains unresolved at the ceiling, preserve `UNCERTAIN` and report a breach interval.

`N_max` is a structural ceiling from corpus cardinality, not an invitation to automatically escalate every point from 4,000 to 5,000.

---

## L5 — p99 definition

For all **redesigned headline/secondary measurements**, define empirical p99 by nearest-rank order statistic:

```text
samples = sorted(valid_ttft_samples)
rank = ceil(0.99 * n)       # one-indexed
p99 = samples[rank - 1]
```

Requirements:

- implement one shared percentile function used by live and offline analysis;
- do not use NumPy/Pandas interpolation defaults implicitly;
- persist the percentile method/version in point provenance;
- historical metrics remain historical and are **not rewritten** under the new convention;
- readers must distinguish legacy metric semantics from redesigned metric semantics by explicit version/provenance.

Add tests where the historical 2-RPS-style small sample produces different answers under interpolation methods, and assert that the redesigned path always returns the nearest-rank result.

---

## L6 — prefix-cache policy

For the **controlled headline benchmark**, prefix caching must be disabled.

Rationale:

> Exact prompt replay is an experimental control introduced to hold prompt cost fixed. If prefix caching recognizes those replays, the control itself changes the cost being controlled and makes later points/repeats cheaper as a function of run order.

Requirements:

- disable prefix caching in the headline vLLM configuration using the mechanism appropriate to the pinned vLLM version;
- verify the **effective runtime configuration**, not only the CLI string;
- persist the effective prefix-cache setting in every relevant run/session provenance artifact;
- make preflight fail if the controlled headline run detects prefix caching enabled;
- use the same prefix-cache-disabled server configuration for apples-to-apples Week 4+ controlled routing comparisons unless a later explicit experiment supersedes it.

Do **not** attempt to fix this with run-order randomization alone, prompt permutation alone, or back-to-back repeats. Those do not neutralize accumulated cache state.

The natural-random secondary workload must not silently change server configuration. If prefix caching is ever studied enabled, treat it as a separate explicit configuration experiment rather than mixing it into the headline comparison.

---

# 3. Close provenance before R4 implementation

Before writing the canonical-workload/schedule implementation, amend the authoritative docs so the code is not knowingly implementing a contradiction.

## 3.1 `WEEK2_PLAN.md`

Add a falsification-driven amendment. Preserve the historical text/decision provenance; do not silently erase the old rationale.

Explicitly supersede:

### Old prompt lock

Historical:

```text
natural ShareGPT random draws
no length stratification
same seeded population distribution holds prompt cost fixed
```

Superseded because:

- fixed-duration points realized different empirical prompt tails;
- a single rare long prompt could flip the p99 breach verdict;
- exact repeated prompts then exposed prefix-cache run-order contamination.

New:

```text
headline = controlled stratified canonical ShareGPT multiset
secondary = natural-random ShareGPT validation
```

### Old window lock

Historical:

```text
Y = 120s fixed measurement duration
```

Supersede for the headline with:

```text
N = 4,000 exact post-warmup scheduled arrivals
schedule duration = outcome of the frozen Poisson realization
```

The old 120s rule may remain documented for historical/secondary uses, but it is no longer the headline p99-validity basis.

### Old tail-validity lock

Historical:

```text
n >= 100
```

Supersede with the R3 evidence policy and independent-repeat classification.

### Add

- `N_max = 5,000` structural evidence ceiling;
- nearest-rank p99 definition;
- prefix-cache-disabled headline configuration;
- interval-valued breach fallback;
- four point states: `UNDER`, `OVER`, `UNCERTAIN`, `CENSORED`;
- >5% TTFT censoring hard gate plus sub-5% boundary-tail review;
- nominal λ vs materialized schedule vs actual-send semantics.

---

## 3.2 `WEEK2_EXECUTION.md`

Insert the R0–R3 redesign checkpoint and make the R3 closeout a predecessor of R4.

The execution path must clearly show:

```text
first GPU findings
  -> R0-R3 offline redesign/calibration
  -> Hard Stop R3
  -> provenance closeout + missing design locks
  -> R4-R10 implementation
  -> regression + negative controls
  -> new pre-GPU hard stop
  -> human-owned GPU session
```

Do not leave the old flow implying that Block F can simply recompute a final breach from the first-session artifacts.

---

## 3.3 `STATUS.md`

Update current state to reflect:

- Week 2 remains in progress;
- first GPU session produced diagnostic/falsification evidence, **not a final breach RPS**;
- R0–R3 redesign calibration is complete;
- R3 locks are now being closed/implemented;
- 120s and `n>=100` are historical locks superseded for the redesigned headline;
- prefix-cache discovery invalidates the first-session 1.5-RPS point as a clean UNDER anchor.

---

## 3.4 Permanent findings record

Create/update:

```text
docs/WEEK2_GPU_SESSION_FINDINGS.md
```

Record at minimum:

- corpus CRLF/hash finding;
- prompt-tail confound;
- p99 sample-size instability;
- timeout censoring;
- finite-Poisson offered-vs-achieved semantics issue;
- fractional-RPS artifact bug;
- prefix-cache/run-order confound;
- percentile-method ambiguity;
- trusted vs invalid first-session conclusions;
- explicit statement that no final breach RPS was produced.

---

# 4. Two pre-R4 evidence checks

These are GPU-free.

## P1 — audit the historical unloaded floor's cache state

The historical floor was approximately 402ms p99 over the old 2-RPS prompt set. Because prefix caching was active in the session, determine from durable timestamps/logs/run order whether that floor was measured:

- before those prompts could have been cached,
- after prior exposure,
- or with insufficient evidence to know.

Classify it as one of:

```text
CLEAN_UNLOADED_FLOOR
CACHE_STATE_AMBIGUOUS_DIAGNOSTIC
CACHE_INFLUENCED_DIAGNOSTIC
```

Do not rewrite the floor artifact.

If cache state cannot be proven clean, stop citing 402ms as the definitive unloaded floor. The next GPU session will collect a new clean unloaded anchor with prefix caching disabled.

This audit does **not** block R4 workload construction if provenance is unrecoverable; it only controls how the old floor may be described.

---

## P2 — do not renormalize historical schedule artifacts

The committed historical schedule blobs are LF while Windows working-tree behavior can produce CRLF for uncovered formats.

Required policy:

- preserve all existing historical schedule/corpus blob bytes and hashes;
- do **not** run a broad `git add --renormalize` that rewrites committed benchmark evidence;
- add explicit future newline/serialization protection for new benchmark artifact formats;
- test that newly generated frozen schedules are byte-stable across supported checkout/platform paths;
- if an old working-tree checkout differs only by newline transformation, readers should validate the committed/historical identity according to its existing recorded contract rather than silently rewriting the artifact.

Historical evidence cleanliness is more important than cosmetic normalization.

---

# 5. R4 — construct the canonical headline workload

Proceed only after §3 provenance amendments are complete.

## R4A — deterministic candidate selection

Build the approved k6 / q99 / N=4,000 canonical multiset from the pinned 5,000-prompt corpus.

Requirements:

- exact 4,000 unique prompt IDs;
- no duplicate prompt IDs within the measured canonical multiset;
- use the approved k6 stratum boundaries from R3 evidence exactly;
- controlled representative support above `L=11,471 chars`;
- deterministic selection algorithm/version;
- explicit selection seed if randomness is used;
- corpus hash/version recorded;
- per-stratum available count and selected count recorded;
- overall char-length histogram/quantiles recorded;
- exact ordered canonical membership stored separately from repeat-specific permutations if needed.

Do not fetch live ShareGPT. Do not mutate the corpus.

### Negative controls

- changed corpus hash -> refuse;
- changed stratum definition -> workload identity changes;
- dropped/duplicated canonical ID -> reconciliation fails;
- tail-support count differing from provenance -> fail.

---

## R4B — exact tokenizer-based capacity check before final freeze

The old `--max-model-len=20000` was based on a conservative char-to-token estimate. The redesign now deliberately guarantees upper-tail prompts appear, so replace probabilistic sizing with exact tokenizer evidence.

Using the tokenizer corresponding to the exact pinned Llama-3.2-3B-Instruct model/server configuration, compute for the **selected canonical 4,000 IDs**:

```text
max_input_tokens
p99_input_tokens
per-stratum token quantiles
prompt_id achieving max_input_tokens
```

Then verify the intended server context limit can accommodate:

```text
max_input_tokens
+ locked output-token budget/policy
+ documented safety margin
```

Do not change the Week 3 project-wide `prompt_len` logging unit here; char-count logging may remain the Week 2 raw-log contract. This tokenizer pass is specifically a preflight capacity guarantee for the controlled workload.

If the selected canonical workload does not fit the intended model/context configuration, **halt**. Do not silently drop/reselect long prompts merely to make the server boot; that would alter the locked workload construction.

---

## R4C — freeze only after capacity validation

After R4B passes, write the canonical workload and provenance as versioned immutable benchmark input.

Deterministic regeneration must reproduce the membership byte-for-byte.

Do not rewrite legacy schedules/corpus/evidence.

---

# 6. R5/R6 — repeat-family schedules and exact-N open-loop semantics

## R5 — repeat identity

For each headline repeat:

```text
canonical membership = identical 4,000 IDs
assignment/permutation seed = new
Poisson arrival seed = new
vLLM process = same
prefix caching = disabled
```

Within a repeat, every RPS point must use the same canonical prompt order/assignment lineage so the RPS comparison is matched.

Across repeats, the canonical membership remains identical but prompt order and arrival realization change independently.

Warmup traffic:

- remains time-based;
- is not counted in canonical N;
- is fully pre-materialized;
- comes from pinned corpus traffic with explicit derived RNG provenance;
- cannot alter the canonical post-warmup membership.

---

## R6 — N is a schedule-generation constraint, never a response stop condition

This is regression-critical.

### Offline materialization

For each `(repeat_id, nominal_lambda_rps)`:

1. materialize the full Poisson warmup portion;
2. continue drawing Poisson arrivals until there are exactly **4,000 scheduled arrivals at/after the warmup boundary**;
3. assign the frozen repeat-specific permutation of the canonical 4,000 prompts to those 4,000 post-warmup arrivals;
4. freeze the complete schedule;
5. record the resulting stochastic duration.

Therefore:

```text
post-warmup scheduled count = exactly 4,000
schedule duration = Poisson realization outcome
```

### Runtime

Runtime must:

```text
load frozen schedule
-> issue every scheduled arrival
-> stop schedule issuance only when the frozen schedule is exhausted
-> drain/record outstanding outcomes under the existing lifecycle
```

Never implement:

```text
while completed < 4000
while successful_ttft < 4000
while valid_samples < 4000
```

Completions, TTFT, timeout rate, errors, current p99, and censoring may affect **measurement validity**, but must never change the offered workload or schedule length.

### Required negative control

Build a deliberately response-dependent stopping variant and prove the same open-loop validation rejects it. Fast and slow response servers must issue the identical frozen schedule/count in the real implementation.

---

# 7. R7/R8 — measurement semantics

## R7 — separate the three RPS quantities

Persist:

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

Interpretation:

```text
nominal λ
  = workload parameter / headline x-axis

materialized schedule
  = exact finite Poisson workload the driver was asked to issue

actual sends
  = what the driver actually issued
```

Driver fidelity compares **actual execution vs frozen materialized schedule**.

Finite-Poisson deviation from nominal λ is metadata, not client under-delivery.

Do not rewrite the legacy first-session `flagged:true` records that used the old semantics; document their historical meaning instead.

---

## R8 — censoring-aware validity

Use four statistical states:

```text
UNDER
OVER
UNCERTAIN
CENSORED
```

Hard gate:

```text
TTFT censoring rate > 5%
  -> CENSORED
  -> ordinary p99 verdict suppressed
```

For `0 < censoring <= 5%`:

- p99 is eligible to be computed,
- persist a tail-censoring warning,
- if the point could determine the final UNDER/OVER boundary, require an explicit tail-sensitivity/review record before it may finalize the crossing,
- without that review, aggregate state remains `UNCERTAIN`.

Always report timeout/error count and rate.

Do not silently compute survivor-only p99 at materially censored points.

---

# 8. R9/R10 — independent repeats and bounded uncertainty

## R9 — repeat boundary

Independent repeats use:

- same canonical 4,000 membership,
- new assignment/permutation seed,
- new Poisson arrival seed,
- same vLLM process,
- prefix caching disabled,
- drain to in-flight = 0 before next repeat,
- own time-based warmup discard,
- separate artifacts/provenance.

The runner must refuse to begin repeat B while repeat A has in-flight requests.

Do not use slices/blocks of one continuous run as independent repeats.

---

## R10 — final classification and evidence ceiling

Bootstrap does **not** determine the final breach verdict. Independent GPU repeats do.

Implement classification plumbing so the repeat policy can be applied without pooling away per-repeat evidence.

Required behavior:

- preserve every repeat's p99/state/provenance;
- do not pool a censored repeat with valid repeats to manufacture a clean aggregate;
- do not let a sub-5%-censored boundary repeat finalize without its tail review;
- support `UNDER`, `OVER`, `UNCERTAIN`, `CENSORED` at the point level.

### Evidence ceiling

Initial headline run size:

```text
N = 4,000
```

Hard structural ceiling:

```text
N_max = 5,000
```

Do not automatically escalate every point to 5,000. Escalation must be part of the pre-authorized evidence plan.

If the crossing remains unresolved after the authorized evidence ceiling is reached:

```text
highest defensible UNDER = lambda_low
lowest defensible OVER   = lambda_high

breach interval = (lambda_low, lambda_high]
```

If no valid bracket exists, report that the breach was not resolved within the authorized range/evidence budget.

Do **not** duplicate corpus prompts, raise N beyond 5,000, or add unplanned GPU repeats on the meter merely to force a point estimate.

---

# 9. R11 — natural-random secondary curve

Keep the secondary workload separate from the controlled headline.

Purpose:

> Does the same broad knee/degradation behavior survive unconstrained natural ShareGPT traffic?

Requirements:

- pinned corpus;
- normal natural-random draws;
- explicit independent seeds;
- same model/server/output policy as the controlled headline unless a separate experiment is explicitly declared;
- same percentile definition and censoring semantics;
- separate artifact namespace/chart labeling;
- never use secondary points to define the controlled headline breach RPS.

Do not attempt to force the secondary curve to reproduce the exact controlled crossing.

---

# 10. Regression gate before pre-GPU review

The redesign must preserve everything the first implementation already proved.

## Existing suites

The R3 state already demonstrated:

```text
everything except router: 176 passed, 25 deselected
router tier:              25 passed, 176 deselected
redesign suite:           52 passed
R0-R3 controls:           6/6 red-then-green
```

R4+ must keep these green, except any explicitly documented environment-only flake.

---

## New mandatory controls

Add and demonstrate red-then-green controls for at least:

### Workload identity

- canonical membership drift across RPS -> fail;
- duplicate/missing canonical prompt -> fail;
- corpus hash mismatch -> fail;
- wrong tail-support reconciliation -> fail.

### Repeat identity

- same repeat seeds -> byte-identical schedule family;
- different repeat arrival seed -> arrival realization changes;
- different assignment seed -> prompt order changes;
- canonical membership remains identical.

### Open-loop exact-N semantics

- exactly 4,000 post-warmup **scheduled** arrivals are materialized;
- fast and slow responders issue the same frozen schedule;
- deliberately stop after 4,000 completions -> control must fail;
- timeout/error behavior cannot extend/shorten frozen schedule issuance.

### Percentile definition

- multiple library interpolation methods disagree on a crafted small sample;
- redesigned metric path always uses nearest-rank;
- live/offline recomputation returns the same nearest-rank result.

### Prefix-cache policy

- controlled headline preflight with prefix caching enabled -> fail;
- prefix caching disabled/effective -> pass;
- provenance records the effective state.

### Censoring

- 0% -> eligible, no warning;
- <=5% nonzero -> warning;
- >5% -> CENSORED and no ordinary p99 verdict;
- boundary-determining <=5% without review -> cannot finalize UNDER/OVER.

### Evidence ceiling

- attempt to build headline canonical membership >5,000 unique prompts -> fail;
- unresolved classification at ceiling -> interval path, not automatic larger-N path.

### Legacy compatibility

- historical first-session schedules still parse under recorded versions;
- historical raw log + sidecar still recompute under historical semantics;
- fractional `rps1.5` discovery remains correct;
- historical artifact hashes remain unchanged;
- `git diff HEAD -- benchmarks/schedules corpus/` remains empty unless a human explicitly approves a versioned new artifact addition; no renormalization of old blobs.

---

# 11. Design the second GPU session only after implementation passes

The old bracket is not authoritative because the 1.5-RPS point is cache-confounded. Do not jump directly to a full N=4,000 fine sweep around 1.5–2 RPS.

Use a two-tier session design.

## Tier A — diagnostic scouting

Purpose:

> cheaply rediscover the approximate clean crossing region with prefix caching disabled and the redesigned workload machinery.

Scouting runs may use a smaller explicitly documented evidence size and are **diagnostic only**.

They may locate the region but may **not** produce final UNDER/OVER headline claims.

The exact scout RPS points/sample budget must be proposed offline and human-approved before meter start.

---

## Tier B — headline confirmation

Spend the calibrated N/repeat evidence only on points capable of determining the crossing.

Each independent repeat must obey:

```text
same canonical membership
new Poisson seed
new assignment/permutation seed
drain before next repeat
own warmup
same vLLM process
prefix caching disabled
```

The pre-GPU plan must already define:

- scout points/budget,
- confirmation candidate points,
- number/order of independent repeats initially authorized,
- when N=5,000 escalation is allowed,
- maximum evidence/session budget,
- UNDER/OVER/UNCERTAIN/CENSORED aggregation rule,
- interval-reporting stop condition,
- teardown/artifact promotion path.

No on-meter improvisation beyond the pre-authorized branches.

---

# 12. Required agent output before the next human hard stop

After completing the work in this README, produce one evidence package containing:

1. authoritative-doc diffs with explicit supersession provenance;
2. historical unloaded-floor cache-state audit;
3. canonical k6/q99/N=4,000 workload provenance;
4. exact tokenizer capacity report and proposed `--max-model-len` value;
5. prefix-cache-disabled launch/preflight evidence;
6. schedule-format/version changes, if any;
7. exact-N open-loop schedule proof;
8. nearest-rank metric proof;
9. censoring-state proof;
10. repeat/drain orchestration proof;
11. `N_max=5,000` / interval fallback proof;
12. full regression results;
13. all new negative-control red-then-green evidence;
14. confirmation that historical schedule/corpus/evidence hashes were not rewritten;
15. a proposed **second GPU session scouting + confirmation plan**, including estimated runtime/cost.

Then halt.

Do not create the GPU instance.

---

# 13. Definition of done for this continuation block

Before asking the human to approve the next GPU session, all must be true:

- [ ] R3 k6 / q99 / N=4,000 / N_max=5,000 provenance is written into authoritative docs;
- [ ] old `no length stratification`, `Y=120s`, and `n>=100` headline locks are explicitly superseded, not silently deleted;
- [ ] first-session 1.5 RPS is documented as prefix-cache-confounded diagnostic evidence, not a clean UNDER anchor;
- [ ] old unloaded floor is classified for cache-state trustworthiness;
- [ ] controlled headline prefix caching is disabled and preflight-enforced;
- [ ] nearest-rank p99 is one shared versioned measurement definition;
- [ ] historical metrics remain historical and are not silently recomputed under the new percentile convention;
- [ ] canonical 4,000-prompt workload is unique, deterministic, stratified, and frozen only after tokenizer capacity validation;
- [ ] exact tokenizer evidence confirms the selected workload fits the planned server context/output policy;
- [ ] schedule generation produces exactly 4,000 post-warmup scheduled arrivals before runtime;
- [ ] runtime always issues the complete frozen schedule, independent of responses;
- [ ] nominal λ, realized schedule rate, and actual send rate are separated;
- [ ] >5% TTFT censoring suppresses ordinary p99 verdicts;
- [ ] sub-5% boundary censoring cannot silently finalize a crossing;
- [ ] repeats use new arrival + assignment seeds, drain between runs, own warmup, no vLLM restart;
- [ ] N cannot exceed 5,000 by hidden prompt reuse;
- [ ] persistent uncertainty has a tested interval-reporting path;
- [ ] natural-random secondary remains separate from the controlled headline;
- [ ] all old regression suites remain green;
- [ ] every new load-bearing control is proven to bite on a bad variant;
- [ ] historical artifacts/blobs/hashes remain unchanged;
- [ ] no GPU instance was created;
- [ ] agent halts with the second-session plan for human review.

---

## One-line mental model

```text
R3 gave the evidence size and exposed cache/metric confounders;
now freeze a cache-neutral, versioned, exact-N matched workload,
prove the new measurement contract without regressing the old instrument,
and only then design a narrow human-owned GPU re-bracket + confirmation session.
```

# Week 2 GPU Session — Redesign Handoff README

## Purpose

Use this document to resume Week 2 planning in a fresh chat without re-reading the full project history.

Week 2 is **not complete**. The first real GPU session was valuable, but it exposed a flaw in the statistical design of the headline breach experiment. The load generator, replay controls, GPU plumbing, and most measurement infrastructure worked; the remaining problem is narrower:

> **The current fixed-duration / natural-random-prompt design does not isolate load cleanly enough for a defensible p99 TTFT breach RPS.**

The next planning session should focus on redesigning the statistical/sampling layer, not rebuilding the load generator or reopening unrelated Week 2 decisions.

Authoritative project docs still take precedence:
- `WEEK2_PLAN.md` — locked decisions and provenance
- `WEEK2_EXECUTION.md` — execution order and hard stops
- `docs/WEEK2_GPU_PREFLIGHT.md` — GPU-session preflight
- `docs/WEEK2_REMEDIATION_REPORT.md` — pre-GPU remediation record
- `STATUS.md` — current phase/state

If this handoff conflicts with an authoritative source on a locked decision, surface the conflict rather than silently reconciling it.

---

## 1. Original Week 2 objective

Produce `BASELINE.md` with:

> **At X RPS, naive single-replica serving breaches the 500ms p99 TTFT SLO.**

The intended causal story was:

```text
same workload characteristics
same model/server configuration
same output policy
same corpus

change only RPS
        ↓
observe p99 TTFT
        ↓
find first point ≥ 500ms
```

Important pre-existing locks:
- p99 TTFT is the headline metric
- 500ms is the headline SLO
- 2s is a secondary severe-degradation line
- seeded Poisson arrivals define the headline breach
- steady arrivals are a secondary reference
- natural ShareGPT prompt spread is used
- open-loop load generation
- frozen schedules + pinned corpus define replay identity
- concurrent mock latency is untrusted
- all reported latency comes from real vLLM/GPU
- durable artifacts must be sufficient for offline recomputation

---

## 2. Pre-GPU state

Pre-GPU remediation had closed the known blockers.

| Setting | Value |
|---|---|
| Concurrency cap | 3000 |
| Offered-vs-achieved band | ±5% |
| Measurement window | 120s |
| Warmup | 10s placeholder; final value deferred |
| Linux scheduler spin | 0ms |
| Linux fd limit | 65535 enforced by run script |
| Driver topology | same GCP VM as vLLM |
| Network path | loopback (`127.0.0.1:8000`) |
| GPU | 1× L4 Spot |
| Model | `meta-llama/Llama-3.2-3B-Instruct` |
| Output-token policy used | `max_tokens=512` |
| vLLM eager policy | non-eager preferred; eager fallback only if required |

The GPU session pins an exact pushed SHA; it does not require merging to `main`.

---

## 3. First GPU session summary

The first real Week 2 GPU session ran on 2026-08-18.

Approximate total:
- ~1h50m
- ~$1.85
- instance deleted
- no orphaned disks
- teardown independently verified

The session did **not** produce a defensible final breach RPS.

It did produce important findings and exposed:
1. a corpus hash portability bug
2. a prompt-tail confound in the headline experiment
3. an inadequate p99 sample-validity rule
4. timeout censoring at saturation
5. a low-RPS offered-vs-achieved semantics issue
6. a fractional-RPS artifact-checker bug

---

## 4. Corpus reproducibility defect — caught and fixed

### Symptom

Stage A initially refused with:

```text
corpus drift detected
```

### Cause

Windows had `core.autocrlf=true` and the repo lacked `.gitattributes` protection for the corpus JSONL.

Result:
- committed Git blob / Linux checkout: LF
- Windows working tree: CRLF
- frozen schedules had pinned the Windows working-tree hash

### Important interpretation

The actual prompt values did **not** change.

Verified three ways:
1. parsed corpus rows were identical: 5000 = 5000
2. regenerated schedules had byte-identical `entries`
3. only the stored `corpus_sha256` values changed

The guardrail correctly refused a supposedly frozen workload that was not portable.

### Fix

`.gitattributes` now prevents newline rewriting for corpus/benchmark JSONL files.

Treat this as a **successful reproducibility-control finding**, not as a reason to distrust the corrected prompt workload.

---

## 5. Clean low-load measurements

Observed clean points included:

| Offered RPS | Achieved | p99 TTFT | Shed | Errors | Initial read |
|---:|---:|---:|---:|---:|---|
| 1.5 | ~matched | 113.6ms | 0 | 0 | under SLO |
| 2 | 1.875 | ~524–553ms depending percentile implementation | 0 | 0 | apparently near/beyond breach |
| 5 | 5.000 | ~819ms | 0 | 0 | clearly over SLO |

The exact 2-RPS p99 differs slightly between the live point-record percentile implementation and later diagnostic code. That is not the central issue.

The central issue is that the 2-RPS classification was **not robust**.

---

## 6. Unloaded TTFT floor

A true no-contention floor was measured because the first Stage A point appeared already breached.

Method:
- concurrency 1
- same 248 prompts as the 2-RPS schedule
- same model/configuration
- each stream stopped after first content token
- 248 samples
- 0 errors

Results:

| Metric | Value |
|---|---:|
| p50 TTFT | 82.8ms |
| p95 TTFT | 176.4ms |
| **p99 TTFT** | **402.3ms** |
| max | 523.4ms |

### Trusted conclusion

> **The 500ms SLO is achievable for this corpus/model/configuration with no competing decode work.**

Therefore the project thesis remains viable.

Do **not** interpret `402ms → ~525ms` as a precise decomposition of load cost. The safe conclusion is only that concurrent load/interference can move the tail enough to matter.

---

## 7. Main design defect — prompt-tail confounding

### What the plan intended

The plan intended the same seeded natural ShareGPT distribution to hold the prompt contribution constant while RPS changed.

### What actually happened

The seeding worked correctly and prompt streams were nested.

But the fixed 120s window means:

```text
higher RPS
    ↓
more requests
    ↓
larger finite sample
    ↓
greater chance of drawing rare long prompts
```

So the **population distribution** was constant, but the **realized empirical tail** was not.

Observed prompt-tail realization:

| Schedule | Requests | prompt p50 | prompt p99 | max prompt | prompts >10k chars |
|---|---:|---:|---:|---:|---:|
| 1.0 RPS | ~116 | 129 | 6,890 | 8,049 | 0 |
| 1.5 RPS | ~182 | 129 | 8,049 | 14,960 | 1 |
| 2 RPS | ~248 | 129 | 11,327 | 16,781 | 4 |
| 5 RPS | ~643 | 130 | 10,034 | 16,781 | 7 |
| 10 RPS | ~1316 | 142 | 10,034 | 39,801 | 14 |

That is why:

```text
1.5 RPS p99 ≈ 113.6ms
```

could be much lower than:

```text
unloaded p99 over the 2-RPS prompt set ≈ 402.3ms
```

They are different realized prompt sets.

### Diagnostic evidence

A diagnostic restricted the 2-RPS sample to a shared prompt-length ceiling.

At 2 RPS, excluding essentially one extreme prompt moved p99 from about:

```text
552.9ms → 434.8ms
```

which flips breach classification.

Correct interpretation:

> **The current 2-RPS breach classification is highly sensitive to the realized long-prompt tail.**

Do not interpret the ~118ms difference as an exact causal prompt contribution.

---

## 8. Second statistical defect — `n >= 100` is not enough for a reliable p99

The existing validity rule uses a minimum of 100 achieved samples.

That makes p99 computable, but does **not** make it reliable for this heavy-tailed workload.

Approximate top-1% support:

| n | Expected observations in top 1% |
|---:|---:|
| 100 | 1 |
| 166 | 1.66 |
| 225 | 2.25 |
| 600 | 6 |

A diagnostic bootstrap showed:

| Point | n | p99 | diagnostic 95% interval | Interpretation |
|---|---:|---:|---:|---|
| 1.5 RPS | 166 | 113.4ms | [110.0, 120.5] | clearly under |
| **2 RPS** | 225 | 552.9ms | **[361.1, 656.8]** | **straddles 500ms** |
| 5 RPS | 600 | 817.9ms | [662.9, 1267.2] | clearly over |

The bootstrap is diagnostic only; concurrent request latencies are not guaranteed iid.

Trusted conclusion:

> **The 2-RPS point is too statistically unstable to support a final under/over classification relative to 500ms.**

Do not lock `n=2000` merely because a rough scaling estimate suggested it.

The next plan must define the actual statistical-quality criterion first.

---

## 9. Third measurement defect — 60s timeout censors saturated points

The loadgen default client timeout is:

```text
--timeout-s 60.0
```

At higher load:

| RPS | Rows | TTFT samples | Errors |
|---:|---:|---:|---:|
| 5 | 643 | 643 | 0 |
| 10 | 1316 | 876 | 440 (~33%) |
| 20 | 2597 | 772 | 1825 (~70%) |
| 30 | 3847 | 714 | 3133 (~81%) |

Reported p99 values clustered near 60s.

That is **not a valid latency plateau**.

Slow requests timed out and disappeared from the percentile calculation, leaving only survivors. This creates survivorship/right-censoring bias.

Therefore:
- 10/20/30-RPS p99 values are invalid as ordinary latency measurements
- they are still valid evidence of severe saturation / timeout behavior
- the metrics validity layer needs an error/censoring rule
- `tail_valid` cannot mean only “enough surviving samples”

Do not assume the right fix is simply increasing the timeout.

---

## 10. Offered-vs-achieved issue at low Poisson rates

At 2 RPS:

```text
target lambda = 2.0
achieved = 1.875
reported divergence = -6.25%
```

But the materialized finite Poisson schedule itself realized fewer than exactly `lambda × time` arrivals.

Separate these concepts:

```text
nominal lambda
    = stochastic workload parameter

materialized schedule
    = exact sends the driver was asked to issue

actual sends
    = what the driver really issued
```

The existing gate was intended to answer:

> Did the driver keep up with its schedule?

The next plan should explicitly decide:
1. what defines the x-axis
2. what tests scheduler fidelity
3. how finite-Poisson count variance is reported

Do not silently change semantics.

---

## 11. Fractional-RPS artifact checker bug

`pull_artifacts.sh` currently mis-parses names like:

```text
poisson_rps1.5.raw_log.jsonl
```

because logic equivalent to:

```python
name.split(".")[0]
```

truncates it to:

```text
poisson_rps1
```

The 1.5-RPS artifacts were actually intact:
- raw log present
- sidecar present
- metrics present
- 182/182 requests
- 0 errors

This bug must be fixed before the next GPU run because the corrected breach search will likely use fractional RPS points.

---

## 12. Artifact state after teardown

Before teardown, every remote artifact was SHA-256 compared against its local copy.

Result:

```text
22 verified
0 missing
0 mismatched

ARTIFACT SET COMPLETE: YES
```

Then the GPU instance was deleted and independently verified absent.

Current issue:

```text
benchmarks/runs/
```

is gitignored.

Therefore these session artifacts currently exist only on the local machine.

Recommended next action:

> Promote the accepted first-session artifacts into tracked diagnostic evidence, clearly labelled **diagnostic / failed-experiment evidence**, not baseline evidence.

---

## 13. What is trustworthy from this session

### Trusted findings

1. corpus-drift guard worked correctly
2. corrected corpus/schedules preserve actual prompt entries
3. vLLM ran successfully in the intended environment
4. open-loop low-load driving worked with no shed/errors
5. unloaded p99 on the tested 248-prompt set is ~402.3ms
6. 500ms is achievable without contention
7. concurrent load materially affects TTFT
8. realized long-prompt tail can dominate low-sample empirical p99
9. current ≥100-sample rule is inadequate as a p99 reliability criterion
10. 60s timeout censors saturated points
11. current metrics validity can incorrectly bless highly censored points
12. fractional RPS breaks artifact completeness parsing
13. no precise final breach RPS is supportable from this session

### Do not publish as final claims

Do **not** claim:
- `breach RPS = 2`
- `p99 at 10 RPS ≈ 60s` as ordinary measured latency
- capped-prompt diagnostic = corrected baseline
- the ~118ms diagnostic delta is exactly “prompt-caused latency”
- ≥100 samples is enough for p99
- a fine breach location from the current session

---

## 14. What did NOT fail and should remain locked by default

Do not reopen these unless new evidence requires it:

- open-loop scheduler architecture
- absolute-time scheduling
- Poisson as headline arrival process
- steady as secondary reference
- adversarial as separate scenario
- pinned ShareGPT corpus
- frozen schedule/replay model
- independent arrival/corpus RNGs
- raw log + samples sidecar
- 500ms SLO
- 2s secondary line
- concurrency cap = 3000
- Linux scheduler spin = 0ms
- on-instance load generation
- loopback network path
- fd-limit protection
- Spot provisioning
- exact benchmark-SHA pinning
- Week 2 teardown wrapper
- mock trust boundary
- durable artifact capture

The redesign is primarily about:

> **prompt matching + p99 statistical validity + timeout/error validity**

---

## 15. Mental model for redesign

Think of observed p99 TTFT as:

```text
observed p99
    =
intrinsic prompt-cost tail
    +
load-induced interference / queueing / decode contention
    +
finite-sample variability
    +
measurement artifacts
```

For the headline baseline:

```text
intrinsic prompt-cost tail
    = held fixed by construction

load-induced interference
    = the variable changed by RPS

finite-sample variability
    = made small / quantified enough to classify relative to 500ms

measurement artifacts
    = eliminated or explicitly invalidate the point
```

The first GPU design controlled the prompt **population distribution**.

It did not sufficiently control the **realized empirical tail**, which is what dominates a small-sample p99.

---

## 16. Three design questions the next chat must solve

### 16.1 Matched empirical prompt workload

Goal:

> Comparable RPS points must see a controlled empirical prompt-cost mix so p99 movement can be attributed to load rather than luck of the prompt draw.

Candidate direction:

#### Canonical prompt block / matched prompt multiset

Conceptually:

```text
canonical block:
P1 P2 P3 ... PN
including a fixed representative tail

low RPS:
same composition scheduled slowly

higher RPS:
same composition / repetitions scheduled faster
```

Need to reconcile this with:
- Poisson remains headline arrival process
- 120s fixed duration was previously locked
- different RPS implies different counts in a fixed duration
- repeating prompts may introduce periodicity or cache effects if done carelessly
- natural ShareGPT spread should remain represented
- Week 4+ comparisons must replay the same corrected workload fairly

Candidate approaches to compare:
1. repeated canonical prompt block with fixed duration
2. matched prompt strata / quantile buckets
3. fixed request count with variable duration
4. longer natural-random runs + repetitions/uncertainty
5. controlled headline workload + natural-random secondary validation

Preferred high-level direction from current discussion:

> **Use a matched controlled workload for the headline causal breach curve, and natural-random traffic as secondary realism validation.**

Not yet formally locked.

---

### 16.2 What makes p99 statistically reliable?

Current rule:

```text
n >= 100
```

is insufficient.

Possible approaches:

#### A. Larger minimum sample size
Simple, but N needs justification.

#### B. Repeated runs per point
Makes run-to-run variability visible.

#### C. Classification uncertainty/stability rule
Conceptually:

```text
UNDER only if uncertainty stays below 500ms
OVER only if uncertainty stays above 500ms
otherwise collect more evidence
```

Need care because concurrent latencies may be temporally dependent.

#### D. Hybrid
For example:
- minimum duration
- minimum request count
- repeated blocks/seeds
- classification stability criterion

The actual question is:

> **What evidence is enough to classify a point as under or over 500ms with confidence appropriate for this project?**

The rough `~2000 samples/point` idea is not locked.

---

### 16.3 Timeout/error/censoring validity

Current defect:

```text
81% errors
+
>100 surviving TTFT samples
```

can still produce `tail_valid=true`.

Need to decide:
- whether any timeout invalidates p99
- whether a small allowed error rate exists
- what threshold counts as material censoring
- whether 60s timeout remains
- how censored points appear on charts
- whether deep-saturation points are reported as `timeout/saturated`
- whether error rate becomes a secondary saturation metric

Likely principle:

> **If the TTFT sample is materially censored by timeout/error, do not report its p99 as an ordinary latency percentile.**

Exact rule still open.

---

## 17. Secondary cleanup before the next GPU session

These are real but subordinate:

### A. Offered vs achieved
Clarify nominal λ vs realized materialized schedule vs actual send rate.

### B. Fractional-RPS parser
Fix before next session.

### C. Artifact promotion
Promote the 22 first-session artifacts into tracked diagnostic evidence.

### D. Session findings record
Recommended permanent doc:

```text
docs/WEEK2_GPU_SESSION_FINDINGS.md
```

It should record:
- original assumption
- what GPU data falsified
- trusted vs invalid results
- timeout/censoring defect
- prompt-tail confound
- sample-size problem
- tooling defects
- redesign requirements
- explicit statement that no final breach RPS was produced

---

## 18. Recommended execution order from here

Do **not** start another GPU session yet.

```text
1. Preserve first-session diagnostic artifacts
        ↓
2. Write GPU-session findings record
        ↓
3. Fix fractional-RPS artifact checker
        ↓
4. Design matched prompt workload
        ↓
5. Design p99 validity / evidence policy
        ↓
6. Design timeout/error censoring gate
        ↓
7. Revisit 120s window only if new evidence requires it
        ↓
8. Update authoritative Week 2 plan/execution docs with provenance
        ↓
9. Pre-generate corrected schedules
        ↓
10. Run a narrow second GPU session
        ↓
11. Fine-resolve breach
        ↓
12. Resolve final warmup N offline
        ↓
13. Produce BASELINE.md
        ↓
14. Close Week 2
```

---

## 19. What the second GPU session should look like

The second session should be much narrower than the first.

Before meter start it should already know:
- matched workload construction
- p99 classification rule
- sample/repetition target
- timeout/error validity rule
- candidate RPS region informed by first session
- artifact paths
- fractional-RPS handling fixed
- exact benchmark SHA

Likely region of interest:

```text
low single-digit RPS
```

Do not assume the final crossing is exactly 2 RPS.

Current data supports only:
- 1.5 RPS under its current realized prompt draw was clearly below
- 5 RPS under its current draw was clearly above
- 2 RPS is confound-sensitive / statistically unstable

The corrected workload can move the exact crossing.

---

## 20. Definition of success for the redesign

Before another GPU run, answer YES to all:

- [ ] comparable RPS points see a controlled empirical prompt-cost mix
- [ ] p99 cannot flip because one point randomly drew one extra rare prompt
- [ ] p99 validity is stronger than `n >= 100`
- [ ] sample/repetition requirement is justified before meter start
- [ ] Poisson remains the headline arrival process
- [ ] fixed duration vs request count is explicitly resolved
- [ ] timeout/censored points cannot print misleading ordinary p99 values
- [ ] offered-vs-achieved semantics are separated from finite-Poisson realization noise
- [ ] fractional-RPS artifact handling works
- [ ] first-session diagnostic artifacts are preserved
- [ ] later Week 4+ routing strategies can replay the corrected workload fairly
- [ ] changes to previous locks carry provenance

---

## 21. Current project state in one paragraph

Week 2's infrastructure is largely successful, but the first real GPU session falsified the assumption that seeded natural prompt sampling over a fixed 120s window holds the prompt contribution sufficiently constant for a low-sample p99 breach curve. The unloaded floor (~402ms p99 on the 248-prompt 2-RPS set) proves the 500ms SLO is achievable without contention, so the project thesis remains viable. However, the 2-RPS breach classification is too sensitive to the realized long-prompt tail, the ≥100-sample rule is insufficient for a reliable p99 near the crossing, and a 60s client timeout censors deep-saturation percentiles while the current validity gate fails to reject them. The GPU session is fully torn down and its artifacts are safely copied locally but still gitignored. The next task is an offline redesign of matched prompt sampling, p99 statistical validity, and timeout/error censoring; only after those are locked should a narrow second GPU session run to produce the final `BASELINE.md`.

---

## 22. Suggested opening prompt for the next chat

> We are resuming Week 2 of LLMRouter from the attached handoff. The first GPU session exposed a statistical-design defect in the breach experiment; do not reopen the load-generator architecture or other already-locked infrastructure. Help me redesign the remaining experiment in decision order. I want to lock three things before another GPU session: (1) how to hold the empirical prompt-cost mix constant while preserving Poisson arrivals, (2) what sample/repetition/uncertainty rule makes p99 classification around 500ms defensible, and (3) how timeout/error censoring invalidates a point. Walk me through the tradeoffs one decision at a time and preserve provenance when changing any previously locked Week 2 rule.

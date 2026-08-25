# Week 2 Closeout Plan — Targeted Breach Confirmation

> **STATUS: EXECUTABLE — SESSION 3**
>
> Role: the session-3 lambda/decision-tree addendum. Sustained-scout and
> headline schedules for λ∈{0.4, 0.6, 0.3} are pre-generated and committed
> under `benchmarks/schedules/week2_redesign/` (`sustained_scout/`,
> `headline/`); `repeat_policy.json` (`policy_version` 5) authorizes them.
> Server/model/corpus/percentile/warmup/censoring/repeat mechanics are
> **unchanged from session #2** — `WEEK2_GPU_SESSION_2_PLAN.md` remains the
> mechanics reference; this document adds only which schedules to drive and
> the stop/continue decision tree. By explicit user direction, a separate
> Hard Stop R-DOC / R-PREGPU document pass was **not** run for this
> extension — see `repeat_policy.json`'s `human_locks_session3`.
> Index: `WEEK2_DOC_INDEX.md`.

## Objective

Finish Week 2 with a defensible sustained-capacity statement for one naive vLLM replica:

> Under the locked canonical Poisson workload, the replica remains below the 500 ms p99 TTFT SLO at **A RPS** and breaches it by **B RPS**, giving a breach interval of **`(A, B]`**.

Current evidence establishes **0.75 RPS = OVER** and **0.5 RPS = UNCERTAIN**. The missing result is a confirmed **UNDER** anchor below 0.5 RPS.

## Phase 1 — Close Session 2 Offline

1. Review and commit the threshold-family classification fix.
2. Re-run the complete test suite and both control-bite suites.
3. Reclassify Session 2 as `NO_UNDER_ANCHOR` and promote accepted artifacts with a hash manifest.
4. Update the execution/status documents so 0.5 remains `UNCERTAIN`; do not majority-vote or add post-hoc repeats.
5. Investigate the local background-monitor kills before another long session.

## Phase 2 — Prepare the Minimal Session 3

Pre-generate and freeze all schedules before renting the GPU:

| RPS | Role |
|---:|---|
| 0.4 | Candidate UNDER endpoint |
| 0.6 | Candidate tighter OVER endpoint |
| 0.3 | Fallback only if 0.4 is not cleanly UNDER |
| 0.75 | Existing confirmed OVER fallback; do not rerun by default |

Retain the locked server, model, corpus, output-token, eager-mode, prefix-cache, warmup, censoring, and repeat policies. Each sustained or headline run must satisfy **at least 45 minutes and at least 2,000 post-warmup requests, whichever binds last**.

Before launch:

- Exercise the real CLI paths end to end with the frozen schedules.
- Verify threshold-family classification using independently seeded, unequal-count synthetic repeats.
- Complete fresh document and pre-GPU audits; record the new benchmark SHA.
- Precommit the decision tree below. Do not invent new RPS points while the GPU is running.

## Phase 3 — Targeted GPU Execution

1. Verify configuration, prefix caching off, server health, and an acceptable unloaded floor.
2. Run sustained scouts at **0.4** and **0.6 RPS** only.
3. Apply the decision tree:

| Scout outcome | Action |
|---|---|
| 0.4 UNDER; 0.6 OVER | Run three independent headline repeats at both endpoints. Target result: `(0.4, 0.6]`. |
| 0.4 not UNDER | Run the prepared 0.3 scout; if UNDER, confirm 0.3 and the lowest prepared OVER endpoint. |
| 0.6 not OVER | Confirm 0.4 as UNDER and reuse the already confirmed 0.75 OVER endpoint, subject to identity/audit approval. |
| No prepared UNDER | Stop with `NO_UNDER_ANCHOR`; design any further extension offline. |

Endpoint classification remains unanimous across three independent repeats. Preserve split outcomes as `UNCERTAIN`.

## Scope Control for Optimal Gain

- Do **not** rerun 0.5 merely to force a classification; its split repeats are meaningful boundary evidence.
- Do **not** repeat the natural-random, steady-arrival, or adversarial scenarios; they already served their diagnostic purpose.
- Do **not** perform a fine-grained search around 0.5. Natural run-to-run variation is large enough that narrower points may add uncertainty rather than precision.
- Stop as soon as the highest confirmed UNDER and lowest confirmed OVER endpoints produce a defensible interval.

## Final Closeout

After endpoint confirmation:

1. Promote evidence and hashes immediately.
2. Generate the breach curve and supporting queueing/censoring plots.
3. Write `BASELINE.md` with the measured interval, workload identity, endpoint repeat results, validity gates, and limitations.
4. Update `WEEK2_PLAN.md`, `WEEK2_EXECUTION.md`, and `STATUS.md`; mark Week 2 complete.

## Completion Criterion

Week 2 closes when `BASELINE.md` can state a reproducible interval such as:

> The naive single L4 replica is unanimously UNDER at 0.4 RPS and unanimously OVER at 0.6 RPS; therefore its sustained 500 ms p99 TTFT breach interval is **`(0.4, 0.6]` RPS** under the locked canonical workload.

Report an interval, not an interpolated single-number capacity that was never measured.

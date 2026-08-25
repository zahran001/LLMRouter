# Week 2 — GPU session #3 report: a closed breach interval

> **STATUS: EVIDENCE — DOES NOT GOVERN EXECUTION**
>
> Record of what actually happened on 2026-08-25. Decides no experiment
> semantics; not a runbook. The runbook followed was `WEEK2_CLOSEOUT_PLAN.md`
> (session-3 addendum layered on `WEEK2_GPU_SESSION_2_PLAN.md`'s unchanged
> mechanics). By explicit user direction this session ran without a separate
> Hard Stop R-DOC / R-PREGPU document pass — session #2 already established
> and evidenced the server/model/corpus/percentile/warmup/censoring/repeat
> machinery, and this session only extended the λ range using the same
> tooling (`repeat_policy.json` `human_locks_session3` / D-SESSION3-1).

## 1. Executive summary

Session #3 set out to find a confirmed **UNDER** anchor below session #2's
open interval (`NO_UNDER_ANCHOR`: λ=0.75 OVER, λ=0.5 UNCERTAIN). It drove
sustained-scout at λ∈{0.4, 0.6}, read a clean bracket (0.4 UNDER, 0.6 OVER),
and confirmed it with three full Tier B headline repeats at both λ.

**Result: unanimous at both endpoints.** λ=0.4 classified **UNDER** on all
three repeats (472.6ms / 447.0ms / 484.3ms). λ=0.6 classified **OVER** on all
three repeats (526.3ms / 567.1ms / 599.7ms). No split, no `UNCERTAIN`
outcome — this is the clean bracket the closeout plan set out to find.

> **The naive single L4 replica is unanimously UNDER at 0.4 RPS and
> unanimously OVER at 0.6 RPS: the sustained 500ms p99 TTFT breach interval
> is `(0.4, 0.6]` RPS** under the locked canonical Poisson workload —
> tighter than session #2's open `(?, 0.75]`.

Two spot preemptions hit the session (one during the initial λ=0.4 scout,
one during Tier B repeat 3's λ=0.4 leg), both recovered cleanly by
restarting the instance, relaunching vLLM (model already cached, so fast),
re-verifying the prefix-cache gate, discarding the incomplete point, and
redriving it from scratch. Neither preemption reached a completed,
promoted point — every number above is from an uninterrupted drive.

## 2. Session identity

| Field | Value |
|---|---|
| Benchmark SHA | `4700a00523d56c29d38bfb92252d0543650a6e3e` |
| Instance | `llmrouter-vllm-l4-week2`, `g2-standard-8` + 1× L4, SPOT, `us-central1-a` (3 launches — see §6) |
| Model | `meta-llama/Llama-3.2-3B-Instruct` |
| Resolved server config | `enforce_eager=1`, `disable_prefix_caching=1`, `max_model_len=20000` — unchanged from session #2 |
| Prefix-cache verdict | `PREFIX_CACHING_DISABLED`, re-verified after every relaunch (ratios 0.93–0.97, all ≥ 0.85) |
| Floor | 4000/4000, p99=410.3ms, 90ms headroom, 0% censoring |
| Policy | `repeat_policy.json` `policy_version` 5, `human_locks_session3` / D-SESSION3-1 |
| Runbook | `WEEK2_CLOSEOUT_PLAN.md` (session-3 addendum) + `WEEK2_GPU_SESSION_2_PLAN.md` (mechanics, unchanged) |

Canonical headline membership (unchanged from session #2):
`a49ecdd8071920303f240fcf0b8da42dbbc66da593ae88e3c07aa246c4b5aa7b` (4,000
prompts).

## 3. Tier A — sustained-scout bracket

| λ | state | p99 TTFT | issued (target N) | gates |
|---|---|---:|---|---|
| 0.4 | UNDER | 452.8ms | 2031/2031 (N=2000 post-warmup) | clean — 0 shed, 0% censoring, exact_n_honoured, schedule_delivery_ok |
| 0.6 | OVER | 571.4ms | 2040/2040 (N=2000 post-warmup) | clean — 0 shed, 0% censoring, exact_n_honoured, schedule_delivery_ok |

λ=0.4's scout attempt was interrupted once by a spot preemption (§6) and
redriven cleanly from scratch; the number above is from the completed
redrive. Diagnostic only — `evidence_class: scout_diagnostic`, never enters
classification.

**Decision (equivalent to Hard Stop GPU-1, applied per the precommitted
`WEEK2_CLOSEOUT_PLAN.md` decision tree):** 0.4 UNDER + 0.6 OVER → proceed to
Tier B, three headline repeats at both λ, driven one repeat at a time.

## 4. Tier B — headline confirmation (`headline_evidence`)

Driven repeat-major, one repeat per invocation (both λ in one drain-gated
`drive_headline_family.py` call per repeat), pulling artifacts after every
repeat — same discipline as session #2.

| Repeat | λ=0.4 | λ=0.6 |
|---|---|---|
| 1 | UNDER, p99=472.6ms | OVER, p99=526.3ms |
| 2 | UNDER, p99=447.0ms | OVER, p99=567.1ms |
| 3 | UNDER, p99=484.3ms | OVER, p99=599.7ms |

All 6 points: `N=2000` measured population, `exact_n_honoured`/
`schedule_delivery_ok` true, 0 shed, 0 censored, `over_censored_proven:
false` (never needed — every OVER point resolved on a computed p99, not
censoring alone).

**Classification:** λ=0.4 → **UNDER** (3/3 unanimous). λ=0.6 → **OVER** (3/3
unanimous). Matches D-CLEAN-1's unanimity rule with no split at either
endpoint — no majority vote, no fourth repeat, no re-drive of the boundary
was needed or performed.

Repeat 3's λ=0.4 leg was interrupted once by a spot preemption (§6) and the
entire repeat (both λ) was redriven from scratch; the numbers above are from
the completed redrive.

## 5. Final classification

```
under_lambdas:      [0.4]
over_lambdas:       [0.6]
unresolved_lambdas: []
resolution:         RESOLVED
breach_interval:    (0.4, 0.6]
message: "Both endpoints unanimous across 3 independent repeats. The
          crossing is bracketed and the interval is closed."
```

This closes `WEEK2_CLOSEOUT_PLAN.md`'s completion criterion. Combined with
session #2's λ=0.75 OVER point (still valid, not re-driven — Scope Control),
the full confirmed picture across sessions is: UNDER at 0.4, OVER at 0.5
(`UNCERTAIN`, boundary split, left as-is per D-CLEAN-1 — not resolved and
not re-driven), OVER at 0.6 and 0.75. The defining, closed interval for a
breach statement is **`(0.4, 0.6]`**.

## 6. Operational notes — two spot preemptions, both recovered

Session #3 ran across **three instance launches** on the same spot
instance name, `llmrouter-vllm-l4-week2`:

| Launch | Started (UTC) | Ended | Cause | What was lost |
|---|---|---|---|---|
| 1 | 2026-08-25 06:35 | 2026-08-25 08:01 (preempted) | spot reclaim | in-flight sustained-scout λ=0.4 attempt (~51 min of drive time; no completed point, nothing promoted) |
| 2 | 2026-08-25 ~08:12 | 2026-08-25 17:47 (preempted) | spot reclaim | in-flight Tier B repeat 3, λ=0.4 leg (~62 min of drive time; no completed point) |
| 3 | 2026-08-25 ~17:53 | 2026-08-25 ~20:40 (teardown) | — | — |

**Recovery procedure, both times (matching session #2 attempt-2's §9
precedent — "poll the remote PID directly" — but here applied proactively
per the user's explicit request to check preemption status every ~8
minutes):**
1. Detect via `gcloud compute instances describe ... --format=value(status)`
   → `TERMINATED`.
2. `gcloud compute instances start` — same instance name, new external IP
   each time; boot disk (venv, model weights, repo clone, HF token) is
   preserved.
3. Wait for SSH (host key re-accepted via `--quiet`), relaunch vLLM under
   `nohup` (fast both times — the model was already cached on disk, no
   re-download).
4. Re-verify the prefix-cache gate (`verify-cache`) — required before
   driving anything further; passed both times.
5. Delete the incomplete point's partial `raw_log.jsonl`/`samples.jsonl` (no
   `metrics.json` exists for an interrupted point, so nothing valid was ever
   at risk of being silently accepted).
6. Redrive the interrupted point (or whole repeat, for the Tier B case)
   from scratch.

**Cost impact:** each preemption cost roughly its own elapsed drive time in
wasted GPU-seconds (no partial credit — the schedules are deterministic and
replayed byte-for-byte from the same frozen artifact) plus a few minutes of
relaunch overhead. Neither reached a written `metrics.json`, so no
completed point was lost or had to be distrusted — every number in §3–§4 is
from an uninterrupted, complete drive.

**Worth investigating before a future long session** (carried over from
session #2 attempt-2's own unresolved note): two preemptions in one ~14-hour
session is a high rate for `us-central1-a` spot L4 capacity; if this
recurs, consider a different zone/region or an on-demand instance for the
next long Tier B drive.

## 7. Artifacts on disk

All pulled, hash/completeness-checked via `pull_artifacts.sh`, left in place
under `benchmarks/runs/` (gitignored, per session #2's pattern — not yet
promoted to `benchmarks/evidence/`):

| Path | Contents |
|---|---|
| `floor/` | Unloaded floor for this session's instance; 410.3ms p99 |
| `sustained_scout/` | 2 new Tier A points (λ=0.4, 0.6), `scout_diagnostic` — alongside session #2's existing 4 points in the same directory |
| `headline/` | 6 new points: 3 repeats × {0.4, 0.6} — alongside session #2's existing 9 points (3×{0.5,0.75} + 3 legacy repeat-1 points) in the same directory, 15 total |
| `preflight/prefix_cache_verdict.json` | Latest gate verdict (re-verified 3 times, once per launch) |
| `vllm.log` | Most recent launch's log (overwritten on each relaunch; not preserved per-launch) |

Not yet done: promotion into `benchmarks/evidence/week2/session_3/` with a
hash manifest, mirroring `scripts/promote_session_2_evidence.py`'s pattern.
Held pending review of this report, same reasoning as session #2's
promotion delay.

## 8. Approximate cost and duration

~13.8 hours of total instance uptime across the 3 launches (86 min + ~9.6h +
~2.8h), including both preemption-recovery overheads. At the plan's cited
spot rate (~$0.40–0.50/h), approximate session cost is **$5.50–$7.00** —
consistent with session #2 attempt-2's per-session cost and well under the
$10 canary.

## 9. What's next

1. Promote this session's 8 new points (2 sustained-scout + 6 headline)
   into `benchmarks/evidence/week2/session_3/` with a hash manifest.
2. Generate the breach curve and supporting plots from the now-closed
   `(0.4, 0.6]` interval, per `WEEK2_CLOSEOUT_PLAN.md`'s Final Closeout
   steps.
3. Write `BASELINE.md`: the measured interval, workload identity, endpoint
   repeat results (§4 above), validity gates, and limitations (the λ=0.5
   `UNCERTAIN` boundary split from session #2 remains on record as boundary
   evidence, not resolved and not overwritten).
4. Update `WEEK2_PLAN.md`, `WEEK2_EXECUTION.md`, and `STATUS.md` to reflect
   the closed interval; mark Week 2 complete per `WEEK2_CLOSEOUT_PLAN.md`'s
   completion criterion.

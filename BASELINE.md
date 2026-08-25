# BASELINE.md — Week 2 naive single-replica breach baseline

> **STATUS: AUTHORITATIVE — WEEK 2 DELIVERABLE**
>
> Role: the Week 2 deliverable named in `STATUS.md`, `WEEK2_PLAN.md` and
> `WEEK2_EXECUTION.md`'s Block F. States the measured breach interval, fully
> sourced and reproducible from committed schedule/corpus artifacts and the
> promoted evidence under `benchmarks/evidence/week2/`.
> Index: `WEEK2_DOC_INDEX.md`.

## The finding

> Under the locked canonical controlled-Poisson workload, a naive single
> vLLM replica (1× L4, `meta-llama/Llama-3.2-3B-Instruct`, eager mode,
> prefix caching disabled) remains below the 500ms p99 TTFT SLO at **0.4
> RPS** and breaches it by **0.6 RPS**.
>
> **Breach interval: `(0.4, 0.6]` RPS.**

Both endpoints are unanimous across three independent repeats — not an
interpolation, not a single-repeat read, and not a majority vote over a
split. Full per-repeat numbers are in [Endpoint results](#endpoint-results)
below.

## Workload identity

| Parameter | Value | Locked at |
|---|---|---|
| Corpus | Pinned ShareGPT-derived corpus, `corpus/baseline_prompts.jsonl` | Week 1 |
| Canonical multiset | `k`=6 strata (corpus quantiles 0/50/90/95/99/99.5/100), `L`=corpus q99=11,471 chars, `N`=4,000 unique prompt IDs, without replacement, membership frozen once and identical across every λ point and repeat | Hard Stop R3, 2026-08-19 (`WEEK2_PLAN.md` §10.1) |
| Canonical membership ID | `a49ecdd8071920303f240fcf0b8da42dbbc66da593ae88e3c07aa246c4b5aa7b` | — |
| `N_max` | 5,000 (structural — the pinned corpus holds exactly 5,000 prompts) | Hard Stop R3 |
| Model | `meta-llama/Llama-3.2-3B-Instruct` | — |
| Server | vLLM 0.27.1 lineage, `--enforce-eager`, `--no-enable-prefix-caching`, `--max-model-len 20000` | `WEEK2_GPU_SESSION_2_PLAN.md` §0 |
| Output policy | `max_tokens` = 512 | locked, session #2 |
| Prefix caching | Disabled and independently verified per launch (`verify_prefix_cache_disabled.py`) — a warm cache changes the cost being controlled as a function of run order; session #1's floor was invalidated by exactly this (`WEEK2_PLAN.md` §10.8) | Hard Stop R3 |
| Percentile convention | Nearest-rank: `rank = ceil(p/100 · n)`, one-indexed over sorted valid samples | `WEEK2_PLAN.md` §10.5 |
| Warmup boundary | 60s, frozen into every schedule (not a post-hoc filter) | `WEEK2_PLAN.md` §10.2/§11.4 |
| Concurrency cap | 3,000 | Week 1 (`WEEK2_PLAN.md` §8) |
| SLO | 500ms p99 TTFT | — |

The controlled canonical multiset (not natural-random draws) is what
`headline_evidence` is built from — it holds the realized prompt-length tail
constant across every λ and repeat, which is what let session #1's original
120s-window design falsify itself (`WEEK2_PLAN.md` §10.1). The
natural-random secondary curve exists precisely to check the controlled
workload isn't itself an artifact (below).

## Repeat and evidence policy

Three independent repeats per λ; classification requires **unanimous**
agreement; a 2–1 split is reported as `UNCERTAIN`, never resolved by
taking a majority or adding a fourth repeat (`repeat_policy.json`, locks D-CLEAN-1
through D-CLEAN-6, `policy_version` 5). λ≥1.5 uses a fixed `N`=4,000 per
repeat; λ≤1.25 (including this baseline's two endpoints) uses the
threshold-freeze rule — `min(45 min elapsed, 2,000 post-warmup arrivals)`,
whichever binds last — because `N`=4,000 was measured impractical below
λ=1.5 (over two hours per repeat at λ=0.5). Each threshold-lambda repeat is
an independently-seeded draw and legitimately realizes a different exact
population count; classification accepts a floor rather than requiring
exact equality for these λ (`repeat_policy.json` `headline_threshold`
block, D-ATTEMPT2-2 / D-SESSION3-1).

No escalation was used or is authorized: `n_max`=5,000 was never
approached, no majority vote was taken, and the λ=0.5 boundary split
(below) was left as recorded evidence rather than re-driven.

## Endpoint results

Three repeats per endpoint, driven across GPU session #3 (2026-08-25).
Every repeat: `exact_n_honoured`/`schedule_delivery_ok` true, 0 shed, 0
censored.

| Repeat | λ=0.4 | λ=0.6 |
|---|---|---|
| 1 | UNDER, p99=472.6ms | OVER, p99=526.3ms |
| 2 | UNDER, p99=447.0ms | OVER, p99=567.1ms |
| 3 | UNDER, p99=484.3ms | OVER, p99=599.7ms |
| **Classification** | **UNDER (3/3 unanimous)** | **OVER (3/3 unanimous)** |

Sustained-scout (Tier A, diagnostic, one point each) read the same bracket
before Tier B confirmed it: λ=0.4 UNDER at 452.8ms, λ=0.6 OVER at 571.4ms —
`evidence_class: scout_diagnostic`, never itself part of this
classification.

Full provenance, per-request logs and hash manifest:
`benchmarks/evidence/week2/session_3/`.

## Full λ sweep, both defining sessions

The controlled Poisson headline family, across the two sessions that
defined it:

| λ | Classification | Repeats | Source |
|---:|---|---|---|
| 0.4 | **UNDER** | 3/3 unanimous (472.6 / 447.0 / 484.3 ms) | session #3 |
| 0.5 | `UNCERTAIN` | 2 OVER (500.3, 504.5 ms), 1 UNDER (494.4 ms) — genuine boundary split | session #2 |
| 0.6 | **OVER** | 3/3 unanimous (526.3 / 567.1 / 599.7 ms) | session #3 |
| 0.75 | **OVER** | 3/3 unanimous (589.2, 559.0 ms, and 2.5% censoring — `OVER_CENSORED`, proven without a computed p99 on the third repeat) | session #2 |
| 1.0 | OVER | 1 (Tier A sustained-scout, diagnostic only) | session #2 |
| 1.25 | OVER_CENSORED | 1 (Tier A sustained-scout, diagnostic only, 24.2% censoring) | session #2 |
| 1.5, 2, 2.5 | `CENSORED` | 1 each (legacy repeat-1, attempt 1) — 27–37% timed out; superseded diagnostic evidence, not part of this baseline's defining family | session #2 attempt 1 |

**The defining, closed interval for this baseline is `(0.4, 0.6]`** — the
tightest bracket with unanimous agreement at both endpoints. λ=0.5's
`UNCERTAIN` split is retained as boundary evidence (it shows the crossing is
genuinely near 0.5, not that the measurement is unreliable) but is
deliberately **not** resolved here — `repeat_policy.json` forbids taking a
majority or adding a repeat to force it, and the closeout plan's own scope
control says not to re-drive it.

## Validity gates

Every point cited above as part of this baseline (λ∈{0.4, 0.6} plus the
supporting λ=0.75) passed, on every repeat:

- `exact_n_honoured`: true — the frozen schedule delivered exactly its
  target population.
- `schedule_delivery_ok`: true — offered vs. achieved rate within the ±5%
  band.
- 0 shed (no request dropped by the concurrency cap).
- 0 censored (no request timed out against the 60s client ceiling) at
  λ∈{0.4, 0.6}; λ=0.75's one `OVER_CENSORED` repeat is a proven breach via
  the exact rank-based censoring condition, not an ambiguous result
  (`repeat_policy.json` rationale, `over_censored_state_authorized`).
- Prefix-cache verdict `PREFIX_CACHING_DISABLED`, independently re-verified
  before every drive (ratios 0.93–0.97 across both sessions' launches, all
  ≥ the 0.85 gate).

## Unloaded floor

Measured fresh per GPU instance, concurrency 1, over the full canonical
4,000-prompt multiset, no arrival process:

| Session | p99 TTFT | Headroom to 500ms SLO |
|---|---:|---:|
| #2 | 397.6ms | 102ms |
| #3 | 410.3ms | 90ms |

Both floors are well clear of the SLO with no queueing — the breach at
λ∈(0.4, 0.6] is a genuine effect of sustained load, not an artifact of the
model or corpus being unable to serve fast at all.

## Secondary scope (interpretive, not headline-defining)

Per `WEEK2_PLAN.md` §11.6, the controlled Poisson workload alone defines
the breach; these support interpretation and never redefine it. All three
were driven once, at λ=0.75, during session #2 — inside the confirmed OVER
region, not re-driven for session #3's tighter interval:

| Scenario | Result |
|---|---|
| Natural-random (secondary) | UNDER, p99=371.6ms, n=471 — realized rate 0.80 rps vs. offered 0.75 (+6.4%, outside the ±5% band, flagged; plotted at achieved rate per policy). Diagnostic only. |
| Steady-arrival reference | UNDER, p99=434.8ms, N=500, issued 544/544, 0% censoring. Diagnostic only. |
| Adversarial (λ=2, long-context, run last by design) | Saturated as designed: p99≈60,005ms (client timeout ceiling), 577/1212 sent, 635 errored, 0 shed. Confirms real saturation under deliberate overload, not a latency measurement. |

## Limitations

- **λ=0.5 remains `UNCERTAIN`**, not resolved. It sits inside the closed
  `(0.4, 0.6]` bracket (a real crossing was confirmed on both sides of it),
  but its own classification is a genuine 2–1 split and this baseline does
  not claim a value for it.
- **λ≥1.5's `CENSORED` points are session #1-attempt-1 legacy diagnostic
  evidence**, not part of the family that defines this interval — kept for
  continuity, not cited as a breach measurement.
- **No further escalation was performed or is authorized.** A tighter
  bracket than `(0.4, 0.6]` (e.g. bisecting toward λ=0.5) was in scope for
  a further session but was not pursued — the closeout plan's own
  completion criterion (a defensible, unanimous, non-adjacent-integer
  bracket) was already met.
- Two spot preemptions hit GPU session #3, both recovered before any point
  completed and promoted — no cited number here is from an interrupted
  drive (`WEEK2_GPU_SESSION_3_REPORT.md` §6).

## Provenance

- Full session narratives: `WEEK2_GPU_SESSION_2_REPORT.md`,
  `WEEK2_GPU_SESSION_2_ATTEMPT_2_REPORT.md`, `WEEK2_GPU_SESSION_3_REPORT.md`.
- Promoted, hash-manifested evidence:
  `benchmarks/evidence/week2/session_2/`,
  `benchmarks/evidence/week2/session_3/` (each with its own `README.md` and
  `MANIFEST.json`).
- Machine-readable policy: `benchmarks/workloads/week2_headline/repeat_policy.json`.
- Canonical workload provenance: `benchmarks/workloads/week2_headline/canonical_v1.json`.
- Classification logic: `metrics/classification.py`.

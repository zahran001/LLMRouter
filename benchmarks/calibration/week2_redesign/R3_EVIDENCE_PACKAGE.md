# Week 2 redesign — R3 evidence package

> **STATUS: EVIDENCE — DOES NOT GOVERN EXECUTION**
>
> Role: the offline calibration `k` / `L` / `N` / `N_max` were read off at Hard Stop R3.
>
> This document records *why* something is believed. It does not govern
> execution, and any command text below is a record of what was run at the
> time, not an instruction to run it now.
> Current execution instructions: `WEEK2_GPU_SESSION_2_PLAN.md`.
> Index: `WEEK2_DOC_INDEX.md`.

**Status: recommendations, not decisions.** `k`, `L`, `N` and `N_max` are locked by the
human at Hard Stop R3 (Redesign README §4). Every number below is an input to that read.

Generated 2026-08-19T02:34:09+00:00 from:
- `benchmarks/calibration/week2_redesign/corpus_tail_analysis.json`
- `benchmarks/calibration/week2_redesign/p99_sample_size.json`
- `benchmarks/calibration/week2_redesign/prompt_cost_analysis.json`
- `benchmarks/calibration/week2_redesign/run_order_effects.json`

Regenerate the whole package with:

```
python scripts/analyze_corpus_tail.py
python scripts/analyze_prompt_cost.py
python scripts/analyze_run_order_effects.py
python scripts/calibrate_p99_sample_size.py
python scripts/report_kln_candidates.py
```

## 1. Corpus tail structure (R1)

Pinned corpus: `corpus/baseline_prompts.jsonl`, 5000 prompts, `sha256=f7ec37d33bc2f53c…`

Prompt length in characters is strongly right-skewed — the mean sits above the 80th
percentile, so "average prompt" describes almost nothing about the requests that
decide a p99.

| quantile | char_len | prompts at or above |
|---|---|---|
| p0 | 1 | — |
| p1 | 4 | — |
| p5 | 22 | — |
| p10 | 34 | — |
| p25 | 60 | — |
| p50 | 142 | — |
| p75 | 594 | — |
| p90 | 2,358 | 500 |
| p95 | 4,566 | 250 |
| p97.5 | 8,000 | — |
| p99 | 11,471 | 50 |
| p99.5 | 13,101 | 26 |
| p99.9 | 16,424 | 5 |
| p100 | 44,445 | — |

Histogram (log-spaced bins):

```
      1 -       2      1  
      2 -       4     39  ##
      4 -       6     39  ##
      6 -       9     20  #
      9 -      15     49  ###
     15 -      23    106  ######
     23 -      35    259  ################
     35 -      55    590  ####################################
     55 -      86    655  ########################################
     86 -     135    652  ########################################
    135 -     211    493  ##############################
    211 -     329    390  ########################
    329 -     514    343  #####################
    514 -     803    300  ##################
    803 -   1,255    246  ###############
  1,255 -   1,960    234  ##############
  1,960 -   3,061    193  ############
  3,061 -   4,781    155  #########
  4,781 -   7,468     95  ######
  7,468 -  11,664     95  ######
 11,664 -  18,218     43  ###
 18,218 -  28,455      1  
 28,455 -  44,445      2  
```

## 2. Candidate `k` / `L` constructions (R1)

Allocation is **proportional to each stratum's natural population share**, largest-
remainder, selected **without replacement** inside a stratum. Proportional rather than
tail-inflating because D3 asks for *controlled representative* coverage: the point is to
make the realized composition deterministic, not to reshape it.

| construction | k | quantile edges | scarcest stratum | implied N ceiling | largest grid N | rationale |
|---|---|---|---|---|---|---|
| `k3_coarse` | 3 | 0/90/99/100 | #0 | 5,000 | 5,000 | Minimal structure: body / shoulder / top-1%. |
| `k4_tail_split` | 4 | 0/50/90/99/100 | #0 | 4,982 | 4,000 | Splits the body at the median so the bulk prompt cost is held fixed too, not only the tail. |
| `k6_readme_example` | 6 | 0/50/90/95/99/99.5/100 | #4 | 4,800 | 4,000 | The structure the README offers as an exploration starting point. |
| `k5_deep_tail` | 5 | 0/50/90/99/99.9/100 | #0 | 4,982 | 4,000 | Isolates the top 0.1% -- the region where the single extreme prompt that flipped the 2-RPS classification lives. |

*Implied ceiling* is where the scarcest stratum runs out under proportional allocation;
*largest grid N* is the biggest candidate `N` at or below it. They differ because the
grid is coarse — `k6` can serve 4,800 in principle but 5,000 is the next grid step up.

Tail support — canonical prompts above `L`, per candidate `N`:

| L | L chars | in corpus | N=250 | N=500 | N=750 | N=1,000 | N=1,250 | N=1,500 | N=2,000 | N=2,500 | N=3,000 | N=4,000 | N=5,000 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| q90 | 2,358 | 500 | 25 | 50 | 75 | 100 | 125 | 150 | 200 | 250 | 300 | 400 | 500 |
| q95 | 4,566 | 250 | 12 | 25 | 37 | 50 | 62 | 75 | 100 | 125 | 150 | 200 | 250 |
| q99 | 11,471 | 50 | 2 | 5 | 7 | 10 | 12 | 15 | 20 | 25 | 30 | 40 | 50 |
| q99.5 | 13,101 | 26 | 1 | 2 | 3 | 5 | 6 | 7 | 10 | 12 | 15 | 20 | 25 |

`!` = the construction would need more prompts above `L` than the corpus holds.

## 3. What makes a tail boundary meaningful (measured, not assumed)

A quantile edge is a fact about the corpus, not about latency. The unloaded floor
(concurrency 1, 248 prompts, 0 errors) measures the intrinsic relation directly:

```
TTFT_unloaded  =  76.8ms  +  25.70ms per 1000 chars
pearson r = 0.953     R^2 = 0.908     n = 248
```

Prompt length alone explains **91%** of unloaded TTFT variance.
Per candidate stratum:

| char range | n | TTFT p50 | TTFT max | over 500ms |
|---|---|---|---|---|
| 0 – 142 | 133 | 82ms | 86ms | 0% |
| 142 – 2,358 | 96 | 84ms | 147ms | 0% |
| 2,358 – 4,566 | 6 | 176ms | 224ms | 0% |
| 4,566 – 11,471 | 11 | 242ms | 402ms | 0% |
| 11,471 – 44,445 | 2 | 515ms | 523ms | 100% |

Projecting that fit across the whole corpus (an **extrapolation**, flagged as such in the
JSON) gives the headroom the headline experiment has to work with:

- projected unloaded p99 TTFT ≈ **372ms**
- headroom to the 500ms SLO ≈ **128ms** (26% of the SLO)
- a prompt reaches 500ms *unloaded* at ≈ **16,469 chars**, the 99.90th corpus percentile

So the curve is not being measured in open space: interference only has to add ~130ms at
the tail to cross the line. That argues for placing `L` where intrinsic cost starts to be
a material fraction of the SLO — q99 (11,471 chars, ~370ms unloaded) rather than q90
(2,358 chars, ~140ms), which is a length the SLO barely notices.

## 4. p99 stability vs `N` (R2) — the two sources, separately

Nonparametric bootstrap, 10,000 resamples per `N`, master seed 20260818, percentile method `linear`.

**These are shown separately and combined conservatively. They are never averaged** —
README R2, and see §6 for why that matters more than it looks.

### 4.1 — 2 RPS (near-boundary)

Source: `benchmarks/evidence/week2/first_session/stage_a/poisson_rps2.samples.jsonl` `sha256=46c59091df3f5cce…`  
n = 225 post-warmup samples, nominal λ = 2.0 RPS, materialized schedule = 248, censoring = 0.0%, warmup = time-based  
Matches the committed point record: **True** (record p99 524.6ms)  
Point estimate 524.6ms → **OVER**

| N | top-1% support | p99 median | 95% interval | width | rel width | flip rate | straddles 500ms |
|---|---|---|---|---|---|---|---|
| 250 | 2 | 495.0ms | [366.0, 656.8] | 290.8ms | 0.59 | 51.8% | **yes** |
| 500 | 5 | 552.9ms | [408.3, 656.8] | 248.5ms | 0.45 | 33.7% | **yes** |
| 750 | 8 | 552.9ms | [421.6, 574.8] | 153.2ms | 0.28 | 33.5% | **yes** |
| 1,000 | 10 | 552.9ms | [421.7, 574.8] | 153.1ms | 0.28 | 22.1% | **yes** |
| 1,250 | 12 | 552.9ms | [428.3, 574.8] | 146.5ms | 0.26 | 21.9% | **yes** |
| 1,500 | 15 | 552.9ms | [434.8, 574.8] | 140.0ms | 0.25 | 14.9% | **yes** |
| 2,000 | 20 | 552.9ms | [434.8, 574.8] | 140.0ms | 0.25 | 11.5% | **yes** |
| 2,500 | 25 | 552.9ms | [434.8, 574.8] | 140.0ms | 0.25 | 8.0% | **yes** |
| 3,000 | 30 | 552.9ms | [434.8, 574.8] | 140.0ms | 0.25 | 6.0% | **yes** |
| 4,000 | 40 | 552.9ms | [436.0, 574.8] | 138.8ms | 0.25 | 3.0% | **yes** |
| 5,000 | 50 | 552.9ms | [552.9, 574.8] | 21.9ms | 0.04 | 1.9% | no |
| 7,500 | 75 | 552.9ms | [552.9, 574.8] | 21.9ms | 0.04 | 0.6% | no |
| 10,000 | 100 | 552.9ms | [552.9, 574.8] | 21.9ms | 0.04 | 0.1% | no |

Smallest grid `N` per candidate criterion (none of these thresholds is locked):

| criterion | threshold | smallest N |
|---|---|---|
| flip rate ≤ | 0.10 | 2500 |
| flip rate ≤ | 0.05 | 4000 |
| flip rate ≤ | 0.01 | 7500 |
| 95% CI width ≤ | 200ms | 750 |
| 95% CI width ≤ | 150ms | 1250 |
| 95% CI width ≤ | 100ms | 5000 |
| 95% CI width ≤ | 50ms | 5000 |
| 95% CI relative width ≤ | 0.50 | 500 |
| 95% CI relative width ≤ | 0.30 | 750 |
| 95% CI relative width ≤ | 0.20 | 5000 |
| 95% CI relative width ≤ | 0.10 | 5000 |
| 95% CI entirely clear of 500ms | — | 5000 |

### 4.2 — 1.5 RPS (sparse low-load)

Source: `benchmarks/evidence/week2/first_session/stage_a/poisson_rps1.5.samples.jsonl` `sha256=e1f231f667af45a6…`  
n = 166 post-warmup samples, nominal λ = 1.5 RPS, materialized schedule = 182, censoring = 0.0%, warmup = time-based  
Matches the committed point record: **True** (record p99 113.6ms)  
Point estimate 113.6ms → **UNDER**

| N | top-1% support | p99 median | 95% interval | width | rel width | flip rate | straddles 500ms |
|---|---|---|---|---|---|---|---|
| 250 | 2 | 113.7ms | [111.7, 120.5] | 8.8ms | 0.08 | 0.0% | no |
| 500 | 5 | 114.0ms | [112.0, 120.5] | 8.5ms | 0.07 | 0.0% | no |
| 750 | 8 | 114.0ms | [112.0, 120.5] | 8.5ms | 0.07 | 0.0% | no |
| 1,000 | 10 | 114.0ms | [112.0, 120.5] | 8.5ms | 0.07 | 0.0% | no |
| 1,250 | 12 | 114.0ms | [113.4, 117.3] | 3.9ms | 0.03 | 0.0% | no |
| 1,500 | 15 | 114.0ms | [113.4, 114.1] | 0.7ms | 0.01 | 0.0% | no |
| 2,000 | 20 | 114.0ms | [113.4, 114.0] | 0.6ms | 0.01 | 0.0% | no |
| 2,500 | 25 | 114.0ms | [113.4, 114.0] | 0.6ms | 0.01 | 0.0% | no |
| 3,000 | 30 | 114.0ms | [113.4, 114.0] | 0.6ms | 0.01 | 0.0% | no |
| 4,000 | 40 | 114.0ms | [113.4, 114.0] | 0.6ms | 0.01 | 0.0% | no |
| 5,000 | 50 | 114.0ms | [113.4, 114.0] | 0.6ms | 0.01 | 0.0% | no |
| 7,500 | 75 | 114.0ms | [113.4, 114.0] | 0.6ms | 0.01 | 0.0% | no |
| 10,000 | 100 | 114.0ms | [113.4, 114.0] | 0.6ms | 0.01 | 0.0% | no |

Smallest grid `N` per candidate criterion (none of these thresholds is locked):

| criterion | threshold | smallest N |
|---|---|---|
| flip rate ≤ | 0.10 | 250 |
| flip rate ≤ | 0.05 | 250 |
| flip rate ≤ | 0.01 | 250 |
| 95% CI width ≤ | 200ms | 250 |
| 95% CI width ≤ | 150ms | 250 |
| 95% CI width ≤ | 100ms | 250 |
| 95% CI width ≤ | 50ms | 250 |
| 95% CI relative width ≤ | 0.50 | 250 |
| 95% CI relative width ≤ | 0.30 | 250 |
| 95% CI relative width ≤ | 0.20 | 250 |
| 95% CI relative width ≤ | 0.10 | 250 |
| 95% CI entirely clear of 500ms | — | 250 |

### 4.3 — the two disagree, and the reason is not sample size

The 1.5-RPS array is satisfied at the smallest `N` on the grid under every criterion; the
2-RPS array needs thousands. Read naively that says 1.5 RPS is an easy point. It is not
what the data says. The 1.5-RPS array is **prefix-cache contaminated** (§6): its TTFT
distribution is compressed, so its bootstrap interval is narrow for a reason that has
nothing to do with how many samples were taken.

This is exactly why README R2 forbids averaging. Conservative combination, per criterion:

| criterion | threshold | 1.5 RPS | 2 RPS | max() |
|---|---|---|---|---|
| flip rate ≤ | 0.10 | 250 | 2500 | **2500** |
| flip rate ≤ | 0.05 | 250 | 4000 | **4000** |
| flip rate ≤ | 0.01 | 250 | 7500 | **7500** |
| 95% CI width ≤ | 200ms | 250 | 750 | **750** |
| 95% CI width ≤ | 150ms | 250 | 1250 | **1250** |
| 95% CI width ≤ | 100ms | 250 | 5000 | **5000** |
| 95% CI width ≤ | 50ms | 250 | 5000 | **5000** |

**The single most decisive number in this package:** at `N = 250` — close to the n = 225 the first session actually had — the 2-RPS
point flips its own classification in **52%**
of resamples. The first session's breach read was a coin toss, and `n ≥ 100` cannot
distinguish that from a measurement.

## 5. Joint `k` / `L` / `N` candidates with runtime (R3)

`N_candidate = max(N_prompt_tail_requirement, N_p99_stability_requirement)`

**Structural ceiling:** the pinned corpus holds 5,000 prompts, so the
largest canonical multiset selectable without repeating a prompt is **5,000**.

Held at `L = q99` (11,471 chars) on the measured grounds in §3. The four candidate
constructions do not change `N` for a given `L` — they differ only in the ceiling they
impose, the tightest being **4,000** (`k6_readme_example`). Every
`(k, L, N)` combination is in `kln_candidates.json`.

| prompts > L target | flip ≤ | N from tail | N from p99 | **N candidate** | prompts > L | top-1% support | 1 point @1.5 RPS | headline total | fits 4,000 ceiling |
|---|---|---|---|---|---|---|---|---|---|
| 10 | 10% | 1,000 | 2,500 | **2,500** | 25 | 25 | 28 min | 4.9 h | yes |
| 10 | 5% | 1,000 | 4,000 | **4,000** | 40 | 40 | 45 min | 7.5 h | yes |
| 10 | 1% | 1,000 | 7,500 | **7,500** | 75 | 75 | 84 min | 13.8 h | **NO** |
| 20 | 10% | 2,000 | 2,500 | **2,500** | 25 | 25 | 28 min | 4.9 h | yes |
| 20 | 5% | 2,000 | 4,000 | **4,000** | 40 | 40 | 45 min | 7.5 h | yes |
| 20 | 1% | 2,000 | 7,500 | **7,500** | 75 | 75 | 84 min | 13.8 h | **NO** |
| 30 | 10% | 3,000 | 2,500 | **3,000** | 30 | 30 | 34 min | 5.8 h | yes |
| 30 | 5% | 3,000 | 4,000 | **4,000** | 40 | 40 | 45 min | 7.5 h | yes |
| 30 | 1% | 3,000 | 7,500 | **7,500** | 75 | 75 | 84 min | 13.8 h | **NO** |
| 50 | 10% | 5,000 | 2,500 | **5,000** | 50 | 50 | 56 min | 9.3 h | **NO** |
| 50 | 5% | 5,000 | 4,000 | **5,000** | 50 | 50 | 56 min | 9.3 h | **NO** |
| 50 | 1% | 5,000 | 7,500 | **7,500** | 75 | 75 | 84 min | 13.8 h | **NO** |

Runtime model: fine sweep at λ ∈ [1.5, 2.0, 2.5, 3.0, 4.0], 3 repeats,
30s warmup per point, 15 min standup. headline matched workload only -- excludes the unloaded floor, the natural-random secondary curve (R11), steady reference and adversarial. Duration per point is the EXPECTED N/lambda; the materialized Poisson realization decides the actual value (R6).

## 6. Two findings that were not on the R0–R3 worklist

### 6.1 — Prefix caching makes run order an experimental variable

The server ran with `enable_prefix_caching=True` and `enable_chunked_prefill=True` (vLLM defaults;
neither was set by the runbook). Every Stage A schedule was built from the same master
seed, so the shorter schedules are strict **prefixes** of the longer ones — every point
replays the prompts of every shorter point.

Joining each loaded point against the unloaded floor on `prompt_id`:

| point | prompts ≥ q95 in common | median loaded/unloaded TTFT | verdict |
|---|---|---|---|
| `poisson_rps1.5` | 7 | 0.46× | CONTAMINATED |
| `poisson_rps2` | 12 | 1.18× | CONSISTENT |

Worked example — the same prompt, same model, same server:

```
prompt 458 (14,960 chars)
  concurrency 1, no load        523.3ms
  under 1.5 RPS of load         103.9ms   (0.20x)
```

Load cannot make prefill five times faster. The 1.5-RPS point was driven **last**, after
the sweep and after the unloaded floor had just re-loaded those exact prompts. vLLM's
reported hit rate ends the session at 27.4%, and the final low-load block
(20:04:09–20:06:19, peak concurrency 24) accounts for
17.4% → 27.4% of that on its own — the contamination
happening in real time, not a session-wide average.

**Why this outlives the old data.** D2 fixes one canonical prompt multiset across every
RPS point *and* every repeat; D4 forbids restarting vLLM between repeats. Together they
guarantee that every point after the first replays prompts the server has already cached
— a drift aligned with run order, which is the same class of confound as the prompt tail
the redesign exists to remove, but systematic rather than random.

Options, for the human (full trade-offs in `run_order_effects.json`):

- **A -- disable prefix caching for headline runs** — Removes the confound at the source; every request pays full prefill. *Cost:* Changes the served configuration from the first session's, and moves the measured baseline away from how vLLM is normally deployed. The 500ms SLO and the breach location would both shift.
- **B -- keep prefix caching, randomize point order across repeats** — Cache advantage no longer aligns with lambda, so it becomes noise across repeats instead of a monotone trend along the x-axis. *Cost:* Needs more repeats to average out, and does not remove the advantage within a repeat.
- **C -- keep prefix caching, record hit rate per point and gate on it** — Contamination becomes measurable and a point whose hit rate differs materially from its neighbours can be flagged or re-driven. *Cost:* Needs a hit-rate scrape from /metrics per point, and a threshold that is itself a calibration.
- **D -- drain-and-flush between points/repeats** — Restores a comparable cache state per point without restarting vLLM. *Cost:* Requires a supported cache-reset path; D4's 'no restart' rule exists to avoid re-paying CUDA-graph/init variance, and a flush must not reintroduce it.

Whatever is chosen, prefix cache hit rate is currently **not** recorded per point. It
should become a per-point covariate so a contaminated point is visible in its own
artifact instead of reconstructed from a server log.

### 6.2 — Two percentile conventions already coexist in the evidence

The promoted `unloaded_floor.metrics.json` reports p99 = 402.269ms. On the same 248 samples,
`metrics.compute.percentile` (linear interpolation — the method every Stage A point
record uses) gives 388.553ms. The floor was produced by a
one-off on-instance script that is not in the repo.

At the boundary this is not cosmetic. The 2-RPS point's p99, same samples:

| method | p99 | classification |
|---|---|---|
| linear | 524.6ms | OVER |
| lower | 434.8ms | UNDER |
| higher | 552.9ms | OVER |
| nearest | 552.9ms | OVER |
| midpoint | 493.9ms | UNDER |

**The percentile method alone flips the verdict.** The bootstrap shows the disagreement
is a small-sample effect — by `N ≥ 1000` every method agrees — which is one more
independent argument for a large `N`, and an argument for locking the method explicitly
as part of the classification rule rather than inheriting it from whichever script ran.

## 7. Recommendations — for the human to lock, reject or replace

**None of the following is a decision.** They are the reads this evidence supports, with
the reasoning attached so a different call can be made against the same data.

### `k` — recommend `k6_readme_example` (6 strata: 0/50/90/95/99/99.5/100)

Because the fixed multiset is reused everywhere, tail *composition* is held constant at
any `k`. What `k` actually buys is fidelity of the fixed multiset to the corpus's natural
shape, and control over *which* prompts fill the top stratum. Inside a single 99–100
stratum the char range runs 11,471 → 44,445 — a 4× spread whose projected unloaded TTFT
runs ~370ms → ~1,200ms. Splitting it at q99.5 stops the selection from filling the top
1% from its cheaper half. Cost: the tightest implied `N` ceiling of the four candidates
(4,800; 4,000 once rounded to this grid — though `k4_tail_split` and
`k5_deep_tail` round to the same place, so on this grid the cost is only against
`k3_coarse`). If `N > 4,000` is wanted, only `k3_coarse` reaches 5,000, and it buys that
by giving up all intra-tail control.

### `L` — recommend `q99` = 11,471 chars

On measured grounds, not roundness (§3): a q99-length prompt costs ~370ms of TTFT with
**no load at all**, i.e. ~74% of the SLO, so it is where prompt length starts deciding
the verdict. q90 (2,358 chars, ~140ms) is a length the SLO barely notices, and gating on
it would call 500 prompts "tail" while controlling nothing that moves a p99. `L = q99`
also makes tail support and top-1% support the same quantity, which keeps the two halves
of the `N` requirement on one axis.

### `N` — recommend 4,000, with 2,500 as the budget alternative

| | N = 2,500 | N = 4,000 |
|---|---|---|
| per-run flip rate (2 RPS source) | ~8% | ~3% |
| prompts above `L` | 25 of 50 available | 40 of 50 available |
| one point at λ=1.5 | ~28 min | ~45 min |
| headline total (3 repeats × 5 λ) | ~4.9 h | ~7.5 h |
| fits the `k6` ceiling (4,000) | yes | exactly |

4,000 is the smallest grid `N` reaching a ≤5% per-run flip rate, and it lands exactly on
the `k6` ceiling — so it is simultaneously the most evidence this construction can carry
and the least that meets the criterion. That coincidence is worth noticing rather than
relying on.

**The argument for 2,500 instead is the repeat structure.** D5 gives the verdict to
independent repeats, not to one run. A 10% per-run flip rate does not mean a 10% chance
of a wrong verdict when three independent repeats must agree — so per-run stability may
be worth less than the extra 2.6 hours of session length, and session length is where
spot preemption risk lives. That trade is the human's; both rows are supported.

### `N_max` / evidence ceiling — recommend 5,000, plus a repeat and wall-clock bound

- **`N_max` = 5,000 — structural, not chosen.** It is the pinned corpus size, hence the
  largest canonical multiset selectable without repeating a prompt. Going past it means
  either changing the pinned corpus (locked) or repeating prompts inside a run, which
  §6.1 shows is not a neutral act on a prefix-caching server.
- **`repeats_max` = 3 at the locked `N`**, then stop escalating.
- **headline wall-clock budget ≈ 8 h**, which `N = 4,000` consumes almost entirely.

**The escape hatch is not hypothetical.** A ≤1% per-run flip rate needs `N ≈ 7,500` —
**above `N_max`, and therefore unreachable with this corpus.** If the crossing is still
`UNCERTAIN` at the ceiling, R10's interval-valued breach is the outcome the evidence
actually supports, not a fallback to apologise for.

### Two locks this evidence says are missing

1. **Percentile method** must be locked explicitly as part of the classification rule
   (§6.2). It is currently inherited from whichever script runs, and at small `n` it
   flips the verdict on its own.
2. **Prefix-cache policy** must be decided before the canonical workload is frozen
   (§6.1), because D2's fixed multiset is what makes the effect systematic.

## 8. Tensions found with the authoritative documents

Surfaced, not reconciled (`WEEK2_EXECUTION.md` precedence rule).

### 8.1 — `WEEK2_PLAN.md` §3.4 forbids exactly what D3 requires

§3.4 is LOCKED as *"Random sample, **no length stratification** — preserves the natural
length distribution locked in §2.2. Stratifying would shape the distribution toward a
preferred shape rather than measuring the corpus's natural mix."* D3 requires deriving
prompt-length strata and freezing a fixed membership from them, and §3.4's
with-replacement i.i.d. draw is replaced by without-replacement selection.

**Assessment:** in scope for supersession — the first session falsified §2.2's premise
that a fixed seeded distribution holds the prompt contribution constant, and §3.4's rule
is not in the README §3 keep-locked list. Worth noting that *proportional* allocation
honours §3.4's stated intent better than the random draw did: it reproduces the natural
shape exactly instead of approximately, which is what "measuring the corpus's natural
mix" was asking for. **But the amendment README §7 requires has not been written**, and
it is gated behind this hard stop. Flagged so the lock is not left contradicted in the
authoritative doc while code implements the opposite.

### 8.2 — the README's own description of the 1.5-RPS source array is falsified

R2 calls it "the sparser clean low-load diagnostic". It is not clean (§6.1). Both arrays
were still used as instructed, and the conservative `max()` rule contains the damage —
but the array cannot be cited as evidence that 1.5 RPS sits comfortably under the SLO,
and handoff §19's "1.5 RPS ... was clearly below" does not survive either.

### 8.3 — D2 and D4 jointly guarantee the contamination in §6.1

Both are LOCKED redesign decisions, and neither is wrong on its own. Together, on a
server with prefix caching on, they make cache advantage a monotone function of run
order. This needs a decision before R4 freezes the canonical workload.

### 8.4 — both R2 source points are `flagged` for a reason D7 declassifies

The promoted point records carry `flagged: true` at −6.25% (2 RPS) and −7.8% (1.5 RPS)
divergence, and are plotted at *achieved* RPS under Option Y. D7 says finite-Poisson
realization variance is descriptive metadata and must not fail the driver. So the legacy
records label as driver divergence precisely what the redesign reclassifies as noise.
The legacy interpretation is pinned and must not be rewritten (R0.4) — but anyone reading
those records needs to know the flag is measuring the old semantics.

### 8.5 — `--max-model-len` sizing changes from probabilistic to guaranteed

`WEEK2_PLAN.md` §6.1 requires `--max-model-len` sized to the longest corpus prompt plus
max output. The first session ran `max_model_len=20000`, and the corpus's longest prompt
(44,445 chars, `prompt_id` 790) was **never drawn** — the 2-RPS schedule topped out at
16,781 chars. A canonical multiset with a fixed top stratum will include the extremes
**at every point of every repeat, by construction**. The sizing must therefore be
re-verified against the actual tokenizer before R4, not inherited.

### 8.6 — reopened by provenance, noted for completeness

`Y = 120s` (§2.4) and `n ≥ 100` (§2.4/§8) are explicitly reopened by the README, so they
are not conflicts. Recorded here only because both still read as RESOLVED/LOCKED in
`WEEK2_PLAN.md` and `STATUS.md`, which is a stale-lock hazard for the next reader.


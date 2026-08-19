# benchmarks

Benchmark inputs, calibration evidence, and results.

## What is committed and what is not

The split is deliberate. A published claim has to be reproducible from tracked
files, but a benchmark directory also fills up with exploratory sweeps, retries
and debug output — and committing all of it makes the repo noisy while
committing none of it makes `BASELINE.md` unverifiable. So:

| Path | Tracked? | What lives here |
|---|---|---|
| `schedules/` | **yes** | Frozen materialized workload **inputs** — replay's source of truth (`WEEK2_PLAN.md` §5). `stage_a/` is committed; `stage_b/` is generated mid-session from the observed bracket. |
| `calibration/` | **yes** | The evidence behind every resolved `[CALIBRATE]` value. `noise_floor/` (mock timing, Block 0), `scheduler_spin/` (loadgen spin A/B, Block C), `block_c/` (cap / band reads). |
| `evidence/week2/` | **yes** | Results **promoted** out of a session run, including their raw logs and sidecars — either because they support a published claim, or because they are the durable record of an experiment that failed and must not be lost. `first_session/` is the second kind and says so in its own README. |
| `workloads/` | **yes** | Frozen canonical prompt multisets and their provenance — the controlled headline workload's membership, its tokenizer capacity proof, and the repeat/evidence policy. Inputs, like `schedules/`. |
| `runs/` | no | Raw session output as produced, before anything is promoted. |
| `scratch/` | no | Exploratory, debug and retry output. Safe to delete at any time. |

**The promotion rule:**

> Only accepted artifacts that support `BASELINE.md` or calibration provenance
> are committed; exploratory, debug and retry artifacts remain scratch.

Promotion is a deliberate act — copy a point from `runs/` into
`evidence/week2/` — not a side effect of running something. `.gitignore` is set
up so that promoted artifacts are then **naturally trackable with a plain
`git add`**: no `git add -f`, which would otherwise be the only signal that
something was promoted and would leave no trace of the decision.

Per-request `*.raw_log.jsonl` / `*.samples.jsonl` are ignored **everywhere
except** `evidence/`, precisely so that promoting a point is what makes its raw
data tracked.

## Contents

- **`schedules/stage_a/`** — the ten committed Stage A coarse-sweep Poisson
  schedules (1/1.5/2/5/10/20/30/40/60/80 RPS; the two sub-2 anchors were added
  when the sweep turned out to have no clearly-under-SLO point), all at the
  locked `BASELINE_SEED` so the prompt-length contribution is held constant
  across the sweep (`WEEK2_PLAN.md` §2.2). Regenerate with
  `scripts/generate_stage_a_schedules.py`; generate Stage B's fine bracket with
  `scripts/generate_schedules.py`.
  - *One seed for every point also means one `corpus_rng` draw sequence, so a
    shorter schedule is a strict prefix of a longer one. That is what makes the
    points matched — and, on a prefix-caching server, what makes run order an
    experimental variable. See `calibration/week2_redesign/run_order_effects.json`.*
- **`evidence/week2/first_session/`** — the 2026-08-18 GPU session's artifacts,
  promoted as **diagnostic / failed-experiment evidence** with a hash manifest
  and an interpretation pin. No breach RPS came out of that session; the
  directory's own README says what is and is not trustworthy in it.
- **`calibration/week2_redesign/`** — the offline redesign calibration (Redesign
  README R1–R3): corpus tail structure, measured prompt cost vs TTFT, the
  prefix-cache run-order finding, the p99-vs-`N` bootstrap, and the unloaded
  floor's cache-state audit. The read-up for the human is
  `R3_EVIDENCE_PACKAGE.md`; every number in it regenerates from the JSON files
  beside it.
- **`workloads/week2_headline/`** — the frozen canonical multiset locked at Hard
  Stop R3: `k`=6 strata, `L`=q99=11,471 chars, `N`=4,000 unique prompt IDs,
  `N_max`=5,000. `canonical_v1.json` carries the membership, the per-stratum
  accounting and the capacity proof it was frozen behind;
  `tokenizer_capacity_report.json` is that proof (10,482 max input tokens,
  measured with the pinned model's own tokenizer and chat template);
  `repeat_policy.json` is the evidence policy, still `PROPOSED`.
- **`workloads/week2_scout/`** — the smaller Tier A scouting workload
  (`N`=500), built through the same pipeline and the same capacity gate, in its
  own namespace so a diagnostic membership can never be mistaken for the
  headline one.
- **`schedules/week2_redesign/`** — the redesigned schedule families, format
  `headline-schedule-v2`. `headline/` is 3 repeats × 5 λ, each holding **exactly
  4,000 post-warmup scheduled arrivals** with duration as an outcome of the
  Poisson realization; `scout/` is the Tier A diagnostic family; and
  `secondary_natural/` is the natural-random realism curve, which never
  contributes a point to the headline classification.
- **`calibration/noise_floor/`** — Block 0's mock-timing spin A/B on a
  dedicated Linux `e2` VM, 200 runs per arm. Read-up in
  `MOCK_TRUST_BOUNDARY.md`.
- **`calibration/scheduler_spin/`** — the loadgen scheduler's spin-margin A/B
  (0ms vs 5ms) on a dedicated Linux `e2` VM. Produced by
  `scripts/calibrate_scheduler_spin.py`; read-up in `BENCHMARKS.md`.
- **`calibration/block_c/`** — Block C's shed-onset, natural-concurrency and
  low-load-tracking sweeps, the source for the concurrency cap and the
  offered-vs-achieved band. The distilled `calibration_reads.json` is tracked;
  the ~44 raw sweep logs behind it are scratch.

Timing methodology and results narrative live in `BENCHMARKS.md`.

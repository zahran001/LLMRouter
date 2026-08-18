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
| `evidence/week2/` | **yes** | Accepted results supporting a published claim. Points **promoted** out of a session run, including their raw logs and sidecars. |
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

- **`schedules/stage_a/`** — the eight committed Stage A coarse-sweep Poisson
  schedules (2/5/10/20/30/40/60/80 RPS), all at the locked `BASELINE_SEED` so
  the prompt-length contribution is held constant across the sweep
  (`WEEK2_PLAN.md` §2.2). Regenerate with
  `scripts/generate_stage_a_schedules.py`; generate Stage B's fine bracket with
  `scripts/generate_schedules.py`.
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

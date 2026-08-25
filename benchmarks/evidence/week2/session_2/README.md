# GPU session #2, attempt 2 — headline evidence (2026-08-23)

> **STATUS: EVIDENCE — DOES NOT GOVERN EXECUTION**
>
> Role: the promoted GPU session #2 attempt-2 artifacts and what each may be
> cited for.
>
> This document records *why* something is believed. It does not govern
> execution, and any command text below is a record of what was run at the
> time, not an instruction to run it now.
> Full narrative: `WEEK2_GPU_SESSION_2_ATTEMPT_2_REPORT.md`.
> Current execution instructions: `WEEK2_GPU_SESSION_2_PLAN.md`.

**This is the headline-defining evidence for Week 2, but the interval is not
closed.** λ=0.75 classifies **OVER** (unanimous, 3/3 repeats). λ=0.5
classifies **UNCERTAIN** (2 OVER, 1 UNDER — a genuine boundary split).
Offline resolution is `NO_UNDER_ANCHOR`: no swept λ came back a confirmed
UNDER, so the crossing sits at or below λ=0.5. No escalation is authorized on
this data (`repeat_policy.json`: `escalation.authorized: false`) — a
confirmed UNDER anchor requires a new session with schedules generated below
λ=0.5.

## Why it is here at all

These artifacts were pulled off the L4 instance before teardown into
`benchmarks/runs/`, which is gitignored — so they existed on exactly one
laptop, for an instance that no longer exists. Promotion into
`benchmarks/evidence/` (the tracked subtree, per `benchmarks/README.md`) is
what makes them survive.

Promoted by `scripts/promote_session_2_evidence.py`, which copies bytes
verbatim, **refuses** to overwrite a promoted artifact whose bytes differ, and
records a SHA-256 per file in `MANIFEST.json`. Re-check any time with
`--verify`.

## What is trustworthy here, and what is not

**Trusted** (see the attempt-2 report for the full record):

- `headline/` — 9 points: 3 independent repeats × {λ=0.5, λ=0.75} from this
  session (all `exact_n_honoured`/`schedule_delivery_ok` true, 0 shed), plus 3
  legacy λ∈{1.5, 2, 2.5} repeat-1 points carried over from attempt 1
  (`CENSORED` at every point, 27–37%). This is the family that actually
  defines the breach — `may_define_headline_breach: true` on every record.
- `sustained_scout/` — 4 Tier A points at λ∈{0.5, 0.75, 1.0, 1.25}.
  **Diagnostic only** — `workload_class: sustained_scout_controlled` keeps it
  out of classification (`scenario_contract.py`). Used to bracket where Tier B
  should look (Hard Stop GPU-1), not to classify a breach itself.
- `floor/` — the unloaded floor for this session's instance: 4000/4000,
  p99=397.6ms, 102ms of headroom under the 500ms SLO.
- `secondary/` — natural-random realism check at λ=0.75: UNDER, p99=371.6ms,
  n=471. Achieved rate 0.80rps vs offered 0.75rps (+6.4%, outside the ±5%
  band) — flagged in the record, plotted at *achieved* rate per policy.
  Diagnostic only; never contributes a point to headline classification.
- `steady/` — steady-arrival reference at λ=0.75: UNDER, p99=434.8ms,
  N=500, issued 544/544, 0% censoring. Diagnostic only.
- `adversarial/` — λ=2, long-context, saturation probe, run last by design:
  p99≈60,005ms (client timeout ceiling). 577/1212 sent, 635 errored
  (timeouts), 0 shed — real saturation, not a concurrency-cap artifact.
  Diagnostic only; confirms the driver behaves correctly under deliberate
  overload, not a latency measurement.
- `preflight/prefix_cache_verdict.json` — this session's gate verdict,
  `PREFIX_CACHING_DISABLED` (min ratio 0.95).
- `vllm.log` — the second instance's full launch log (single process epoch,
  no preemption).

**Known caveats, not defects:**

- Population counts vary naturally across the three λ=0.5/0.75 headline
  repeats (2000 exactly at λ=0.5 on all three; 2069/2078/2065 at λ=0.75) —
  each repeat is an independently-seeded threshold-freeze draw
  (`min(45min, 2000 post-warmup)`), not a driver bug. This is what
  `metrics/classification.py`'s `headline_threshold` floor check (D-ATTEMPT2-2)
  exists to accept correctly.
- `secondary/`'s achieved-vs-offered rate deviation (+6.4%) is outside the
  ±5% band and is flagged for exactly that reason; it does not affect
  headline classification since `secondary/` never enters it.

## Contents

| Path | What |
|---|---|
| `floor/` | Unloaded floor, second instance: 4000/4000, p99=397.6ms. |
| `sustained_scout/` | 4 Tier A diagnostic points, λ∈{0.5, 0.75, 1.0, 1.25}. |
| `headline/` | 9 points: 3 repeats × {0.5, 0.75} (this session) + 3 legacy repeat-1 points (attempt 1) + `family_report.json`. |
| `secondary/` | Natural-random realism check, λ=0.75. |
| `steady/` | Steady-arrival reference, λ=0.75. |
| `adversarial/` | λ=2 long-context saturation probe. |
| `preflight/` | Prefix-cache gate verdict for this session's instance. |
| `vllm.log` | Second instance's full launch log. |
| `MANIFEST.json` | SHA-256 per promoted file; `--verify` re-checks it. |

The frozen schedules these points were driven from are **not** copied here;
they are tracked separately under `benchmarks/schedules/week2_redesign/` as
workload *inputs*. Workload and record are never conflated
(`WEEK2_GPU_SESSION_2_PLAN.md` §5).

## What this does not settle

`BASELINE.md` cannot yet state a closed breach interval from this directory
alone — only an open one: UNDER at nothing confirmed, OVER at 0.75. Closing
it to `(A, 0.75]` (or narrower) needs a confirmed UNDER anchor below λ=0.5,
which requires a new session with schedules generated and frozen offline
first (see `WEEK2_CLOSEOUT_PLAN.md` for the planned approach).

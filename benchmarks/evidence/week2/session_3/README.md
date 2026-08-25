# GPU session #3 — the closing evidence (2026-08-25)

> **STATUS: EVIDENCE — DOES NOT GOVERN EXECUTION**
>
> Role: the promoted GPU session #3 artifacts and what each may be cited
> for.
>
> This document records *why* something is believed. It does not govern
> execution, and any command text below is a record of what was run at the
> time, not an instruction to run it now.
> Full narrative: `WEEK2_GPU_SESSION_3_REPORT.md`.
> Session-3 runbook: `WEEK2_CLOSEOUT_PLAN.md` (session mechanics unchanged
> from `WEEK2_GPU_SESSION_2_PLAN.md`).

**This is the evidence that closes Week 2's breach interval.** λ=0.4
classifies **UNDER** (3/3 unanimous). λ=0.6 classifies **OVER** (3/3
unanimous). Offline resolution is **`RESOLVED`**: the crossing is
bracketed at both endpoints with no split at either — the sustained 500ms
p99 TTFT breach interval is **`(0.4, 0.6]` RPS**.

## Why it is here at all

These artifacts were pulled off the L4 instance before teardown into
`benchmarks/runs/`, which is gitignored — so they existed on exactly one
laptop, for an instance (across 3 launches — see the report §6) that no
longer exists. Promotion into `benchmarks/evidence/` (the tracked subtree,
per `benchmarks/README.md`) is what makes them survive.

Promoted by `scripts/promote_session_3_evidence.py`, which copies bytes
verbatim, **refuses** to overwrite a promoted artifact whose bytes differ,
and records a SHA-256 per file in `MANIFEST.json`. Re-check any time with
`--verify`.

**Unlike session #2's promotion script**, this one promotes an explicit
filename allowlist rather than whole subdirectories: session #3 reused
session #2's local `sustained_scout/` and `headline/` artifact directories
(`benchmarks/runs/`), so those directories hold both sessions' points side
by side on disk. Only session #3's new points (λ∈{0.4, 0.6}) are promoted
here; session #2's points remain solely under
`benchmarks/evidence/week2/session_2/`, not duplicated.

## What is trustworthy here, and what is not

**Trusted** (see `WEEK2_GPU_SESSION_3_REPORT.md` for the full record):

- `headline/` — 6 points: 3 independent repeats × {λ=0.4, λ=0.6}, all
  `exact_n_honoured`/`schedule_delivery_ok` true, 0 shed, 0% censoring.
  This is the family that closes the breach classification —
  `may_define_headline_breach: true` on every record. `family_report.json`
  reflects only the **last** invocation (repeat 3, both λ) — it is not a
  cross-repeat aggregate; read the per-point `*.metrics.json` files for
  repeats 1 and 2.
- `sustained_scout/` — 2 Tier A points at λ∈{0.4, 0.6}. **Diagnostic
  only** — `workload_class: sustained_scout_controlled` keeps it out of
  classification (`scenario_contract.py`). Read λ=0.4 UNDER / λ=0.6 OVER
  before Tier B confirmed the same bracket unanimously.
- `floor/` — the unloaded floor for this session's (first) instance:
  4000/4000, p99=410.3ms, 90ms of headroom under the 500ms SLO.
- `preflight/prefix_cache_verdict.json` — the gate verdict from this
  session's final relaunch. Re-verified fresh after each of the 2
  preemption-recovery relaunches (report §6); every check passed
  (`PREFIX_CACHING_DISABLED`, ratios 0.93–0.97).

**Known caveats, not defects:**

- This session had 2 spot preemptions (report §6). Neither reached a
  written `metrics.json` for the point in flight at the time, so nothing
  promoted here is from an interrupted drive — every point was completed
  from a clean, uninterrupted redrive.
- Population counts vary naturally across repeats at both λ (independently
  seeded threshold-freeze draws, same as session #2's D-ATTEMPT2-2
  finding) — accepted correctly by `metrics/classification.py`'s
  `headline_threshold` floor check, which session #3 extended to cover
  λ∈{0.4, 0.6} (`repeat_policy.json` `policy_version` 5).

## Contents

| Path | What |
|---|---|
| `floor/` | Unloaded floor, this session's instance: p99=410.3ms. |
| `sustained_scout/` | 2 Tier A diagnostic points, λ∈{0.4, 0.6}. |
| `headline/` | 6 points: 3 repeats × {0.4, 0.6}, plus the last-invocation `family_report.json`. |
| `preflight/` | Prefix-cache gate verdict for this session's final instance launch. |
| `MANIFEST.json` | SHA-256 per promoted file; `--verify` re-checks it. |

The frozen schedules these points were driven from are **not** copied here;
they are tracked separately under `benchmarks/schedules/week2_redesign/` as
workload *inputs*, extended for session #3 by
`scripts/generate_sustained_scout_schedules.py` and
`scripts/generate_headline_schedules.py` (existing λ=0.4/0.6 schedules
appended, not regenerated — verified byte-identical for every
pre-existing point).

## What this closes

Combined with session #2's evidence (`benchmarks/evidence/week2/session_2/`
— λ=0.75 OVER unanimous, λ=0.5 UNCERTAIN split, left as recorded boundary
evidence and not re-driven), the full picture across both sessions:

| λ | Classification | Source |
|---|---|---|
| 0.4 | UNDER (3/3 unanimous) | session #3 |
| 0.5 | UNCERTAIN (2 OVER, 1 UNDER) | session #2 |
| 0.6 | OVER (3/3 unanimous) | session #3 |
| 0.75 | OVER (3/3 unanimous) | session #2 |

The defining, closed breach interval is **`(0.4, 0.6]`** — the tightest
confirmed bracket, and the one `BASELINE.md` states.

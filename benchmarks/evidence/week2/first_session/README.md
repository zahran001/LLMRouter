# First Week 2 GPU session — diagnostic evidence (2026-08-18)

> **STATUS: EVIDENCE — DOES NOT GOVERN EXECUTION**
>
> Role: the promoted GPU session #1 artifacts and what each may be cited for.
>
> This document records *why* something is believed. It does not govern
> execution, and any command text below is a record of what was run at the
> time, not an instruction to run it now.
> Current execution instructions: `WEEK2_GPU_SESSION_2_PLAN.md`.
> Index: `WEEK2_DOC_INDEX.md`.

**This is not baseline evidence.** The session produced **no defensible breach
RPS**, and nothing in this directory may be cited as one. It is the durable
record of an experiment whose *statistical design* was falsified while it ran,
kept because the falsification is itself the finding
(the redesign handoff §13 — removed 2026-08-20; in git history at 39ed3f1; the note inside `MANIFEST.json` still
cites it by name, and is left byte-identical because it is hashed).

## Why it is here at all

These artifacts were pulled off the L4 instance before teardown into
`benchmarks/runs/`, which is gitignored — so they existed on exactly one laptop,
for an instance that no longer exists. Promotion into `benchmarks/evidence/`
(the tracked subtree, per `benchmarks/README.md`) is what makes them survive.

Promoted by `scripts/promote_first_session_evidence.py`, which copies bytes
verbatim, **refuses** to overwrite a promoted artifact whose bytes differ, and
records a SHA-256 per file in `MANIFEST.json`. Re-check any time with
`--verify`.

## What is trustworthy here, and what is not

**Trusted** (handoff §13):

- the corpus-drift guard fired correctly and the corrected corpus/schedules
  preserve the actual prompt entries;
- vLLM ran as intended; open-loop low-load driving produced 0 shed, 0 errors;
- the unloaded floor — **p99 TTFT 402.3ms over the 248-prompt 2-RPS set at
  concurrency 1** — which is the finding that keeps the project thesis alive:
  500ms is achievable for this corpus/model without contention.

**Not valid as ordinary latency measurements:**

- `poisson_rps2` — its 500ms classification is dominated by the realized
  long-prompt tail. Excluding essentially one extreme prompt moved p99 from
  ~552.9ms to ~434.8ms, which flips the verdict (handoff §7);
- `poisson_rps10/20/30/40` — 33%/70%/81% of requests hit the 60s client
  timeout. The surviving-request p99 clusters near 60s and is a
  **survivorship artifact**, not a latency plateau (handoff §9). These points
  remain valid evidence of *severe saturation*, and nothing else.

## Contents

| Path | What |
|---|---|
| `stage_a/` | 7 Stage A points: raw 6-field log, TTFT/TPOT sidecar, session-time metrics record. `poisson_rps40` has no `metrics.json` — the point was driven, its record never written. |
| `unloaded_floor/` | The concurrency-1 no-contention floor: 248 requests, 248 TTFT samples, 0 errors. |
| `session_logs/` | vLLM server log and the unloaded-floor driver stdout. |
| `MANIFEST.json` | SHA-256 per promoted file; `--verify` re-checks it. |
| `LEGACY_FIXTURES.json` | The immutable fixture pin — bytes **and** interpretation (README R0.6). |

The frozen schedules these points were driven from are **not** copied here;
they were already tracked in `benchmarks/schedules/stage_a/` as workload
*inputs*. Workload and record are never conflated (`WEEK2_PLAN.md` §5).

## The interpretation pin

`MANIFEST.json` proves the bytes did not change. That is not enough: the
redesign rewrites the warmup basis, the validity gate and the point-record
schema, and every one of those changes what a sidecar *says* without touching
a byte of it. `LEGACY_FIXTURES.json` therefore also pins what today's readers
**derive** from these bytes for the two R2 source points (1.5 and 2 RPS), and
`tests/redesign/test_legacy_compatibility.py` fails if any reader change moves
those numbers.

If that test goes red, the correct response is a **new format version**, never
an edit to the pinned values or to the artifacts.

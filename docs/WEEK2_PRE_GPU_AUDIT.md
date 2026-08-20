# Week 2 Pre-GPU Audit — Remediation Record

> **STATUS: EVIDENCE — DOES NOT GOVERN EXECUTION**
>
> Role: the 2026-08-17 pre-GPU audit trail and how each finding was closed.
>
> This document records *why* something is believed. It does not govern
> execution, and any command text below is a record of what was run at the
> time, not an instruction to run it now.
> Current execution instructions: `WEEK2_GPU_SESSION_2_PLAN.md`.
> Index: `WEEK2_DOC_INDEX.md`.

**Audit performed 2026-08-17** against `week2/loadgen-baseline` @ `3ac82aa`.
**Remediation completed 2026-08-18.** All blockers closed; the audit's findings
are preserved below as the record of what was wrong and how it was fixed.

Session #1's Hard Stop 4 *evidence checklist* (removed 2026-08-20; in git history at 39ed3f1) was the companion; this is
the *audit trail* behind it.

---

## Verdict

| Gate | At audit (08-17) | Now (08-18) |
|---|---|---|
| Hard Stop 1 — open-loop architecture | PASS | **PASS** |
| Hard Stop 2 — five negative controls bite | PASS | **PASS** (V2 tightened, §R4) |
| Hard Stop 3 — calibrations | PARTIAL | **PASS** — all resolved but warmup N, which is post-GPU by design |
| Hard Stop 4 — pre-GPU readiness | **FAIL** | **PASS** |

---

## 🔴 Blockers — both CLOSED

### ✅ B1. `teardown.sh` default targeted the wrong instance

**Was:** `scripts/teardown.sh:10` defaulted to Week 1's `llmrouter-vllm-l4`
while Week 2 creates `llmrouter-vllm-l4-week2`. Two runbook paths
(`pull_artifacts.sh`, `scripts/README.md` step 7) told the operator to run it
bare — which would describe a non-existent instance, print *"nothing to tear
down"*, exit **0**, and leave the L4 billing. Verbatim `WEEK2_PLAN.md` §6.1's
named failure mode.

**Fixed:** `scripts/gpu_session/teardown_week2.sh` — a Week 2 wrapper that owns
the instance/zone, prints the resolved target **before** deleting, delegates the
deletion to the still-generic primitive, then **polls to verify the instance is
actually gone** (§6.4: do not trust the delete's exit code) and exits non-zero if
it is not. `DRY_RUN=1` resolves the target without touching anything. Every Week
2 call site now routes through it.

Pinned by `tests/gpu_session/test_teardown_target.py` (11 cases), which fails if
the wrapper and `create_instance.sh` drift apart or if any Week 2 path starts
recommending the bare primitive again.

### ✅ B2. Loadgen scheduler spin margin was never Linux-calibrated

**Was:** `SPIN_MARGIN_S = 0.005`, Windows-tuned, with no artifact — and the two
authoritative docs conflicted on whether that blocked the GPU session
(`WEEK2_EXECUTION.md:213-217` said "before this ships onto Linux vLLM runs";
Hard Stop 4's enumerated checklist omitted it). **The conflict was surfaced
rather than reconciled, and the human's decision was to run the A/B.**

**Fixed:** A/B run on a dedicated CPU-only `e2-standard-4`, 0ms vs 5ms, 20 and
80 RPS, 5×30s per cell; VM destroyed and deletion verified. The margin is now
**per platform, from measurement** (`WINDOWS_SPIN_MARGIN_S` /
`LINUX_SPIN_MARGIN_S`), overridable per host via `--spin-margin-s` or
`LOADGEN_SPIN_MARGIN_S` without editing tracked source, and recorded per point as
`provenance.spin_margin_s` + `provenance.platform`.

**Result: Linux = 0ms.** Zero early sends at 0ms in every cell — the only
property the spin protects. Evidence: `benchmarks/calibration/scheduler_spin/`;
decision and reasoning in `BENCHMARKS.md`.

---

## 🟡 Should-fix — all CLOSED

| # | Was | Now |
|---|---|---|
| S1 | Budget ladder $75/$135/$150 vs docs' $50/$100/$150 | **Policy resolved as $10 / $75 / $135 / $150** and the docs changed to match the live ladder — the $10 canary is the rung that actually fires at a ~$5–15 session (D5) |
| S2 | Offered-vs-achieved band still `[CALIBRATE]` | **±5% resolved** from Block C low-load tracking; deliberately *not* tightened to the measured 0.67% max (`WEEK2_PLAN.md` §2.5/§8) |
| S3 | V2's control never routed its bad variant through the real check | **Shared helper** `assert_achieved_rps_invariant`: the real open-loop run passes it, the closed-loop driver is fed to the *same* helper under `pytest.raises`. Now structurally identical to V1/V3/V4/V5 |
| S4 | No parameterized Stage B generator | **`scripts/generate_schedules.py`** — explicit points or inclusive range, one implementation; Stage A is now a thin wrapper and still regenerates its committed artifacts **byte-identically**. 18 tests |
| S5 | `benchmarks/runs/` needed `git add -f` to promote evidence | **Explicit split** — `schedules/`, `calibration/`, `evidence/` tracked; `runs/`, `scratch/` ignored; raw logs ignored *except* under `evidence/`, so promotion is a plain `git add` (D6) |
| S6 | Mock omitted 4 keys real vLLM sends | **Fixed** — the three chunk kinds now carry vLLM 0.27.1's actual key sets, verified clean in *both* directions. Parser contract untouched (R1) |
| S7 | `adversarial.py` documented a flag that doesn't exist | Docstring corrected; the 90th-percentile cut is a **fixed Week 2 constant**, and no knob was added (R5) |
| S8 | `create_instance.sh` didn't request Spot | **`--provisioning-model=SPOT`** + `--maintenance-policy=TERMINATE` + `--no-restart-on-failure`, and the script reads the resolved model back from the API (R2) |

---

## 🟢 Post-GPU by design — unchanged, and correct

- **Warmup N** — resolved in Block F from Stage A's transient. Applying it is a
  metrics-side re-filter over committed sidecars, never a GPU re-run.
- **Transient plotting** — Block F, post-teardown, free. The `(send_time,
  ttft_ms)` pairs are already captured per request.
- **`--enforce-eager`** and the **output-token policy** — deliberately left open
  for the human at session start.
- **Token-count `prompt_len`** — Week 3.

---

## 📄 Documentation staleness — all CLOSED

D1 `STATUS.md` test counts/state · D2 `WEEK2_PLAN.md` preamble claiming §3–§7
unlocked · D3 stale "branch not on origin" warning · D4 stale loadgen test counts
(19/23/35 → **63**) · D5 Window Y not marked resolved · D6 cap cross-referenced as
§3.2 instead of §3.3.

Each was corrected **in place with the old value preserved as historical
context**, not silently overwritten — "which sections were locked when" and "what
this checklist used to claim" are part of these documents' own provenance.

---

## Findings the remediation itself produced

Two methodology traps, hit for real while running the B2 calibration, both now
recorded in `BENCHMARKS.md` and `benchmarks/calibration/scheduler_spin/README.md`:

1. **An in-process mock shares the driver's GIL** and its request handling shows
   up as scheduling lag. The real GPU topology (separate processes) does not have
   this; the harness now supports `--mock-url`.
2. **`ulimit -n` applies to calibration harnesses too.** The first 80 RPS attempt
   hit `OSError: [Errno 24] Too many open files` — §3.3's documented
   precondition, in a script that had not raised it.

And one substantive observation for the session, **not a blocker**: against the
*mock*, response time stays flat at 0.911s with concurrency scaling linearly
through 60 RPS, then collapses at 80 RPS (response p50 10.8s, peak concurrency
78 → 1323) while client CPU stays at ~25% of one core. **That is the mock
saturating, not the driver** — and `MOCK_TRUST_BOUNDARY.md` explicitly does not
trust the mock for saturation behaviour. It says nothing about real vLLM, but it
does mean the mock cannot be used to rehearse Stage A's top point.

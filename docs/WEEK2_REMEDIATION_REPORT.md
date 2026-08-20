# Week 2 Pre-GPU Remediation — Report

> **STATUS: EVIDENCE — DOES NOT GOVERN EXECUTION**
>
> Role: what the 2026-08-18 remediation changed, and what it proved.
>
> This document records *why* something is believed. It does not govern
> execution, and any command text below is a record of what was run at the
> time, not an instruction to run it now.
> Current execution instructions: `docs/WEEK2_GPU_SESSION_2_PLAN.md`.
> Index: `docs/WEEK2_DOC_INDEX.md`.

**Completed 2026-08-18.** Every blocker from `docs/WEEK2_PRE_GPU_AUDIT.md` is
closed. The repository is clean, committed and pushed, and no GPU instance was
created.

| | |
|---|---|
| Branch | `week2/loadgen-baseline` |
| HEAD | `5e6ff46` (= `origin`) |
| Commits | `9ebc420` remediation · `5e6ff46` session-notes addendum |
| Started from | `3ac82aa` |

**Document map.** `WEEK2_PLAN.md` is the decision record and
`WEEK2_EXECUTION.md` the execution order — both authoritative.
`docs/WEEK2_PRE_GPU_AUDIT.md` is the audit trail (what was wrong).
Session #1's Hard Stop 4 evidence checklist (removed 2026-08-20; in git history at 39ed3f1) was its companion. **This
document is the record of what was changed and what it proved.**

---

## 1. Changes made

### D1 — Week 2 teardown ownership

**Files:** **+`scripts/gpu_session/teardown_week2.sh`** · `pull_artifacts.sh` ·
`run_on_instance.sh` · `scripts/README.md` · session #1's pre-flight §5

`scripts/teardown.sh` stays a generic deletion primitive (Week 1 still depends
on its default). A Week 2 wrapper now owns `llmrouter-vllm-l4-week2` /
`us-central1-a`: it prints the resolved instance and zone **before** deleting,
delegates the deletion to the primitive, then **polls to verify the instance is
actually gone** and exits non-zero if it is not. `DRY_RUN=1` resolves the target
without touching anything. Every Week 2 call site was rerouted.

**Why.** Run bare against a Week 2 session, the generic primitive describes an
instance that does not exist, prints *"nothing to tear down"* and **exits 0** —
while the L4 keeps billing. That is verbatim `WEEK2_PLAN.md` §6.1's named
failure mode, and it was sitting in two runbook paths. §6.4 also requires
verifying deletion rather than trusting the delete's exit code, which nothing
previously did.

### D2 — Linux loadgen scheduler spin calibration

**Files:** `loadgen/scheduler.py` · `loadgen/_cli.py` ·
**+`scripts/calibrate_scheduler_spin.py`** ·
**+`benchmarks/calibration/scheduler_spin/`**

The spin margin is now **per platform, from measurement** —
`WINDOWS_SPIN_MARGIN_S = 0.005`, `LINUX_SPIN_MARGIN_S = 0.0` — resolved through
`default_spin_margin_s()`, overridable per host via `--spin-margin-s` or the
`LOADGEN_SPIN_MARGIN_S` environment variable, and recorded on every point record
as `provenance.spin_margin_s` and `provenance.platform`.

**Why.** `WEEK2_PLAN.md` §8 forbade shipping the Windows-tuned 5ms onto the
Linux vLLM runs unverified. Configuration rather than a hidden constant matters
specifically because `run_on_instance.sh bootstrap` pins the instance to a
commit and refuses a dirty tree — re-tuning by editing source would either block
the session or cost the "which code drove this sweep" answer `BASELINE.md` owes.

Full result in §2.

### D3 — Offered-vs-achieved band

**Files:** `WEEK2_PLAN.md` §2.5 and §8 · `metrics/point.py`

**±5%, resolved.** Provenance is Block C's low-load tracking sweep
(`benchmarks/calibration/block_c/calibration_reads.json` → `low_load_tracking`):
**0.0% / 0.0% / 0.0% / −0.67%** at 0.5 / 1 / 2 / 5 RPS — rates far below anything
that could saturate a single client, where divergence would indicate a loadgen
bug rather than saturation.

Deliberately **not** tightened to the measured 0.67% maximum. The band's job is
to detect *material driver under-delivery*, not to certify perfection at trivial
load; a band with no headroom would flag healthy points near the breach, which
is the worst place to lose data. Option Y semantics are unchanged — clean points
plot at offered, flagged points are kept and plot at achieved, both logged.

### D4 — Generic Stage A / Stage B schedule generator

**Files:** **+`scripts/generate_schedules.py`** ·
`scripts/generate_stage_a_schedules.py` (now a thin wrapper) ·
**+`tests/loadgen/test_schedule_cli.py`** (18 tests)

```bash
python scripts/generate_schedules.py --rps 32 34 36 38          --out-dir …
python scripts/generate_schedules.py --rps-start 32 --rps-stop 38 --rps-step 2 --out-dir …
```

Both styles route through one `generate()` function, so there is exactly one
place a workload lock could be broken. Every lock is inherited rather than
re-established: same frozen format, RNG scheme and version, arrival/corpus
stream independence, materialization-time prompt assignment, pinned corpus,
provenance fields, duration behaviour, replay compatibility.

**Verified:** the two syntaxes emit **byte-identical** artifacts, and Stage A
regenerates its eight committed schedules **byte for byte** through the new
shared path.

**Why.** Stage B's bracket is only known mid-session and the old generator
hard-coded its RPS list, so producing Stage B meant editing tracked source *on
the meter*.

### D5 — Budget alert policy

**Files:** `WEEK2_PLAN.md` §6.1 · `WEEK2_EXECUTION.md` ·
session #1's pre-flight §2

Authoritative policy is now **$10 canary / $75 / $135 / $150 hard line**, and
the docs were changed to match the live ladder rather than the reverse. No
billing API was touched.

**Why this direction.** A g2-standard-8 + L4 spot runs ~$0.40–0.50/hr, so a
session lands in the $5–15 range: a $50 first warning would never fire at all.
An alert ladder whose lowest rung sits above expected spend is decorative. The
$150 hard line — the only rung that bounds spend — was never in question. These
remain a tripwire, not a stop; verified teardown is the actual control.

### D6 — Benchmark evidence / scratch Git policy

**Files:** `.gitignore` · `benchmarks/README.md` · `scripts/calibrate_block_c.py`
· `scripts/calibrate_noise_floor.py` · artifacts relocated

| Path | Tracked | Contents |
|---|---|---|
| `benchmarks/schedules/` | **yes** | frozen workload inputs (replay's source of truth) |
| `benchmarks/calibration/` | **yes** | evidence behind every resolved `[CALIBRATE]` value |
| `benchmarks/evidence/week2/` | **yes** | accepted results supporting a published claim |
| `benchmarks/runs/` | no | raw session output, before promotion |
| `benchmarks/scratch/` | no | exploratory, debug, retry |

Raw `*.raw_log.jsonl` / `*.samples.jsonl` are ignored **everywhere except**
`evidence/`. The promotion rule is documented:

> Only accepted artifacts that support `BASELINE.md` or calibration provenance
> are committed; exploratory, debug and retry artifacts remain scratch.

**Why the negation matters.** Promoting a point is now a plain `git add` rather
than `git add -f`. A `-f` is invisible in history, so promotion would have left
no trace of the decision.

### R1 — Mock / vLLM faithfulness regression

**Files:** `mock/app.py`

Real vLLM 0.27.1 sends **different key sets per chunk kind**, so the mock now
builds three chunk kinds separately rather than emitting one shape:

- **role** — `delta:{role, content:""}`, `logprobs`, plus top-level
  `prompt_token_ids` / `prompt_text`
- **content** — `delta:{content}`, `logprobs`, per-choice `token_ids`
- **final** — `delta:{content:""}`, `logprobs`, `finish_reason`, `stop_reason`,
  `token_ids`, plus top-level `system_fingerprint`

Emitting the *union* on every chunk would have passed the test while being
**less** faithful — real vLLM never puts `prompt_token_ids` on a content chunk —
and shape fidelity is the point of Layer 3.

The assertion was not weakened, and the parser contract is untouched:
`metrics/parse.py` classifies a chunk as content **iff `delta.content` is a
non-empty string**, so the role chunk's `""` stays a non-content chunk and TTFT
is still measured to the first real token.

`system_fingerprint` is `"mock-replica-nohash"`, not a vLLM build string — the
check compares key *sets*, not values, and a reader tailing the mock's stream
should never mistake it for the real server.

**Proof (both directions, all three chunk kinds):**

```
role     real-minus-mock=CLEAN   mock-extra=none
content  real-minus-mock=CLEAN   mock-extra=none
final    real-minus-mock=CLEAN   mock-extra=none

role chunk classified as content?  False   (must be False)
final chunk classified as content? False   (must be False)
content chunk classified?          True    (must be True)
```

`pytest tests/faithfulness` → **7 passed** (mock schema, real-fixture schema,
recursive key-set diff, parser-is-a-no-op). Router eval remains **green**.

### R2 — Explicit Spot provisioning

**Files:** `scripts/gpu_session/create_instance.sh`

```bash
--provisioning-model=SPOT --maintenance-policy=TERMINATE --no-restart-on-failure
```

`SPOT` requires a non-`MIGRATE` maintenance policy and a GPU instance cannot
live-migrate anyway, so `TERMINATE` is both mandatory and correct;
`--no-restart-on-failure` stops a preempted instance silently restarting the
meter. The script then **reads the resolved model back from the API** rather
than trusting the flag went through — a silently on-demand L4 is a budget
finding, and spot capacity can be refused. All machine/GPU/model settings are
otherwise unchanged.

### R3 — Measurement window Y

**Files:** `WEEK2_PLAN.md` §2.4 and §8

**Y = 120s, resolved.** Stage A's lowest offered point is 2 RPS, so the window
carries `2 × 120 = 240` scheduled requests — **2.4×** the ≥100 achieved-sample
validity floor, leaving room for material under-delivery before a point becomes
tail-invalid. Every higher point clears it by more. No runtime change; it was
already 120s in code and only unmarked in the authoritative table.

### R4 — V2 negative-control assertion style

**Files:** `tests/loadgen/_assertions.py` · `test_negative_controls.py` ·
`test_v2_open_loop_fidelity.py`

New shared helper `assert_achieved_rps_invariant(fast, slow, tol=0.2)`. The real
open-loop implementation passes it; the deliberately closed-loop driver's own
fast/slow numbers are fed to the **same** helper under
`pytest.raises(AssertionError)`. Threshold unchanged.

**Why.** V2 was the only one of the five controls whose bad variant never went
through the real check — it demonstrated divergence numerically instead. Now
structurally identical to V1/V3/V4/V5.

### R5 — Adversarial CLI / docstring drift

**Files:** `loadgen/adversarial.py`

The docstring advertised `--long-context-percentile 90`, which does not exist.
`loadgen/schedule.py:130` calls `draw_prompt_id_long_context` **without** a
percentile, so the 90th-percentile cut is fixed by the wiring. The docstring was
corrected to say so; **no knob was added** — §2.1 defines adversarial as one
scenario, and a sweepable cut would make it a length sweep, which §2.2 puts out
of scope for Week 2.

### R6 — Documentation consistency

`STATUS.md` (counts and known-issues state) · `WEEK2_PLAN.md` preamble that
still said §3–§7 were unlocked · stale "branch not on origin" warning ·
loadgen test counts 19/23/35 → **63** · Window Y status · cap cross-referenced
as §3.2 instead of §3.3 · teardown instructions · budget thresholds · the new
evidence policy · the scheduler-spin result.

Every correction was made **in place with the old value preserved as historical
context**. "Which sections were locked when" and "what this checklist used to
claim" are part of those documents' own provenance.

### Unplanned — pre-commit hook false positive

**Files:** `scripts/hooks/pre-commit`

The project-number pattern now excludes decimal fractions
(`[^0-9.]` leading class). Committed calibration JSON is full of full-precision
timing floats such as `105.6721945006575` — 13 digits after the point — which
matched the 12-plus-digit rule.

Directly caused by D6: making calibration artifacts routinely committable turned
a rare false positive into a recurring one. Without the fix every calibration
commit would need `--no-verify`, which skips the billing-account checks too — a
strictly worse outcome than narrowing the pattern. Verified the pattern still
catches a real project number at line start, after a space, and in
`projects/<number>`.

---

## 2. Calibration result — Linux scheduler spin

**Method.** Dedicated CPU-only **`e2-standard-4`**, `us-central1-a`, Ubuntu
22.04, kernel 6.8.0-1066-gcp, Python 3.10.12, httpx 0.28.1. Created and
destroyed for this measurement; **deletion verified**. Not CI — a shared runner
would measure the neighbour's contention, and the question is platform-specific.

One variable: `spin_margin_s ∈ {0.0, 0.005}`. Same machine, seed (20260818),
Poisson schedule construction, corpus, client, concurrency cap (3000), mock
config (`slow`), 5 runs × 30s per cell. Mock in a **separate process** over
loopback; `ulimit -n 65535`.

| RPS | Spin | lag p50 | p95 | p99 | max | offered | achieved | divergence | early sends |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 | **0ms** | 0.910 | 2.016 | 2.667 | 5.741 | 20 | 20.97 | +4.83% | **0** |
| 20 | 5ms | 0.081 | 0.548 | 1.384 | 36.559 | 20 | 20.97 | +4.83% | **0** |
| 80 | **0ms** | 745.884 | 4448.784 | 5030.837 | 6293.291 | 80 | 79.87 | −0.17% | **0** |
| 80 | 5ms | 733.896 | 4398.058 | 5174.818 | 6082.602 | 80 | 79.87 | −0.17% | **0** |

Lag in ms, averaged over the 5 runs per cell; `max` is the worst single
observation across all 5.

### The 80 RPS rows measure the mock, not the scheduler

A companion sweep (`rps_knee_diagnostic.txt`) with CPU sampling:

| RPS | peak concurrency | response p50 | response p99 | errored | client CPU |
|---:|---:|---:|---:|---:|---:|
| 20 | 30 | 0.911s | 0.917s | 0 | ~20–25% of one core |
| 40 | 53 | 0.912s | 0.920s | 0 | ~20–25% |
| 60 | 78 | 0.913s | 0.933s | 0 | ~20–25% |
| 80 | **1323** | **10.838s** | **50.062s** | 5 | ~20–25% |

The mock holds a flat 0.911s response — its configured slow-config duration —
with concurrency scaling linearly through 60 RPS, then collapses at 80:
response time 12×, concurrency 17×. Client CPU never exceeded ~25% of one core
and load average stayed ~0.2, so **the driver is not what saturated**. The
scheduling lag is downstream of 1323 concurrent open streams, and
`MOCK_TRUST_BOUNDARY.md` explicitly does not trust the mock for saturation
behaviour or latency under concurrency (the deferred Week 1 concurrency bug).

Both arms are affected identically, so the A/B comparison survives; the absolute
80 RPS numbers do not transfer to real vLLM.

### Decision: Linux 0ms, Windows 5ms

`loadgen/scheduler.py: LINUX_SPIN_MARGIN_S = 0.0`, `WINDOWS_SPIN_MARGIN_S = 0.005`

1. **The spin's only justification does not apply on Linux.** It exists to stop
   a send firing *before* its scheduled offset (§4 V5, "late allowed, early
   impossible"). **Zero early sends at 0ms in every cell of every pass**,
   including the saturated ones. Windows keeps 5ms because that is the platform
   where bare `asyncio.sleep` actually returns early.
2. **Where the measurement is clean it buys nothing that matters.** At 20 RPS
   the 5ms arm lands closer to target in the body (p50 0.08ms vs 0.91ms), but
   both are negligible against a 50ms inter-arrival gap — and the 5ms arm's
   *worst* case is 6× worse (36.6ms vs 5.7ms). At 80 RPS the arms are
   indistinguishable.
3. **It costs CPU where this project can least afford it.** Week 2 drives the
   loadgen **on the GPU instance**, so a 5ms busy-wait per send burns ~40% of a
   core at 80 RPS *on the same box as vLLM* — spending CPU the measured system
   needs, for no measured benefit.
4. Consistent with Block 0's independent finding that the *mock's* busy-wait is
   a Windows-only fix.

Evidence: `benchmarks/calibration/scheduler_spin/` (raw JSON for both passes,
the RPS-knee diagnostic, and a README with run conditions). Reading and decision
also written up in `BENCHMARKS.md`.

### Two methodology traps, both hit for real

1. **An in-process mock shares the driver's GIL.** The first pass ran the mock
   in a thread of the driving process; at 80 RPS its request handling and the
   scheduler's send loop competed for one interpreter and dominated the result.
   Fixed with `--mock-url`, pointing at a separately-started mock — which is
   also the real topology, since the GPU session drives vLLM in its own process
   and venv.
2. **`ulimit -n` applies to calibration harnesses too.** The first 80 RPS
   attempt hit `OSError: [Errno 24] Too many open files` — §3.3's documented
   precondition, from the same default soft limit of 1024, in a script that had
   not raised it. `remote_loadgen.sh` enforces the raise for the GPU run; the
   calibration runner now does too.

---

## 3. Tests

| Command | Result |
|---|---|
| `.venv/Scripts/python -m pytest tests/loadgen -v` | **63 passed** |
| `.venv/Scripts/python -m pytest tests/gpu_session` | **11 passed** |
| `.venv/Scripts/python -m pytest tests/loadgen/test_schedule_cli.py` | **18 passed** |
| `.venv/Scripts/python -m pytest tests/loadgen/test_scheduler_spin_config.py` | **8 passed** |
| `.venv/Scripts/python -m pytest tests/faithfulness` | **7 passed** |
| `PYTHON=.venv/Scripts/python bash scripts/router_eval.sh` | **green** — 9 cargo, 5 controls, 20 eval |
| `.venv/Scripts/python -m pytest tests` | **141 passed, 3 failed** (see below) |

### Negative-control evidence, live

```
closed-loop achieved RPS: fast=4.33 slow=1.04 ratio=4.15x
open-loop  achieved RPS: fast=5.33 slow=5.33 divergence=0.0%
open-loop  max scheduling lag: fast=15.2ms slow=15.2ms
V2 invariance: fast=3.67 slow=3.67 divergence=0.0%
V3 control: real peak=10 broken peak=11 (cap=10)
```

All five controls construct their known-bad variant in-process and assert the
**same** helper the positive test uses goes red under `pytest.raises`. The red is
re-proven on every run, not archived.

### The 3 full-suite failures are not a regression

`tests/mock/test_timing_accuracy.py` (fast / slow / bursty) — the mock delivering
its configured TTFT outside the ±10ms fidelity band on the Windows dev box
(bursty: 311.50ms vs 300ms configured).

Distinguishing evidence:

- **An earlier full-suite run the same day passed 144/144** with all these code
  changes already in place.
- They **fail standalone too** (`pytest tests/mock` → 3 failed), so this is *not*
  suite-wide contention.
- **Stashing `mock/app.py` and re-running against the committed original
  reproduces the failure identically** (bursty 312.36ms vs the changed version's
  311.50ms). Not caused by R1.

This is the machine-drift signal `WEEK2_PLAN.md` §7 explicitly defers ("mock
timing overshoots the 10ms band on the Windows dev box… not a separate bug"),
and mock latency is outside the trusted set per `MOCK_TRUST_BOUNDARY.md` — it is
not a Week 2 measurement input. **Tolerances were not widened.** The Linux
calibration measured the mock delivering its configured timing to within ~1ms,
which is consistent with this being environment-specific.

---

## 4. Remaining issues

| Class | Item |
|---|---|
| **BLOCKER** | *none* |
| **SHOULD FIX** | Windows dev-box mock timing intermittently overshoots the 10ms fidelity band (~+11ms). Not a Week 2 measurement input; re-measure on Linux rather than re-banding. |
| **POST-GPU BY DESIGN** | Warmup N (Block F; a metrics-side, time-based re-filter over committed sidecars, **never** a GPU re-run) · transient plotting (post-teardown, data already captured per request) · `--enforce-eager` and the output-token policy (deliberately left for the human at session start) · token-count `prompt_len` (Week 3) |
| **DOCUMENTATION / HISTORICAL** | Schedule provenance records an absolute Windows `corpus_path`. Informational only — `validate_corpus_version` compares the **sha256**, not the path. Left alone because changing it would rewrite frozen artifacts. |

---

## 5. Hard-stop verdict

| Gate | Verdict | Evidence |
|---|---|---|
| Hard Stop 1 — open-loop architecture | **PASS** | Single `await` in the hot loop (`scheduler.py:127`); cap checked inside the spawned task and sheds without blocking; `max_connections=None` overrides httpx's default of 100, which would have serialized. Live: closed-loop 4.15× divergence vs open-loop **0.0%** |
| Hard Stop 2 — negative controls bite | **PASS** | 63/63 loadgen green. All five controls now route their bad variant through the same shared helper under `pytest.raises`, V2 included (R4). Reds re-proven every run |
| Hard Stop 3 — calibrations | **PASS** | cap **3000** · band **±5%** · window Y **120s** · mock spin **resolved** · loadgen spin **resolved** (Linux 0ms, artifact committed). Warmup N remains open **by design** and correctly does not count against this gate |
| Hard Stop 4 — pre-GPU readiness | **PASS** | §4 gate green; teardown wrapper resolves `llmrouter-vllm-l4-week2` / `us-central1-a` and verifies deletion; Spot requested and read back; Stage A committed; Stage B a command, not a source edit; evidence policy proven in both directions; tree clean, committed and pushed |

**Cloud state.** No GPU instance was created at any point. The calibration `e2`
was created, used, destroyed, and its deletion verified.
`gcloud compute instances list` → **0 items**.

> ## GPU SESSION READY: YES

Block E remains human-owned. The agent does not stand up, drive, or tear down
the instance.

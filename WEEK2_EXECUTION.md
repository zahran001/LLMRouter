# Week 2 — Execution & Agent Runbook

> **STATUS: AUTHORITATIVE — WEEK 2**
>
> Role: execution order, hard stops, and definitions of done.
>
> Current document authority: experiment semantics `WEEK2_PLAN.md` · execution
> and gating `WEEK2_EXECUTION.md` · GPU commands `docs/WEEK2_GPU_SESSION_2_PLAN.md`.
> Index: `docs/WEEK2_DOC_INDEX.md`. If these appear to conflict, **HALT and surface the
> conflict** — do not reconcile silently.

**Companion to `WEEK2_PLAN.md`.** The plan is the *decision record* (what was
decided and why). This is the *execution order* (what to build, in what sequence,
and where to stop).

**Precedence rule.** The two docs are authoritative on different axes and should not
conflict on the same one:
- **`WEEK2_PLAN.md` is authoritative on *what was decided and why*** — the locks, the
  spec, the provenance, the calibration sources.
- **This doc is authoritative on *order and gating*** — sequence, blocks, hard stops,
  definitions-of-done.
- **If they appear to conflict on the same axis, HALT and surface it — do not
  silently reconcile.** An apparent conflict almost always means a lock was misread,
  and silently reconciling it is exactly how a locked decision gets quietly weakened.
  Surfacing the conflict turns a potential drift into a checkpoint.

---

## How this doc works (agent: read first)

- Work proceeds in **BLOCKS**. Each block is delegable: build it, meet its
  definition-of-done, then reach the **HARD STOP** that follows.
- **A HARD STOP is a blocking gate.** At a hard stop you (the agent) **halt and wait
  for explicit human sign-off** before proceeding to the next block. Do not proceed
  on your own judgment, even if confident. Especially if confident.
- At each hard stop your job is to **produce the evidence the human needs to verify**,
  then stop. The human renders the verdict. You do not self-certify.
- **You never stand up the GPU instance.** The human owns the meter. Every GPU action
  is human-run (Block E).
- Section references (e.g. §3.3) point into `WEEK2_PLAN.md` for the locked spec.

---

## Execution order (overview)

```
Block 0  Linux calibration            (GPU-free; agent runs e2 VM end-to-end)
Block A  Loadgen build                (delegable)
         ── HARD STOP 1: open-loop architecture review ──
Block B  Mock validations V1–V5       (delegable build; controls must bite)
         ── HARD STOP 2: negative-control verification (THE gate) ──
Block C  Calibration reads            (delegable data-gen; human reads values)
         ── HARD STOP 3: [CALIBRATE] resolution ──
Block D  Trace/replay + pre-flight    (delegable prep)
         ── HARD STOP 4: pre-GPU pre-flight (money about to burn) ──
Block E  GPU session #1               (HUMAN-RUN) -- ran 2026-08-18
         ── HARD STOP 5: mid-session Stage A bracket / escape hatch ──
         >>> ESCAPE HATCH TAKEN. See "The redesign arc" below. <<<
```

**Blocks 0–E completed and the first GPU session ran.** It produced **no
defensible breach RPS**: the escape hatch at Hard Stop 5 fired, the session was
torn down, and the experiment moved offline. Block F never ran as designed, and
**must not** — see the warning under Block F.

### The redesign arc (added 2026-08-19)

```
GPU session #1 findings          (diagnostic evidence; no breach RPS)
         ↓
Block R0 Preserve first-session evidence      (GPU-free)
Block R1 Corpus histogram + candidate strata  (GPU-free)
Block R2 p99-vs-N bootstrap, both sources     (GPU-free)
Block R3 Joint k/L/N + evidence-ceiling report
         ── HARD STOP R3: human locks k, L, N, N_max ── DONE 2026-08-19
Block R3.5 Provenance closeout + the locks R3 exposed as missing
Block R4  Freeze canonical workload  (gated on tokenizer capacity proof)
Block R5  Matched repeat-family schedule generation
Block R6  Exact-N open-loop schedule semantics
Block R7  Nominal λ vs materialized vs actual-send metrics
Block R8  Censoring-aware validity
Block R9  Drain-separated independent-repeat orchestration
Block R10 Repeat-level classification + bounded-UNCERTAIN fallback
Block R11 Natural-random secondary workload
         ── Regression + negative controls (every new control must bite) ──
Block R-DOC Documentation authority cleanup   (GPU-free)
         ── HARD STOP R-DOC: documentation governance + human verdict ──
         ── final regression / benchmark SHA ──
         ── HARD STOP R-PREGPU: new pre-GPU audit + human approval ──
Block E2 GPU session #2              (HUMAN-RUN; scout tier then confirm tier)
Block F  Offline analysis + BASELINE.md
```

**Authority for the redesign blocks:** `WEEK2_PLAN.md` §10 (what was superseded
and why), `docs/WEEK2_GPU_SESSION_FINDINGS.md` (what the session found), and
`benchmarks/calibration/week2_redesign/R3_EVIDENCE_PACKAGE.md` (the calibration
the locks were read off). The precedence rule at the top of this document is
unchanged: `WEEK2_PLAN.md` remains authoritative on *what was decided and why*,
this document on *order and gating*.

### ── HARD STOP R3 — canonical workload locks (CLEARED 2026-08-19) ──

**Why this was human-gated:** `k`, `L`, `N` and `N_max` set both the workload and
the size of the GPU spend that follows. They are judgment reads off calibration
data, in the same class as Hard Stop 3 — the agent plots, the human reads the
number off the plot.

**Locked:** `k` = 6 strata (0/50/90/95/99/99.5/100); `L` = corpus q99 = 11,471
chars; `N` = 4,000 post-warmup scheduled arrivals per run; `N_max` = 5,000
(structural corpus ceiling). Plus two locks the R3 evidence showed were
*missing* rather than merely unset: **nearest-rank p99** and **prefix caching
disabled for the controlled headline**.

### ── HARD STOP R-DOC — documentation authority (PASSED 2026-08-19) ──

**Why this is human-gated:** R4–R11 made the *code* enforce the redesign. They
could not make the *documents* stop describing the old experiment. Week 2 now
carries two design generations, four executed implementation briefs, a
superseded GPU runbook and a superseded pre-flight — every one of which was
correct when written, and several of which would still run.

R-DOC answers one question:

> Can a fresh-context agent enter the repository and unambiguously determine
> which documents govern GPU session #2, **without relying on conversation
> history**?

**Agent produces, then halts:** the documentation map (authoritative /
executable / evidence / historical / superseded), the repo-wide
stale-assumption audit with zero unexplained stale hits, the six human locks
committed into current authority, the documentation-governance test suite,
every documentation control shown red-then-green, the fresh-context
integration result, and the full regression totals recorded rather than
substituted.

**Human verifies and renders the verdict.** The agent does not self-certify a
documentation gate any more than a measurement one.

**Verdict: PASS, rendered 2026-08-19.** Cleared in two passes — the first
cleanup's checker reported zero stale hits over documents that still carried
the superseded warmup re-filter and session #1's Stage A/B runbook, so
`T-DOC-4`'s exemption scope was rebuilt and the audit re-run. Evidence:
`docs/WEEK2_GPU_SESSION_2_PREFLIGHT.md`.

**Definition of done:** `docs/WEEK2_DOC_INDEX.md` exists and classifies every
Week 2 process document; exactly one document is the current GPU-session
runbook; every historical or superseded document says `DO NOT EXECUTE`; the
locks `1A / 2B / 3A / 4A / 5A / 6A` are in `WEEK2_PLAN.md` §11 and in
`repeat_policy.json`; and `tests/redesign/test_week2_doc_state.py` passes.

**Order matters:** R-DOC precedes R-PREGPU. The benchmark SHA is cut *after*
the documentation is correct, so the SHA the session pins to is one whose
documents describe the experiment it will actually run.

### ── HARD STOP R-PREGPU — pre-GPU audit for session #2 ──

**Why this is human-gated:** the same reason as Hard Stop 4, plus one more. The
first session spent its money discovering that its own design was unsound. The
second session must execute an experiment that is already fully specified, so
everything discoverable offline must have been discovered before the meter
starts.

**Agent produces, then halts:** the §12 evidence package from the R4 continuation
README — doc supersession diffs, canonical workload provenance, tokenizer
capacity report and proposed `--max-model-len`, prefix-cache-disabled preflight
evidence, exact-N open-loop proof, nearest-rank metric proof, censoring-state
proof, repeat/drain proof, `N_max`/interval proof, full regression results, every
new negative control shown red-then-green, confirmation that historical hashes
are unchanged, and a proposed two-tier session plan with runtime and cost.

**Human verifies:** every item above, plus the standing Hard Stop 4 checklist
(quota, budget ladder, launch and teardown staged, schedules committed).

**The human — not the agent — proceeds to Block E2 and stands up the instance.**

---

## Block 0 — Linux spin-disabled calibration (READY, parallel)

**Ref:** §7. GPU-free; does not gate the baseline; start now, run alongside Block A.

**Environment (this matters — it IS the measurement's subject):** run on a
**dedicated, CPU-only GCP Linux VM (`e2-standard` class), NOT CI.** A noise floor is
**machine-specific** (§7 / Week 1 closeout). A 200-run floor measured on a shared
`ubuntu-latest` CI runner would measure GitHub's neighbor-VM contention, not the
mock's timing floor — the runner's noise contaminates the exact quantity being
measured. The floor needs a quiet, dedicated, known-hardware box. An `e2` CPU
instance is cents/hour and is that box.

**The CI number does NOT count.** CI (`ubuntu-latest`) already emits a Linux timing
number (~3ms, spin *enabled*, single run). That is the **discredited prior**, not a
partial result — do **not** read CI output and conclude Block 0 is done or half-done.
CI keeps its Week 1 role as a cheap *regression signal* that timing hasn't drifted
(spin enabled, as-is); it is **not** the calibration. The calibration is a separate,
dedicated-VM measurement with spin **disabled**.

**Agent runs it end-to-end (delegable, including the VM).** Unlike the GPU session,
the agent **may stand up, run, and tear down the `e2` CPU VM itself** — a CPU
instance is cents/hour with no runaway risk (the GPU meter-ownership rule exists for
~$70/weekend L4s, not ~$5/week e2s). Build the calibration harness — sequential
noise measurement, `precise_sleep` spin **disabled**, 200-run rigor (matching the
original calibration, not one run), output = run-to-run p50 spread — run it on the
`e2`, and **tear the VM down when done** (cheap is not free; a forgotten instance is
still a forgotten instance).

**DoD:** run-to-run p50 spread on the dedicated Linux VM with spin disabled,
documented, landed back with the human and into the noise-floor provenance (this
closes the Week 1 loose end — don't let it be a task the agent closes and forgets).
VM torn down. Answers "is the busy-wait needed on Linux without the spin."

*No hard stop. Fully agent-run including the VM. Blocks nothing downstream — but the
result must return to the human for the noise-floor provenance, not be silently
filed.*

---

## Block A — Loadgen build (delegable)

**Ref:** §3 (all subsections).

**Build, in order:**
1. **Schedule generator** (§3.2): pre-materialize the full `(offset, prompt_id)`
   schedule from a dedicated `arrival_rng`; independent `corpus_rng` via
   `SeedSequence.spawn()` (or equivalent) — the two RNG streams **must not
   interleave**. Poisson = exponential gaps at λ=RPS, cumsum to absolute offsets;
   steady = constant 1/RPS gaps. One continuous schedule (warmup = first N seconds,
   discarded metrics-side). Embed the provenance header (seed, RNG scheme version,
   RPS, arrival process).
2. **Corpus artifact** (§3.4): pin a random ShareGPT subset, commit as a versioned
   file with provenance header (source/version, seed, filter def, date). Documented
   validity-only junk filter (empty/malformed only — NOT length/content shaping).
   With-replacement i.i.d. draws via `corpus_rng`.
3. **Open-loop scheduler** (§3.3): absolute-time targets (`t_start + offset`, self-
   correcting); fire-and-forget async task spawn (scheduler loop sleeps-until, spawns,
   moves on — **never awaits the send's issue**); per-send scheduling lag logged
   (`scheduled_offset` vs actual `send_time`); in-flight **streaming responses**
   bounded by a concurrency cap, over-cap = `shed` (fail-fast, non-blocking).
4. **Raw log** (§3.1): 6 fields — `request_id`, `send_time`, `close_time`,
   `prompt_id`, `prompt_len`, `status ∈ {sent, shed, errored}`. Streamed to disk, not
   buffered.
5. Three entry points: `loadgen/steady.py`, `loadgen/poisson.py`,
   `loadgen/adversarial.py`.

**DoD:** loadgen runs against the mock end-to-end; schedule is pre-materialized and
committed before sending; raw log written with all 6 fields; per-send lag captured.

### ── HARD STOP 1 — Open-loop architecture review ──

**Why this is human-gated:** if the scheduler is subtly *closed-loop* (a hidden
`await` on the send, or a connection-pool cap that serializes sends behind in-flight
requests), V2 will still pass against a *fast* mock and you will not discover it until
the GPU session shows a breach that can't be reached. This is architectural — it
cannot be tested away downstream. It must be eyeballed now.

**Agent produces, then halts:**
- The scheduler's core loop (the sleep-until → spawn → continue path), highlighted.
- Explicit confirmation of where the send is spawned vs. awaited, and where the
  concurrency cap is enforced.
- Any place response handling could feed back into send timing.

**Human verifies (the actual gate):**
- The scheduler loop **spawns and moves on** — no `await` on the send's issue in the
  hot path.
- The concurrency cap bounds **open streams**, not sends-in-flight.
- No connection-pool / client default silently serializes sends.

**Proceed only on explicit human "open-loop confirmed."**

---

## Block B — Mock validations V1–V5 (delegable build)

**Ref:** §4. Build all five validations **with their negative controls** into
`docs/WEEK2_MOCK_VALIDATION.md` + test code. The trusted/not-trusted boundary list
goes in `MOCK_TRUST_BOUNDARY.md` (principle); the procedure goes in the new doc.

**Build each validation AND its control:**
- **V1 arrival dist** (offline): Poisson gaps fit `Exponential(λ=RPS)`; **control: the
  steady schedule must FAIL the fit.** Plus same-seed→byte-identical determinism.
- **V2 open-loop fidelity** (drive slow mock): per-send lag within band; **control:
  fast-mock vs slow-mock achieved RPS must be INVARIANT.** (The load-bearing check.)
- **V3 concurrency cap** (drive slow mock past cap): over-cap = `shed`, scheduler keeps
  firing; **control: zero sheds below the cap.** Records shed-onset RPS (feeds Block C).
- **V4 corpus faithfulness** (offline): draws only from pinned corpus, i.i.d. stats,
  histogram logged; **control: same corpus seed→identical sequence, different→different;
  every drawn prompt passes the junk filter.**
- **V5 logging integrity**: every send logged once with status; `scheduled = sent +
  shed + errored` reconciles; `send_time ≥ scheduled_offset` always; **control: an
  injected dropped log-write must trip reconciliation.**

**DoD:** all five validations implemented; all five negative controls implemented and
currently **red against a deliberately-broken variant** (proving they bite), then green
against the real implementation.

### ── HARD STOP 2 — Negative-control verification (THE gate) ──

**Why this is human-gated:** this is the single most important checkpoint in Week 2. A
green test that never went red proves nothing, and an agent has every incentive to
make tests green. "Make the test pass" and "make the test *meaningfully* pass" look
identical in a checkmark. The human must confirm each control **actually fires**, not
that the agent reports it fires.

**Agent produces, then halts:** for **each** of the five controls, the evidence that it
bites — i.e. run the control against the known-bad input and show it goes RED:
- V1: steady schedule fed to the exponential-fit check → show it FAILS.
- V2: fast-vs-slow achieved RPS comparison → show that a *deliberately closed-loop*
  variant makes them DIVERGE (and the real one keeps them invariant).
- V3: below-cap run → show shed count is exactly 0; a broken cap → show it sheds early.
- V4: mismatched corpus seed → show sequences differ; a filter-bypass → show junk reaches
  assignment.
- V5: injected dropped log-write → show reconciliation TRIPS.

**Human verifies (the actual gate):** personally confirm each control goes red on the
bad input and green on the real one. Do **not** accept "all five pass" as a summary —
the reds are the proof.

**Proceed only on explicit human "all five controls bite."** This gate also stands
between here and any GPU spend (re-checked at Hard Stop 4).

---

## Block C — Calibration reads (delegable data-gen; human reads)

**Ref:** §2.4, §3.3, §8. The agent *generates the data*; the human *reads the value*.
These are judgment reads, not computations — delegating the read delegates the
calibration, which violates the trace-to-source discipline.

**Agent produces:**
- **Cap value input:** the V3 shed-onset curve against the slow mock — offered RPS vs
  shed count — so the human can read the client's healthy ceiling.
- **Warmup N input:** *this one needs GPU transient data (Block E §6.3), so it is
  resolved post-session.* For now, generate the *mock-side* equivalent if useful, but
  flag that the real N comes from the GPU transient plot.
- **Window Y / ±5% band:** confirm against §8 sources (Y clears ≥100 samples at lowest
  RPS; band from low-load tracking).
- **Loadgen scheduler spin margin — RESOLVED 2026-08-18.** `SPIN_MARGIN_S` is now
  platform-dispatched: **0ms on Linux**, 5ms on Windows. The A/B ran on a real Linux
  VM (kernel `6.8.0-1066-gcp`, arms 0ms vs 5ms, 20 and 80 RPS, 5 repeats), evidence in
  `benchmarks/calibration/scheduler_spin/scheduler_spin_linux_ab.json`. *(This item
  previously read "Windows-tuned, not yet Linux-calibrated … before this ships onto
  Linux vLLM runs" — that was the open state at Hard Stop 2, and it was closed here.)*

### ── HARD STOP 3 — [CALIBRATE] resolution (session #1 — CLEARED 2026-08-18) ──

**Why this is human-gated:** "where does the curve flatten" and "where does shedding
onset" have a human eye in them. The agent plots; the human reads the number off the
plot and records it with provenance.

**Human verifies/sets:** cap value (from shed-onset, with headroom, provably above the
characterized RPS range); ±5% band; window Y. *(Deferring the warmup N to
post-session, as this stop originally did, is superseded: session #2 freezes a
60s boundary into the schedules and validates it forward in Tier A —
`WEEK2_PLAN.md` §11.4.)*

**Proceed only on explicit human sign-off of the values set so far.**

---

## Block D — Trace/replay + pre-flight prep (session #1 — COMPLETED 2026-08-18)

**Ref:** §5, §6.1.

**Build:**
- **Replay** (§5): re-drive a committed frozen schedule artifact (Option M).
  Determinism check asserts **workload identity** (byte-identical arrivals + prompt
  sequence), NOT latency identity. Validate schedule references the pinned corpus by
  version.
- **Pre-flight staging** (§6.1): stage the vLLM launch sequence from
  `docs/GPU_SESSION_NOTES.md`; size `--max-model-len` to actual test traffic (longest
  corpus prompt + max output); stage `teardown.sh` and dry-run-verify its target
  name/zone; pre-generate and commit the Stage A coarse schedules.

**DoD:** replay reproduces a workload byte-identically from a frozen artifact; all
pre-flight artifacts staged and committed.

### ── HARD STOP 4 — Pre-GPU pre-flight (session #1 — CLEARED; session #2's equivalent is Hard Stop R-PREGPU) ──

**Why this is human-gated:** the next block spends real money against the $150 cap.
Every item here is a "before the meter starts" confirmation, and the human owns the
meter.

**Agent produces, then halts:** the pre-flight checklist with evidence each item is
ready (launch staged, `--max-model-len` value, teardown dry-run output, committed Stage
A schedules).

**Human verifies (the actual gate):**
- **All five §4 validations green AND their controls confirmed biting** (re-affirm Hard
  Stop 2 — this is the §4 hard gate).
- L4 quota live in target region; pay-as-you-go active; budget alerts
  **$10 canary / $75 / $135 / $150 hard line** (resolved 2026-08-18; was
  $50/$100/$150 — the $10 canary is the rung that actually fires at a ~$5–15
  session, see `WEEK2_PLAN.md` §6.1).
- Launch + teardown staged; teardown dry-run confirmed to target the right
  instance/zone.
- Stage A schedules committed.

**The human — not the agent — proceeds to Block E and stands up the instance.**

---

## Block E — GPU session #1 (HUMAN-RUN) — RAN 2026-08-18, SUPERSEDED by Block E2

> **⚠ This block ran, and does not run again (2026-08-19).** It is session #1's
> sequence, kept as the record of what was done. **Session #2 is Block E2**, and
> its only runbook is `docs/WEEK2_GPU_SESSION_2_PLAN.md`. Two things below are
> now explicitly forbidden rather than merely superseded: **generating schedules
> mid-session** (session #2 drives frozen, committed artifacts; a new schedule
> means a new benchmark SHA and a stopped session) and **extending the λ range
> live** (the scout ladder is 1/2/4/8 with 0.5 and 16 pre-authorized and nothing
> else — lock 5A).

**Ref:** §6.2–§6.4. **The agent does not stand up, drive, or tear down the instance.**
The agent may assist by generating Stage B schedules on request mid-session and by
confirming durable writes are landing. Single continuous session; adversarial last.

**Human-run sequence:**
1. Stand up 1× L4 spot, vLLM Llama-3.2-3B, wait for healthy.
2. Confirm config-only swap (`UPSTREAM_BASE_URL` only). Any code change = finding, STOP.
3. **Stage A coarse sweep** — durable per-point writes (§6.3).

### ── HARD STOP 5 — Stage A bracket / escape hatch (session #1 — ESCAPE HATCH TAKEN; superseded by Hard Stop GPU-1) ──

**Why this is human-gated:** this is the one place mid-session judgment is sanctioned.
Whether the breach is bracketed, or something surprised (breach in an odd place,
achieved-RPS diverged badly), is a human read on live data — and the abort-to-offline
vs. continue decision is human.

**Human verifies:** is the breach bracketed (one point clearly <500ms p99 TTFT, one
clearly >)? If the whole sweep stayed under → extend upward live. If the first load
point was already over → add lower points. If something genuinely surprised → **invoke
the escape hatch**: tear down, analyze offline, resume in a second session rather than
improvising on the meter.

> *Superseded by lock 5A (2026-08-19).* "Extend upward live" and "add lower
> points" were this stop's authorized responses in session #1. They are not
> session #2's: the scout ladder is λ = 1/2/4/8, the **only** authorized
> expansions are λ = 0.5 (if 1 is already OVER) and λ = 16 (if 8 is still
> UNDER), and if those still fail to bracket the answer is **STOP and return to
> human review**. Session #2's equivalent gate is **Hard Stop GPU-1**, which
> also has to answer "is 60s of warmup enough?" — see
> `docs/WEEK2_GPU_SESSION_2_PLAN.md`.

**On "bracketed, continue":**
4. **Stage B fine sweep** between the bracketing points (agent generates fine schedules
   on request).
5. **Steady reference** curve.
6. **Adversarial LAST** (deliberately — it may degrade the server; baseline + steady are
   already durably written).
7. **Teardown** — run `teardown.sh`, **verify deletion in the console** (not just exit
   code).

---

## Block F — Offline analysis + BASELINE.md (delegable)

> **⚠ Block F cannot run against the first session's artifacts (2026-08-19).**
> Nothing below is wrong as a *procedure*, and it is what Block F will do after
> GPU session #2. But re-reading it as "we already have the artifacts, so just
> recompute the breach offline" would produce a number with no evidence behind
> it. The first session's points cannot support a breach RPS: the 2-RPS
> classification flips on one extreme prompt and flips again on the choice of
> percentile convention; the 1.5-RPS point is prefix-cache confounded and is not
> a clean UNDER anchor; and 10/20/30 RPS are 33–81% censored by client timeouts.
> The breach is not recoverable by better arithmetic over that data — it needs
> the redesigned workload and a second session. See `WEEK2_PLAN.md` §10.
>
> Two mechanical changes also apply when Block F does run: the percentile is
> **nearest-rank** (§10.5), and the warmup-N read is against session #2's
> transient, not session #1's.

**Ref:** §2.6, §6.4, §8. All post-teardown, free.

**Build (current — after GPU session #2):**
- Compute per-point p50/p95/p99 TTFT + TPOT from the **raw log + samples sidecar**
  (§3.1 — TTFT lives in the sidecar; the raw log's six fields hold no first-token
  time, by design), using **nearest-rank** percentiles (§10.5). Apply
  **censoring-aware validity** (§10.6): >5% censoring ⇒ `CENSORED`, ordinary p99
  suppressed. Flag any offered-vs-achieved divergent points against the
  **materialized** schedule (§10.4 — plot at achieved, log both).
- Classify each repeat, then each λ, via `metrics/classification.py`:
  three repeats, **unanimous** agreement, 2–1 ⇒ `UNCERTAIN` (§11.1).
- Resolve the **breach** = lowest λ classified `OVER`, with the highest `UNDER`
  below it. If unresolved at `N = 4000`, report the **interval** (§11.2). Do not
  escalate.
- Author **`BASELINE.md`**: the 500ms-breach problem statement, the canonical
  workload's prompt-length profile, the controlled-workload sentence (§10.1),
  the offered-vs-achieved footnote, the 2s secondary line, shared-y-axis chart
  (500ms + 2s lines), and the secondary/steady/adversarial curves (§11.6).

> **Superseded procedure, kept for the session #1 record only (2026-08-19).**
> Block F as originally written applied the **`n >= 100`** achieved-sample check
> (superseded by calibrated `N = 4000` + repeats, §10.3), linear-interpolation
> percentiles (superseded by nearest-rank, §10.5), and **resolved the deferred
> warmup N post-hoc by re-filtering the committed sidecars** (§2.4).
>
> **That last step is invalid for the redesigned exact-N headline** and must not
> be applied to session #2 data. Exactly N arrivals are materialized at or after
> the frozen 60s boundary, so filtering past it discards canonical arrivals and
> leaves fewer than N measured samples; `metrics/headline_point.py` refuses it.
> The warmup boundary is now **validated forward at Hard Stop GPU-1**, and an
> insufficient boundary is resolved by regenerating schedules offline — never by
> re-filtering after the fact (§11.4).

**DoD:** `BASELINE.md` states "at X RPS, naive single-replica serving breaches the 500ms
p99 TTFT SLO," fully sourced, reproducible from committed schedule + corpus artifacts.

*Note: the warmup-N read is a residual human checkpoint folded into Block F — surface
the plot, let the human read the value, don't self-assign it.*

---

## Summary of hard stops (all blocking, all human-verdict)

| # | After block | Human verifies | Failure mode it prevents |
|---|---|---|---|
| 1 | A | Scheduler is genuinely open-loop | Closed-loop hidden until GPU breach unreachable |
| 2 | B | Each negative control *bites* (goes red on bad input) | Green-but-meaningless tests; self-certified validity |
| 3 | C | [CALIBRATE] values read from data with provenance | Guessed constants; delegated calibration |
| 4 | D | Pre-flight green incl. §4 gate; meter ownership | Burning money on an unvalidated loadgen |
| 5 | E (mid) | Breach bracketed / escape-hatch decision | Mid-session improvisation on the meter |
| R3 | R2 | `k`, `L`, `N`, `N_max` read off calibration evidence | A workload and a GPU budget chosen by the agent's own judgment |
| R-DOC | R11 | One unambiguous execution path; every dead doc says `DO NOT EXECUTE` | A fresh agent executing a superseded runbook that was correct when written |
| R-PREGPU | R-DOC | Full redesign evidence package + every new control biting | Paying for a second session that rediscovers its own design flaws |

**The through-line:** the agent builds the plumbing fast between stops; the stops are
where the project's *trustworthiness* is established, and those are unskippable and
human-owned.

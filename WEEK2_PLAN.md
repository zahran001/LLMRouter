# Week 2 — Load Generation & Baseline: Implementation Plan

Week 1 is closed: transparent router merged to `main`, measurement pipeline
locked and calibrated, mock→vLLM faithfulness confirmed on real GPU. This
document is the authoritative plan for Week 2. It follows the same discipline
as `WEEK1_MEASUREMENT_SPEC.md`: every boundary that can be fixed on paper is
fixed here and marked **LOCKED**; every value that needs empirical calibration
is marked **[CALIBRATE]** with a named source; every expansion of a prior
artifact carries a provenance note.

**Status of this document: every design section (§2–§7) is LOCKED and
implemented.** See §9 for the closeout. The `[CALIBRATE]` values are tracked in
§8; all are resolved except the per-point warmup N, which is resolved from Stage
A's GPU transient data in Block F **by design** and is not an open design
question.

> *Historical note.* This line previously read "Sections §3–§7 are scoped but not
> yet fully designed… Do not implement §3–§7 against this draft; implement §2."
> That was accurate while §2 was being locked, and was left stale after §3–§7
> closed — so the preamble told a fresh reader not to implement work that was
> already built, locked and shipped. Recorded rather than quietly deleted,
> because "which sections were locked when" is part of this document's own
> provenance.

---

## 0. Goal

Produce `BASELINE.md` — the project's **problem statement** — stated as:

> At **X RPS**, naive single-replica serving breaches the **500ms p99 TTFT
> SLO**; later weeks push that breach to higher RPS.

Everything after Week 2 is measured against this number. Because the breach
threshold (500ms) is the *same* SLO the router defends in Weeks 4–8, this
baseline requires **zero re-baselining** later — the naive curve's 500ms
crossing computed here *is* the leftmost reference the router improves on.

**Hard boundary (from `MOCK_TRUST_BOUNDARY.md`):** every latency number in
`BASELINE.md` comes from **real vLLM on GPU, not the mock.** The mock's role in
Week 2 is defined in §4.

---

## 1. Design order vs execution order

These are deliberately different.

**Design order** (the order decisions are locked):
baseline semantics → loadgen → mock validation → trace/replay → GPU runbook.

**Execution order** (the order work actually happens):
Linux spin-disabled calibration → loadgen build → mock validation →
trace/replay → GPU session.

The Linux calibration is **first to execute** (it is GPU-free, independent of
the baseline spec, and can run while the loadgens are being built) but it does
**not** gate the baseline design, so it is designed last and run first.

---

## 2. Baseline semantics (LOCKED — all seven knobs)

This is the spec `BASELINE.md` executes. It is fully pinned before any GPU meter
runs. Placeholder numeric values that require measurement are marked
**[CALIBRATE]** with their source.

### 2.1 Arrival process (LOCKED)

- **Poisson (seeded) defines the headline breach RPS.** The project thesis names
  bursty load as the problem; the headline number must be measured under the
  load the thesis is about. Poisson is the standard model for independent
  arrivals (users don't coordinate).
- **Steady (fixed-interval) is captured in the same sweep** as a legible,
  lower-variance reference curve. Nearly free — same loadgen, different
  inter-arrival generator, same session.
- **Adversarial (long-context flood) is a separate Week 2 scenario, NOT part of
  the baseline breach number.** Its breach is driven by per-request cost, not
  arrival rate; folding it into an RPS-axis baseline would muddy the axis.

**Provenance — Poisson reproducibility.** Poisson is as reproducible as steady
*only because* the arrival schedule is seeded and logged as *scheduled* (see
§2.5 and §5). This is a hard dependency, not a nicety: build the schedule log
**with** the generator, not after. Without it, the Poisson headline is not
reproducible.

**Provenance — the breach RPS will read lower than a steady number would.**
Poisson bursts breach at a lower mean RPS than steady arrivals. This is the
*honest* number for the thesis. Recorded here so nobody later "fixes" it by
quietly switching the headline to steady for a friendlier figure.

### 2.2 Prompt distribution (LOCKED)

- **Fixed distribution, natural ShareGPT spread, pinned seed.** Every RPS point
  draws from the *same* seeded ShareGPT sample with its natural length spread
  preserved. Only one variable moves across the sweep: offered RPS.
- **The realized length histogram is logged in `BASELINE.md`** — the baseline
  documents its own prompt profile rather than asserting one.
- ShareGPT, not invented prompts (locked project principle). Length sweeps are
  **out of scope for Week 2** — they belong in Week 3, where KV-cache-aware
  routing makes prompt length the independent variable of interest.

**Provenance — the two-source tail, controlled by holding it fixed.** With
natural spread, a p99 TTFT breach has two contributing sources: queueing under
load *and* the long-prompt tail of the corpus. This is deliberate — p99 is the
headline precisely because real tail effects matter, and prompt-length variation
is a legitimate one. It is not a confound **because the same seeded distribution
feeds every RPS point**: the prompt-length contribution is held constant across
the sweep, so the *movement* of the breach as RPS climbs is attributable to
load. The prompt tail sets the curve's floor; RPS moves it. This sentence must
appear in `BASELINE.md`.

### 2.3 RPS sweep methodology (LOCKED; numbers from Stage A)

- **Two-stage coarse→fine discovery.** The exact RPS range/step is NOT locked in
  advance — it cannot be, because the breach location is unknown, and a fine step
  across the whole range either misses the breach or burns GPU on flat regions.
- **Stage A — coarse sweep:** wide steps across a broad range to locate the
  approximate breach region. Stage A also records the **unloaded TTFT floor** (see
  §2.6) and the **wall-clock transient** used to pin the warmup value (§2.4).
- **Stage B — fine sweep:** smaller RPS increments around the breach region
  identified by Stage A, to resolve the breach RPS to step granularity.
- Stage A output determines Stage B's points; Stage B is staged (not spent)
  before it runs.

### 2.4 Warmup + measurement window (LOCKED; N [CALIBRATE])

- **Warmup is per-point and time-based:** discard the first **N seconds** at each
  RPS step. A sustained-RPS run has a wall-clock transient (queue filling, KV
  cache + CUDA graph warming, connection pool establishment) that is a time
  phenomenon, not a request-count one. This supersedes Week 1's count-based
  "discard first 10" (which was correct for single-shot mock requests).
  - **N = 10s placeholder. [CALIBRATE]** from the Stage A transient plot (TTFT
    vs wall-clock; pin N where it flattens).
  - **Per-point, not once-at-session-start:** each RPS step has its own transient
    as load changes and the queue re-equilibrates. A shared warmup would
    contaminate every point after the first. The per-point warmup wall-clock
    (~N × number of points) is an accepted line item in the GPU budget.
- **Measurement window is fixed duration:** measure for **Y seconds** per point,
  same Y across all points. Fixed duration (not fixed request count) keeps every
  point comparable and the run legible.
  - **Y = 120s — RESOLVED 2026-08-18** (was a placeholder pending the coarse
    sweep's lowest RPS). Stage A's lowest offered point is **2 RPS**
    (`scripts/generate_stage_a_schedules.py: STAGE_A_RPS_POINTS`), so the
    measurement window carries `2 × 120 = 240` scheduled requests — **2.4×** the
    ≥100 achieved-sample validity floor, leaving room for material
    under-delivery before a point becomes tail-invalid. Every higher point
    clears it by more. The p99 over a 120s window also cannot be moved by a
    single transient spike (sustained-ness is inherent — see §2.6).
- **≥100-sample rule carries forward as a post-hoc validity check on *achieved*
  samples:** require `achieved_RPS × window ≥ 100` before reporting a point's
  tail percentile. A point that fails (e.g. offered high but achieved collapsed
  under load) is **tail-invalid and flagged, not reported.** Ties into §2.5.

### 2.5 Offered-vs-achieved validity gate (LOCKED)

This is the Week 2 analog of Week 1's negative controls: a guard against the
measurement instrument silently lying about its own input. Week 1 caught the mock
overshooting configured timing; this catches the loadgen failing to deliver the
offered rate.

- **Achieved RPS is measured from *sends*:** count of requests actually sent
  (`t0`/`send_time` captured) within the measurement window, divided by window
  duration. NOT completions — offered-vs-achieved is a question about whether the
  *driver kept up*, and the driver's job ends at send.
- **Divergence band: ±5% — RESOLVED 2026-08-18** (was `[CALIBRATE]`). If achieved
  is within ±5% of offered, the point is clean and plotted against offered RPS.
  Beyond ±5%, the point is flagged.
  - *Provenance.* Block C's low-load tracking sweep against the slow mock
    (`benchmarks/calibration/block_c/calibration_reads.json` → `low_load_tracking`)
    measured divergence at rates far below anything that could saturate a single
    client, where any divergence would be a loadgen bug rather than saturation:
    **0.5 RPS → 0.0%, 1 RPS → 0.0%, 2 RPS → 0.0%, 5 RPS → −0.67%.**
  - *Why ±5% is kept rather than tightened to the measured 0.67% maximum.* The
    band's job is to detect **material driver under-delivery**, not to certify
    that the driver is perfect at trivial load. Tightening to the observed
    maximum would leave no headroom for legitimate scheduler/client jitter and
    for Poisson's own realized-count variance at short windows, and would flag
    healthy points near the breach — the exact region where Option Y says losing
    data is worst. ±5% sits well above the noise and well below any divergence
    that would change a conclusion.
- **Flagged-point handling — Option Y (plot against achieved):** a flagged point
  is **kept** and plotted at the rate the server actually saw (achieved), not the
  intended rate (offered). Both values are logged; the divergence is recorded as
  a column. Rationale: the honest x-value is what the server experienced;
  dropping flagged points would systematically remove data near the breach — the
  worst place to lose it. The x-axis is then mixed-provenance (offered where
  clean, achieved where flagged) and carries a footnote.
- **The offered-vs-achieved gap is itself a finding** (e.g. "beyond ~40 RPS
  offered, a single client can't sustain the rate"), and it surfaces the
  client-saturation risk below.

**Client-saturation risk (surfaced by this gate).** If the loadgen saturates
before the server breaches — offered 40→50→60→70 but achieved 40→42→42→42 — then
nothing can be claimed about the server above ~42 RPS, and if the client saturates
*before* the server breaches, **the real server breach is never observed with a
single client.** This makes loadgen capability a **hard requirement**, not an
assumption (see §3 and §4).

### 2.6 Breach definition (LOCKED)

- **Breach metric: p99 TTFT.** TTFT (not TPOT) because first-token latency is what
  interactive users feel first and what queueing attacks first — a backed-up queue
  delays the first token. TPOT is still measured and logged, but the breach
  *number* is TTFT.
- **Headline threshold: 500ms.** The baseline claim is "at X RPS, naive
  single-replica serving breaches the 500ms p99 TTFT SLO." This is the *same*
  number the router defends in Weeks 4–8 — one SLO across the whole project, no
  "why two breach definitions" footnote.
- **2s retained as a secondary severe-degradation reference line** — plotted and
  recorded, not the headline. Preserves the "not just breached but unusable" data
  point without introducing a second breach definition.
- **Breach RPS = the lowest swept RPS whose full-window (Y-second) p99 TTFT ≥
  500ms**, resolved to step granularity by the Stage B fine sweep.
- **Sustained-ness is inherent to the window, not a separate rule:** a p99
  computed over a Y=120s window cannot be moved by one transient spike; sustained
  tail elevation is required to move it.
- **Unloaded TTFT floor is characterized first** (recorded in Stage A). This tells
  you how large a blowup 500ms represents and whether the knee is sharp and close
  or shallow and far — informing the Stage B step granularity.

### 2.7 Chart axis convention (LOCKED — binds Week 4)

- **Both the Week 2 baseline chart and the Week 4 headline chart use the same
  y-axis: p99 TTFT.**
- **Two horizontal reference lines on both charts: 500ms (headline SLO) and 2s
  (severe degradation).**
- Week 2 shows the single naive curve crossing both lines; Week 4 shows all four
  routing strategies against the *same two lines*. Same axis, same lines → one
  continuous visual story: naive crosses early, routing pushes the crossings
  right. Locked now so Week 4's chart is not re-litigated when built.

**Provenance — no future seam.** Because 500ms is both the breach line and the
defended SLO, Week 4 inherits the Week 2 naive 500ms crossing directly as its
reference. A 2s headline would have forced a "but the real SLO is 500ms" recompute
later. That seam is removed.

---

## 3. Load generator design (LOCKED — mechanism and both calibrated values)

Fully specified. Both calibrated values it once carried are resolved: the
**concurrency cap (§3.3) = 3000** and the **offered-vs-achieved band (§2.5) =
±5%**, each from a named mock-based source (§8). Three generators:
`loadgen/steady.py`, `loadgen/poisson.py`, `loadgen/adversarial.py`.

*(The cap lives in §3.3. An earlier version of this line cross-referenced it as
§3.2, which is the seed→schedule mapping.)*

### 3.1 Open-loop core (LOCKED)

- **Open-loop scheduler.** The arrival scheduler fires sends at scheduled times;
  **request completion never gates the next send.** A closed-loop generator
  (send → wait → send) lets server latency feed back into arrival timing, so it
  backs off exactly at the breach — and therefore *cannot observe the breach*.
  Open-loop is the only design that can push the system past its knee.
- **Raw log schema: 5 fields + status.** `request_id`, `send_time`, `close_time`,
  `prompt_id`, `prompt_len`, **`status` ∈ {`sent`, `shed`, `errored`}**. Achieved
  RPS counts `sent`. Shed count reported alongside.
  - **Provenance — deliberate expansion of the Week 1-locked schema.** The Week 1
    handoff specified 5 fields. Open-loop generation made shed/errored a
    first-class *outcome* rather than an error case, so the schema gained a status
    field. This is a justified expansion with a named cause, not schema drift.
- **Companion TTFT/TPOT sidecar — a second file, NOT more raw-log fields.** The
  schema above is complete and closed as written; the sidecar sits beside it. Per
  point the loadgen emits `<tag>.raw_log.jsonl` (this schema, unchanged) *and*
  `<tag>.samples.jsonl` — one row per **issued** request (`sent` or `errored`; a
  `shed` request never opened a stream and has no sample), carrying `request_id`,
  `send_time`, `ttft_ms`, `tpot_samples_ms`, `content_chunk_count`, `error`. The
  two join on `request_id`, and the sidecar repeats `send_time` in the same
  t_start-relative basis so the time-based warmup filter (§2.4) needs no join.
  - **Why a separate file — read this before proposing TTFT columns.**
    Nothing in the six fields above is a first-token time: `close_time` bounds the
    *whole* stream. So the breach metric (§2.6 — p99 TTFT) and §6.3's per-request
    TTFT-vs-wall-clock transient data cannot come from the raw log, while §6.3's
    per-point percentiles need both files. Adding TTFT columns to the raw log
    would have been a *second* expansion of a locked schema; adding a companion
    file keeps the lock intact and costs nothing. **A reader who finds the raw log
    alone insufficient for a TTFT number has not found a contradiction — they have
    found this bullet's reason for existing.**
  - Written per row and flushed, same durable-on-produce discipline as the raw log
    (§6.3). Mechanism: `loadgen/log.py` (`RunLogger` / `SampleLogger`);
    per-point metrics computed from the pair by `metrics/point.py`.
- **ShareGPT corpus** for request content; `prompt_len` is **char count for now**,
  revisited as token count in **Week 3** for KV-cache math (deferred, do not change
  in Week 2).

### 3.2 Seed → schedule mapping (LOCKED)

The Poisson headline's reproducibility rides on this. The failure mode it avoids:
lazily drawing arrival gaps inline lets the arrival RNG interleave with prompt
selection, so draw order becomes runtime-timing-dependent and the "deterministic"
schedule silently isn't.

- **Pre-materialize the entire arrival schedule up front**, from a dedicated
  `arrival_rng`, before any sending starts. The send loop reads the list and does
  **zero RNG work**.
- **Independent RNG streams:** `arrival_rng` and `corpus_rng`, derived from one
  master seed via independent sub-streams (`SeedSequence.spawn()` or equivalent),
  so arrival timing and prompt selection never interleave.
- **Poisson:** exponential inter-arrival gaps at λ = target RPS, cumulative-summed
  to absolute offsets. **Steady:** constant 1/RPS gaps, no RNG (trivially
  reproducible — part of why steady is the legible reference).
- **One continuous schedule** covers warmup + measurement window; warmup is the
  first N seconds, discarded **metrics-side by timestamp** (§2.4). The schedule
  does not know about warmup; the metrics filter does. Warmup load is therefore
  statistically identical to measured load.
- Schedule materialized as **`(scheduled_offset, prompt_id)` pairs**, written to
  the log **before** sending begins — the schedule *is* the "logged as scheduled"
  artifact, and is inspectable/validatable offline before any GPU spend.

**Schedule provenance header (LOCKED):** logged alongside the schedule — master
seed, **derived-RNG scheme** (how sub-streams are spawned, so the derivation is
reconstructable), target RPS, arrival process, schedule-generation version/config.

- **Provenance — the RNG scheme is part of the reproducibility contract, not just
  metadata.** If the sub-stream derivation later changes (e.g. spawn order, or
  which child is arrival vs corpus), the *same master seed produces a different
  schedule*. The version field lets a replay know "seed 42 *under generation-scheme
  vN*" and detect when an archived schedule predates a scheme change — same
  discipline as the Week 1 golden-fixture version tag.

### 3.3 Scheduler mechanism (LOCKED; cap value [CALIBRATE])

- **Absolute-time scheduling:** each send targets `t_start + offset`, self-
  correcting against cumulative drift (a late send does not push later sends late;
  each has an independent absolute target).
- **Fire-and-forget async task spawn:** the scheduler loop sleeps-until the target,
  spawns a send-task, and immediately moves on — it never awaits the send's issue.
  This keeps the scheduler loop lightweight so it can keep up with clustered
  (bursty) targets. The spawned tasks issue concurrently.
- **Per-send scheduling lag is logged** (`scheduled_offset` vs actual `send_time`).
  This is the ground-truth instrument for open-loop fidelity; the aggregate
  offered-vs-achieved gate (§2.5) is a summary of these per-send lags.
- **In-flight *streaming responses* bounded by a concurrency cap; over-cap spawns
  fail fast and record as `shed`, never block.** The cap bounds **open response-
  streams not yet drained** — NOT sends-being-issued. Because an LLM streaming
  response lives for its full duration (TTFT + all TPOT gaps until `[DONE]`), the
  backlog that accumulates under load is slow-draining open streams, and that is
  what must be bounded to keep the client from exhausting sockets/memory and
  *becoming* the bottleneck.
- **Single-process start (approach A).** The scheduling-lag instrument makes
  escalation to multiple client processes **evidence-based** — if lag blows up
  before the breach region, escalate; otherwise A suffices (tens of RPS against a
  single replica is well within one process).

**Concurrency cap value — RESOLVED: 3000** (set 2026-08-17; Hard Stop 3-class
read, deferred there pending Stage A's real RPS range, closed at Block E
pre-flight). Constant: `loadgen/_cli.py: BASELINE_CONCURRENCY_CAP`.

*Provenance for the value.* It clears every concurrency level Block C ever
produced: the uncapped ("natural") sweep peaked at **2380** simultaneous open
streams at 300 offered RPS against the slow mock, and at **651** at 100 RPS —
the closest comparable rate to Stage A's 80 RPS ceiling. 3000 is above the
former and ~4.6× the latter. Stated as the guardrail's own condition (Little's
Law): at Stage A's top offered point the cap cannot bite until *mean* end-to-end
response time exceeds **37.5s** (3000 ÷ 80 RPS) — far beyond any latency at
which the 500ms p99 TTFT breach is still an interesting measurement. It is
therefore provably above offered load through the breach region, per the
requirement below, while still bounding true runaway.

*Verify per point, do not assume:* every point record carries `n_shed_total`
and `provenance.concurrency_cap` (`metrics/point.py`), and
`scripts/compute_point_metrics.py` flags any point with `shed > 0`. A
non-zero shed count at any swept point means the cap bit and that point is
cap-shaped, not server-shaped — the §2.5 instrument-lies failure mode below.

*Operational precondition — file-descriptor headroom.* 3000 concurrent
streams means ~3000 open sockets in the driving process. Linux's default soft
`ulimit -n` is **1024**, well under the cap: the process would fail with
`EMFILE` before the cap could ever engage, and those failures land as
`errored` (a real send that failed), **not** `shed` — silently corrupting both
achieved RPS and the error accounting rather than tripping the shed check
above. Raise it (`ulimit -n 65535`) before driving any point from a Linux
host. This is a precondition of the cap value, not a detail of it.

**Original calibration requirements (unchanged, and what the value above
satisfies):**
- Calibrated against the mock's **slow config** (realistic response duration) —
  NOT the fast config. A fast mock drains streams immediately, in-flight never
  climbs, and the calibrated cap would be meaningless the moment real vLLM
  responses take real time. The slow config is the regime where in-flight actually
  accumulates. (Same slow-config session as the §4 open-loop fidelity test — it
  does double duty.)
- Set **provably above the offered load through the breach region, with headroom**,
  while still catching true runaway.
- **Provenance — the cap is a client-health guardrail, not a workload parameter.**
  It must **never shed within the characterized RPS range** — if it does, the cap
  (not the server) is shaping results, which is exactly the §2.5 instrument-lies
  failure mode. Cap calibration and the §2.5 capability requirement are the **same
  measurement**: can one capped client sustain offered load through the breach
  region without the cap ever biting? If not, that is the evidence-based trigger to
  escalate to multi-process.

### 3.4 Corpus sampling mechanics (LOCKED)

- **Pinned ShareGPT subset — versioned artifact** (e.g.
  `corpus/baseline_prompts.jsonl`), committed with a provenance header: ShareGPT
  source/version/URL, selection seed, filter definition, date. Runs draw from the
  committed file, **never live ShareGPT** — a re-download or version change must
  not silently alter the corpus (same drift discipline as the RNG scheme and the
  golden fixture).
- **Random sample, no length stratification** — preserves the natural length
  distribution locked in §2.2. Stratifying would shape the distribution toward a
  preferred shape rather than measuring the corpus's natural mix.
- **Minimal validity/junk filter allowed, fully documented.** May remove only
  empty/malformed/non-parseable entries (a *validity* predicate). **May NOT remove
  valid prompts to shape the spread** (that is stratification wearing a filter's
  clothes). The filter operates on *validity, not value*; a criterion referencing
  length or content that shifts the distribution of *valid* prompts is forbidden.
  Filter definition + this constraint recorded in the provenance header.
- **With-replacement, i.i.d. draws** via the independent `corpus_rng` — decouples
  subset size from run length and matches the independent-arrivals model. The
  pinned seed + logged histogram make any luck-of-the-draw over-representation
  reproducible and visible.
- **Prompt assignment at schedule-materialization time**, bound into the
  `(scheduled_offset, prompt_id)` schedule (§3.2) — NOT drawn at send time (which
  would reintroduce the interleaving nondeterminism the pre-materialization
  avoids). Replay reproduces timing and prompts identically.
- **Run logs:** committed-corpus filename/version + `corpus_rng` seed derivation +
  realized length histogram, alongside the schedule-provenance header.

---

## 4. Mock validation sequence (LOCKED)

The mock is a **request-pattern oracle, never a latency source.** Its concurrency
bug (deferred from Week 1) must not contaminate GPU conclusions. Every validation
below is a **request-generation** question, squarely inside the mock's trusted
role.

**Doc split (LOCKED):**
- The standing **trusted / not-trusted boundary list** lives in
  `MOCK_TRUST_BOUNDARY.md` (the *principle* — what the mock is ever trusted for).
- The **five validations + pass/fail + negative controls** below live in new
  **`docs/WEEK2_MOCK_VALIDATION.md`** (the *procedure* for Week 2). Principle vs
  procedure, kept separate so the boundary doc isn't overloaded with Week 2
  specifics.

**Boundary recap (full list in `MOCK_TRUST_BOUNDARY.md`):**
- *Trusted:* arrival distribution, achieved RPS / open-loop fidelity, concurrency
  + shedding, corpus sampling, logging/ordering.
- *NOT trusted (GPU only):* concurrent p99 TTFT, queueing behavior, saturation
  behavior.

### The five validations (each with a biting negative control)

A validation that cannot fail proves nothing — every check below names the control
that must bite.

**V1 — Arrival distribution (offline; no sending).** The materialized schedule is a
static artifact, so this is checked by inspecting the generated schedule.
- **Pass:** Poisson inter-arrival gaps at (RPS, seed) fit `Exponential(λ=RPS)`
  (goodness-of-fit, e.g. K-S; at minimum mean gap ≈ 1/λ and shape is not constant).
- **Negative control:** the **steady** schedule must **fail** the exponential fit
  (steady gaps are constant). If both pass, the check is broken.
- **Determinism (asserted here, free):** same seed → byte-identical
  `(offset, prompt_id)` list; different seed → different list.

**V2 — Open-loop fidelity (THE load-bearing check).** Requires driving the mock.
- **Pass:** driven at target RPS against the **slow mock (500ms)**, per-send
  scheduling lag (`scheduled_offset` vs actual `send_time`) stays within band; the
  aggregate is the §2.5 offered-vs-achieved gate.
- **Negative control (the open-loop proof):** **fast-mock and slow-mock achieved
  RPS must be invariant.** If achieved RPS *drops* when switching fast→slow,
  response time is leaking into send timing = hidden closed-loop dependency = the
  open-loop design is compromised. This fast-vs-slow invariance is the single most
  important validation in §4.

**V3 — Concurrency cap.** Against the slow mock, drive in-flight past the cap.
- **Pass:** over-cap sends record `shed` (fail-fast, non-blocking); the scheduler
  keeps firing on schedule for non-shed sends (shedding one does not delay the
  next).
- **Negative control:** below the cap, shed count is **exactly zero**. Any shed
  under the cap = cap logic wrong.
- **Calibration output:** the offered RPS at which shedding *onsets* against the
  slow mock IS the §3.3 cap `[CALIBRATE]` value (the client's healthy ceiling).

**V4 — Corpus faithfulness (offline).** Inspect the schedule's prompt assignments.
- **Pass:** draws come only from the pinned corpus file; with-replacement produces
  expected i.i.d. draw statistics; realized length histogram logged.
- **Negative control:** same `corpus_rng` seed → identical prompt sequence,
  different seed → different. Plus: every drawn prompt passes the junk filter (a
  filtered/empty prompt reaching assignment = filter didn't run).

**V5 — Logging / ordering integrity.** Every downstream number reads the raw log.
- **Pass:** every scheduled send appears once with a status ∈
  {`sent`, `shed`, `errored`}; `scheduled = sent + shed + errored` reconciles;
  `send_time ≥ scheduled_offset` always (late allowed, early impossible).
- **Negative control:** an injected dropped log-write must trip the reconciliation
  check. If `scheduled ≠ sent + shed + errored` doesn't flag it, the check is
  decorative.

### Hard pre-GPU gate (LOCKED)

**All five validations must pass before the GPU meter starts.** Rationale: the one
paid session must test *only* the thing that can't be tested free — does real vLLM
behave like the mock. An unvalidated loadgen makes a bad GPU number ambiguous
(server or driver?); the gate collapses that ambiguity before any spend. This
mirrors how Week 1's faithfulness checks gated its GPU session. The gate is
enforced as a pre-flight checklist item in §6.

---

## 5. Trace capture / deterministic replay (LOCKED)

Replay's job: re-drive a baseline run *exactly* for regression comparison later.
The question it answers in Week 6+ is "same workload against a changed system —
did latency change?" For that to be valid, the workload must be **provably
identical, independent of whether the generator code changed** across weeks.

### Replay source of truth: the materialized schedule artifact (Option M)

Of the two candidate sources — regenerate from the provenance header (seed + scheme
version) vs. re-drive the materialized `(offset, prompt_id)` list — the **frozen
materialized schedule** is the source of truth.

- **Replay re-drives the exact committed `(offset, prompt_id)` list**, independent
  of generator code. This is **immune to RNG-scheme drift**: the schedule is a
  static file, so replaying it in Week 6 yields the identical workload it yielded in
  Week 2 even if the generator was rewritten in between. Any latency delta on replay
  is therefore attributable to the *system* — the entire point of a regression
  comparison.
- Regeneration-from-seed is the *wrong* property for replay's job (it proves
  generation determinism, which V1 already asserts offline) and is fragile across
  code changes. It is **not** the replay path — but the provenance header (§3.2:
  seed, RNG scheme version, RPS, arrival process) is **embedded in the artifact**,
  so regeneration remains possible for *audit*. Drift-immune replay + intact audit
  trail, both.

### Determinism check: workload identity, NOT latency identity

- Re-driving the same schedule artifact reproduces **byte-identical arrivals**
  (send times within the open-loop lag band) and the **identical prompt sequence**.
- **Latencies differ run-to-run** — that is the system's noise, and it is exactly
  what regression comparison measures. The check asserts **workload identity only**;
  asserting latency identity would be wrong.

### Reproducibility contract: schedule + pinned corpus

The schedule references corpus content by `prompt_id`, not by embedding it. So an
identical workload requires the **pinned corpus artifact (§3.4)** to be unchanged
too. Full contract:

> **frozen schedule artifact + pinned corpus artifact (by version) = identical
> workload.**

The schedule records the corpus version it was built against; a replay validates it
is driving that same corpus version, closing the loop against silent divergence from
a mutated corpus.

### Storage

- **Frozen schedule artifacts** live in a versioned location (e.g.
  `benchmarks/schedules/`), each named by its generating parameters and carrying its
  embedded provenance header.
- **Per-run raw logs** (the §3.1 6-field log) are the *record* of a given run/replay,
  stored separately per run.
- Workload (frozen schedule) and record (per-run log) are **never conflated** — the
  schedule is the input, the raw log is the output.

---

## 6. GPU session runbook (LOCKED)

Pre-staged and teardown-disciplined, mirroring the Week 1 close-out runbook. The
GPU is **not** used to figure out the experiment — it executes an already-locked
spec and **collects raw artifacts only**. All analysis (percentiles, breach-RPS
resolution, warmup-N calibration, cap-onset confirmation, `BASELINE.md` authoring)
happens **offline after teardown**. The meter runs to collect, never to analyze or
think.

**Session shape (LOCKED): single continuous session.** Bracket (Stage A) → fine-
sweep (Stage B) → steady reference → adversarial, in one meter run. Standup + model
load is the expensive part; splitting into two sessions would pay it twice.
**Escape hatch:** if Stage A surprises (breach in an unexpected place, or achieved-
RPS diverges badly enough to reconsider the sweep), abort to offline analysis and
resume in a second session rather than improvising on the meter.

**Wall-clock is a sizing note, not a gate.** Record an estimate for planning, but a
clean coarse→fine sweep takes the time it needs. The discipline that matters is
teardown, not shaving minutes. (Week 2 budget line was ~5 hrs on-demand / ~$4.45;
treat as a guide, not a ceiling.)

### 6.1 Pre-flight (all free, before the meter starts)

- **§4 hard gate: all five mock validations green.** The loadgen is proven against
  the mock (arrival shape, open-loop fidelity, cap/shedding, corpus, logging). An
  unvalidated loadgen makes a bad GPU number ambiguous (server or driver?).
- **Quota + billing:** confirm L4 quota live in target region (`us-central1`,
  fallback `us-east4`); pay-as-you-go active; budget alerts at **$10 canary /
  $75 warning / $135 near-cap / $150 hard line** (resolved 2026-08-18 — see the
  note below).

  **Provenance — the alert ladder was changed from $50/$100/$150.** The live
  budgets are a `$150` budget firing at 50/90/100% (= $75/$135/$150) plus a
  separate `$10` canary. The $150 hard line, which is the one that matters, is
  unchanged. The `$10` canary was added because it is the threshold that will
  *actually fire*: a g2-standard-8 + L4 spot runs roughly $0.40–0.50/hr, so a
  single session lands in the $5–15 range and a $50 first-warning would never
  trigger at all — an alert ladder whose lowest rung is above the expected spend
  is decorative. $75/$135 keep the same escalating shape above it. Recorded here
  rather than left as a doc-vs-reality mismatch (`docs/WEEK2_GPU_PREFLIGHT.md`
  §2 carries the live `gcloud` evidence).

  These are a **tripwire, not a stop** — nothing here halts an instance, GCP
  budget evaluation is not real-time, and the alerts are email-only. Verified
  teardown (§6.4, `scripts/gpu_session/teardown_week2.sh`) remains the actual
  control.
- **Launch staged** from `docs/GPU_SESSION_NOTES.md` (working `gcloud` + vLLM
  sequence, environment-specific bugs already worked around).
- **`--max-model-len` sized to actual test traffic** (longest corpus prompt + max
  output tokens), NOT "small enough to boot" as in Week 1's single-request check. A
  sustained load run needs real headroom.
- **Teardown staged and dry-run verified** — know `teardown.sh` targets the right
  instance name/zone. A silent no-op teardown is how a forgotten L4 runs all
  weekend.
- **Stage A schedules pre-generated and committed** (§5 frozen artifacts — they are
  deterministic, so generate offline, commit, and the session just drives them).

### 6.2 Session sequence (meter running)

1. **Stand up** 1× L4 spot, vLLM Llama-3.2-3B-Instruct, wait for healthy `/health`.
2. **Confirm config-only swap holds** — router points at vLLM via `UPSTREAM_BASE_URL`
   only (same as Week 1). Any required code change is a finding; STOP and record it.
3. **Stage A — coarse sweep.** Drive the pre-generated coarse schedules (low anchor
   to capture the unloaded floor, then wide steps up — e.g. ~2–5 RPS anchor, then
   5/10/20/30/40/60/80-ish). **Success criterion = the breach is bracketed:** one
   point clearly under 500ms p99 TTFT and one clearly over. If the whole sweep stays
   under, extend upward *live* (staged, meter running, cheap). If the first real
   load point is already over, add lower points. Success is "breach bracketed," not
   "N points done."
4. **Stage B — fine sweep.** Generate fine schedules *from Stage A's bracket*
   (offline-generatable in seconds mid-session), drive smaller RPS increments
   *between* the bracketing points to resolve breach RPS to step granularity.
5. **Steady reference.** Capture the steady-arrival curve (same loadgen, constant-
   gap schedule) over the same or a subset of points — the legible lower-variance
   reference (§2.1).
6. **Adversarial — LAST.** Run the long-context flood scenario (§2.1, separate from
   the baseline number). **Ordered last deliberately:** it deliberately drives the
   replica toward saturation and may leave KV cache / scheduler degraded; running it
   after the baseline + steady are durably written means a destabilized server
   cannot contaminate the measurements that matter most.

### 6.3 Recording plan (LOCKED — durable-on-produce)

**Every measurement is written to disk the moment it is produced, never buffered in
memory until session end.** A crash at point 5 must not lose points 1–4.

Per RPS point:
- **Frozen schedule artifact** (§5) — committed *before* the point runs (it is an
  input).
- **Raw 6-field log** — streamed to disk *during* the run, per point.
- **Per-point computed metrics** — p50/p95/p99 TTFT + TPOT, achieved RPS, shed
  count, sample count — written immediately after the point's window closes.
- **Transient data** — per-request TTFT vs wall-clock for (at least) the first point,
  logged raw so the warmup **flatten-point** can be found offline to pin the
  `[CALIBRATE]` warmup N (§2.4).

Principle: the session produces **raw durable artifacts**; percentiles, breach
location, warmup-N, and cap-onset confirmation are all computed **offline after
teardown**. Never pay GPU time to analyze.

### 6.4 Teardown (meter stops)

- Run `teardown.sh`. **Verify the instance is actually deleted in the console** — do
  not trust the script's exit code alone.
- Everything after this is local/free: percentile computation, breach-RPS
  resolution, warmup-N calibration, `BASELINE.md` authoring.

### 6.5 What the session already knows (no on-meter improvisation)

The session starts already knowing: the workload (frozen schedules), the RPS points
(Stage A coarse set; Stage B derived from the bracket), warmup/window behavior
(per-point N-second discard, fixed Y window, §2.4), what gets recorded and where
(§6.3), the run-end condition (breach bracketed + fine-resolved + steady + adversarial
done), and teardown. The GPU is not used to design the experiment.

---

## 7. First executable action — Linux spin-disabled calibration (READY)

No further design needed — this is a ready-to-execute task, not an open decision.
Carried forward from Week 1; **first in execution order**; GPU-free; runs in
parallel with loadgen dev; does **not** gate the baseline spec.

**Context:** CI on `ubuntu-latest` showed the mock's structural TTFT offset at
~3ms (vs ~13–15ms on Windows), suggesting the busy-wait spin
(`mock/timing.py: precise_sleep`) may not be needed on Linux — BUT that CI run
still had the spin **enabled**, so it did not test the real question, and was a
single run / single config, not a calibration.

**The check:** sequential noise calibration on Linux, spin **disabled**, repeated
at scale (matching the original calibration rigor — many runs, not one). Do NOT
read the ~3ms CI number as settling this; it is a prior, not an answer.

**Deferred (do not chase as separate bugs):**
- **`prompt_len` units** — char count now; token count in Week 3 for KV-cache math.
- **Machine-drift signal** — mock timing overshoots the 10ms band on the Windows
  dev box; the noise floor is machine-specific. Re-measure on Linux as part of the
  calibration above; not a separate bug.

---

## 8. Open [CALIBRATE] values (Week 2)

**One row remains open: the per-point warmup N, which is resolved from GPU
transient data in Block F by design (§2.4/§6.3) and is not a pre-GPU gap.**
Everything else is resolved with named evidence.

| Value | Status | Source |
|---|---|---|
| Per-point warmup N | **10s placeholder — OPEN BY DESIGN** | Stage A transient plot (TTFT vs wall-clock, find flatten point). Resolved in Block F, post-teardown. Applying the real N is a **re-filter over the committed sidecars, never a GPU re-run**: the warmup filter is metrics-side and time-based (§2.4), so `scripts/compute_point_metrics.py --warmup-n <N>` re-derives every point |
| ~~Measurement window Y~~ | **RESOLVED: 120s** (2026-08-18) | Stage A's lowest offered point is 2 RPS, so the window carries `2 × 120 = 240` scheduled requests — 2.4× the ≥100 achieved-sample floor, with headroom for under-delivery before a point goes tail-invalid. Full reasoning in §2.4 |
| ~~Offered-vs-achieved band~~ | **RESOLVED: ±5%** (2026-08-18) | Block C low-load tracking (`benchmarks/calibration/block_c/calibration_reads.json` → `low_load_tracking`): 0.0% / 0.0% / 0.0% / −0.67% at 0.5/1/2/5 RPS. Deliberately **not** tightened to the measured 0.67% max — the band detects material driver under-delivery, and a band with no headroom would flag healthy points near the breach. Reasoning in §2.5. Constant: `metrics/point.py: DEFAULT_BAND_PCT` |
| ~~Concurrency cap value~~ | **RESOLVED: 3000** (2026-08-17) | Set above Block C's uncapped peak concurrency (2380 @ 300 RPS; 651 @ 100 RPS) — cannot bite below a 37.5s mean response time at Stage A's 80 RPS ceiling. Full provenance + the `ulimit -n` precondition in §3.3. Constant: `loadgen/_cli.py: BASELINE_CONCURRENCY_CAP` |
| ~~Loadgen capability target~~ | **RESOLVED with the cap** (2026-08-17) | Same measurement (see note below). Verified per point rather than assumed: `shed > 0` at any swept point means the cap bit and that point is cap-shaped — flagged automatically by `scripts/compute_point_metrics.py` |
| Loadgen scheduler spin margin (`loadgen/scheduler.py:SPIN_MARGIN_S`) | 5ms | **Windows-tuned, not yet Linux-calibrated.** Carried forward from Hard Stop 2 review (2026-08-16): same class of A/B as Block 0's mock-timing spin (`mock/timing.py:SPIN_MARGIN_S`) — run it on the Linux e2 VM, same session if convenient. Do not ship the Windows-tuned 5ms onto Linux vLLM runs unverified. |

Note: the concurrency-cap value and the loadgen-capability target are the **same
measurement** (§3.3) — "can one capped client sustain offered load through the
breach region without shedding." They are listed as two rows only because they are
referenced from two sections.

---

## 9. What remains to close out Week 2 planning

Locked: baseline semantics (§2, all seven knobs), loadgen design (§3, mechanism
and both calibrated values), mock validation (§4, five validations + hard pre-GPU
gate), trace/replay (§5, Option M frozen-schedule + schedule-plus-corpus
contract), and the GPU session runbook (§6, single continuous session,
durable-on-produce recording, adversarial-last).

**All design sections are locked, and every `[CALIBRATE]` value is resolved
except the one that is deliberately post-GPU:**

| Value | State |
|---|---|
| Concurrency cap | **3000** — resolved 2026-08-17 from Block C's uncapped concurrency sweep (§3.3) |
| Offered-vs-achieved band | **±5%** — resolved 2026-08-18 from Block C's low-load tracking (§2.5) |
| Measurement window Y | **120s** — resolved 2026-08-18 against the ≥100-sample floor at Stage A's 2 RPS anchor (§2.4) |
| Mock timing spin (Block 0, §7) | **Resolved 2026-08-16** — Windows-only fix; A/B in `benchmarks/calibration/noise_floor/`, read-up in `MOCK_TRUST_BOUNDARY.md` |
| Loadgen scheduler spin | **Resolved 2026-08-18** — platform-specific defaults in `loadgen/scheduler.py`; A/B in `benchmarks/calibration/scheduler_spin/`, read-up in `BENCHMARKS.md` |
| **Per-point warmup N** | **OPEN BY DESIGN** — offline from the §6.3 transient data (TTFT vs wall-clock flatten-point), resolved in Block F. Applying it is a metrics-side re-filter over the committed sidecars, never a GPU re-run (§2.4) |

Nothing further to design. Execution order: §7 Linux calibration → loadgen build →
§4 mock validations (the gate) → §6 GPU session → offline analysis → `BASELINE.md`.

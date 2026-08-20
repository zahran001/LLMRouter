# Week 2 — Load Generation & Baseline: Implementation Plan

> **STATUS: AUTHORITATIVE — WEEK 2**
>
> Role: the Week 2 decision record — what is measured, what is locked, and why.
>
> Current document authority: experiment semantics `WEEK2_PLAN.md` · execution
> and gating `WEEK2_EXECUTION.md` · GPU commands `docs/WEEK2_GPU_SESSION_2_PLAN.md`.
> Index: `docs/WEEK2_DOC_INDEX.md`. If these appear to conflict, **HALT and surface the
> conflict** — do not reconcile silently.

Week 1 is closed: transparent router merged to `main`, measurement pipeline
locked and calibrated, mock→vLLM faithfulness confirmed on real GPU. This
document is the authoritative plan for Week 2. It follows the same discipline
as `WEEK1_MEASUREMENT_SPEC.md`: every boundary that can be fixed on paper is
fixed here and marked **LOCKED**; every value that needs empirical calibration
is marked **[CALIBRATE]** with a named source; every expansion of a prior
artifact carries a provenance note.

> **⚠ Read §10 first (added 2026-08-19).** The first GPU session falsified
> several of this document's statistical and workload assumptions. §10 records
> every supersession with its evidence; the superseded sections carry pointers
> and keep their original text. Nothing in §10 reopens the infrastructure or the
> 500ms SLO — see §10.9 for the explicit list of what did *not* change.

**Status of this document: every design section (§2–§7) is LOCKED and
implemented, and §6 is superseded for session #2 — see §10 and §11.** See §9 for
the closeout. The `[CALIBRATE]` values are tracked in §8; all are resolved,
including the per-point warmup N, which is now a **frozen 60-second boundary
materialized into the exact-N schedules and validated forward in Tier A**
(§11.4). It is no longer an open value read off a transient after the fact.

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

### 2.2 Prompt distribution (LOCKED — **headline SUPERSEDED 2026-08-19, see §10.1**)

> **Read §10.1 before implementing this section.** The first GPU session
> falsified the load-bearing claim below — that feeding every RPS point the same
> seeded distribution holds the prompt-length contribution constant. It holds the
> *population* constant and lets the *realized* tail move, which is what a
> small-sample p99 actually reads. The headline workload is now a controlled
> stratified canonical multiset; the natural spread described here survives as
> the **secondary** workload. The text is kept intact because the reasoning it
> records is why the confound was invisible.

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

### 2.3 RPS sweep methodology (LOCKED — **SUPERSEDED for session #2 2026-08-19, see §11.5 and the session #2 runbook**)

> **Read §11.5 before implementing this section.** The two-stage coarse→fine
> sweep below is session #1's discovery procedure, and it is superseded. Session
> #2 discovers the crossing with a **diagnostic Tier A scout** at λ = 1/2/4/8
> (N = 500, never classified), pre-authorized fallback λ = 0.5 or 16 **and no
> other**, then drives **Tier B** at three λ × three repeats × N = 4,000. The
> scout ladder is bounded in advance precisely because the sweep below was not:
> its "extend the range live" escape valve is what the no-improvisation matrix
> now forbids. Operational form: `docs/WEEK2_GPU_SESSION_2_PLAN.md`.

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

### 2.4 Warmup + measurement window (LOCKED; N [CALIBRATE] — **headline window and sample floor SUPERSEDED 2026-08-19, see §10.2 and §10.3**)

> **Read §10.2/§10.3 before implementing this section.** Two of its three parts
> are superseded for the headline: the fixed `Y = 120s` window (replaced by an
> exact post-warmup arrival count) and the `≥100 achieved samples` tail-validity
> floor (replaced by the R3 evidence policy). The **time-based per-point warmup**
> is *not* superseded and carries forward unchanged — including into the
> redesigned repeat boundaries.

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

### 2.5 Offered-vs-achieved validity gate (LOCKED — **semantics SUPERSEDED 2026-08-19, see §10.4**)

> **Read §10.4 before implementing this section.** The gate's *purpose* — catch
> the driver failing to deliver its schedule — is unchanged and still correct.
> What changed is what it compares against: measuring achieved sends against
> `λ × window` folds finite-Poisson realization variance into a driver-fidelity
> verdict, which is how both first-session low-RPS points came to be `flagged`
> for a stochastic property of their own schedules.

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

### 2.6 Breach definition (LOCKED — **percentile definition and point validity EXTENDED 2026-08-19, see §10.5 and §10.6**)

> **Read §10.5/§10.6 before implementing this section.** The metric (p99 TTFT),
> the threshold (500ms) and the secondary line (2s) are **unchanged and remain
> locked**. Two things this section left implicit are now explicit: *which* p99
> (nearest-rank, because on a small near-boundary sample the interpolation
> convention alone flips the verdict), and what happens when a point's TTFT
> sample is materially censored by timeouts (it cannot report an ordinary p99 at
> all). "Lowest swept RPS whose p99 ≥ 500ms" also becomes a repeat-level verdict
> with four states rather than a single-run boolean.

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
- **Breach RPS = the lowest swept RPS whose p99 TTFT ≥ 500ms**, resolved to step
  granularity. *(Originally "full-window (Y-second) p99, resolved by the Stage B
  fine sweep" — the **basis** is superseded by §10.2: the redesigned headline
  reads exactly N post-warmup arrivals, not a fixed window, and resolves the
  crossing with three unanimous repeats rather than a fine sweep. The 500ms
  threshold and the "lowest swept RPS" rule are unchanged.)*
- **Sustained-ness is inherent to the measurement basis, not a separate rule:** a
  p99 over N = 4,000 post-warmup arrivals cannot be moved by one transient spike;
  sustained tail elevation is required to move it. *(Superseded wording: the same
  argument was originally made about a Y=120s window — see §10.2 for why the
  window was replaced, and §10.3 for why sample count, not elapsed time, is what
  actually protects a p99.)*
- **Unloaded TTFT floor is characterized first** (session #2 records it in Tier
  A, before the scout; session #1 recorded it in Stage A). This tells you how
  large a blowup 500ms represents and whether the knee is sharp and close or
  shallow and far — informing which three λ Tier B spends its repeats on.

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
read, deferred there pending session #1's Stage A RPS range, closed at Block E
pre-flight). Constant: `loadgen/_cli.py: BASELINE_CONCURRENCY_CAP`. The value
carries forward to session #2 unchanged — it was set above a ceiling far higher
than any λ the scout ladder reaches (§10.9).

*Provenance for the value, from session #1's sweep design.* It clears every
concurrency level Block C ever produced: the uncapped ("natural") sweep peaked
at **2380** simultaneous open streams at 300 offered RPS against the slow mock,
and at **651** at 100 RPS — the closest comparable rate to Stage A's 80 RPS
ceiling. 3000 is above the former and ~4.6× the latter. Stated as the
guardrail's own condition (Little's Law): at Stage A's top offered point the
cap cannot bite until *mean* end-to-end response time exceeds **37.5s**
(3000 ÷ 80 RPS) — far beyond any latency at
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

### 3.4 Corpus sampling mechanics (LOCKED — **headline sampling SUPERSEDED 2026-08-19, see §10.1**)

> **Read §10.1 before implementing this section.** Its "random sample, no length
> stratification" and "with-replacement i.i.d. draws" rules are superseded **for
> the headline workload only** and survive verbatim for the secondary
> natural-random workload. Everything else here — the pinned committed corpus,
> the validity-only junk filter, never drawing from live ShareGPT,
> prompt assignment at materialization time, and the logged realized histogram —
> is **unchanged and still binding**.



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

## 6. GPU session runbook — SUPERSEDED (session #1's runbook, kept as the record)

> **STATUS: SUPERSEDED — DO NOT EXECUTE.** This section is the runbook GPU
> session #1 ran on 2026-08-18. The session it drove falsified its own design
> (§10), and it is preserved here as provenance, not as instructions. It is not
> the current runbook and no part of it may drive session #2.
>
> **The one current GPU runbook is `docs/WEEK2_GPU_SESSION_2_PLAN.md`**, with
> its policy in §11 and `benchmarks/workloads/week2_headline/repeat_policy.json`.
>
> What changed, concretely: Stage A/B coarse→fine became a bounded Tier A scout
> plus Tier B repeats (§11.5); "extend upward live" and mid-session schedule
> generation are now forbidden by the no-improvisation matrix; the warmup is a
> frozen 60s boundary rather than a value read off the transient afterwards
> (§11.4). What carried forward unchanged is listed in §10.9 — the meter
> collects and never analyzes, durable-on-produce recording, adversarial last,
> and verified teardown.

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

### 6.1 Pre-flight (SUPERSEDED — session #1; current: `docs/WEEK2_GPU_SESSION_2_PREFLIGHT.md`)

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
  rather than left as a doc-vs-reality mismatch (session #1's pre-flight,
  removed 2026-08-20; in git history at 39ed3f1,
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

### 6.2 Session sequence (SUPERSEDED — session #1's Stage A/B sweep; current: Tier A/Tier B, §11.5)

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

### 6.3 Recording plan (SUPERSEDED as a runbook — session #1; the durable-on-produce principle carries forward, §10.9)

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

### 6.4 Teardown (SUPERSEDED — session #1; current: `scripts/gpu_session/teardown_week2.sh`)

- Run `teardown.sh`. **Verify the instance is actually deleted in the console** — do
  not trust the script's exit code alone.
- Everything after this is local/free: percentile computation, breach-RPS
  resolution, warmup-N calibration, `BASELINE.md` authoring.

### 6.5 What the session already knew (SUPERSEDED — session #1; session #2's equivalent is the no-improvisation matrix)

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

**No rows remain open.** Every value is resolved with named evidence,
including the per-point warmup N — which is no longer a value read off a
transient after the run, but a **frozen 60-second boundary materialized into
the exact-N schedules and validated forward in Tier A** (§11.4). *(This preamble
previously read "one row remains open: the per-point warmup N, resolved from GPU
transient data in Block F by design." That was true under the superseded
fixed-duration design and is not true under lock 4A.)*

| Value | Status | Source |
|---|---|---|
| Per-point warmup N | **RESOLVED STRUCTURALLY: 60s frozen boundary** (2026-08-19, lock 4A) | Not a value read off a plot after the run. The 60s boundary is materialized into the exact-N schedules — N arrivals land at or after it — and is **validated forward** against session #2's Tier A transient at Hard Stop GPU-1. If 60s proves insufficient: STOP, regenerate the schedules offline at a larger boundary, and return to pre-GPU approval. Post-hoc re-filtering of headline sidecars is not a valid resolution and `metrics/headline_point.py` refuses it (§11.4) |
| ~~Measurement window Y~~ | **RESOLVED: 120s** (2026-08-18) — **SUPERSEDED for the headline 2026-08-19 (§10.2)** | Stage A's lowest offered point is 2 RPS, so the window carries `2 × 120 = 240` scheduled requests — 2.4× the ≥100 achieved-sample floor, with headroom for under-delivery before a point goes tail-invalid. Full reasoning in §2.4. *Superseded because its justification rested on the ≥100 floor, which the first session falsified, and because a fixed duration is the mechanism of the prompt-tail confound. Headline basis is now `N = 4,000` exact post-warmup scheduled arrivals* |
| **Canonical workload `k` / `L` / `N`** | **RESOLVED: k6 (0/50/90/95/99/99.5/100), L = q99 = 11,471 chars, N = 4,000** (2026-08-19) | Read off the R3 evidence package by the human at Hard Stop R3: `benchmarks/calibration/week2_redesign/R3_EVIDENCE_PACKAGE.md`. `N` from the ≤5% classification-flip criterion on the conservative 2-RPS bootstrap source; `L` from the measured unloaded TTFT-vs-length relation (§10.1/§10.3) |
| **Evidence ceiling `N_max`** | **RESOLVED: 5,000** (2026-08-19) | Structural: the pinned corpus holds 5,000 prompts, so that is the largest canonical multiset with no prompt reuse. Not an escalation target (§10.3) |
| ~~Offered-vs-achieved band~~ | **RESOLVED: ±5%** (2026-08-18) | Block C low-load tracking (`benchmarks/calibration/block_c/calibration_reads.json` → `low_load_tracking`): 0.0% / 0.0% / 0.0% / −0.67% at 0.5/1/2/5 RPS. Deliberately **not** tightened to the measured 0.67% max — the band detects material driver under-delivery, and a band with no headroom would flag healthy points near the breach. Reasoning in §2.5. Constant: `metrics/point.py: DEFAULT_BAND_PCT` |
| ~~Concurrency cap value~~ | **RESOLVED: 3000** (2026-08-17) | Set above Block C's uncapped peak concurrency (2380 @ 300 RPS; 651 @ 100 RPS) — cannot bite below a 37.5s mean response time at session #1's Stage A 80 RPS ceiling, far above any λ the session #2 scout reaches. Full provenance + the `ulimit -n` precondition in §3.3. Constant: `loadgen/_cli.py: BASELINE_CONCURRENCY_CAP` |
| ~~Loadgen capability target~~ | **RESOLVED with the cap** (2026-08-17) | Same measurement (see note below). Verified per point rather than assumed: `shed > 0` at any swept point means the cap bit and that point is cap-shaped — flagged automatically by `scripts/compute_point_metrics.py` |
| Loadgen scheduler spin margin (`loadgen/scheduler.py:SPIN_MARGIN_S`) | **RESOLVED: platform-dispatched — Linux 0ms, Windows 5ms** (2026-08-18) | A/B run on a real Linux VM (`benchmarks/calibration/scheduler_spin/scheduler_spin_linux_ab.json`: kernel `6.8.0-1066-gcp`, arms 0ms vs 5ms, 20 and 80 RPS, 5 repeats each). Constants: `LINUX_SPIN_MARGIN_S` / `WINDOWS_SPIN_MARGIN_S`, selected by platform, overridable via `LOADGEN_SPIN_MARGIN_S`. Session #2 drives on-instance Linux, so the effective value is **0ms**. Read-up in `BENCHMARKS.md` |

Note: the concurrency-cap value and the loadgen-capability target are the **same
measurement** (§3.3) — "can one capped client sustain offered load through the
breach region without shedding." They are listed as two rows only because they are
referenced from two sections.

---

## 9. What remains to close out Week 2 planning

Locked: baseline semantics (§2, all seven knobs), loadgen design (§3, mechanism
and both calibrated values), mock validation (§4, five validations + hard pre-GPU
gate), trace/replay (§5, Option M frozen-schedule + schedule-plus-corpus
contract), and session #1's GPU runbook (§6 — superseded, single continuous session,
durable-on-produce recording, adversarial-last).

**All design sections are locked, and every `[CALIBRATE]` value is resolved.**
*(Superseded wording, kept as provenance: this line previously read "…except
the one that is deliberately post-GPU", meaning the warmup N. Lock 4A closed
that — the boundary is frozen into the schedules, not resolved afterwards,
§11.4.)*

| Value | State |
|---|---|
| Concurrency cap | **3000** — resolved 2026-08-17 from Block C's uncapped concurrency sweep (§3.3) |
| Offered-vs-achieved band | **±5%** — resolved 2026-08-18 from Block C's low-load tracking (§2.5) |
| Measurement window Y | **120s** — resolved 2026-08-18 (§2.4); **superseded for the headline 2026-08-19 by `N = 4,000` exact post-warmup scheduled arrivals** (§10.2) |
| Canonical workload k / L / N | **k6 / q99 = 11,471 chars / 4,000** — resolved 2026-08-19 at Hard Stop R3 (§10.1, §10.3) |
| Evidence ceiling N_max | **5,000** — structural corpus-cardinality ceiling, resolved 2026-08-19 (§10.3) |
| Headline percentile definition | **nearest-rank** — locked 2026-08-19; interpolation convention alone flipped the near-boundary verdict (§10.5) |
| Headline prefix-cache policy | **disabled, preflight-enforced** — locked 2026-08-19 (§10.8) |
| Mock timing spin (Block 0, §7) | **Resolved 2026-08-16** — Windows-only fix; A/B in `benchmarks/calibration/noise_floor/`, read-up in `MOCK_TRUST_BOUNDARY.md` |
| Loadgen scheduler spin | **Resolved 2026-08-18** — platform-specific defaults in `loadgen/scheduler.py`; A/B in `benchmarks/calibration/scheduler_spin/`, read-up in `BENCHMARKS.md` |
| **Per-point warmup N** | **RESOLVED: 60s frozen boundary** — materialized into the exact-N schedules and validated forward in Tier A. Post-hoc re-filtering of headline sidecars is not valid and is refused in code (§11.4) |

Nothing further to design. Execution order as originally written: §7 Linux
calibration → loadgen build → §4 mock validations (the gate) → §6 GPU session →
offline analysis → `BASELINE.md`. **The live order is now
`WEEK2_EXECUTION.md`'s redesign arc** — R0→R11, Hard Stop R-DOC, Hard Stop
R-PREGPU, Block E2 (GPU session #2, run from
`docs/WEEK2_GPU_SESSION_2_PLAN.md`), then Block F.

> *Historical note (2026-08-19).* "Nothing further to design" was true of the
> plan as written and false of the experiment. The first GPU session ran that
> design and falsified three of its statistical assumptions; §10 records what
> replaced them. The sentence is kept because a plan that believed itself
> finished, and was not, is part of this document's own provenance — the same
> reason the stale §3–§7 preamble note above was kept rather than deleted.

---

## 10. Redesign supersessions — falsification-driven (2026-08-19)

The first real GPU session ran on 2026-08-18. It did **not** invalidate the load
generator, the replay model, the GPU plumbing, the open-loop architecture, or the
500ms p99 TTFT objective — all of those worked. It falsified the **statistical
and workload assumptions** underneath the breach experiment, and produced **no
defensible breach RPS**.

Full narrative: `docs/WEEK2_GPU_SESSION_FINDINGS.md`. Calibration evidence:
`benchmarks/calibration/week2_redesign/R3_EVIDENCE_PACKAGE.md`. Session
artifacts, promoted as diagnostic evidence:
`benchmarks/evidence/week2/first_session/`.

**Scope rule for this section.** Every supersession below applies to the
**controlled headline workload**. The natural-random **secondary** workload
(§10.7) keeps the original sampling rules deliberately, because its job is to
show that the knee survives unconstrained traffic. Where a rule is unchanged,
this section says so rather than staying silent — an unlisted rule is still
binding.

### 10.1 — Prompt distribution and corpus sampling (supersedes §2.2, §3.4 for the headline)

**Was:**

```text
natural ShareGPT random draws
no length stratification
with-replacement i.i.d. draws
same seeded population distribution holds prompt cost fixed
```

**Falsified by:** a fixed 120s window makes the number of requests a function of
λ, so each RPS point drew a different number of prompts and therefore a different
*realized* tail. Measured across the Stage A schedules: 1.0 RPS drew ~116
requests with **zero** prompts over 10k chars; 10 RPS drew ~1316 with
**fourteen**. The population was constant; the empirical tail — the only part a
p99 reads — was not. At 2 RPS, excluding essentially one extreme prompt moved p99
from ~552.9ms to ~434.8ms, which **flips the breach verdict**.

A second finding compounds it. Because every Stage A schedule shared one master
seed, the shorter schedules are strict *prefixes* of the longer ones, and vLLM
ran with `enable_prefix_caching=True` (a default, never a decision). Exact prompt
replay is therefore not free: the 1.5-RPS point, driven last, served a
14,960-char prompt in **103.9ms** that cost **523.3ms** at concurrency 1. Load
cannot make prefill five times faster; cache state was the missing variable. See
§10.8.

**Now, for the headline:**

```text
controlled stratified canonical ShareGPT multiset
  k = 6 strata at corpus quantiles 0/50/90/95/99/99.5/100
  L = tail boundary at corpus q99 = 11,471 chars
  N = 4,000 unique prompt IDs, selected WITHOUT replacement
  membership frozen once, identical across every RPS point and every repeat
```

Allocation is **proportional to each stratum's natural population share**, so the
canonical multiset reproduces the corpus's natural shape *deterministically*
instead of approximately. This is controlled representative tail coverage, not
tail inflation — and it serves §3.4's original stated intent ("measuring the
corpus's natural mix") more faithfully than a random draw did, because the mix is
now exact rather than sampled.

`L = q99` is chosen on measured grounds, not roundness: a q99-length prompt costs
~370ms of TTFT **with no load at all**, i.e. ~74% of the SLO, so it is where
prompt length starts deciding the verdict. Prompt length alone explains 91% of
unloaded TTFT variance (`benchmarks/calibration/week2_redesign/prompt_cost_analysis.json`).

**Unchanged and still binding from §3.4:** pinned committed corpus, never live
ShareGPT, validity-only junk filter, prompt assignment at schedule-materialization
time, logged realized length histogram, independent arrival/corpus RNG streams.

### 10.2 — Headline measurement basis (supersedes the `Y = 120s` window in §2.4)

**Was:** `Y = 120s` fixed measurement window per point, justified by clearing the
≥100-sample floor at Stage A's 2 RPS anchor.

**Falsified by:** the justification depended on the ≥100 rule (§10.3), and the
fixed window is the direct mechanism of the §10.1 tail confound — holding
*duration* fixed is what makes *count* vary with λ.

**Now:**

```text
N = exactly 4,000 post-warmup SCHEDULED arrivals per run
schedule duration = the stochastic outcome of the frozen Poisson realization
```

`N` is a **schedule-generation constraint enforced offline, never a runtime stop
condition.** Runtime loads the frozen schedule and drives every scheduled
arrival, stopping only when issuance is exhausted. Completions, TTFT
observations, successful-sample count, errors, censoring rate and current p99 may
all change a point's *measurement validity*; none of them may change the
*offered workload*. A build that stops after N completions is closed-loop and
must fail its negative control.

`N / λ` is the expected duration and must not be used as the runtime duration —
using it would reintroduce exactly the finite-Poisson count variance that fixing
`N` exists to remove.

**Unchanged from §2.4:** warmup remains per-point and **time-based**, applied
metrics-side by send timestamp. Warmup traffic is excluded from `N`, comes from
the pinned corpus with recorded derived-RNG provenance, and is fully
pre-materialized. The warmup value itself remains `[CALIBRATE]`, now resolved
from the *second* session's transient data.

`Y = 120s` remains documented for the historical first-session artifacts and may
be used for secondary/legacy comparisons. It is no longer the headline validity
basis.

### 10.3 — Tail validity (supersedes `n >= 100` in §2.4/§8)

**Was:** report a point's tail percentile once `achieved_RPS × window ≥ 100`.

**Falsified by:** the rule makes a p99 *computable*; it does not make it
*reliable* on a heavy-tailed workload. A nonparametric bootstrap over the
first session's own 2-RPS TTFT array (n=225, the near-boundary point) measured:

| candidate N | p99 median | 95% interval | classification flip rate |
|---:|---:|---|---:|
| 250 | 495.0ms | [366.0, 656.8] | **51.8%** |
| 1,000 | 552.9ms | [421.7, 574.8] | 22.1% |
| 2,500 | 552.9ms | [434.8, 574.8] | 8.0% |
| 4,000 | 552.9ms | [436.0, 574.8] | 3.0% |
| 7,500 | 552.9ms | [552.9, 574.8] | 0.6% |

At the sample size the session actually had, the point flipped its own
under/over verdict in **roughly half** of resamples. `n ≥ 100` cannot tell that
apart from a measurement.

**Now:**

- `N = 4,000` per run — the smallest grid candidate reaching a ≤5% per-run flip
  rate on the conservative source. At N=4,000 the empirical top 1% carries ~40
  observations rather than ~2.
- `N` is a **run-sizing calibration, not a repeatability proof.** The bootstrap
  cannot invent tail mass the source never observed, and concurrent request
  latencies are not iid, so it is a lower bound on real variability.
- The final UNDER/OVER/UNCERTAIN verdict comes from **independent GPU repeats**
  (new membership-identical, seed-independent runs), never from bootstrap slices
  of one run and never from blocks of one continuous run.
- `N_max = 5,000` is a **structural** evidence ceiling: the pinned corpus holds
  5,000 prompts, so that is the largest canonical multiset selectable without
  repeating a prompt — and repeating prompts is not neutral on a prefix-caching
  server (§10.8). A ≤1% flip rate would need N≈7,500, **above the ceiling and
  therefore unreachable with this corpus.** Interval-valued breach reporting is
  consequently a live possible result, not a theoretical fallback.

*Provenance for `[CALIBRATE]` bookkeeping:* the `Measurement window Y` and
`≥100 samples` rows in §8 and §9 are superseded for the headline by this section.
`N = 4,000`, `N_max = 5,000`, `k`, and `L` are new locked values, read off the R3
evidence by the human at Hard Stop R3 — the same discipline as every other
calibrated value in this document.

### 10.4 — Offered-vs-achieved semantics (supersedes §2.5's comparison basis)

**Was:** achieved sends within the window compared against offered λ; beyond ±5%
the point is flagged and plotted at achieved (Option Y).

**Falsified by:** a materialized finite-Poisson schedule does not contain exactly
`λ × duration` arrivals, and it is not supposed to. The 2-RPS schedule
materialized 248 arrivals over 130s and the point was flagged at −6.25%; the
1.5-RPS point at −7.8%. Both were flagged for a stochastic property of their own
frozen schedules, not for anything the driver did.

**Now, three quantities recorded separately:**

```text
nominal_lambda_rps          workload parameter and headline x-axis
materialized_schedule_rps   the finite Poisson realization the driver was handed
actual_send_rps             what the driver actually issued
```

- **Driver fidelity** compares actual sends against the **materialized
  schedule**. This is the gate; it still fails loudly.
- **`nominal_realization_delta_pct`** — materialized vs nominal λ — is
  descriptive stochastic metadata and **must never fail the driver**.
- The ±5% band and per-send scheduling-lag instrumentation are **unchanged**;
  only the denominator of the fidelity comparison changes.
- Option Y's plot-at-achieved rule is retired for the headline: the x-axis is
  nominal λ, which is now a well-defined workload parameter rather than a target
  the schedule may miss.

**The legacy `flagged: true` records are not rewritten.** They are correct under
the semantics of their own time and are pinned as such.

### 10.5 — Percentile definition (makes §2.6 explicit; new lock)

The first session's artifacts contain **two** percentile conventions, and on the
near-boundary point the choice alone decides the verdict. Same 225 samples:

| method | p99 | verdict |
|---|---:|---|
| nearest-rank | 552.9ms | OVER |
| linear (numpy default) | 524.6ms | OVER |
| midpoint | 493.9ms | **UNDER** |
| lower | 434.8ms | **UNDER** |

**Now — locked for all redesigned measurements:**

```text
samples = sorted(valid_ttft_samples)
rank    = ceil(0.99 * n)      # one-indexed
p99     = samples[rank - 1]
```

Nearest-rank, from **one shared implementation** used by both the live session
path and offline recomputation, with the method and its version persisted in
point provenance. Library interpolation defaults must not be inherited
implicitly. Nearest-rank is chosen because it returns an **actually observed
latency** rather than an interpolation between two of them — at the tail, where
the neighbouring order statistics are far apart, the interpolated value is a
number no request ever experienced.

**Historical metrics are not recomputed under this convention.** The Stage A
records stay linear, the unloaded-floor record stays nearest-rank, and readers
distinguish them by explicit provenance version — never by assuming.

### 10.6 — Censoring-aware point validity (extends §2.6)

**Falsified by:** at 10/20/30 RPS the 60s client timeout removed 33%/70%/81% of
requests from the TTFT sample, and the survivors' p99 clustered near 60s. The
existing validity gate blessed those points because enough *surviving* samples
remained. A survivor-only percentile at a materially censored point is not a
latency measurement.

**Now — four point states:** `UNDER`, `OVER`, `UNCERTAIN`, `CENSORED`.

```text
TTFT censoring rate > 5%  ->  CENSORED, ordinary p99 verdict suppressed
0 < rate <= 5%            ->  p99 eligible, tail-censoring warning persisted
```

Eligible is **not** the same as tail-valid. A point with sub-5% censoring that
could determine the final UNDER/OVER boundary requires a recorded
tail-sensitivity review before it may finalize the crossing; without that record
the aggregate stays `UNCERTAIN`. Timeout/error count and rate are always
reported. Deep-saturation points remain valid evidence of saturation and are
never reported as ordinary latency percentiles.

### 10.7 — Two workloads (new)

- **Headline (controlled).** The canonical stratified multiset above. Answers:
  at what nominal λ does p99 TTFT breach 500ms *for this documented controlled
  workload*, with prompt-cost composition held fixed by construction.
- **Secondary (natural-random).** Pinned corpus, natural random draws,
  independent seeds, same server/output policy, same percentile and censoring
  semantics, separate artifact namespace. Answers: does the same general
  knee/degradation behaviour survive unconstrained natural traffic.

They are never collapsed. Secondary points never define the headline breach RPS,
and the secondary is not expected to reproduce the headline crossing exactly.

### 10.8 — Prefix-cache policy for the controlled headline (new)

**Finding:** exact prompt replay is the experimental control introduced by
§10.1. If prefix caching recognizes those replays, the control changes the cost
it is controlling — and it does so as a function of **run order**, making later
points and later repeats systematically cheaper. Measured: a 14,960-char prompt
at 523.3ms cold and 103.9ms on a warm replay of the same prompt.

**Now:** prefix caching is **disabled** for the controlled headline benchmark.
The **effective runtime configuration** is verified — not merely the CLI string —
persisted in run/session provenance, and preflight **fails** if a controlled
headline run finds prefix caching enabled. Week 4+ controlled routing
comparisons use the same prefix-cache-disabled configuration so the comparison
stays apples-to-apples.

Run-order randomization, prompt permutation, and back-to-back repeats do **not**
neutralize accumulated cache state and are not substitutes. If prefix caching is
ever studied enabled, that is a separate declared configuration experiment, never
mixed into the headline comparison.

*Consequence for the first session's unloaded floor:* it was measured with
caching enabled, after the same prompts had been served by the sweep, and is
classified `CACHE_INFLUENCED_DIAGNOSTIC`
(`benchmarks/calibration/week2_redesign/unloaded_floor_cache_audit.json`). The
402.3ms figure is no longer citable as *the* unloaded floor. The thesis-level
conclusion it supported is weakened rather than overturned: cache influence
biases a floor **low**, so the true cold floor is at or above 402.3ms and may sit
closer to the SLO. A new clean floor is collected next session with caching
disabled.

### 10.9 — What did NOT change

Recorded explicitly so nothing is quietly reopened under cover of the redesign:
p99 TTFT as headline metric; 500ms SLO; 2s secondary line; Poisson as the
headline arrival process; steady as secondary reference; adversarial as a
separate scenario; open-loop scheduling; absolute-time targets; fire-and-forget
send-task spawn; per-send scheduling-lag logging; fail-fast shedding;
concurrency cap 3000; the cap never shaping the characterized region; Linux
scheduler spin 0ms; on-instance loopback load generation; `ulimit -n 65535`;
pinned corpus content; frozen materialized schedule as replay source of truth;
raw log + sidecar durability model; the raw log's six-field schema; exact
benchmark-SHA pinning; human-owned GPU lifecycle; the mock trust boundary; and
per-point **time-based** warmup.

---

## 11. Session #2 evidence locks (2026-08-19)

Six decisions taken by the human ahead of Hard Stop R-DOC, at the pre-GPU
documentation cleanup. They are **not proposals**. Each closes a question the
GPU session #2 plan had left open, and each is encoded machine-readably in
`benchmarks/workloads/week2_headline/repeat_policy.json` so the runbook and the
classifier cannot drift apart from this text.

Where §10 records what the *first session falsified*, §11 records what the
*second session is authorized to do*.

### 11.1 — Repeat classification: agreement, never majority (1A)

Each headline λ receives **three independent repeats**. Final classification
requires **agreement**:

```
UNDER + UNDER + UNDER  →  UNDER
OVER  + OVER  + OVER   →  OVER
any 2-1 split          →  UNCERTAIN
```

**Majority voting is not implemented and must not be.** Near the SLO a 2–1
split *is* the finding: the point is unstable, and unanimity is what makes that
visible instead of averaging it away. Converting a split into a verdict is
precisely the error the first session made once already, and the reason `n >=
100` looked like sufficient evidence at the time.

Three is also the smallest number that can show disagreement *as* disagreement —
with two, a split is a tie and there is no way to tell which run was unusual.

### 11.2 — `N = 4000` is the ceiling for session #2 (2B)

```
N = 4000    authorized headline evidence size
N = 5000    NOT AUTHORIZED
```

If `N = 4000` under the three-repeat unanimity rule cannot resolve the crossing:

```
report a breach interval = (highest defensible UNDER λ, lowest defensible OVER λ]
```

**Do not increase N on the meter.** This supersedes the earlier proposed "one
pre-authorized escalation" — a single UNCERTAIN boundary λ re-driven at
`N = 5,000` for all three repeats. That option is withdrawn;
`repeat_policy.json` now records `escalation.authorized: false` and
`escalation.n5000.authorized: false` where it previously recorded `null`.

The reasoning that makes an interval respectable rather than a shortfall: a ≤1%
per-run classification-flip rate would need N ≈ 7,500, which is above
`N_max = 5,000` — the structural ceiling set by the pinned corpus holding
exactly 5,000 prompts. The resolution an escalation would buy is not reachable
with this corpus at any authorized N, so spending 2.1 additional hours to move
from 4,000 to 5,000 buys a marginal improvement in flip rate and no change in
kind. An interval is the honest shape of the answer.

### 11.3 — Process epochs are not combinable (3A)

**Headline repeats from different vLLM process epochs must not be combined into
one final classification family.**

D4 forbids restarting vLLM between repeats, so the repeatability estimate
measures arrival and queue variability rather than cold-process variance. A spot
preemption forces a restart, which means the two are no longer the same
measurement. If Tier B is interrupted after two complete repeats, a new process
may **not** contribute only `repeat 3`:

```
epoch A → preserved diagnostic evidence
epoch B → repeat 1 + repeat 2 + repeat 3 → final family
```

The schedules are frozen, so re-driving all three in a fresh process is exactly
reproducible. Only meter time is lost — and meter time is the cheap thing here.
The alternative, a family whose third member carries process-initialization
variance the other two do not, would be a silent confound at exactly the
boundary where the verdict is decided.

### 11.4 — The 60-second warmup boundary is frozen, and validated forward (4A)

The redesigned headline schedules freeze a **60-second warmup boundary**: exactly
N arrivals are materialized at or after it. Tier A must establish that the
relevant transient has stabilized by that boundary.

If it has not:

```
STOP
pull artifacts
regenerate schedules with a larger frozen boundary
re-run the required GPU-free checks
return to pre-GPU approval
```

**Post-hoc warmup re-filtering of headline sidecars is superseded and invalid.**
Under the old fixed-duration design (§2.4) it was sound: the window held a
surplus of samples, so filtering later simply discarded some. Under exact-N it is
not, and the failure is quiet — filtering past the frozen boundary discards
canonical arrivals and leaves fewer than N measured samples, so the run silently
stops being the size the calibration was read off.
`metrics/headline_point.py` refuses it rather than letting the count drop.

This is the single most load-bearing stale assumption in the repository: the
procedure it supersedes is written down in several places, was correct when
written, and would still run.

### 11.5 — Scout expansion is pre-authorized and bounded (5A)

```
initial scout:   λ = 1, 2, 4, 8
fallback:        if λ=1 is already OVER  →  add λ=0.5
                 if λ=8 is still UNDER   →  add λ=16
```

If the authorized fallback still fails to establish a useful bracket:

```
STOP. Return to human review.
```

**Do not invent additional λ values on the meter.** 0.5 and 16 are the only
pre-authorized additions — the earlier draft's "0.5, 0.25" and "16, 32" ladders
are not authorized. The point of pre-authorizing a fallback at all is that the
boundary between *following the plan* and *improvising* stays legible while the
meter is running; an open-ended ladder erases it.

### 11.6 — Week 2's secondary scope stays in scope (6A)

Week 2 is not closed until all four intended scenarios are accounted for:

1. controlled Poisson headline,
2. natural-random secondary,
3. steady-arrival reference,
4. adversarial scenario.

**The controlled Poisson workload alone defines the headline breach.** The other
three may support interpretation but may never redefine it, and secondary points
never enter the headline classification (§10.7). Adversarial remains last in
execution order (§2.1, §6.2) — it deliberately drives the replica toward
saturation, so it runs once the curves that matter are already durably written.

This closes the "out of scope, flagged rather than dropped" question the session
#2 plan raised: steady and adversarial are *deferred within Week 2*, not dropped
from it. If session wall-clock forces a cut, the cut comes from the bottom of
that list and what was deferred is recorded.

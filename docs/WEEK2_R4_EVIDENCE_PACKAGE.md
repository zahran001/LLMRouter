# Week 2 — R3 closeout and R4→R11 evidence package

**Status: halted for human review at Hard Stop R-PREGPU.** No GPU instance was
created. Nothing was committed.

This is the §12 deliverable of
`WEEK2_R3_CLOSEOUT_AND_R4_IMPLEMENTATION_README.md`: the evidence that the
redesign is implemented, that the old instrument still works, and that every
new load-bearing control has been shown to bite.

---

## 1. Authoritative-doc supersession, with provenance

Every superseded lock keeps its original text and gains a pointer. Nothing was
deleted.

| Document | Change |
|---|---|
| `WEEK2_PLAN.md` | New **§10 — Redesign supersessions**, ~200 lines, one subsection per falsified assumption with the measurement that falsified it. §2.2, §2.4, §2.5, §2.6 and §3.4 gained SUPERSEDED headers pointing into it. §8/§9 tables carry the new locked values. **§10.9 lists what did *not* change**, so nothing is quietly reopened under cover of the redesign. |
| `WEEK2_EXECUTION.md` | Block E marked as run; the escape hatch marked as taken. New **redesign arc** (R0→R11 → pre-GPU stop → session #2), Hard Stop R3 recorded as cleared, new **Hard Stop R-PREGPU** defined. **Block F carries a warning** that it cannot be run against session #1's artifacts. |
| `STATUS.md` | Week 2 restated as mid-redesign, not near closeout. Explicit "do not cite" list. Redesign progress table, the six locks from R3, and the note that `Y=120s` / `n≥100` are historical. |
| `docs/WEEK2_GPU_SESSION_FINDINGS.md` | **New.** The permanent record: setup, six trusted findings, eight falsifications with their evidence, the do-not-publish list, and a table mapping each finding to what it changed. |

The locks now written into the authoritative docs:

```
k       = 6 strata at corpus quantiles 0/50/90/95/99/99.5/100
L       = corpus q99 = 11,471 chars
N       = 4,000 post-warmup scheduled arrivals per run
N_max   = 5,000  (structural: corpus cardinality)
p99     = nearest-rank, one shared versioned implementation
prefix caching = disabled for the controlled headline, preflight-enforced
```

### One conflict, surfaced rather than reconciled

`WEEK2_PLAN.md` §3.4 was LOCKED as *"random sample, **no length
stratification**"*, which is exactly what D3 requires. I judged this in scope
for supersession — it is not in the README §3 keep-locked list, and §2.2's
premise is what the first session falsified — and wrote the amendment with that
reasoning stated in §10.1, including the argument that *proportional* allocation
serves §3.4's stated intent (measure the corpus's natural mix) more faithfully
than a random draw did, because the mix is now exact rather than sampled.

**This was flagged at Hard Stop R3 and is now resolved in the docs. If you
disagree with the reading, §10.1 is the paragraph to reject.**

---

## 2. P1 — the unloaded floor's cache state

`scripts/audit_floor_cache_state.py` →
`benchmarks/calibration/week2_redesign/unloaded_floor_cache_audit.json`

**Verdict: `CACHE_INFLUENCED_DIAGNOSTIC`.** The floor artifact was not modified.

The audit reads the vLLM log's activity blocks and confirms the floor ran at
19:51:29 with peak concurrency 1 — **after** the six Stage A blocks
(19:15–19:34) had already served the same prompts, with caching enabled. Prior
exposure is documented, so a cold cache cannot be *proven*.

Behavioural evidence, from an internal control nobody planned: 12 prompts were
served twice **inside the floor run itself**, and the one pair long enough to
discriminate says both halves of the story at once —

```
prompt 1903 (4,992 chars)
  first serving  (#29)   197.7ms    = 0.96x the cold-prefill prediction
  replay        (#164)    83.9ms    = 0.42x the first serving
```

The replay was a cache hit, so the cache was live. The *first* serving still
paid full prefill despite the sweep having served that prompt seven times
earlier — so that earlier exposure had been evicted. And none of the top 10
TTFT samples, the ones that set the floor's p99, is a repeat serving.

**Consequence, applied:** 402.3ms is no longer cited as *the* unloaded floor.
The thesis-level conclusion it supported is **weakened, not overturned** — a
cache-influenced floor is biased *low*, so the true cold floor is at or above
it and may sit closer to the SLO. Session #2 collects a new one with caching
disabled, over the exact canonical multiset.

*Evidence strength is stated in the artifact: one discriminating pair. It is
enough to prevent writing the floor off entirely; it is not enough to
characterise eviction, and the verdict does not rest on it.*

---

## 3. P2 — no historical artifact was renormalized

- `git diff HEAD -- benchmarks/schedules/stage_a corpus/` is **empty**, asserted
  by `tests/redesign/test_legacy_compatibility.py`.
- No broad `git add --renormalize` was run.
- `.gitattributes` gained `-text` for **new paths only**
  (`benchmarks/workloads/**`, `benchmarks/schedules/week2_redesign/**`,
  `benchmarks/evidence/**`). The historical `stage_a` schedules are deliberately
  **not** listed: adding a rule there would mark every committed blob as
  modified and invite exactly the rewrite P2 forbids.
- `metrics.artifacts.write_json_artifact` pins LF and ASCII on every platform,
  so newly generated artifacts are byte-stable. Verified: every new artifact is
  LF.

### What this surfaced

The existing byte-identity test compared regenerated schedules against the
**working-tree** file, and passed on both platforms for a coincidental reason —
the writer applied the same newline translation git had applied on checkout, so
two platform-dependent transformations cancelled. Pinning the writer removed
one half and the test went red.

It now compares against the **committed blob** (`git show HEAD:…`), which is
what a Linux GPU instance actually clones. That makes it genuinely
platform-independent rather than accidentally symmetric. `ensure_ascii=True` is
likewise load-bearing, not a default: the committed schedules escape section
signs as `§`, so UTF-8 output would have diverged from history at the first
non-ASCII character while every line still looked identical.

---

## 4. R4 — the canonical workload

`benchmarks/workloads/week2_headline/canonical_v1.json`
`membership_id a49ecdd8071920303f240fcf0b8da42dbbc66da593ae88e3c07aa246c4b5aa7b`

| Stratum | Quantiles | Char range | Available | Selected |
|---|---|---|---:|---:|
| 0 | 0–50 | 1 – 142 | 2,491 | 2,000 |
| 1 | 50–90 | 142 – 2,358 | 2,009 | 1,600 |
| 2 | 90–95 | 2,358 – 4,566 | 250 | 200 |
| 3 | 95–99 | 4,566 – 11,471 | 200 | 160 |
| 4 | 99–99.5 | 11,471 – 13,101 | 24 | 20 |
| 5 | 99.5–100 | 13,101 – 44,445 | 26 | 20 |

- **4,000 unique prompt IDs**, no duplicates, proportional allocation by
  largest remainder, selection **without replacement**.
- **40 prompts above `L`** — exactly 1.00% of `N`, matching what R3 sized for.
- Selection is **hash-keyed**, not RNG-keyed: `sha256(seed:prompt_id)`, lowest
  keys win. NumPy does not promise `Generator` stream stability across
  releases, so an RNG selection would silently stop reproducing after an
  upgrade and the failure would look like corruption.
- `--verify` re-derives the membership from the recorded seed and compares
  byte-for-byte: **VERIFY OK**.

### R4B — capacity, measured rather than estimated

`tokenizer_capacity_report.json` — **PASS**

The tokenizer is the gated `meta-llama/Llama-3.2-3B-Instruct` one, obtained
without access to the gated repo and **proven** to be it: the public metadata
API reports the git blob SHA-1 of every file, an ungated mirror's copy was
downloaded, and its locally computed blob id was required to match. It does
(`tokenizer.json` blob `5cc5f00a5b20…`, 9,085,657 bytes).

Prompts are counted **as rendered through the model's own chat template**,
which is what vLLM tokenizes — 35 tokens of overhead for an empty message.

```
max input      10,482 tokens   (prompt_id 790, 44,445 chars, 4.25 chars/token)
+ output          512 tokens   (locked policy)
+ margin        1,099 tokens   (10%, floor 512)
= required     12,093 tokens   <=  20,000       PASS
```

**Proposed `--max-model-len`: 20000 — unchanged, but for a different reason.**
It was previously safe because the extremes were unlikely to be *drawn*; prompt
790 was never served in the entire first session. The canonical construction
guarantees it at every point of every repeat.

### R4C — the freeze gate is enforced in code

`--freeze` refuses unless a capacity report exists, covers **this**
`membership_id`, and says PASS. Demonstrated refusing before the report
existed. It also refuses to overwrite a *different* frozen workload.

---

## 5. R5–R11 — the machinery

### Exact-N open-loop schedules (R5/R6) — `headline-schedule-v2`

15 headline schedules (3 repeats × 5 λ), every one carrying **exactly 4,000
post-warmup scheduled arrivals**:

| repeat | λ | total | warmup | post | duration | realized λ | vs nominal |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1.5 | 4,089 | 89 | **4,000** | 2,681.4s | 1.526 | +1.73% |
| 1 | 2.0 | 4,106 | 106 | **4,000** | 2,020.5s | 2.040 | +2.01% |
| 2 | 2.5 | 4,166 | 166 | **4,000** | 1,661.1s | 2.498 | −0.07% |
| 3 | 4.0 | 4,273 | 273 | **4,000** | 1,055.7s | 4.017 | +0.43% |

*(4 of 15 shown; total drive time 7.36 h across all 15, of which only 3 λ × 3
repeats get driven — see the session plan.)*

Duration is an **outcome**: ten different arrival seeds at the same λ produce
ten different durations and the same 4,000 post-warmup count. `N/λ` is never
used as the runtime duration.

### The invariant, and the control that proves it

`tests/redesign/test_exact_n_open_loop.py` builds
`StopAfterNCompletionsScheduler` — a deliberate `while completed < N`
implementation — and drives both it and the real scheduler against fast and
slow mocks:

- **real scheduler**: identical issued count at both server speeds;
- **broken scheduler**: stops short, and stops at a *different* point depending
  on server speed. That asymmetry is the operational meaning of "closed-loop":
  the server's latency decided the workload.

A control that only checked "did it stop short" could pass on a truncating bug;
this one distinguishes truncation from feedback.

### Warmup boundary — a constraint discovered while building

The per-point warmup is still `[CALIBRATE]`. Under the old fixed-window design
a resolved warmup was applied by **re-filtering** the sidecars. Under exact-N
it cannot be: the schedule materialized exactly `N` arrivals at or after *its*
boundary, so filtering later discards canonical arrivals and leaves fewer than
`N` measured samples — with every count still looking plausible.

`metrics/headline_point.py` now **refuses** a warmup filter past the frozen
boundary, and the schedules were regenerated at a deliberately generous 60s
boundary to buy headroom (cost: ~90–260 extra warmup requests per point against
4,000 measured ones). If session #2's transient runs past 60s, the schedules
are regenerated, not re-filtered.

### R7 — three RPS quantities

`nominal_lambda_rps` / `materialized_schedule_rps` / `actual_send_rps`, with
driver fidelity measured against the **materialized schedule**. Reproducing the
first session's 2-RPS numbers (248 arrivals over 130s, all delivered): the gate
now **passes**, and the −4.6% finite-Poisson realization is recorded as
metadata. Dropping 48 of 248 scheduled sends still fails it at −19.4%.

### R8 — censoring-aware validity

Four states. `>5%` censoring ⇒ `CENSORED` with the ordinary p99 **suppressed**;
`0 < rate ≤ 5%` ⇒ eligible **with** a tail warning and a review requirement.
All of R8's named boundary cases are tested: 0%, just below 5%, exactly 5%,
just above, and 33/70/81% (the first session's measured rates).

### R9 — repeat orchestration

Drain to in-flight = 0, verified by polling, before the next repeat *and*
between λ points within a repeat. No vLLM restart. The runner **refuses** to
start a repeat while requests are in flight, and refuses duplicate repeat ids.

### R10 — classification and bounded uncertainty

Repeats decide the verdict, never bootstrap slices. Censored/invalid repeats
are excluded rather than pooled; a 2-1 split is `UNCERTAIN`, not a majority
verdict; a boundary point with unreviewed sub-5% censoring cannot finalize. At
the evidence ceiling an unresolved crossing reports
`breach interval = (highest UNDER λ, lowest OVER λ]` rather than escalating.

The policy is an **argument**, not a constant — it lives in
`benchmarks/workloads/week2_headline/repeat_policy.json`, still `PROPOSED`.

### R11 — natural-random secondary

Five schedules in their own namespace, natural i.i.d. draws, fixed duration —
i.e. exactly what the headline stopped being, deliberately, so it can act as
the control for whether the controlled workload's knee is an artifact of the
control. Marked `never_defines_headline_breach: true` in its own provenance.

### L6 — prefix caching

`--no-enable-prefix-caching` by default in the launch script, plus
`verify_prefix_cache_disabled.py`, which sends the three longest canonical
prompts twice and refuses the session if a replay comes back at ≤0.75× its
first serving. Prometheus counters and the engine config line are recorded as
supporting evidence but **cannot vote "disabled"** — a counter absent from a
build would otherwise supply a clean bill of health.

---

## 6. Regression results

| Suite | Result |
|---|---|
| everything except router | **288 passed**, 25 deselected (9m57s) |
| router tier (`-m router`, builds the Rust binary) | **25 passed** |
| redesign suite alone | 165 passed |
| control demonstration | 13/13 red-then-green |

The documented environment-only flake
(`test_end_to_end_fast_config`, `STATUS.md` "Known issues") did **not** fire.

For comparison, the R3 state was 176 + 25 + 52. The redesign suite grew from
52 to **165** tests across ten files; one pre-existing test was *strengthened*
rather than added to (§3).

Legacy compatibility specifically:

- first-session schedules parse under `loadgen-schedule-v1`; the redesign's are
  `headline-schedule-v2`; **an unknown version raises** rather than being
  coerced;
- both R2 source points re-read **bit-for-bit identical** to their committed
  records;
- promoted artifact hashes unchanged (`--verify`: 24/24);
- `rps1.5` artifact discovery still correct;
- `git diff HEAD -- benchmarks/schedules/stage_a corpus/` empty.

---

## 7. Controls, red before green

`scripts/show_control_bites.py` runs each against a deliberately broken input
first:

| Control | The red it goes through |
|---|---|
| fractional-RPS discovery | old rule invents phantom point `poisson_rps1` |
| promotion refuses overwrite | changed source bytes → exit 1, promoted copy intact |
| hash manifest | one flipped digit moves the sha256 |
| interpretation pin | 2s warmup shift moves p99 524.6 → 526.9ms |
| corpus-drift refusal | mutated corpus refused for replay |
| bootstrap seeding | different seed → 169/200 resample p99s differ |
| canonical identity | drifted corpus refused; N > N_max refused |
| exact-N vs fixed duration | 120s window gives 116/248/643/1316 by λ; exact-N gives 4,000 at every λ |
| percentile lock | same 225 samples: 434.8 UNDER … 552.9 OVER |
| censoring suppression | 134 survivors clear `n≥100`; new gate returns CENSORED |
| driver fidelity | 48 dropped sends → −19.4%, FAILS |
| prefix-cache gate | measured 0.20× replay → PREFIX_CACHING_ENABLED |
| repeat drain + ceiling | 7 in flight → REFUSED; ceiling → interval `(1.5, 2.5]` |

Plus the live-server control in `tests/redesign/test_exact_n_open_loop.py`
described in §5.

---

## 8. What I could not complete, and what needs your decision

**Nothing in the README's scope was skipped.** Three things need you:

1. **`repeat_policy.json` is `PROPOSED`.** In particular `escalation.authorized`
   is `null` — the one pre-authorized N=5,000 escalation is not authorized
   until you say so, in advance.
2. **The spot-preemption branch.** D4 forbids restarting vLLM between repeats,
   but a preemption forces one. If the session dies after two complete repeats,
   the third cannot be added in a new process and still satisfy D4 as written.
   Three options are laid out in the session plan §6; all three are yours.
3. **Steady reference and adversarial scenarios** (`WEEK2_PLAN.md` §2.1) are not
   mentioned by the R4 README and are **not** in the session estimates. Flagged
   rather than dropped.

Two environment notes: `tokenizers` and `jinja2` were installed into `.venv`
for the R4B capacity proof (the check refuses to fall back to a char estimate —
replacing that estimate is its entire purpose), and the verified tokenizer is
cached in gitignored `.tokenizer_cache/` with its hash proof, since a 9MB
vendored file is a build input rather than evidence.

---

## 9. Proposed session #2

Full plan: `docs/WEEK2_GPU_SESSION_2_PLAN.md`.

```
preflight + standup + prefix-cache gate            ~20 min
Tier A  clean floor over the canonical 4,000       ~10 min
Tier A  scout sweep, λ 1/2/4/8, N=500, 1 repeat    ~20 min
        -- human reads crossing region + warmup transient --
Tier B  3 λ x 3 repeats at N=4,000              2.8 - 5.4 h
        repeat-major ordering (preemption hedge)
secondary natural-random curve                   30 - 50 min
pull, verify, teardown                             ~15 min
                                          TOTAL  4.3 - 7.2 h
                                           COST  ~$1.70 - $3.60
```

The binding constraint is wall-clock and spot preemption, not money — the $150
hard line is not in reach; the $10 canary may fire.

Tier A exists because **the old bracket is not authoritative**: the 1.5-RPS
point was cache-confounded, prefix caching is now off (so the server does
strictly more work at the same λ), and the canonical workload's tail is heavier
than most first-session realizations. All three push the crossing down by an
unquantified amount. Scouting cheaply first is what stops 5 hours of calibrated
evidence landing entirely on one side of it.

**Halting here for your review. No GPU instance was created; nothing was
committed.**

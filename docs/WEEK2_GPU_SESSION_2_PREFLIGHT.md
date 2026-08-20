# Week 2 — GPU session #2 pre-flight

> **STATUS: EVIDENCE — DOES NOT GOVERN EXECUTION**
>
> Role: the R-DOC / R-PREGPU evidence checklist for GPU session #2.
>
> This document records *why* the repository is believed ready. It does not
> govern execution, and any command text below is a record of what was run, not
> an instruction to run it now.
> Current execution instructions: `docs/WEEK2_GPU_SESSION_2_PLAN.md`.
> Index: `docs/WEEK2_DOC_INDEX.md`.

A short evidence checklist, not another design document. It replaces session
#1's Hard Stop 4 checklist, which was superseded and then deleted on
2026-08-20 (recoverable: `git show 39ed3f1:docs/WEEK2_GPU_PREFLIGHT.md`).

**Produced 2026-08-19 at the completion of the pre-GPU documentation cleanup.**

**Revised 2026-08-19, same day, after the first version of this checklist was
reviewed and its central claim did not hold.** It reported "stale-assumption
scan = PASS, 0 unexplained stale hits". That was wrong: `T-DOC-4` had two
unsound exemptions, and 29 stale statements — including the load-bearing warmup
one, in the AUTHORITATIVE plan — passed straight through them. The rule, the
controls and the documents are all corrected below, and the numbers in this file
are the ones measured after that correction.

---

## Repository identity

| | |
|---|---|
| Branch | `week2/loadgen-baseline` |
| HEAD at audit start | `efbf3e5`; R-DOC cut `0c09878`; the R-PREGPU lead-in fixes cut the SHA reported at closeout |
| Working tree | **clean** at the benchmark SHA; R-DOC PASSED 2026-08-19 |
| Files changed | 30 at R-DOC, plus the R-PREGPU lead-in corrections |
| Benchmark SHA | Cut from this tree and reported at closeout — writing it into a tracked file would advance `HEAD` past the commit it names |

`run_on_instance.sh bootstrap` refuses a dirty or unpushed HEAD, so the
benchmark SHA cannot be skipped by accident.

---

## Documentation governance (Hard Stop R-DOC)

| Item | Result |
|---|---|
| Documents classified | **15** live Week 2 process documents, in `docs/WEEK2_DOC_INDEX.md`; the 8 dead ones were deleted 2026-08-20 |
| Index completeness | **PASS** — no unindexed markdown at repo root or in `docs/`; new files fail closed |
| Current GPU runbooks | **1** — `docs/WEEK2_GPU_SESSION_2_PLAN.md` |
| Stale-assumption scan | **PASS on the third pass** — 29 hits (second) + 4 lead-ins (third), all resolved, 0 unexplained (§ below) |
| Documentation tests | **PASS** — `tests/redesign/test_week2_doc_state.py`, 17 tests, 13 stale concepts |
| Documentation controls | **PASS** — 6/6 red→green, `scripts/show_doc_control_bites.py` |
| Fresh-context test | **Automated chain + policy-fact check PASS**; human-run review **outstanding** (§ below) |

### Classification summary

| State | Count | Documents |
|---|---:|---|
| `AUTHORITATIVE` | 6 | `STATUS.md`, `WEEK2_PLAN.md`, `WEEK2_EXECUTION.md`, `docs/WEEK2_DOC_INDEX.md`, `docs/WEEK2_MOCK_VALIDATION.md`, `repeat_policy.json` |
| `EXECUTABLE` | 2 | `docs/WEEK2_GPU_SESSION_2_PLAN.md` **(the runbook)**, `docs/GPU_SESSION_NOTES.md` (setup reference) |
| `EVIDENCE` | 7 | session #2 preflight (this file), session #1 findings, R4 evidence package, pre-GPU audit, remediation report, first-session artifact README, R3 evidence package |
| `SUPERSEDED` | 0 | Both deleted 2026-08-20 (session #1's runbook and its pre-flight) |
| `HISTORICAL` | 0 | All six briefs deleted 2026-08-20 |

**The dead documents were deleted rather than banner-marked (2026-08-20, human
decision).** Removal is the stronger guarantee — a file absent from the working
tree cannot be found, read or followed by mistake — and all eight remain
recoverable from git at `39ed3f1`. The `DO NOT EXECUTE` rule stays in force for
anything added later: `test_historical_and_superseded_documents_say_do_not_execute`
now bites from both directions, rejecting a dead index row without the banner
**and** a file declaring a dead state that the index does not list. Every banner
is still verified against the index by `test_every_indexed_document_declares_its_state`.

### The three documents that were actually dangerous

Worth naming, because the rest of the classification is bookkeeping. All three
are now either deleted or explicitly marked:

1. **`WEEK2_GPU_IMPLEMENTATION_README.md`** — a complete GPU runbook (phases
   E-1 → E4, approval gates, teardown, `BASELINE.md` authoring). It would have
   run. Its Stage A/B fixed-duration design is precisely what session #1
   falsified.
2. **`docs/WEEK2_GPU_PREFLIGHT.md`** — carried a `GPU SESSION READY` verdict and
   five `gcloud` invocations. A reader could reasonably have treated it as
   current clearance.

3. **`WEEK2_PLAN.md` §6** — found on the second pass, and worse than both,
   because it is inside the document at the top of the authority chain. A
   section headed "GPU session runbook (LOCKED)", carrying session #1's full
   procedure and an instruction to extend the λ range live on the meter.

### The controls, and what they now prove

Six, all red→green, all mutating real tracked files with hash-verified restore:

| Control | Proves |
|---|---|
| C-DOC-1 | A superseded runbook that stops saying `DO NOT EXECUTE` is rejected |
| C-DOC-2 | A policy that quietly authorizes `N=5000` is rejected |
| **C-DOC-3** | The **real** stale warmup sentence — "a re-filter over the committed sidecars, **never a GPU re-run**" — is rejected, and its corrected form is accepted |
| C-DOC-4 | A second document marked as the current GPU runbook is rejected |
| **C-DOC-5** | A `SUPERSEDED` marker on one table row does **not** exempt the row beside it — and the red is checked to be for the warmup row, not the marked window row |
| **C-DOC-6** | Identical stale text is accepted under an explicitly historical heading — provenance stays writable, so the rule does not buy safety by deleting history |

C-DOC-3's previous form injected a synthetic sentence that matched a regex, sat
in an unmarked section and contained no negative word — it exercised the one
path where every exemption happened to be open, so it went red on a defect the
repository did not have while the defect it did have went green. The four scope
cases are also unit tests in the suite, so they run in every regression rather
than only when someone remembers the control script.

---

## Stale-assumption audit

Three passes. The first is recorded below as it was reported; the second —
after the checker that produced it was found to be unsound — and the third,
found at R-PREGPU on the section lead-ins the second pass left behind.
**Unexplained stale hits after the third pass: 0.**

### First pass (as originally reported)

36 patterns scanned repository-wide (not only `.md`), per the cleanup brief §9.
Every occurrence classified, and 15 corrected.

| Class | Count | Notes |
|---|---:|---|
| `CURRENT_CORRECT` | majority | Code, tests, calibration JSON and schedule provenance that already encode the redesigned semantics — e.g. `warmup_n` in `metrics/point.py`, `natural-random` in the secondary schedules, `prefix caching` in `loadgen/prefix_cache.py` |
| `HISTORICAL_EXPLICIT` | substantial | Session #1 artifacts, `benchmarks/evidence/week2/first_session/**`, `R3_EVIDENCE_PACKAGE.md`, and the superseded/historical documents — all now banner-marked |
| `STALE` → corrected | **15** | Listed below |

### The 15 stale statements corrected

| # | Location | What was stale |
|---:|---|---|
| 1 | `WEEK2_GPU_IMPLEMENTATION_README.md` | Whole document reachable as a current runbook → `SUPERSEDED` |
| 2 | `docs/WEEK2_GPU_PREFLIGHT.md` | `GPU SESSION READY` reachable as current clearance → `SUPERSEDED` |
| 3 | `docs/WEEK2_GPU_SESSION_2_PLAN.md` §5 | Offered an `N = 5,000` escalation — **contradicts lock 2B**. Removed |
| 4 | `docs/WEEK2_GPU_SESSION_2_PLAN.md` §6 | Scout fallback ladder read "λ 0.5, 0.25" and "λ 16, 32" — **contradicts lock 5A**. Now 0.5 and 16 only |
| 5 | `docs/WEEK2_GPU_SESSION_2_PLAN.md` §6 | "The preemption question this plan cannot resolve alone" — resolved by lock 3A |
| 6 | `docs/WEEK2_GPU_SESSION_2_PLAN.md` §8 | Steady + adversarial listed as out of scope — lock 6A keeps them in Week 2 |
| 7 | `docs/WEEK2_GPU_SESSION_2_PLAN.md` header | `Status: PROPOSED` → `EXECUTABLE` |
| 8 | `WEEK2_EXECUTION.md` Block F | Post-hoc warmup re-filter, `n >= 100` check and linear percentiles asserted as the live procedure |
| 9 | `WEEK2_EXECUTION.md` | No R-DOC gate in the arc or the hard-stop table |
| 10 | `STATUS.md` `[CALIBRATE]` table | Warmup N described as resolved by re-filtering committed sidecars |
| 11 | `STATUS.md` redesign table | R4–R11 "Not started" (they are complete) |
| 12 | `WEEK2_PLAN.md` §2.6 | Breach basis stated as the `Y = 120s` full window |
| 13 | `loadgen/README.md` | Warmup N resolution described as a `--warmup-n` re-filter |
| 14 | `scripts/README.md` | Stage A/B generators and `compute_point_metrics --warmup-n` framed as current |
| 15 | `benchmarks/README.md` | Stage A/B schedule generation framed as current; `repeat_policy.json` described as `PROPOSED` |

**The load-bearing one is the warmup re-filter** (#8, #10, #13, #14). It
appeared in four places, was correct under the fixed-duration design, and would
still run — it just silently produces fewer than N samples, which is exactly the
class of failure that cost session #1 its breach number. It is now refused in
code (`metrics/headline_point.py`), forbidden in policy
(`post_hoc_warmup_refilter: false`), and caught in documentation
(`test_active_documents_do_not_assert_stale_headline_semantics`).

### Second pass — the first pass's checker was unsound

**It appeared in four places. It was in seven, and the checker could not see the
other three.** `T-DOC-4` had two unsound exemptions and one coverage gap:

1. **Generic negation.** Any line containing `never` / `cannot` / `must not` /
   `do not` was treated as denying the stale claim. The sentence actually in
   `WEEK2_PLAN.md` §8 was:

   > Applying the real N is a **re-filter over the committed sidecars, never a
   > GPU re-run**: … so `--warmup-n <N>` re-derives every point

   That `never` denies *a GPU re-run*. It recommends the re-filter. The word
   that proves the sentence is stale is the word that exempted it.

2. **Section-wide markers.** One `SUPERSEDED` anywhere in a section exempted
   every other line in it — including, in §8 and §9, the warmup row sitting
   beside a correctly-marked window row.

3. **No procedural coverage.** The pattern list was statistical only, so
   `Stage A` / `Stage B`, "extend upward live", "add lower points" and
   mid-session schedule generation were never candidates. §2.3 and §6 of the
   AUTHORITATIVE plan were a complete session #1 runbook, unmarked, including
   an instruction to invent λ values on the meter — the exact thing lock 5A and
   the no-improvisation matrix forbid.

The rule is now structural and local: a heading may exempt its own section, a
*unit* (one table row, list item, paragraph or fenced block) may exempt itself,
and a denial must be a phrase specific to that concept. Units are matched with
line wrapping flattened, because `resolved from Stage\nA's transient` is the
same claim to a reader and was invisible to a per-line matcher.

### Third pass — found at R-PREGPU, on the section lead-ins

The second pass corrected table *rows* and left four **section lead-ins** above
them still asserting the old state. Found by reading, when the closeout claim
"the only thing left is the GPU run" was checked rather than accepted:

| Location | Said | Contradicted by |
|---|---|---|
| `WEEK2_PLAN.md` §8 preamble | "One row remains open: the per-point warmup N, resolved from GPU transient data in Block F **by design**" | The row three lines below it, corrected to the 60s frozen boundary; lock 4A |
| `WEEK2_PLAN.md` §9 preamble | "every `[CALIBRATE]` value is resolved **except the one that is deliberately post-GPU**" | Same |
| `WEEK2_PLAN.md` §8 spin row | "`SPIN_MARGIN_S` (5ms) is Windows-tuned, **not yet Linux-calibrated** … do not ship onto Linux vLLM runs unverified" | §9 of the same document, `STATUS.md`, `loadgen/scheduler.py` (`LINUX_SPIN_MARGIN_S = 0.0`, platform-dispatched), and `scheduler_spin_linux_ab.json` — a real Linux VM, kernel `6.8.0-1066-gcp`, arms 0ms/5ms, 20 and 80 RPS, 5 repeats, 2026-08-18 |
| `WEEK2_EXECUTION.md` Block C | Same spin claim, phrased as a live instruction | Same |

All four corrected, with the old wording kept as marked provenance. Both
concepts are now in `STALE_CONCEPTS` — a **resolved calibration still described
as open** is the same failure mode as a superseded procedure still described as
current, and neither had coverage. Verified against the pre-fix text:

```
CAUGHT   PLAN section 8 preamble    [post-hoc warmup re-filtering]
CAUGHT   PLAN section 9 preamble    [post-hoc warmup re-filtering]
CAUGHT   PLAN section 8 spin row    [uncalibrated Linux spin margin]
CAUGHT   EXECUTION Block C spin     [uncalibrated Linux spin margin]
```

**The lesson, recorded because it recurred:** each pass corrected the thing the
scan pointed at and left its neighbours. Rows, then lead-ins. The scan finds
instances; only reading the section finds the claim.

**Re-scan with the corrected rule: 29 hits (second pass), all resolved.**

| Class | Count | Disposition |
|---|---:|---|
| `STALE` → corrected | **16** | 12 locations, listed below; four locations carried two hits each |
| `EXPLICIT_HISTORICAL` → marked at the claim | **13** | Session #1 provenance that was true but unlabelled where it sat: `STATUS.md`'s two narration paragraphs (4), `WEEK2_PLAN.md` §3.3's cap provenance and §8's cap row (3), and `WEEK2_EXECUTION.md`'s Block D, Hard Stop 4, Block E and Hard Stop 5 (6) |
| `CURRENT_DENIAL` | 0 new | The existing denials (`N = 5000 NOT AUTHORIZED`, `No majority voting`) survive the narrower per-concept rule — verified by re-scan, not assumed |
| **Unexplained** | **0** | |

One further correction was made that **no pattern caught**: `WEEK2_EXECUTION.md`
Hard Stop 3 still said "Warmup N is deferred to post-session … resolved in Block
F". Found by reading the sections the scan had flagged, not by the scan. It is
listed as #10 below, and it is the reminder that the scan is a floor, not a
proof.

The 12 corrected locations:

| # | Location | What was stale | Now |
|---:|---|---|---|
| 1 | `WEEK2_PLAN.md` preamble | "the per-point warmup N … is resolved from Stage A's GPU transient data in Block F **by design**" | Frozen 60s boundary, validated forward in Tier A (§11.4) |
| 2 | `WEEK2_PLAN.md` §2.3 | Two-stage Stage A/B sweep presented as `LOCKED` current methodology | Heading marked SUPERSEDED; banner gives the Tier A scout + Tier B procedure and names the bounded fallback |
| 3 | `WEEK2_PLAN.md` §2.6 | Unloaded floor "recorded in Stage A", informing "Stage B step granularity" | Session #2 records it in Tier A; session #1's Stage A named as history |
| 4–5 | `WEEK2_PLAN.md` §6 heading + §6.1–§6.5 | A section titled **"GPU session runbook (LOCKED)"** — session #1's complete runbook, unmarked | `SUPERSEDED — DO NOT EXECUTE` banner naming the current runbook, and every subsection heading marked |
| 6 | `WEEK2_PLAN.md` §6.2 | "extend upward *live*", "add lower points", "offline-generatable in seconds mid-session" | Covered by the §6 banner, which names both as now-forbidden |
| 7 | `WEEK2_PLAN.md` §8 | The warmup row: `OPEN BY DESIGN`, re-filter, `--warmup-n` | `RESOLVED STRUCTURALLY: 60s frozen boundary`, with the STOP-and-regenerate path |
| 8 | `WEEK2_PLAN.md` §9 | Same warmup row, second copy | Same correction |
| 9 | `WEEK2_PLAN.md` §9 | "Execution order: … → §6 GPU session → offline analysis" | Points at the redesign arc, R-DOC/R-PREGPU, Block E2 |
| 10 | `WEEK2_EXECUTION.md` Hard Stop 3 | "Warmup N is deferred to post-session … resolved in Block F" | Marked superseded, pointing at §11.4 |
| 11 | `WEEK2_EXECUTION.md` Block E | "The agent may assist by generating Stage B schedules on request mid-session" | ⚠ banner: schedules are frozen; a new schedule means a new benchmark SHA and a stopped session |
| 12 | `WEEK2_EXECUTION.md` Hard Stop 5 | "If the whole sweep stayed under → extend upward live. If the first load point was already over → add lower points." | Superseded note: scout 1/2/4/8, only 0.5 and 16 authorized, else STOP; session #2's gate is Hard Stop GPU-1 |

**Why this one mattered more than the first fifteen.** Hits #4–#6 and #12 are
not statistics — they are instructions, and they instruct on-meter improvisation
by name. A fresh agent following the index to `WEEK2_PLAN.md`, which is the top
of the authority chain, landed on a section headed "GPU session runbook (LOCKED)".

---

## Human locks

All six committed into current authority — `WEEK2_PLAN.md` §11 (prose),
`repeat_policy.json` (machine-readable), `docs/WEEK2_DOC_INDEX.md` §5 (index),
`docs/WEEK2_GPU_SESSION_2_PLAN.md` (operational).

| Lock | Decision | Verified by |
|---|---|---|
| **1A** | 3 repeats, unanimous, 2–1 ⇒ `UNCERTAIN`, no majority vote | `test_repeat_policy_encodes_the_six_locks` |
| **2B** | `N = 4000`; **`N = 5000` NOT AUTHORIZED**; unresolved ⇒ interval | same, + `escalation.n5000.authorized is False` |
| **3A** | No cross-process-epoch combination | `cross_process_epoch_combination is False` |
| **4A** | 60s frozen boundary, Tier-A validated, no post-hoc re-filter | `post_hoc_warmup_refilter is False` |
| **5A** | Scout 1/2/4/8, fallback 0.5 and 16 only | `preauthorized_fallback` exact-match |
| **6A** | Natural-random, steady, adversarial stay in Week 2 scope | `secondary_scope.required_before_week2_closeout` |

---

## Benchmark

| Item | Evidence |
|---|---|
| Canonical workload verified | `membership_id` recomputes to `a49ecdd8071920303f240fcf0b8da42dbbc66da593ae88e3c07aa246c4b5aa7b` ✔ |
| Membership integrity | 4,000 prompts, 4,000 unique ✔ |
| `N = 4000` | Locked (`repeat_policy.json`, `canonical_v1.json`) |
| `N = 5000` | **Unauthorized** (lock 2B) |
| 60s frozen warmup | `warmup_boundary_s: 60`; schedules materialize N at/after it |
| Prefix caching | Disabled; runtime-verified gate, not the CLI flag |
| Percentile | Nearest-rank, one shared implementation |
| Capacity proof | **PASS** — 10,482 + 512 + 1,099 = 12,093 ≤ 20,000 |
| `--max-model-len` | 20000 |
| Schedules committed | 15 headline + 6 scout + 5 secondary = **26** |
| Lock 5A fallback schedules | **Committed** — λ=0.5 and λ=16, frozen 2026-08-20 (§ below) |

---

## Regression

Recorded, not substituted. Run on the cleaned tree.

| Suite | Command | Result |
|---|---|---|
| Non-router (all tiers) | `pytest tests --deselect tests/router` | **321 passed**, 25 deselected, 0 failed (9m46s) |
| Router tier | `pytest tests/router` | **25 passed**, 0 failed (2m18s) — matches the brief's figure exactly |
| Redesign tier (directory) | `pytest tests/redesign` | **197 passed** — all inside the 321 |
| Redesign tier (marker) | `pytest tests -m redesign` | **141 passed**, 205 deselected — all inside the 321 |
| Documentation tier | `pytest tests/redesign/test_week2_doc_state.py` | **17 passed** |
| Redesign controls | `scripts/show_control_bites.py` | 13/13 red→green + 1 live-server control |
| Documentation controls | `scripts/show_doc_control_bites.py` | **6/6 red→green**, restores hash-verified |
| Legacy artifacts | `promote_first_session_evidence.py --verify` | **24/24 hashes match** |

**Coverage moved up twice, never down:** 304 → 316 at the first cleanup (12 new
documentation-governance tests), then 316 → **321** at the T-DOC-4 fix (four
exemption-scope tests and one index-completeness test). No control was removed,
and the documentation controls went 4 → 6.

> **Note on the brief's historical figures, recorded rather than reconciled.**
> The cleanup brief §18 lists the pre-cleanup counts as non-router **288** and
> redesign **165**. Neither reproduces on this tree under any selection tried:
> the pre-cleanup non-router baseline measured **304** with the same command,
> and the redesign tier collects **197** by directory or **141** by marker
> (180 and 124 respectively before this cleanup's 17). The deltas predate this
> work — no documentation edit can change collection — and the user has
> confirmed tests were added since the brief was written. The brief's figures
> are left in place as the historical record rather than overwritten, per §18.

---

## Historical compatibility

| Item | Result |
|---|---|
| 24/24 promoted hashes verify | **PASS** |
| R2 source records unchanged | **PASS** — no artifact bytes under `benchmarks/evidence/` modified. The one file touched there is `first_session/README.md`, which gained a status banner; `MANIFEST.json` covers the artifacts and re-verifies 24/24 |
| Historical schedules unchanged | **PASS** — no file under `benchmarks/schedules/` modified |
| Canonical workload verifies | **PASS** |

This cleanup modified **no** artifact bytes — no schedule, no promoted run
output, no calibration JSON. Every change is a markdown document, a README,
`repeat_policy.json`, one new test module and one new control script. The
promotion manifest re-verifies 24/24 after the fact, which is the check that
would catch it if that claim were wrong.

---

## Cloud state

| Item | Result |
|---|---|
| GPU instances running | **none** |
| `llmrouter-vllm-l4-week2` | Does not exist (`gcloud compute instances describe` → not found) |
| `gcloud` authed | Account and project both `<REDACTED>` and verified live at audit time — so the empty instance list is a real zero, not an auth failure. Re-check with `gcloud config list` |
| Staged session target | None (`.gpu_session_target` absent) |
| Budget ladder | $10 / $75 / $135 / $150 |
| Teardown target | `teardown_week2.sh` → `llmrouter-vllm-l4-week2` / `us-central1-a`, with post-delete verification |

**No GPU instance was created during this work.**

---

## Fresh-context check

The automated half passes: `test_the_execution_chain_is_reachable_from_the_root_readme`
walks `README.md` → `STATUS.md` → `docs/WEEK2_DOC_INDEX.md` → {`WEEK2_PLAN.md`,
`WEEK2_EXECUTION.md`, `docs/WEEK2_GPU_SESSION_2_PLAN.md`, `repeat_policy.json`}
and fails if any hop is unreachable.

Re-run after the second pass, extended to the full chain the fix brief names
(`README` → `STATUS` → index → session #2 pre-flight → session #2 plan): all
four hops resolve, and all ten policy facts a cold reviewer must report —
`N = 4000`, `N = 5000` unauthorized, three repeats, unanimity, 2–1 ⇒
`UNCERTAIN`, the 60s frozen boundary, no post-hoc re-filter, no cross-epoch
combination, scout 1/2/4/8, fallback 0.5 and 16 — are findable **on that chain**,
without opening a historical document. Both documents a reviewer must not pick
— session #1's runbook and its pre-flight — no longer exist in the working
tree at all.

**The human-facing half is outstanding**, and is the human's to run — the brief
(§16) calls it "a required human-facing control," and an agent that just built
the hierarchy is the worst possible judge of whether it is discoverable. Prompt
a reviewer with no Week 2 context, starting only from the repository root:

> Starting only from the root README, determine: (1) the current Week 2 state,
> (2) which documents are authoritative, (3) which document you would execute
> for the next GPU run, (4) the current N / repeat / warmup / preemption
> policies, (5) which documents are historical and must not be executed.

Expected convergence:

```
README.md → STATUS.md → docs/WEEK2_DOC_INDEX.md
authority:     WEEK2_PLAN.md, WEEK2_EXECUTION.md
GPU execution: docs/WEEK2_GPU_SESSION_2_PLAN.md
machine policy: benchmarks/workloads/week2_headline/repeat_policy.json
```

If the reviewer selects an old preflight or runbook, or cannot identify the
hierarchy unambiguously: **R-DOC = FAIL.** Fix the repository, not the prompt.

---

## Finding raised by this cleanup, and closed: lock 5A's fallback schedules

**Raised.** Lock 5A pre-authorizes scout λ=**0.5** and λ=**16** as fallback. The
committed scout family was λ ∈ {1, 2, 4, 8} only — neither fallback schedule
existed. `run_on_instance.sh bootstrap` refuses a dirty or unpushed tree, so if
the fallback had fired mid-session, generating the schedule would have cost a
commit, a push and a **new benchmark SHA** with the meter running. The lock
authorized a response the frozen artifacts could not deliver.

**Closed 2026-08-20 by human decision** — commit them, rather than accept that
firing 5A ends the session. Generated offline and frozen:

```bash
python scripts/generate_headline_schedules.py --scout --lambdas 0.5 1 2 4 8 16
```

| λ | schedule | sha256 | total / warmup / post | duration |
|---|---|---|---|---|
| 0.5 | `scout/headline_r1_rps0.5.schedule.json` | `99af6b29dc25bbb3…` | 530 / 30 / 500 | 1090.2s |
| 16 | `scout/headline_r1_rps16.schedule.json` | `5014194b69fdfda8…` | 1458 / 958 / 500 | 88.9s |

The generator rewrites `SCOUT_MANIFEST.json` wholesale, so the **whole** scout
family was regenerated rather than the two points alone, and the four existing
schedules were then checked byte-for-byte:

```
headline_r1_rps1.schedule.json: OK
headline_r1_rps2.schedule.json: OK
headline_r1_rps4.schedule.json: OK
headline_r1_rps8.schedule.json: OK
```

Only the manifest changed — two rows added, four `sha256` values untouched,
`total_schedule_duration_s` 1207.5s → 2386.6s. Both new schedules carry
membership id `e9470f8f…`, corpus `f7ec37d3…`, `warmup_boundary_s: 60`, and
exactly 500 post-warmup arrivals. `pytest tests/redesign` — **197 passed** with
the new artifacts in place.

They are **staged, not spent**: neither drives unless Tier A fails to bracket at
the end it covers. Worst case if one fires is 18 minutes at λ=0.5.

---

## Verdict

```
HARD STOP R-DOC:    PASS -- human verdict, 2026-08-19
HARD STOP R-PREGPU: NEXT -- not yet rendered
```

R-DOC cleared on the second pass. The first cleanup reported this gate green
while `WEEK2_PLAN.md` -- the document at the top of the authority chain -- still
carried the superseded warmup re-filter in three places and session #1's whole
Stage A/B runbook under a heading reading "GPU session runbook (LOCKED)",
including an instruction to extend the lambda range live on the meter. The
checker that missed them has been rebuilt (exemptions are now heading- and
unit-scoped, denials are per-concept), the documents are corrected, and the
controls are built from the real sentence rather than a synthetic one.

**Closeout state**

| Step | State |
|---|---|
| Human-run fresh-context review | Rendered with the R-DOC verdict |
| Lock 5A fallback-schedule gap | **Closed** — λ=0.5 and λ=16 committed |
| Human **R-DOC PASS** | **Rendered 2026-08-19** |
| Commit + push; record the benchmark SHA | Done at closeout; the SHA is reported with the closeout, not written into a tracked file — recording it here would advance `HEAD` past the commit it names |
| Human **R-PREGPU PASS** | **Outstanding** |

**The GPU is still not self-authorized.** R-DOC clears the documentation, not
the money. No instance may be created until a human renders **R-PREGPU PASS**,
and the human owns the meter at every step after that.

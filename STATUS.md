# Status

> **STATUS: AUTHORITATIVE — WEEK 2**
>
> Role: where the project currently is, and the session #1 do-not-cite list.
>
> Current document authority: experiment semantics `WEEK2_PLAN.md` · execution
> and gating `WEEK2_EXECUTION.md` · GPU commands `WEEK2_GPU_SESSION_2_PLAN.md`.
> Index: `WEEK2_DOC_INDEX.md`. If these appear to conflict, **HALT and surface the
> conflict** — do not reconcile silently.

Where the project currently is. `README.md` describes what the project *is*
and how it's built, and does not track progress — this file is the only place
that does, so it's the only place that goes stale.

**Current phase: Week 2 — load generation & baseline.**

## Phases

| Phase | Scope | State |
|---|---|---|
| Week 1 | Foundation & measurement: streaming contract, metrics pipeline, transparent router, mock↔vLLM faithfulness | **Closed** |
| Week 2 | Open-loop load generation, mock validation, and `BASELINE.md` — the naive single-replica breach curve | **In progress** |
| Week 3 | Token-count `prompt_len` for KV-cache math (deferred from Week 2 §3.4) | Not started |
| Weeks 4–8 | SLO-aware admission control and routing strategies, measured against Week 2's baseline | Not started |

## Week 1 — closed

Transparent router merged to `main`; measurement pipeline locked and
calibrated with provenance; mock→vLLM faithfulness confirmed against real
vLLM on GPU. Completed process docs are in `docs/archive/week1/`, with the
wrap-up in `docs/archive/week1/WEEK1_CLOSEOUT.md`.

The `router eval` badge in `README.md` is Week 1's gate: it runs the
fidelity, streaming, overhead and header/error tests **and** the two
deliberately-broken routers the eval must fail against, so it goes red both
when the router regresses and when the eval loses its teeth
(`docs/archive/week1/WEEK1_ROUTER_IMPL.md` §4–§5).

## Week 2 — in progress

**GPU session #1 ran on 2026-08-18 and produced diagnostic evidence, not
a final breach RPS.** The infrastructure worked — vLLM served, the open-loop
driver tracked its schedules with zero shed and zero errors at low load, the
corpus-drift guard fired correctly, and artifacts were pulled and verified
before a clean teardown. What failed was the *experimental design*: a fixed
120s window let each RPS point realize a different prompt tail, `n ≥ 100` is far
too weak a floor for a p99 on this workload, and a 60s client timeout censored
every saturated point. Week 2 is therefore **not** near closeout; it is mid-
redesign.

**Do not cite any first-session number as a baseline result.** In particular:
the 2-RPS point is not the breach RPS (its verdict flips on one extreme prompt,
and again on the choice of percentile convention); the 1.5-RPS point is **not** a
clean under-SLO anchor (it was driven last against a warm prefix cache and served
a 14,960-char prompt in 104ms that cost 523ms at concurrency 1); the ~402ms
unloaded floor is classified `CACHE_INFLUENCED_DIAGNOSTIC` and is no longer
citable as *the* unloaded floor; and the 10/20/30-RPS p99 values near 60s are
survivorship artifacts, valid only as evidence of severe saturation.

### Where the redesign stands

| Stage | State |
|---|---|
| R0 preserve first-session evidence | **Done** — 24 artifacts promoted with hashes to `benchmarks/evidence/week2/first_session/` |
| R1 corpus strata / R2 p99-vs-N bootstrap / R3 joint report | **Done** — `benchmarks/calibration/week2_redesign/R3_EVIDENCE_PACKAGE.md` |
| Hard Stop R3 — human locks `k`, `L`, `N`, `N_max` | **Cleared 2026-08-19** |
| R3.5 provenance closeout + missing locks | **Done** |
| R4–R11 implementation, regression + controls | **Done** — `docs/WEEK2_R4_EVIDENCE_PACKAGE.md` |
| R-DOC documentation authority cleanup | **Done** — `WEEK2_DOC_INDEX.md` |
| Hard Stop R-DOC — human verdict on documentation governance | **PASSED 2026-08-19** (human verdict) |
| Tier A execution-path remediation | **Done 2026-08-21** — scout and headline share one session #2 measurement path |
| Final pre-GPU remediation, Phases A–G | **Done 2026-08-21** — removed 2026-08-22; in git history at `625bc0e`; decisions in `WEEK2_PLAN.md` §11.7 |
| GPU session #2, attempt 1 (human-owned) | **Ran 2026-08-22.** Floor + Tier A scout clean; Tier B repeat 1 (λ∈{1.5,2,2.5}) `CENSORED` at every point (27–37%) — see below. Instance torn down cleanly |
| Attempt-2 redesign: sustained-scout tier, `OVER_CENSORED` state, threshold-gated schedules | **Implemented 2026-08-22** — `WEEK2_GPU_SESSION_2_ATTEMPT_2_PLAN.md` §14 locked; runbook (`WEEK2_GPU_SESSION_2_PLAN.md`) rewritten in place for attempt 2 |
| Hard Stop R-DOC (attempt 2) | Session ran without a verdict recorded here — `WEEK2_GPU_SESSION_2_PREFLIGHT.md`'s attempt-2 verdict block still shows `NEXT / Outstanding`. Not resolved by this update; flagged for human backfill |
| Hard Stop R-PREGPU (attempt 2) | Same gap as above |
| GPU session #2, attempt 2 (human-owned) | **Ran 2026-08-23** (two instances — first aborted on an argparse bug, second ran the full runbook). Sustained-scout tier (4 diagnostic points) + Hard Stop GPU-1 (human-cleared) + Tier B headline (λ∈{0.5, 0.75}, 3 repeats each) + secondary/steady/adversarial, clean teardown. **λ=0.75 → `OVER` (unanimous); λ=0.5 → `UNCERTAIN` (2 OVER, 1 UNDER).** Offline resolution: **`NO_UNDER_ANCHOR`** — no λ in the swept range confirmed `UNDER`; escalation not authorized. Full account: `WEEK2_GPU_SESSION_2_ATTEMPT_2_REPORT.md` |
| Threshold-family classification fix (`D-ATTEMPT2-2`) | **Committed 2026-08-24** — real headline family at λ≤1.25 uses the same threshold-freeze rule as sustained-scout; `metrics/classification.py` now checks a population floor instead of exact match for those λ. `repeat_policy.json` `policy_version` 4 |
| Session #2 evidence promoted | **Done 2026-08-24** — 59 artifacts + SHA-256 manifest at `benchmarks/evidence/week2/session_2/` |

**Why attempt 1 is not the closing result.** Tier A's N=500 scout (5–6 minute
points) read λ=1 as clean `UNDER` and λ=2 as barely `OVER` at 0% censoring;
Tier B's real N=4000 (~34–45 minute) confirmation at the adjacent λ found
27–37% censoring instead. A short scouting window cannot see a queue that is
only slowly diverging — the same class of failure the whole Week 2 redesign
exists to catch, recurring one level up. Full account:
`WEEK2_GPU_SESSION_2_REPORT.md`. Attempt 2 replaces the N=500 scout with a
sustained-scout tier (freezes on ≥45min AND ≥2,000 requests, whichever binds
last) and adds `OVER_CENSORED` — the exact order-statistics proof that
censoring alone can establish a breach — as detailed above.

**Attempt 2 is not the closing result either, but for a different reason.**
Unlike attempt 1, it ran cleanly end to end and produced a genuine boundary
read: λ=0.75 breaches (unanimous `OVER`), λ=0.5 is a real 2–1 split
(`UNCERTAIN` — not resolved by taking a majority or adding a fourth repeat;
`repeat_policy.json` locks forbid both). No λ in the swept range confirmed
`UNDER`, so the offline resolution is `NO_UNDER_ANCHOR` and the breach
interval stays open below 0.75. Closing it needs a confirmed `UNDER` anchor
from a further session at a lower λ, generated and frozen offline first — see
`WEEK2_CLOSEOUT_PLAN.md` — not more analysis of this session's data. Full
account: `WEEK2_GPU_SESSION_2_ATTEMPT_2_REPORT.md`.

### What the final pre-GPU pass changed

| Phase | Closed |
|---|---|
| A | Headline classification **fails closed**. A record must prove evidence class, authority flag, record version, schedule scheme, canonical membership, N, and the presence of both validity gates. Missing provenance is refused, never defaulted |
| B | The p99 population comes from the **frozen schedule** (`scheduled_offset >= warmup_boundary_s`), not from wall-clock send time. Late warmup sends can no longer enter the estimator; late canonical sends can no longer leave it |
| C | The unloaded floor has a real command: `run_on_instance.sh floor`. Canonical membership, concurrency 1, sequential, no arrival process |
| D | Steady and adversarial are **frozen and committed**. Nothing is generated on the meter. Their operating points were human decisions taken 2026-08-21, because §2.1 names a λ for neither |
| E | One contract test drives the runbook as a system, plus the cross-role controls |
| F | The stale-semantic scan now covers **active code**, not only Markdown — the defect that opened this pass was a shell line |

**Two locks gained enforcement rather than only prose.** Lock 3A (no
cross-process-epoch families) was unenforceable: no record carried a process
epoch and `vllm_restarted_between_repeats` was a hardcoded `False`. Both are now
measured. Lock 4A's forbidden re-filter is refused in both directions — a warmup
value above *or* below the frozen boundary.

### Locks added at Hard Stop R3

| Value | Locked | Why |
|---|---|---|
| `k` | 6 strata at corpus quantiles 0/50/90/95/99/99.5/100 | Fixes the canonical multiset's shape against the corpus |
| `L` | corpus q99 = 11,471 chars | A q99-length prompt already costs ~370ms TTFT *unloaded* — 74% of the SLO |
| `N` | 4,000 post-warmup scheduled arrivals per run | Smallest candidate with a ≤5% per-run classification-flip rate |
| `N_max` | 5,000 | Structural: the pinned corpus holds 5,000 prompts, so no reuse is possible past it |
| p99 definition | nearest-rank, one shared implementation | On the near-boundary sample the convention alone flips UNDER/OVER |
| prefix caching | **disabled** for the controlled headline, preflight-enforced | Exact prompt replay is the control; caching changes the cost it controls, as a function of run order |

`Y = 120s` and `n ≥ 100` are **historical locks, superseded for the redesigned
headline** — see `WEEK2_PLAN.md` §10.2/§10.3. They remain documented for the
first-session artifacts, which are still read under their original semantics.

Authoritative documents, which take precedence over this summary:

- **`WEEK2_DOC_INDEX.md`** — **start here.** The single index of which Week 2
  documents govern, which are evidence, and which are historical or superseded
  and must not be executed. Week 2 carries two design generations; directory
  names are not authority.
- **`WEEK2_GPU_SESSION_2_PLAN.md`** — the only current GPU-session runbook.
- **`WEEK2_PLAN.md`** — the decision record: what was decided and why, what is
  `LOCKED`, and every `[CALIBRATE]` value with its named source.
- **`WEEK2_EXECUTION.md`** — the execution order: blocks, hard stops, and
  definitions of done. Where the two appear to conflict on the same axis, that
  is a checkpoint to surface, not something to reconcile silently
  (`WEEK2_EXECUTION.md` §"Precedence rule").
- **`WEEK2_GPU_SESSION_2_PREFLIGHT.md`** — the R-DOC / R-PREGPU evidence
  checklist, standing between here and any GPU spend. (Session #1's Hard Stop 4
  checklist was deleted on 2026-08-20 — removed 2026-08-20; in git history at 39ed3f1.)
- **`docs/WEEK2_PRE_GPU_AUDIT.md`** — the pre-GPU audit trail: what the
  2026-08-17 audit found, and how each finding was closed.
- **`docs/WEEK2_REMEDIATION_REPORT.md`** — what was changed on 2026-08-18 and
  what it proved, including the Linux scheduler-spin calibration result and the
  hard-stop verdict.
- **`docs/WEEK2_GPU_SESSION_FINDINGS.md`** — the permanent record of GPU session
  #1: what it set out to measure, what it falsified, which conclusions are
  trusted and which are invalid.
- **`WEEK2_PLAN.md` §10** — every redesign supersession with its evidence, and
  the explicit list of locks that did *not* change.

Work proceeds in blocks separated by **hard stops** — blocking gates where the
agent produces evidence and a human renders the verdict. The summary table at
the end of `WEEK2_EXECUTION.md` lists all seven — the original five plus R3 and
R-DOC — and the failure mode each one prevents.

### Deliverable

`BASELINE.md`, stating: *at X RPS, naive single-replica serving breaches the
500ms p99 TTFT SLO*, fully sourced and reproducible from the committed
schedule and corpus artifacts. **Not yet written.** Session #2 attempt 2
established `OVER` at 0.75 but no confirmed `UNDER` anchor
(`NO_UNDER_ANCHOR`), so the interval is not yet closeable — see
`WEEK2_CLOSEOUT_PLAN.md` for the planned path to a defensible `(A, B]`.

### `[CALIBRATE]` values

Tracked with their named sources in `WEEK2_PLAN.md` §8. **All resolved.** The
per-point warmup N was the last one open, and the redesign closed it by changing
its shape rather than by measuring it — see the note under the table:

| Value | State |
|---|---|
| Concurrency cap | **3000** (2026-08-17) |
| Offered-vs-achieved band | **±5%** (2026-08-18) |
| Measurement window Y | **120s** (2026-08-18) — superseded for the headline by `N = 4,000` (§10.2) |
| Mock timing spin (Block 0) | **Resolved** — Windows-only fix (2026-08-16) |
| Loadgen scheduler spin | **Resolved** — platform-specific defaults (2026-08-18) |
| Per-point warmup N | **Resolved structurally** — frozen 60s boundary, validated forward in Tier A |

**This entry changed shape in the redesign, and the old shape is the single most
dangerous stale instruction in the repo.** Under session #1's superseded
fixed-duration design it was open by design: measure first, read the
flatten-point off the Stage A transient afterwards, and apply it as a
**re-filter over the committed sidecars** — legitimate then, because a
fixed-duration window held a surplus of samples.

Under exact-N it is not. The 60s boundary is **frozen into the schedules**:
exactly N arrivals are materialized at or after it, so filtering later discards
canonical arrivals and silently leaves fewer than N measured samples.
`metrics/headline_point.py` refuses it. The boundary is instead **validated
forward** at Hard Stop GPU-1 against session #2's Tier A transient, and if 60s
proves insufficient the schedules are **regenerated offline at a larger
boundary** — never re-filtered after the fact (`WEEK2_PLAN.md` §11.4).

## Known issues

**None blocking.** The mock/vLLM faithfulness regression
(`test_real_stream_key_set_matches_mock`) is **fixed** as of 2026-08-18 — the
mock's three chunk kinds now carry the same key sets real vLLM 0.27.1 sends,
verified in both directions against the captured fixture, with the parser
contract untouched (`metrics/parse.py` still classifies an empty
`delta.content` as a non-content chunk).

*Historical note:* that failure was latent rather than new. `pytest tests`
previously died during collection — two test files shared the basename
`test_negative_controls.py` with no package markers — so the documented command
never reached the suite. Adding `__init__.py` to the test packages fixed
collection and surfaced it.

**One environment-only flake, not a regression:**
`tests/integration/test_end_to_end.py::test_end_to_end_fast_config` asserts the
mock delivers its configured 100ms TTFT within ±10ms. It passes standalone and
can exceed the band under full-suite contention on the Windows dev box, because
`mock_base_url` is session-scoped (`tests/conftest.py`) — one single-process
mock serves all tiers, including the loadgen tier's high-RPS sweeps. This is the
machine-drift signal `WEEK2_PLAN.md` §7 defers, and mock latency is outside the
trusted set (`MOCK_TRUST_BOUNDARY.md`) — it is not a Week 2 measurement input.
The tolerance has deliberately **not** been widened to hide it.

### Session-start decisions

Items deliberately left open for the human at the start of the metered GPU
session, rather than defaulted silently — `--enforce-eager` and the
output-token policy. Both now carry their session #2 resolution in
`WEEK2_GPU_SESSION_2_PLAN.md` §0 (output `max_tokens` = 512 is locked;
`--enforce-eager` stays a knob, but whichever mode the server comes up in, every
point in the session must run that same mode). The original trade-off write-ups
survive only in git history (removed 2026-08-20; in git history at 39ed3f1), as rationale.
(The budget-alert ladder was previously on this list; it is now resolved as
$10 / $75 / $135 / $150.)

# Week 2 — GPU session #2, first attempt: report and outcome

> **STATUS: EVIDENCE — DOES NOT GOVERN EXECUTION**
>
> Role: the record of what actually happened during the 2026-08-22 GPU
> session — what ran, what it found, and why the session stopped where it
> did. It decides no experiment semantics and is **not** a GPU runbook.
> Current GPU commands live in `WEEK2_GPU_SESSION_2_PLAN.md`. Index:
> `WEEK2_DOC_INDEX.md`.

## 1. Executive summary

GPU session #2 ran on 2026-08-22 against benchmark SHA `625bc0e2ea69c1687991a2825c02192c145ef846`.
It completed the unloaded floor and the full Tier A scout sweep cleanly, then
drove **one repeat** of Tier B (headline confirmation) at the human-chosen
λ = {1.5, 2.0, 2.5}. All three Tier B points came back `CENSORED` — 27–37%
of requests exceeded the 60-second client timeout waiting for a first token
— even at λ=1.5, the lowest of the three, despite Tier A's short-window scout
having read λ=1 as cleanly `UNDER` and λ=2 as only barely `OVER` (0%
censoring). The session was stopped deliberately after repeat 1 rather than
continuing to repeats 2–3: the frozen headline family had no `UNDER` anchor
left in it under sustained load, so finishing the remaining repeats would
almost certainly have reproduced the same `CENSORED` result without adding
information. The instance was torn down cleanly with all collected evidence
pulled and hash-verified.

**No breach RPS was established this session.** What the session did
establish is a genuine, load-bearing finding: Tier A's N=500 scout window is
too short to detect real queue instability that only manifests over Tier B's
N=4000 / 30–45-minute sustained window. That finding is itself the reason a
second attempt needs a redesigned λ range, which has already been generated
and committed to the working tree (§7) as part of closing this report out —
not yet pushed or re-approved.

## 2. Session identity

| Field | Value |
|---|---|
| Benchmark SHA | `625bc0e2ea69c1687991a2825c02192c145ef846` ("week2: final pre-GPU remediation (Phases A–G)") |
| Instance | `llmrouter-vllm-l4-week2`, `g2-standard-8` + 1× L4, **SPOT**, `us-central1-a` |
| Model | `meta-llama/Llama-3.2-3B-Instruct` |
| Resolved server config | `enforce_eager=1`, `disable_prefix_caching=1`, `max_model_len=20000` — all matching locked policy |
| vLLM process epoch | `vllm-start-1787371674` (2026-08-22T04:07:54Z) — single epoch for the whole session; no spot preemption occurred |
| Prefix-cache verdict | `PREFIX_CACHING_DISABLED` (min replay ratio 0.94, all probes ≥ 0.85) |
| Canonical headline membership | `a49ecdd8071920303f240fcf0b8da42dbbc66da593ae88e3c07aa246c4b5aa7b` (4,000 prompts) |
| Canonical scout membership | `e9470f8f85f22835...` (500 prompts) |

## 3. Pre-session gate state

Before this session, `STATUS.md` and `WEEK2_GPU_SESSION_2_PREFLIGHT.md` both
recorded **Hard Stop R-DOC needing a re-run** (the 2026-08-21 remediation
commit had edited the executable runbook after R-DOC's original 2026-08-19
pass) and **Hard Stop R-PREGPU as never rendered**. All GPU-free evidence
underneath those gates was independently re-verified before this session:
478/478 non-router tests, 353/353 redesign tests, 13/13 and 6/6 control-bite
scripts, 24/24 promoted first-session hashes, all 32 then-committed
schedule/manifest files present and tracked.

**The human explicitly rendered both verdicts and directed the session to
proceed**, including an explicit override of `create_instance.sh`'s own
"the agent does not stand up, drive, or tear down this instance" restriction
— recorded here because that restriction is a deliberate repository policy,
not a default this report should let get quietly forgotten in git history.

## 4. What ran

| Step | Result |
|---|---|
| `create_instance.sh` | Instance created, SPOT confirmed via API read-back |
| HF authentication | Gated-model token supplied by the human, transferred via `scp` to an absolute remote path, never echoed into a command string or committed |
| `setup_and_launch_vllm.sh` launch | **Failed on first attempt** — CRLF line endings from git checkout broke the remote `bash` parse (`$'\r': command not found`). Fixed by transferring an LF-normalized copy from a scratch location rather than editing the tracked file (would have dirtied the pinned tree). See the new entry in `GPU_SESSION_NOTES.md`. Second attempt succeeded cleanly, no wasted GPU time (failure was immediate, before any download) |
| `run_on_instance.sh bootstrap` | Pinned instance to `625bc0e...`, clean |
| `run_on_instance.sh check` | fd limit raised to 65535, L4 visible (21GB free), vLLM healthy, corpus present |
| `run_on_instance.sh verify-cache` | **PASS** — `PREFIX_CACHING_DISABLED` |
| `run_on_instance.sh floor` | **4000/4000 served, 0% censoring.** p50/p95/p99 = 84.9 / 209.8 / 411.75 ms. 88ms headroom to the 500ms SLO (plan had projected ~130ms from the first-session fit — headroom came in tighter than projected but still comfortably under) |
| Tier A scout, λ ∈ {1, 2, 4, 8} | See §5 |
| **Hard Stop GPU-1** | Human verdict: crossing bracketed (between λ=1 and λ=2), 60s warmup boundary sufficient (transient settles by t≈30s). Tier B λ set chosen: **{1.5, 2.0, 2.5}** |
| Tier B repeat 1, λ ∈ {1.5, 2, 2.5} | See §6 — all three `CENSORED` |
| Decision point | Human decision: **stop rather than continue to repeats 2–3** |
| Artifact pull | Floor, scout (4 pts), headline repeat 1 (3 pts), prefix-cache verdict, vLLM launch log — all pulled and hash/completeness-verified |
| `teardown_week2.sh` | Instance deletion **verified** (not just exit-code-trusted); confirmed independently via a fresh `gcloud compute instances list` (0 items); `.gpu_session_target` cleaned up |

## 5. Tier A — scout results (N=500, DIAGNOSTIC only)

| λ | state | p99 TTFT | censoring | shed | notes |
|---|---|---:|---:|---:|---|
| 1 | UNDER | 475.6ms | 0.0% | 0 | |
| 2 | OVER | 502.6ms | 0.0% | 0 | barely over the 500ms SLO |
| 4 | OVER | 49,543ms | 0.0% | 0 | deep saturation |
| 8 | CENSORED | — | 59.8% | 0 | 344/961 errored (`ReadTimeout`) |

All gates clean at every point (`exact_n_honoured: true`, `schedule_delivery_ok: true`).
The λ=1 point's TTFT-vs-wall-clock trace showed a real cold-start transient
(mean TTFT ~870–1240ms at t=10–20s) fully resolved by t≈30s, well inside the
frozen 60s warmup boundary — this is what cleared Hard Stop GPU-1's second
question.

## 6. Tier B — headline repeat 1 (N=4000, `headline_evidence`)

| λ | state | censoring | issued (errored) |
|---|---|---:|---|
| 1.5 | **CENSORED** | 36.2% | 4089 (1447 `ReadTimeout`) |
| 2.0 | **CENSORED** | 37.2% | 4106 (1489 `ReadTimeout`) |
| 2.5 | **CENSORED** | 27.5% | 4134 (1099 `ReadTimeout`) |

`vllm_restarted_between_repeats: false` — the whole repeat ran under one
process epoch, so this is not a preemption artifact. All gates on each point
are otherwise clean (`exact_n_honoured: true`, `schedule_delivery_ok: true`,
`n_shed: 0`); the censoring gate (>5%) is the only thing that fired, and it
fired hard, well past the boundary the tail-sensitivity-review exception
would apply to.

### Why this contradicts Tier A, and what it means

Tier A's λ=1 and λ=2 scout points (N=500, drawn over ~5.5 and ~4.2 minutes
respectively) showed **0% censoring**, clean p99s. Tier B's λ=1.5 and λ=2
points (N=4000, drawn over ~45 and ~34 minutes) showed **36–37% censoring**.
The most likely mechanism is duration itself: a queue that is only
marginally unstable can look flat over 5 minutes and still be accumulating
faster than it drains over 30–45 minutes, eventually pushing a large fraction
of requests past the 60-second client timeout. This is the same *class* of
failure that motivated the whole Week 2 redesign — a short measurement window
concealing real sustained-load behavior — just recurring one level up, in
Tier A's own scout rather than in session #1's fixed-duration sweep.

**Practical consequence:** none of the five frozen headline λ values
(`{1.5, 2, 2.5, 3, 4}`) is a demonstrated `UNDER` point under sustained load.
The committed family cannot, by itself, bracket a breach RPS — every point
in it either is already `CENSORED` (1.5, 2, 2.5, driven) or is certain to be
worse (3, 4, undriven but strictly higher load than already-`CENSORED`
points). Continuing repeats 2–3 at the same λ set would spend roughly 3.6
more hours of GPU time to almost certainly reproduce the same three
`CENSORED` results, without narrowing where the real breach is.

## 7. What happens next — schedule redesign (done as part of closing this out)

Generated and verified (offline, GPU-free) after this session, using the
same generators and seed scheme as the original family so every previously
committed and already-GPU-driven schedule reproduces byte-for-byte
unchanged:

| Family | Old | New | What changed |
|---|---|---|---|
| `headline/` | 5 λ × 3 repeats = 15 files | **9 λ × 3 repeats = 27 files** | Added λ ∈ {0.5, 0.75, 1.0, 1.25} as lower anchors below the now-known-bad 1.5 |
| `secondary_steady/` | 5 files | **9 files** | Same 4 new λ added, appended (not sorted) into the generator's lambda tuple to keep the original five schedules' seeds — and therefore bytes — unchanged |
| `secondary_natural/` | 5 files | **9 files** | Same 4 new λ added; this family's seeding is lambda-value-based, not position-based, so order doesn't matter here |
| `scout/`, `adversarial/` | unchanged | unchanged | Not implicated by this finding |

Verified explicitly, not assumed:
- All 15 pre-existing `headline/` schedules: **byte-identical** before/after.
- All 5 pre-existing `secondary_steady/` schedules: **byte-identical** before/after.
- All 5 pre-existing `secondary_natural/` schedules: **byte-identical** before/after.
- `scripts/generate_secondary_scenarios.py --verify`: **PASS** (10 schedules reproduce byte-for-byte, matches manifest, no unlisted files).
- `pytest tests/redesign`: **353 passed** (two tests updated for the new,
  intentionally-larger family sizes — `test_no_scenario_needs_live_generation`
  and `test_the_steady_family_is_committed_at_the_decided_lambdas` in
  `tests/redesign/test_secondary_scenarios.py` — both encoded the *old*
  committed counts as the expected policy, which this redesign deliberately
  changes).
- `scripts/show_control_bites.py`: 13/13. `scripts/show_doc_control_bites.py`: 6/6.

**These new schedules are staged in git (`git add`), not committed.** No
commit, push, or new benchmark SHA has been cut. That step — along with a
fresh R-DOC pass (this report and the schedule changes touch the working
tree again) and a new R-PREGPU rendering — is still ahead of any further GPU
spend, unchanged from what stopping the session was meant to preserve.

### Known documentation drift this report does not fix

`WEEK2_GPU_SESSION_2_PLAN.md` and `WEEK2_PLAN.md` still describe the
5-λ / 15-schedule headline family, the λ ∈ {1.5, 2, 2.5, 3, 4} menu for
Tier B's λ-selection rule, and drive-time tables sized to the old family.
None of that is caught by the automated stale-semantics scan (it matches
known dead *concepts*, not arbitrary numeric drift), so it will not fail a
test — but a fresh reader of the runbook right now would still see the old
menu. This needs its own documentation pass before a next GPU session,
mirroring the R-DOC cycle already established for exactly this kind of
change.

## 8. Artifacts on disk

All pulled, hash/completeness-checked, and left in place:

| Path | Contents |
|---|---|
| `benchmarks/runs/floor/` | Unloaded floor: `floor.raw_log.jsonl`, `.samples.jsonl`, `.metrics.json` |
| `benchmarks/runs/scout/` | 4 Tier A points, `scout_diagnostic` |
| `benchmarks/runs/headline/` | Tier B repeat 1, 3 points, `headline_evidence`, plus `family_report.json` |
| `benchmarks/runs/preflight/prefix_cache_verdict.json` | Gate verdict |
| `benchmarks/runs/vllm.log` | Full launch log, resolved config |

**Not collected**, by deliberate decision rather than failure: Tier B
repeats 2–3, and all of the secondary scope (natural-random, steady,
adversarial) — those share the λ family this session showed has no `UNDER`
anchor, so driving them now would only have reproduced the same problem.

## 9. Approximate cost and duration

vLLM came up at 2026-08-22T04:07:54Z; teardown completed the same day
mid-morning UTC. Total instance lifetime, including setup, all driven points,
and the human deliberation at Hard Stop GPU-1 and the stop/continue decision
(the meter runs the whole time regardless of what is actively being driven),
was on the order of **5.5–6 hours**. At the plan's own stated spot rate for
`g2-standard-8` + L4 (~$0.40–0.50/h), that puts this session at roughly
**$2.20–3.00** — well inside the $10 canary threshold on the budget ladder.

## 10. Summary of the actual outcome

- No breach RPS established.
- A real, gate-clean finding was collected: **the naive single-replica setup
  is already severely censored (27–37% timeout) at every headline λ tried,
  including the lowest (1.5), under sustained load** — worse and lower than
  Tier A's short-window scout indicated.
- A methodological gap was surfaced: N=500 Tier A scouting cannot reliably
  characterize sustained-load stability near a crossing; only Tier B's
  duration reveals it. This is worth carrying into any future redesign of the
  two-tier scout/confirm structure itself, not only into picking new λ.
- The instance was torn down cleanly, with no spot preemption, no orphaned
  billing, and full evidence preservation.
- A redesigned, wider headline/steady family is generated, verified, and
  staged — ready for commit once R-DOC/R-PREGPU are re-cleared for a second
  attempt.

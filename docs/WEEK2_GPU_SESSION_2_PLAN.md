# Week 2 — GPU session #2 plan (proposed)

**Status: PROPOSED. Requires human approval at Hard Stop R-PREGPU.** No
instance may be created until this plan is signed off.

The first session spent its money discovering that its own experimental design
was unsound. This one executes an experiment that is already fully specified.
Everything discoverable offline has been discovered; the meter is for
collecting raw artifacts, not for deciding anything.

- Locks: `WEEK2_PLAN.md` §10
- Why the redesign exists: `docs/WEEK2_GPU_SESSION_FINDINGS.md`
- Calibration: `benchmarks/calibration/week2_redesign/R3_EVIDENCE_PACKAGE.md`
- Repeat/evidence policy: `benchmarks/workloads/week2_headline/repeat_policy.json`

---

## 0. Why two tiers

**The old bracket is not authoritative.** The first session's 1.5 RPS point is
prefix-cache confounded, so "1.5 under, 5 over" is not a bracket the redesigned
experiment inherits. Two things also moved the crossing since:

- **Prefix caching is now off.** Every request pays full prefill where the
  first session was getting a 12–16% engine-wide hit rate. The server is doing
  strictly more work at the same λ, so the crossing should move **down**.
- **The workload changed composition.** The canonical multiset holds the
  corpus's natural shape exactly, including the 44,445-char prompt that was
  never drawn before. Its intrinsic tail is heavier than most first-session
  realizations.

Both push the same way, and neither is quantified. Jumping straight to a
full-N sweep at 1.5–2 RPS could therefore spend 5 hours of calibrated evidence
entirely on one side of the crossing.

So: **scout cheaply, then confirm expensively, and only on points that can
decide the answer.**

---

## 1. Preflight (before the meter starts)

Standing Hard Stop 4 checklist plus the redesign items:

| Item | Evidence |
|---|---|
| Canonical workload frozen | `benchmarks/workloads/week2_headline/canonical_v1.json`, `membership_id a49ecdd8…` |
| Capacity proven | `tokenizer_capacity_report.json`, PASS: 10,482 max input + 512 output + 1,099 margin = 12,093 ≤ 20,000 |
| `--max-model-len` | **20000** — unchanged, now backed by exact tokenizer evidence rather than a char estimate |
| Schedules committed | `benchmarks/schedules/week2_redesign/` (15 headline + 5 secondary) |
| Repeat policy signed off | `repeat_policy.json` — **still `PROPOSED`** |
| All controls bite | `scripts/show_control_bites.py` (13 red-then-green) + `tests/redesign/` |
| Regression suites green | see §7 |
| Quota / budget ladder | $10 canary / $75 / $135 / $150 hard line |
| Teardown dry-run | `DRY_RUN=1 bash scripts/gpu_session/teardown_week2.sh` |

---

## 2. On-instance sequence

```
 1. stand up 1x L4 spot, launch vLLM                        ~15 min
      DISABLE_PREFIX_CACHING=1  (default)
      MAX_MODEL_LEN=20000
 2. verify_prefix_cache_disabled.py            GATE          ~3 min
 3. Tier A: clean unloaded floor over the canonical set     ~10 min
 4. Tier A: scout sweep                                     ~20 min
      -- HUMAN READ: crossing region, warmup transient --
 5. Tier B: confirmation sweep, repeat-major            2.8-5.4 h
 6. Secondary natural-random curve                        30-50 min
 7. pull artifacts, verify, teardown                        ~15 min
```

### Step 2 — the gate that has no equivalent in session #1

`scripts/gpu_session/verify_prefix_cache_disabled.py` sends the three longest
canonical prompts twice each and compares TTFT. A replay at ≤0.75× its first
serving means the cache is live and the script **exits non-zero**. The CLI flag
is not accepted as evidence: it can be renamed between vLLM releases or applied
to a different server than the one being driven.

**If this gate fails, no headline point may be driven.** Relaunch and re-verify.

### Step 3 — a real unloaded floor, over the real workload

Concurrency 1, all 4,000 canonical prompts, prefix caching off, stop at first
content token. ~4,000 × ~100ms ≈ 7 min.

This replaces the first session's floor, which is classified
`CACHE_INFLUENCED_DIAGNOSTIC` and can no longer be cited. It is also better
than its predecessor in kind, not just in cleanliness: the old floor sampled
248 prompts from one schedule's realized draw, while this measures the
**exact multiset the headline curve uses**, so the intrinsic p99 it produces is
the floor that curve actually starts from rather than an estimate of it.

Projected (from the first session's fit, so treat as an order of magnitude,
not a prediction): unloaded p99 ≈ 370ms, leaving ~130ms of headroom to the SLO.

---

## 3. Tier A — diagnostic scouting

> **Diagnostic only. Scout points may locate the region. They may not produce
> an UNDER/OVER headline claim, and they never enter the classification.**

| Parameter | Value | Why |
|---|---|---|
| λ points | **1.0, 2.0, 4.0, 8.0** | Wide, cheap, brackets a crossing that has moved by an unknown amount |
| N per point | **500** | ~34% per-run flip rate — useless for a verdict, ample for locating a knee |
| Repeats | 1 | Scouting, not evidence |
| Warmup boundary | 60s | Same as Tier B, so the transient read transfers |
| Drive time | 500/1 + 500/2 + 500/4 + 500/8 + 4×60 ≈ **20 min** | |

Scout schedules are generated offline and committed alongside the Tier B family
(`--lambdas 1 2 4 8 --repeats 1` against a 500-prompt canonical subset; the
subset is a *scout* artifact and is namespaced separately so it can never be
mistaken for the headline membership).

### What the human reads off Tier A

1. **The crossing region** — which λ are clearly under, which clearly over.
2. **The warmup transient** — TTFT vs wall-clock, to resolve the per-point
   warmup N that has been `[CALIBRATE]` since §2.4.
3. **Sanity gates** — 0 shed, censoring 0%, `exact_n_honoured` true,
   `schedule_delivery_ok` true at every scout point.

**Constraint on (2):** the resolved warmup must be **≤ 60s**, the boundary the
Tier B schedules were frozen with. Exactly N arrivals were materialized at or
after that boundary, so filtering later would discard canonical arrivals and
leave fewer than N measured samples — `metrics/headline_point.py` refuses it
rather than letting the count quietly drop. If the transient runs past 60s,
**regenerate the Tier B schedules at a larger boundary** before driving them.
That is a few seconds of offline work, not a session restart.

---

## 4. Tier B — headline confirmation

| Parameter | Value |
|---|---|
| λ points | **3**, chosen from the Tier A bracket: the highest clearly-under, the lowest clearly-over, and one between |
| N per point | **4,000** (locked) |
| Repeats | **3** (policy `min_valid_repeats`) |
| Order | **repeat-major** — see below |
| Separation | drain to in-flight = 0, then each repeat's own warmup. **No vLLM restart.** |

### Repeat-major ordering is a deliberate choice

```
r1: λ_low → λ_mid → λ_high      (drain between each)
r2: λ_low → λ_mid → λ_high
r3: λ_low → λ_mid → λ_high
```

Not λ-major. This is a spot-preemption hedge: a preemption at hour 4 leaves
**two complete sweeps** rather than three complete λ points and nothing at the
others. Two complete repeats is a reportable (if UNCERTAIN) result; a partial
λ-major sweep is not.

### Drive time

Per repeat, at the worst-case (lowest) λ set:

| λ set | per repeat | × 3 repeats |
|---|---:|---:|
| 1.5 / 2.0 / 2.5 | 1.79 h | **5.37 h** |
| 2.0 / 2.5 / 3.0 | 1.28 h | 3.83 h |
| 3.0 / 4.0 / 5.0 | 0.92 h | 2.76 h |

The committed 15-schedule family covers λ ∈ {1.5, 2, 2.5, 3, 4} × 3 repeats;
only the three chosen λ are driven. The rest are staged, not spent.

---

## 5. Classification and the stop condition

Applied **offline, after teardown**, from
`benchmarks/workloads/week2_headline/repeat_policy.json`:

```
min_valid_repeats      3
require_unanimous      true
n_per_run              4000
n_max                  5000
max_repeats_authorized 3
```

- A repeat that is `CENSORED`, missed exact-N, or failed delivery fidelity is
  **excluded, never pooled**.
- A boundary-determining point with sub-5% censoring and no completed
  tail-sensitivity review **cannot finalize** — it stays `UNCERTAIN`.
- 2-1 splits are `UNCERTAIN`, not a majority verdict. Near the SLO the split
  *is* the finding.

### The stop condition, stated before the money is spent

If the crossing is unresolved once the ceiling is reached:

```
breach interval = (highest defensible UNDER λ, lowest defensible OVER λ]
```

and the session **stops**. It does not escalate. A ≤1% per-run flip rate would
need N ≈ 7,500, which is above `N_max = 5,000` and therefore unreachable with
this corpus — so an interval is a legitimate final answer, not a failure.

### The one pre-authorized escalation

If **exactly one** boundary-determining λ is `UNCERTAIN` after 3 valid repeats,
one escalation may be authorized in advance: re-drive that λ alone at
`N = 5,000` for all 3 repeats. At λ=2 that is +2.1 h.

`repeat_policy.json` currently records `"authorized": null`. **The human sets
it before the session, not during.**

---

## 6. Cost, risk, and the branch points

| | Estimate |
|---|---|
| Total session | **4.3 – 7.2 h** (Tier B dominates) |
| Instance | `g2-standard-8` + 1× L4, Spot |
| Rate | ~$0.40–0.50 / h |
| **Cost** | **~$1.70 – $3.60** |
| Budget ladder | $10 canary may fire; $150 hard line is not in reach |

**The binding constraint is wall-clock and spot preemption, not money.**

### Pre-authorized branches (no on-meter improvisation beyond these)

| Situation | Action |
|---|---|
| Prefix-cache gate fails | Relaunch with `DISABLE_PREFIX_CACHING=1`, re-verify. No headline points until it passes. |
| Tier A shows every point over | Scout downward (λ 0.5, 0.25) before spending Tier B evidence. |
| Tier A shows every point under | Scout upward (λ 16, 32). |
| Warmup transient > 60s | Regenerate Tier B schedules at a larger boundary, offline, then proceed. |
| Any scout point sheds | Stop. The cap is shaping results; that is an instrument finding, not a server one. |
| Preempted after ≥2 complete repeats | **Human decision, see below.** |
| Preempted mid-repeat | Discard the partial repeat. Its artifacts stay as diagnostics. |

### The preemption question this plan cannot resolve alone

D4 forbids restarting vLLM between repeats, so the repeatability estimate
measures arrival/queue variability rather than cold-process variance. A spot
preemption **forces** a restart. If the session dies after two complete
repeats, the third cannot be added in a new process and still satisfy D4 as
written.

Three options, all of which are the human's call and should be decided
**before** the session:

1. **Report with 2 repeats**, marked `UNCERTAIN` where the policy requires 3.
2. **Redo all 3 repeats** in a fresh session (the schedules are frozen, so this
   is exactly reproducible — only meter time is lost).
3. **Relax D4 with recorded provenance**, accepting the third repeat from a new
   process and documenting that it carries process-initialization variance the
   other two do not.

---

## 7. Artifacts and teardown

- **Pull incrementally**, after each repeat, not only at session end. The
  first session pulled once at the end and it worked; it worked because nothing
  went wrong. Over a 5-hour spot session that is a bet, and
  `pull_artifacts.sh` is cheap to run repeatedly.
- Fractional-RPS names (`headline_r1_rps1.5.*`) now survive the completeness
  checker — that fix is a precondition of this session, since every headline
  tag is fractional or repeat-tagged.
- Teardown with `scripts/gpu_session/teardown_week2.sh`, never bare
  `teardown.sh`, and **verify deletion in the console**.
- Promote accepted points into `benchmarks/evidence/week2/session_2/` with a
  hash manifest, the same way session #1's were.

---

## 8. Out of scope, flagged rather than dropped

`WEEK2_PLAN.md` §2.1 also calls for a **steady-arrival reference curve** and an
**adversarial long-context scenario**, and §6.2 orders adversarial last. The R4
continuation README does not mention either.

They are **not** included in the estimates above. Whether session #2 carries
them, or they move to a later session, is a scope decision for the human — it
is roughly +30–60 min for steady over the confirmation λ, and the adversarial
scenario should still run last if it runs at all, since it deliberately drives
the replica toward saturation.

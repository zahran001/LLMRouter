# Week 2 — GPU Session #2, Attempt 2 Plan

> **STATUS: EVIDENCE — DESIGN LOCKED, NOT YET EXECUTABLE**
>
> Role: proposed redesign for a second GPU session #2 attempt, written after
> Attempt 1's all-`CENSORED` Tier B result (`WEEK2_GPU_SESSION_2_REPORT.md`).
> §14's decisions were locked 2026-08-22 and the supporting code is being
> implemented from them. It still does not drive anything — the live runbook
> remains `WEEK2_GPU_SESSION_2_PLAN.md` until (and unless) this design is
> merged into it, which is a separate, deliberate step (`WEEK2_DOC_INDEX.md`'s
> "exactly one current GPU runbook" rule) requiring its own R-DOC/R-PREGPU
> cycle after implementation lands.
> Index: `WEEK2_DOC_INDEX.md`.

> **Purpose:** finish Week 2 by locating the **sustained** RPS boundary where a naive single vLLM replica breaches the **500 ms p99 TTFT SLO**.
>
> **Why this plan changed:** Attempt 1 showed that the old N=500 Tier A scout could look healthy for a few minutes while the queue was actually unstable over 30–45 minutes. The next run therefore makes **minimum sustained duration** a first-class requirement instead of treating duration as an accidental consequence of N.

---

## 1. What carries forward unchanged

Keep the server/workload configuration identical so the next run remains comparable with Attempt 1:

- Model: `meta-llama/Llama-3.2-3B-Instruct`
- 1× NVIDIA L4
- `--enforce-eager` **ON**
- prefix caching **OFF**, behaviorally verified before measurements
- `--max-model-len 20000`
- output cap `max_tokens=512`
- on-instance load generator over loopback
- concurrency cap `3000`
- Linux scheduler spin `0 ms`
- frozen 60 s warmup boundary
- canonical headline workload / corpus identity unchanged
- nearest-rank percentile implementation unchanged

**Reason:** changing any of these now would create a new baseline configuration and make the previous unloaded-floor / scout / Tier B evidence harder to compare.

---

## 2. What Attempt 1 established

Attempt 1 already gave us:

- unloaded canonical p99 TTFT: **411.75 ms**
- only ~**88 ms headroom** to the 500 ms SLO
- N=500 scout:
  - 1 RPS → `UNDER`, 475.6 ms
  - 2 RPS → `OVER`, 502.6 ms
- sustained Tier B:
  - 1.5 RPS → 36.2% censored
  - 2.0 RPS → 37.2% censored
  - 2.5 RPS → 27.5% censored

Therefore the useful sustained boundary is **below 1.5 RPS**.

The new search region is:

```text
0.5, 0.75, 1.0, 1.25 RPS
```

---

# 3. Stage 0 — process/config sanity

Before any load point:

1. launch vLLM with the same locked config;
2. verify prefix caching is disabled;
3. verify fd limit / load-generator environment;
4. record process epoch and benchmark SHA;
5. rerun the canonical unloaded floor.

### Floor acceptance

The floor is not used to redefine the SLO. It is a process sanity check.

If the new floor is materially different from Attempt 1's **411.75 ms p99**, stop and investigate before comparing load curves.

---

# 4. Stage A — sustained scouting

## Key redesign

Do **not** use N=500 scouting to locate the sustainable knee.

Drive:

```text
λ = 0.5, 0.75, 1.0, 1.25
```

one sustained diagnostic run each.

### Per-point duration/sample rule

Each scout schedule must satisfy **both**:

- at least **45 minutes** of post-warmup offered load;
- at least **2,000** canonical post-warmup requests.

For each λ, generate Poisson arrivals offline until the **first arrival for which both conditions are true**:

```text
post_warmup_elapsed >= 2700s
AND
post_warmup_arrivals >= 2000
```

Then stop generation and freeze that realized schedule exactly. Do **not** set
`N = λ × 2700`; under Poisson arrivals that is only an expected count and does
not guarantee a 45-minute run.

Expected behavior:

| λ | What usually binds | Expected post-warmup size / duration |
|---:|---|---|
| 0.50 | 2,000-request floor | N = 2,000; ~66.7 min on average |
| 0.75 | both are close | N ≈ 2,025; ≥45 min |
| 1.00 | 45-minute floor | N ≈ 2,700; ≥45 min |
| 1.25 | 45-minute floor | N ≈ 3,375; ≥45 min |

The exact N is allowed to differ across λ and repeats during **generation**;
once generated, each schedule's realized N and membership are frozen and
replayed exactly.

### Why this design

The previous failure was **time-dependent queue accumulation**.

A fixed N alone makes low-RPS points long and higher-RPS points short. A fixed duration alone can leave too few p99-tail observations at low RPS.

The combined rule gives:

- enough wall-clock time for a slowly diverging queue to reveal itself;
- at least ~20 observations in the top 1% of every scout sample;
- frozen, reproducible exact-N membership.

### What to inspect

For each scout point record:

- p99 TTFT / censoring state
- TTFT vs wall-clock / rolling windows
- scheduling fidelity
- exact-N membership
- shed count
- vLLM running/waiting queue depth as **diagnostic only**

Queue depth helps explain whether latency is drifting because backlog is accumulating, but it does **not** define the published breach.

---

# 5. Sustained scout classification

Use the 500 ms p99 TTFT SLO as before, but improve censoring interpretation.

### `UNDER`

- ordinary p99 is identifiable;
- p99 TTFT < 500 ms;
- all validity gates clean;
- no sustained upward drift indicating unresolved queue instability.

### `OVER`

- ordinary p99 is identifiable;
- p99 TTFT >= 500 ms;
- all validity gates clean.

### `OVER_CENSORED`

If at least 1% of requests are censored waiting for first token, ordinary p99 is not reported numerically, but the SLO breach is already proven:

```text
>=1% of requests have TTFT > 60s
⇒ p99 TTFT > 60s
⇒ p99 TTFT > 500ms
```

### `UNCERTAIN`

Use when delivery validity fails, the percentile is not identifiable under the censoring pattern, or the point shows ambiguous/nonstationary behavior that cannot support a clean classification.

**Do not drop timed-out requests and compute p99 only from survivors.**

---

# 6. Stage B — choose the confirmation bracket

After the sustained scout, choose:

1. **highest defensible sustained `UNDER`**
2. **lowest defensible sustained `OVER` / `OVER_CENSORED`**
3. one frozen point between them **if the committed λ grid contains one**

Example:

```text
0.75 UNDER
1.00 UNDER
1.25 OVER
```

Then the useful confirmation family is centered on:

```text
1.00 and 1.25
```

with an intermediate point only if one has been pre-generated.

### Important

Do not invent a new λ on the meter.

If the sustained scout still has no `UNDER`, stop and extend downward offline.

If all four are `UNDER`, stop and extend upward offline.

---

# 7. Stage B — headline confirmation

The final headline points use **3 independent repeats**.

## Duration/sample rule

Use the same principle as sustained scouting:

- minimum **45 minutes** post-warmup per repeat;
- minimum **2,000** canonical requests per repeat;
- exact N frozen into each schedule.

This replaces the old universal `N=4000`, whose duration became impractical at the new lower RPS range.

### Why

The final estimator needs both:

- enough tail observations for p99;
- enough sustained time to expose slow queue divergence.

The old N=4000 design guaranteed many samples, but at 0.5 RPS one repeat would take >2 hours. The new rule keeps the **property we learned matters — sustained stability —** while retaining a reasonable p99 sample floor.

---

# 8. Repeat ordering

Keep repeat-major ordering for Spot-preemption resilience, but counterbalance point order:

```text
repeat 1: low  → mid  → high
repeat 2: high → mid  → low
repeat 3: mid  → low  → high
```

Drain server running/waiting requests to zero between points; do not restart vLLM between normal repeats.

**Reason:** every repeat still covers the whole bracket, but λ is no longer systematically correlated with process age / session time.

If Spot preemption creates a new vLLM process epoch, do not combine epochs into one final classification family.

---

# 9. Final point classification

Use all 3 valid repeats.

```text
UNDER + UNDER + UNDER
→ UNDER

OVER/OVER_CENSORED + OVER/OVER_CENSORED + OVER/OVER_CENSORED
→ OVER

any mixed classification
→ UNCERTAIN
```

No majority vote.

If the exact boundary remains unresolved, report the defensible interval:

```text
(highest confirmed UNDER, lowest confirmed OVER]
```

An interval is an acceptable Week 2 result.

---

# 10. Secondary scenarios

Do **not** spend GPU time on natural-random, steady, or adversarial scenarios until the headline sustained boundary is successfully established.

After the headline closes:

1. natural-random secondary around the confirmed boundary;
2. steady-arrival reference around the same operating region;
3. adversarial long-context scenario last.

These scenarios explain the headline; they never redefine it.

---

# 11. No-improvisation rules

| Observation | Action |
|---|---|
| New unloaded floor materially inconsistent with Attempt 1 | STOP, investigate |
| No sustained `UNDER` in 0.5–1.25 | STOP, extend downward offline |
| All 0.5–1.25 are sustained `UNDER` | STOP, extend upward offline |
| >=1% first-token censoring | classify `OVER_CENSORED`; suppress numeric ordinary p99 |
| shed > 0 | invalidate point / investigate client shaping |
| schedule fidelity fails | invalidate point |
| exact-N membership fails | invalidate point |
| process preempted | discard partial repeat; new process epoch cannot complete old family |
| code or workload change required | STOP; new benchmark SHA |
| desire to add an uncommitted λ | STOP; generate offline |

---

# 12. Expected next-run flow

```text
same server config
      ↓
prefix-cache gate
      ↓
canonical unloaded floor
      ↓
sustained scout
0.5 / 0.75 / 1.0 / 1.25
45+ min and >=2000 samples each
      ↓
find highest stable UNDER
and lowest unstable OVER
      ↓
3-repeat sustained confirmation
(counterbalanced ordering)
      ↓
final breach interval / crossing
      ↓
only then:
natural → steady → adversarial
      ↓
pull + verify
      ↓
teardown
      ↓
offline BASELINE.md
```

---

# 13. Expected GPU wall-clock and cost

The binding risk is still **wall-clock / Spot preemption**, not dollar cost.

Using the Attempt 1 observed/plan rate of approximately **$0.40–0.50 per hour**
for `g2-standard-8` + 1× L4 Spot:

### Fixed work before headline confirmation

| Work | Approx. time |
|---|---:|
| instance + vLLM + gates + canonical floor | ~0.5 h |
| sustained scout at 0.5 / 0.75 / 1.0 / 1.25 | ~3.4 h |
| **subtotal before confirmation** | **~3.9 h** |

The scout estimate comes from ~66.7 minutes at 0.5 RPS plus at least 45 minutes
at each of the other three points, plus their warmups.

### Headline confirmation

The exact cost depends on the bracket the scout finds.

**Likely case — two adjacent confirmation points, 3 repeats:**

- ~4.6–5.7 h of confirmation time
- total through headline closure: **~8.5–9.6 h**
- raw compute cost: approximately **$3.40–4.80**

**Conservative case — three confirmation points, 3 repeats:**

- ~6.9–8.0 h of confirmation time
- total through headline closure: **~10.8–11.9 h**
- raw compute cost: approximately **$4.30–6.00**

Allowing ~10–15% operational overhead for drains, artifact pulls, checks, and
small delays gives a practical headline-session budget of roughly:

> **~9.5–13.5 hours and ~$3.80–6.80**

### Full Week 2 including secondary scenarios

The exact secondary cost is **not yet fully determined by this plan**, because
their final λ subset and sustained-duration policy are chosen only after the
headline boundary is known.

If the secondary work remains close to the prior runbook's ~1–2 additional
hours, the complete session should still land roughly around:

> **~11–16 hours total and ~$4.50–8.00 on Spot**

Treat the dollar estimate as planning guidance, not a correctness constraint.
If the headline run has to extend the λ range or restart after Spot preemption,
stop and recalculate rather than trimming measurement duration to fit a budget.

---

# 14. Decisions to lock before generating schedules

**Locked 2026-08-22 by human decision, adopted as written.** The `>=1%`
censoring rule is implemented as the exact nearest-rank inequality it argues
for (`n_censored >= n_offered_window - ceil(0.99 * n_offered_window) + 1`),
not a loose percentage cutoff — this is a precisification of the rule below,
not a change to it.

- [x] Keep 60 s warmup.
- [x] Sustained scout λ = `{0.5, 0.75, 1.0, 1.25}`.
- [x] Minimum sustained duration = **45 min**.
- [x] Minimum per-run N = **2,000**.
- [x] Generate each Poisson schedule until **both** `post_warmup_elapsed >= 2700s` and `post_warmup_arrivals >= 2000`, then freeze the realized schedule exactly.
- [x] `>=1%` censoring ⇒ `OVER_CENSORED`, numeric p99 suppressed.
- [x] Final repeats = **3**, unanimous classification.
- [x] Counterbalanced repeat-major ordering.
- [x] Secondary scenarios run only after headline closes.
- [x] Same eager/no-prefix-cache server configuration as Attempt 1.

---

## Intended Week 2 completion criterion

The next run should finish with one defensible statement of the form:

> **Under the locked canonical Poisson workload, naive single-replica serving sustains λ = A RPS below the 500 ms p99 TTFT SLO and breaches by λ = B RPS; therefore the Week 2 breach interval is `(A, B]`.**

If one prepared point itself is unanimously `UNDER` immediately below a unanimously `OVER` point, that interval is the Week 2 baseline result. Do not force a single interpolated RPS that was never measured.

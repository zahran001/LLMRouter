# Calibration Task — Setting the Two Remaining Tolerance Values

Goal: run one empirical measurement and use it to lock the two `[CALIBRATE]` constants:
1. The **noise floor** in the tolerance band `max(±FLOOR ms, ±10%)`.
2. The **high-variance p99 multiplier** (threshold for "p99 meaningfully elevated above p50").

Do this NOW, post-timing-fix, because the fix removed the ~25-40ms bias — so the
measured jitter is now clean, and the floor can likely be much tighter than the 15ms
placeholder.

---

## Part A — Measure the noise floor (sets value #1)

### What to run
`scripts/calibrate_noise_floor.py` (already built, smoke-tested, not yet run at scale).
Run it against ONE stable config — use **fast (100/20)**, because it's the
floor-dominated config: its tolerance is governed by the floor, not the percentage,
so it's the one the floor value actually protects.

Drive it **sequentially** (`DRIVE_CONCURRENCY = 1`), matching how the precision-sensitive
tests run — otherwise the mock's known concurrency degradation contaminates the numbers.

Parameters:
- 200 runs (each run = a full batch of ≥110 requests: 10 warmup + ≥100 measured).
- Record the **p50 TTFT** and **p50 TPOT** of each of the 200 runs.
- Output: two arrays of 200 p50 values each (one for TTFT, one for TPOT).

### What to read from the output
For each metric (TTFT p50 across runs, TPOT p50 across runs), compute:
- **median of the 200 p50s** — the center (should sit ~at configured value post-fix).
- **spread**: the run-to-run variation. Look at BOTH:
  - standard deviation, and
  - the max−min range (the worst-case swing you actually saw).
- The number that matters for the floor is the **spread**, not the center. The floor
  must cover how much p50 legitimately bounces run-to-run, so a correct pipeline never
  flakes.

### How to set the floor
- Take the larger of the two spreads (TTFT vs TPOT — TPOT at 20ms is the tightest case).
- Set `FLOOR = observed_worst_spread + a small safety margin` (e.g. round up to the
  next few ms above the max−min range).
- Example shape (illustrative, NOT your answer — measure yours): if TPOT p50 swings
  ±3ms across 200 runs, a floor of ~5ms is defensible; the old 15ms was absorbing the
  now-removed bias and is likely too loose.
- **Sanity check:** the new floor must still be ≥ the structural ~8-10ms TTFT overhead
  the agent found (connection + send + role chunk), OR — cleaner — assert TTFT against
  the mock's *measured delivered* baseline rather than the raw configured value, so the
  structural floor isn't mistaken for error. Decide which; document it.

### Provenance to record
In BENCHMARKS.md: the 200-run median, stdev, and max−min for both metrics; the chosen
floor; and one sentence tracing the floor to the measured spread. This converts the
constant from a guess into a measured instrument property.

---

## Part B — Set the high-variance p99 multiplier (sets value #2)

### What you already have
The last eval run on the high-variance config gave:
- p50 = 304ms, p95 ≈ 1204ms, p99 ≈ 1207ms
- **p99/p50 = 3.97×**, strict ordering p99 > p95 > p50 held.

The injected tail is ~4× base (5-10% of chunks spiked to 3-5× — landing ~4× at p99).

### How to set the multiplier
The assertion is: `p99 >= p50 × MULTIPLIER`. Pick MULTIPLIER to sit in the gap between:
- **Lower bound — a broken/flat p99:** if the percentile fn were broken (e.g. returned
  the mean or the median), p99/p50 would be ≈1.0–1.5×. The multiplier must be ABOVE this.
- **Upper bound — the true tail:** the real tail clears ~3.97×. The multiplier must be
  BELOW this so the legitimate tail passes with margin.
- **Choose the midpoint-ish with margin on both sides:** e.g. **2.5×**. That's well
  above a flat p99 (catches the bug) and well below 3.97× (won't flake on the real tail).
- Do NOT set it near 3.97× (too tight — flakes when the stochastic tail dips) or near
  1× (too loose — a broken p99 passes).

### Reproducibility note
If the tail is RNG-driven, either seed the mock's RNG so the tail magnitude is stable
run-to-run, or run enough samples that p99 is statistically reliable and assert only the
inequality (which is what this multiplier is). Confirm which the mock does; the multiplier
assumes a stable-enough tail.

### Provenance to record
In BENCHMARKS.md: the observed p99/p50 (3.97×), the flat-p99 lower bound (~1–1.5×), and
the chosen multiplier (with the one-line reason it sits between them).

---

## Part C — Lock it in

1. Replace both placeholders in `tests/tolerances.py` (or wherever the `[CALIBRATE]`
   constants live) with the measured values. Remove the `[CALIBRATE]` markers.
2. Re-run the full suite — must still be all-green with the new, tighter floor.
   - If the tighter floor causes a legitimate flake, the spread was underestimated —
     widen slightly and re-run. (This is expected iteration, not failure.)
3. Re-run the 5× determinism check with the new constants — must be 5/5.
4. Re-confirm the negative controls still bite with the new floor (a tighter floor
   should make them bite HARDER, not softer — verify).
5. Update BENCHMARKS.md with the provenance from Parts A and B.
6. Commit: `chore(tolerances): lock noise floor and p99 multiplier from calibration`.

---

## Definition of done (calibration)
- [ ] 200-run noise measurement executed on fast config, sequential drive
- [ ] Floor set from measured spread (+ margin), traced in BENCHMARKS.md
- [ ] TTFT structural-overhead decision made (raw config vs measured baseline) + documented
- [ ] p99 multiplier set between the flat-p99 bound and the true 3.97× tail, traced
- [ ] Both `[CALIBRATE]` markers removed; constants live in tolerances file
- [ ] Full suite green with new constants
- [ ] 5× determinism still 5/5
- [ ] Negative controls still bite (verified with tighter floor)
- [ ] BENCHMARKS.md provenance updated

After this: tolerances are fully locked, Week 1 measurement pipeline is DONE (pending
only the GPU-session faithfulness capture). Next build: the Rust router.

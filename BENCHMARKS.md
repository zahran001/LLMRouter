# Benchmarks notes

## Mock timing precision fix (busy-wait / `precise_sleep`) -- STATUS: done

`AGENT_TIMING_FIX_BRIEF.md` traced the `fast`/`bursty` eval failures below
to a systematic bias in the mock, not the pipeline, and directed fixing the
mock's timing precision rather than widening tolerances. Implemented as
`mock/timing.py: precise_sleep()` -- coarse `asyncio.sleep` for the bulk of
each wait, then a yielding spin (`await asyncio.sleep(0)` each iteration)
against `time.perf_counter()` for the final `SPIN_MARGIN_S`. Ground truth
remains the mock's *configured* `ttft_ms`/`tpot_ms`, not an empirical
baseline.

**Pre-fix raw `asyncio.sleep` overshoot** (60 samples/duration, no HTTP,
this dev machine, otherwise idle):

```
target=  20ms  overshoot: median=11.24ms  p95=12.43ms  max=15.62ms
target=  50ms  overshoot: median=13.12ms  p95=15.50ms  max=41.74ms (one outlier)
target= 100ms  overshoot: median=9.82ms   p95=11.55ms  max=28.76ms
target= 300ms  overshoot: median=10.99ms  p95=14.45ms  max=14.61ms
target= 500ms  overshoot: median=13.39ms  p95=15.02ms  max=15.42ms
```

`SPIN_MARGIN_S = 20ms` was set from this table (clears the ~15.5ms p95
ceiling with headroom, without spinning for an excessive share of each
interval -- see `mock/timing.py` for the full reasoning).

**`precise_sleep` validated in isolation** (40 samples/duration, no HTTP):
overshoot dropped to sub-0.2ms max at every duration tested, including
under concurrency up to 20 simultaneous callers (median/max overshoot
stayed at 0.00-0.03ms at concurrency 1/5/15/20) -- the timer primitive
itself has no concurrency-dependent degradation.

**`test_mock_timing_accuracy` (mock fidelity, isolated from the pipeline,
sequential driving)**, post-fix:

```
fast:   ttft median=108.22ms (configured 100ms, +8.22ms)   tpot median=20.40ms (configured 20ms, +0.40ms)
slow:   ttft median=508.95ms (configured 500ms, +8.95ms)   tpot median=100.46ms (configured 100ms, +0.46ms)
bursty: ttft median=309.80ms (configured 300ms, +9.80ms)   tpot median=50.42ms (configured 50ms, +0.42ms)
```

TPOT is now precise to well under 1ms (as expected: it's a *difference*
between two chunk arrivals, so constant per-chunk transport latency
cancels out of the subtraction). A ~8-10ms TTFT floor remains, but it's
**not sleep imprecision** -- it's config-independent (same ~8-10ms at
100/300/500ms targets, four independent runs) and structural: TTFT is a
one-way latency from t0 that includes connection + request-send +
role-chunk + ASGI/transport delivery time, which `WEEK1_MEASUREMENT_SPEC.md`
§2 deliberately defines TTFT to include. `precise_sleep` controls wait
*duration*; it has no way to (and per spec, should not) remove this.

### A second, separate finding: concurrent-stream throughput

Applying the fix alone did not make the Tier 3 eval pass -- it got
*worse* at the eval's original concurrency (10-20). Swept concurrency
against the fixed mock:

```
bursty (configured ttft=300ms), n=30/run:
  concurrency= 1  median ttft=307ms  (+7ms)
  concurrency= 3  median ttft=319ms  (+19ms)
  concurrency= 8  median ttft=340ms  (+40ms)
  concurrency=15  median ttft=376ms  (+76ms)
```

Ran the identical sweep against the mock with `precise_sleep` monkeypatched
back to bare `asyncio.sleep` to check whether this was a spin-wait
side-effect: **the scaling was statistically identical** (e.g. concurrency
15 gave median 375ms with bare sleep vs 376ms with `precise_sleep`). This
is a pre-existing limit of this single-process Starlette/uvicorn dev
mock's throughput under many concurrent long-lived SSE streams, unrelated
to which sleep primitive it uses -- not something Part 1's fix could or
should address.

**Mitigation**: every test that asserts on precise timing values
(Tier 3 eval, negative controls, the fast-config Tier 2 tests) now drives
the mock sequentially (`DRIVE_CONCURRENCY = 1`), documented at each call
site. This costs wall-clock time (the full suite went from ~1 to ~8.5
minutes) but keeps the eval measuring pipeline correctness against the
mock's *precise* per-stream timing, rather than being confounded by this
server's separate concurrent-throughput ceiling. A production-grade mock
(multi-process, or one that doesn't need fine timing precision under
concurrent load) could relax this -- out of scope for this fix.

### Post-fix results

- **Full suite**: 42/42 passing (clean run, no other load on the machine).
- **Determinism check** (`AGENT_TIMING_FIX_BRIEF.md` 3e): `tests/unit` +
  `tests/eval` run 5 times in a row. **5/5 clean, 32/32 passing every
  run**, with tight timing consistency (394.86s / 395.43s / 395.86s /
  395.57s / 390.11s -- under 6s / 1.4% spread across runs). Two additional
  attempts were killed mid-run by something external to the tests
  themselves (not a test failure -- both showed all-passing dots up to the
  interruption point); retried rather than counted as flakes.
- **Negative controls re-verified**: both still raise `AssertionError` on
  the injected bug, in every one of the 5 determinism runs and the
  standalone full-suite run. The eval still has teeth.
- **High-variance tail re-confirmed** (`AGENT_TIMING_FIX_BRIEF.md` 3f),
  post-fix, seeded, 150 measured requests:
  `p50=304.13ms  p95=1203.70ms  p99=1207.04ms  mean=370.51ms`,
  `p99/p50 = 3.97x`. Strict ordering (p99 > p95 > p50) holds; p50 stayed
  within 5ms of the base 300ms config; p95/p99 land almost exactly at
  `300ms x 4` (the injected `TAIL_MULTIPLIER`), confirming the fix did not
  flatten the deliberate tail -- if anything it's cleaner now, since the
  old sleep jitter is no longer riding on top of the injected spikes.

### Tolerance provenance (no magic numbers -- `AGENT_TIMING_FIX_BRIEF.md` 3d)

| Constant | Value | Source |
|---|---|---|
| Hybrid band `max(±15ms, ±10%)` | -- | `WEEK1_MEASUREMENT_SPEC.md` §4 (locked) |
| `TOLERANCE_FLOOR_MS` | 15ms | `[CALIBRATE]` placeholder, still pending your 200-run measurement -- see below |
| `HIGH_VARIANCE_P99_OVER_P50_MULTIPLIER` | 2.5x | **Calibrated** (CALIBRATION_TASK.md Part B) -- see "p99 multiplier calibration" below |
| `SPIN_MARGIN_S` | 20ms | Measured: clears the ~15.5ms p95 raw-`asyncio.sleep` overshoot ceiling (table above) |
| `TTFT_TIGHT_BAND_MS` (mock fidelity test) | 10ms | Measured: clears the ~8-10ms structural TTFT floor (table above) |
| `TPOT_TIGHT_BAND_MS` (mock fidelity test) | 5ms | Measured: post-fix TPOT overshoot is <1ms; 5ms leaves headroom |
| `DRIVE_CONCURRENCY` / `PRECISE_CONCURRENCY` | 1 | Measured: concurrency-dependent TTFT degradation (table above); 1 eliminates it |
| `TAIL_PROBABILITY` / `TAIL_MULTIPLIER` (mock) | 8% / 4x | Chosen within spec §5's suggested range (5-10%, 3-5x), not calibrated |

No constant above was chosen to "make a test pass" without a traceable
source -- the two still marked `[CALIBRATE]` are explicitly yours to set
from the pending 200-run noise measurement (unchanged by this fix).

## p99 multiplier calibration (CALIBRATION_TASK.md Part B) -- STATUS: done

`HIGH_VARIANCE_P99_OVER_P50_MULTIPLIER` in `tests/tolerances.py` gates the
high-variance-config eval assertion `p99 >= p50 * MULTIPLIER`, which exists
to catch a broken/flat percentile function (one that returns the mean or
median regardless of `p`) without flaking on the legitimate stochastic tail.

**Observed true tail** (post-fix, seeded, 150 measured requests, from
"Post-fix results" above): `p50=304.13ms  p99=1207.04ms`, **p99/p50 =
3.97x**. Strict ordering (p99 > p95 > p50) held; p95/p99 landed almost
exactly at `300ms x TAIL_MULTIPLIER (4x)`.

**Bounds:**
- Lower bound (~1.0-1.5x) -- what a broken/flat percentile fn would produce:
  collapsing p50/p95/p99 to the same value (mean or median) gives a ratio
  near 1x, at most ~1.5x for a right-skewed mean on this data. The
  multiplier must sit ABOVE this to actually catch that bug.
- Upper bound (3.97x) -- the measured true tail. The multiplier must sit
  BELOW this with margin so the real, stochastic tail passes reliably
  rather than flaking when the tail draw happens to be light.

**Chosen: 2.5x** -- roughly the midpoint, with margin on both sides (~1x
above the flat-p99 bound, ~1.5x below the measured tail). Not tuned to
either edge.

**Reproducibility**: the tail is RNG-driven (`mock/app.py`: per-request
`random.Random(seed)` when a `seed` query param is supplied), and
`tests/eval/test_deterministic_eval.py:test_tail_computation` already
exercises both of spec §5's reproducibility options together -- a fixed
base seed (`20260813`, incremented per request via `tests/helpers.py:
drive_requests`) AND a large sample (n=150, ~12 expected tail draws at the
8% `TAIL_PROBABILITY`) -- so the measured 3.97x is not a one-off draw.

## Router eval calibration (WEEK1_ROUTER_IMPL.md §7) -- STATUS: done

The three `[CALIBRATE]` values in the router spec, locked in
`tests/router/tolerances.py`. Same rule as the metrics tolerances: each
traces to the mock's *configured* timing or to an already-measured noise
floor, never to what the router happened to measure.

| Value | Locked | Traces to |
|---|---|---|
| S1 first->last gap | **> 1000ms** | Configured content-stream duration for the slow config at 20 tokens: `(20-1) x 100ms = 1900ms`. 1000ms is 53% of that -- far below the true value, ~100x above the 10ms noise floor. |
| S2 first-chunk bound | **< 750ms** (TTFT 500ms + 250ms margin) | Margin = `5 x hybrid_band(500ms)` = 5 x 50ms, i.e. five times the band the metrics suite already accepts at that configured value. Also 25x the 10ms noise floor and ~33x the 7.56ms structural TTFT offset. |
| O1 median overhead | **< 10ms**, and growth between response sizes **< 10ms** | `TOLERANCE_FLOOR_MS` reused verbatim from the Part A calibration above -- not a fresh number. |

### Measured -- 5x determinism run (`scripts/router_eval.sh 5`)

This dev machine, release build, strictly sequential. Every pass: 9 cargo
unit tests, 5 negative controls, 20 eval tests, all green; `router eval green
(5 pass(es))`. Ranges are across the five passes.

| Check | Bound | Real router (5 passes) | `WRONG_ROUTER_BUFFERS` (5 passes) |
|---|---|---|---|
| S1 first->last gap | > 1000ms | 1912.4 - 1951.5ms | **0.2 - 0.7ms** |
| S2 first content chunk | < 750ms | 512.0 - 533.2ms | **2445.7 - 2542.5ms** |
| O1 delta, 5 tokens | < 10ms | -1.34 to -0.00ms | **+81.6 to +85.5ms** |
| O1 delta, 25 tokens | < 10ms | -1.08 to +1.10ms | **+490.8 to +500.6ms** |
| O1 growth (large - small) | < 10ms | -0.66 to +1.34ms | **+406 to +418ms** |

Both streaming bounds clear by roughly 2x on the correct router and are
missed by 3-4 orders of magnitude (S1) or ~1.7 seconds (S2) by the buffering
one, which is the separation the bounds were chosen to produce. Run-to-run
spread on the real router is ~39ms for S1 and ~21ms for S2 -- far inside the
bounds' margins, so the streaming assertions are deterministic, not
borderline.

F1 against `WRONG_ROUTER_REEMIT`: 1532 bytes direct vs 1428 re-emitted, the
same figures in all five passes (the mock's seeded mode makes the body
byte-reproducible, so this control is exactly repeatable). The JSON
round-trip alphabetizes keys and compacts separators. F2 still passes against
the same router -- the divergence between F1 and F2 is what shows F1 tests
byte-identity rather than semantic equivalence.

The router's own overhead measures **at or below zero** on most medians here,
i.e. it is inside the instrument's noise. Note that O1 is a *difference*
between two
arms measured under identical conditions, so it is immune to the structural
TTFT offset that the mock-timing self-test measures directly: during these
runs the mock's delivered TTFT sat at ~114ms against a configured 100ms
(machine drift, see caveat below), and the direct-vs-proxied delta was still
sub-millisecond.

### Caveat: mock-timing drift on this machine

`tests/mock/test_timing_accuracy.py` currently fails on this dev machine for
fast/slow/bursty (TTFT overshoot ~+15 to +17ms against its 10ms band). This
predates the router work -- the same three fail identically on unmodified
`main` -- and is a machine-state/calibration question for the mock, not a
router finding. It does not affect the router eval: fidelity and header/error
tests are timing-free, the streaming bounds are seconds-coarse, and O1 is a
difference statistic that cancels the offset.

### CI run (ubuntu-latest) -- first Linux data point

Workflow `router eval`, both runs green on `feature/router-impl`: run
31923160568 (push, 3m19s) and 31923325886 (pull_request, 4m00s), each doing a
cold release build plus the full gate.

| | Windows dev machine | ubuntu-latest (CI) |
|---|---|---|
| direct TTFT p50 (fast, configured 100ms) | ~113-115ms | **102.7-103.1ms** |
| S1 first->last gap (configured 1900ms) | 1912-1952ms | **1903.0ms** |
| S2 first content chunk (configured 500ms) | 512-533ms | **502.4ms** |
| O1 delta, 5 / 25 tokens | -1.34 to +1.10ms | **-0.25 / -0.12ms** |

Negative controls bit identically on Linux: buffering gap 0.1ms, first chunk
2405.8ms, overhead +80.63ms (5 tokens) / +482.10ms (25 tokens); re-emit 1532 ->
1428 bytes.

**Worth noting for Week 2.** The structural TTFT offset is ~3ms on the Linux
runner against ~13-15ms here, and every configured duration lands closer to
target. That is a *free first data point* on the question
`MOCK_TRUST_BOUNDARY.md` §1 defers -- "whether the busy-wait is even needed on
Linux" -- and it points the same way: the overshoot `precise_sleep` exists to
correct looks far smaller on the Linux/GCP target. It is not a substitute for
the planned calibration re-run (one CI run, one config, no repetition, and the
spin was still enabled), but it is evidence the re-run is worth doing early.

## Seed/timing RNG independence (router eval prerequisite) -- STATUS: verified

Making `?seed=` responses byte-reproducible (so F1 has a byte-identity oracle)
touches the mock, which is the project's ground-truth instrument. The
load-bearing claim is that the identity RNG does **not** consume the timing
RNG -- if it did, seeding would shift which chunks get the heavy-tail delay and
silently change what every seeded timing test measures.

Verified by observation, not by reading the code:
`scripts/verify_seed_rng_independence.py` drives the mock's ASGI app in-process
with `precise_sleep` stubbed out (so it compares which delays were *drawn*, not
how accurately they were *delivered*) and records the exact sequence
`_draw_delay_ms` returns on the high-variance config -- the only config whose
draws consume the RNG.

- **5 seeds x 30 draws, against the pre-change mock: identical in every
  position**, including the indices where the 4x tail spike lands (e.g. seed
  20260815 -> positions 14 and 20 in both).
- Same seed twice repeats its sequence in both builds.
- Only the response *bodies* differ (`created` 1786846276 -> 1700000000 and a
  derived uuid) -- the intended change.
- End-to-end: `tests/eval` (both seeded suites -- tail test at seed 20260813,
  negative controls at seed 999) passes 6/6 in 392s with the change present.
- Cost of the seeded identity path: **+5.46us/request** (7.14us vs 1.68us for
  the uuid4 path), ~1800x below the 10ms noise floor, and drawn before the role
  chunk rather than inside a timed gap.

Re-run it (against any pre-change checkout) if the mock's identity or timing
code changes again; usage is in the script's docstring.

## Simulated-token caveat

Week 1 measures inter-SSE-chunk gaps (TPOT), not tokenizer-level per-token
latency. The mock emits one token per chunk, so these coincide for it; real
vLLM may batch multiple tokens per chunk, making true per-token TPOT out of
scope for Week 1 (`WEEK1_MEASUREMENT_SPEC.md` §2, §7).

## Noise floor calibration (CALIBRATION_TASK.md Part A) -- STATUS: done

`tests/tolerances.py: TOLERANCE_FLOOR_MS` is now **calibrated: 10ms**
(down from the 15ms placeholder), from the authoritative 200-run measurement
below. No longer marked `[CALIBRATE]`.

**Method**: `scripts/calibrate_noise_floor.py --config fast --runs 200`,
driven sequentially (`DRIVE_CONCURRENCY = 1`, added to the script for this
run -- it previously defaulted to concurrency=20, which would have
contaminated the measurement with this mock's known concurrency-dependent
TTFT degradation, see "concurrent-stream throughput" above). `fast`
(100ms TTFT / 20ms TPOT) was chosen because it's floor-dominated: 10% of its
TPOT is only 2ms, so its tolerance band is governed entirely by the floor,
not the percentage term -- the config the floor actually has to protect.
200 runs x 110 requests/run (10 warmup + 100 measured), `num_tokens=5`,
post-timing-fix. Full raw data: `benchmarks/noise_floor_fast.json`.

```
TTFT p50 across 200 runs: mean=105.67ms  stdev=0.88ms  min=103.36ms  max=107.56ms  range=4.20ms
                           bias vs 100ms configured=+5.67ms  max |p50-configured|=7.56ms
TPOT p50 across 200 runs: mean=20.23ms   stdev=0.05ms  min=20.10ms  max=20.37ms   range=0.27ms
                           bias vs 20ms configured=+0.23ms   max |p50-configured|=0.37ms
```

**Floor derivation**: the quantity that determines whether the eval flakes
is `max |p50 - configured|` (not centered spread alone), because
`hybrid_band` is checked against the raw *configured* value, and TTFT
carries a real, repeatable ~5-8ms bias on top of its (tiny, ~1ms) spread --
a floor built from stdev/range alone would silently ignore that bias and
flake. TTFT's 7.56ms is the binding case (TPOT's 0.37ms is negligible in
comparison). This also directly answers the pending sanity check
(CALIBRATION_TASK.md Part A): the ~5-8ms TTFT bias measured here is the
same structural, config-independent one-way latency (connection + send +
role chunk + transport) already isolated in `tests/mock/test_timing_
accuracy.py`'s `TTFT_TIGHT_BAND_MS = 10ms` (measured there via a different
method -- direct 40-request per-config median, not p50-of-200-runs -- and
converging on the same ~8-10ms figure). Two independent measurements of the
same physical constant agreeing is stronger evidence than either alone, so
**`TOLERANCE_FLOOR_MS = 10ms` reuses that already-validated number**
rather than shaving a new one to 8ms: it covers the measured 7.56ms worst
case with ~2.4ms margin, and keeps one source of truth for "the structural
TTFT floor" instead of two slightly-different constants for the same thing.
**Decision made**: ground truth for the eval stays the mock's *configured*
value (not a measured baseline) -- consistent with the standing decision in
"Mock timing precision fix" above -- and the floor is set to explicitly
absorb the structural offset, rather than changing what the assertion
compares against.

This confirms the task's prediction: post-fix, the floor is much tighter
than the 15ms placeholder (33% reduction), since that placeholder was
absorbing the now-removed `asyncio.sleep` bias on top of genuine jitter.

**Verification after locking in both calibrated constants**
(`TOLERANCE_FLOOR_MS=10ms`, `HIGH_VARIANCE_P99_OVER_P50_MULTIPLIER=2.5x`):
- Full suite: 42/42 passing (`.venv/Scripts/python -m pytest tests`, 503.68s).
- Negative controls re-verified: both still raise `AssertionError` on the
  injected bugs. The tighter floor makes the leaked-TPOT control's margin
  *stricter*, not softer: `hybrid_band(20ms)` dropped from 15ms to 10ms, so
  the threshold the leaked (~TTFT-sized) TPOT p50 must clear to fail the
  eval is now `20+10=30ms` instead of `20+15=35ms` -- a lower bar for the
  bug to trip, i.e. more sensitive. Similarly the "real pipeline" sanity
  check inside `test_broken_percentile_would_fail` now requires the
  measured tail to clear `2.5x` (was `1.5x`) before the negative control
  even runs -- a stricter bar the real 3.97x tail still clears comfortably.
- 5x determinism re-run (`tests/unit` + `tests/eval`, 5 consecutive runs)
  with the new constants: **5/5 clean, 32/32 passing every run**, timing
  391.42s / 391.46s / 391.49s / 391.86s / 391.45s -- under 0.5s / 0.1%
  spread across runs, tighter than the pre-calibration determinism check
  (5.75s / 1.4%). The tighter floor did not introduce any flakiness.

Prior smoke-test data (`fast` config, 8 runs x 22 requests, default
concurrency=20, this dev machine, 2026-08-13), kept for reference only --
NOT used to set the floor, and NOT comparable to the table above (wrong
concurrency, predates this script's DRIVE_CONCURRENCY fix):

```
p50 TTFT across runs: mean=140.40ms  stdev=8.24ms  min=128.19ms  max=152.43ms  range=24.24ms
```

### Historical finding (RESOLVED -- see "Mock timing precision fix" above)

Earlier in this build, bare `asyncio.sleep()` overshoot (~10-30ms,
independent of HTTP or concurrency) caused `fast`/`bursty` to fail the
Tier 3 eval's tight p50 gate, while `slow`/`bursty`'s wider percentage
bands happened to absorb it. That systematic bias is now fixed at the
source (`precise_sleep`, see above) rather than tolerance-banded away, per
`AGENT_TIMING_FIX_BRIEF.md`'s explicit direction not to paper over it. The
smoke-test data below predates that fix and is kept only as a record of
what run-to-run spread looked like before -- re-run
`scripts/calibrate_noise_floor.py` post-fix for current numbers before
setting `TOLERANCE_FLOOR_MS`.

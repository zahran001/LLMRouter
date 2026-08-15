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
| `HIGH_VARIANCE_P99_OVER_P50_MULTIPLIER` | 1.5x | `[CALIBRATE]` placeholder from the spec, unchanged |
| `SPIN_MARGIN_S` | 20ms | Measured: clears the ~15.5ms p95 raw-`asyncio.sleep` overshoot ceiling (table above) |
| `TTFT_TIGHT_BAND_MS` (mock fidelity test) | 10ms | Measured: clears the ~8-10ms structural TTFT floor (table above) |
| `TPOT_TIGHT_BAND_MS` (mock fidelity test) | 5ms | Measured: post-fix TPOT overshoot is <1ms; 5ms leaves headroom |
| `DRIVE_CONCURRENCY` / `PRECISE_CONCURRENCY` | 1 | Measured: concurrency-dependent TTFT degradation (table above); 1 eliminates it |
| `TAIL_PROBABILITY` / `TAIL_MULTIPLIER` (mock) | 8% / 4x | Chosen within spec §5's suggested range (5-10%, 3-5x), not calibrated |

No constant above was chosen to "make a test pass" without a traceable
source -- the two still marked `[CALIBRATE]` are explicitly yours to set
from the pending 200-run noise measurement (unchanged by this fix).

## Simulated-token caveat

Week 1 measures inter-SSE-chunk gaps (TPOT), not tokenizer-level per-token
latency. The mock emits one token per chunk, so these coincide for it; real
vLLM may batch multiple tokens per chunk, making true per-token TPOT out of
scope for Week 1 (`WEEK1_MEASUREMENT_SPEC.md` §2, §7).

## Noise floor calibration -- STATUS: pending final run

`tests/tolerances.py: TOLERANCE_FLOOR_MS` is marked `[CALIBRATE]` and is
currently a **placeholder (15ms)**, matching the spec's own placeholder
value, not an empirically-set constant. Do not treat it as final.

`scripts/calibrate_noise_floor.py` implements the calibration task (run one
stable config N times, record p50 TTFT per run, look at the run-to-run
spread). It has been smoke-tested (8 short runs, not the spec's 200) to
confirm it works end-to-end; the full 200-run calibration is intentionally
left for you to execute and review before changing `TOLERANCE_FLOOR_MS` --
see AGENT_METRICS_BRIEF.md's calibration note.

Smoke-test data (`fast` config, 8 runs x 22 requests, this dev machine,
2026-08-13), for reference only -- NOT the authoritative 200-run result:

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

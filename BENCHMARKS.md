# Benchmarks notes

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

### A finding worth reading before running the full calibration

On this Windows dev machine, bare `asyncio.sleep()` overshoots its target
by ~10-30ms, independent of HTTP or concurrency (confirmed with no network
involved at all: `asyncio.sleep(0.02)` measured ~31ms actual,
`asyncio.sleep(0.1)` measured ~109ms actual). Since the mock uses
`asyncio.sleep()` to produce its configured `ttft_ms`/`tpot_ms` waits, this
shows up as two distinct effects that the calibration procedure should not
conflate:

1. **Run-to-run p50 spread** -- what `TOLERANCE_FLOOR_MS` is meant to
   absorb, per the spec's own wording ("observe run-to-run p50 spread").
   The smoke-test data above is this.
2. **A roughly constant systematic bias** (measured p50 running ~30-45ms
   above the configured value, consistently, not just occasionally) --
   this is a different phenomenon from run-to-run noise, and a 15ms (or
   even a calibrated-noise-based) floor will not absorb it, because it
   isn't noise, it's a consistent offset.

Concretely, in this session's test run: `slow` (500ms) passed comfortably
(10% band = 50ms comfortably covers the offset), but `fast` (100ms, 15ms
floor) and `bursty` (300ms, 30ms band) failed the tight p50 gate against
the *current placeholder* -- not because the measurement pipeline is wrong
(Tier 1's 26 pure unit tests are 100% green, and both negative controls
proved the eval catches injected bugs), but because the placeholder
tolerance hasn't yet been calibrated against this machine's real timer
behavior, and that behavior includes a bias term the calibration
procedure as literally specified doesn't measure.

Before setting a final `TOLERANCE_FLOOR_MS`, decide (this is a judgment
call, not something to guess): is the intent that the tolerance band
should also absorb this systematic bias (in which case measure mean
offset too, not just spread), or is the mock's timer precision itself
worth improving first (e.g. a busy-wait/hybrid sleep for short waits) so
the bias shrinks instead of being tolerance-banded away? Either is
defensible; it just needs to be a deliberate choice.

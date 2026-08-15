# Metrics Module — Test & Eval Suite

The metrics module is the measurement instrument the whole project trusts. These
tests exist to make the pipeline **fail loudly when measurement is wrong** and pass
only when it is correct. Organized in three tiers: pure unit tests (synthetic
inputs, no I/O), integration tests (against the live mock), and the deterministic
eval (the "bulletproof" gate).

Cross-references WEEK1_MEASUREMENT_SPEC.md. Tolerances are defined there.

---

## Tier 1 — Pure unit tests (synthetic, no HTTP, fast)

These feed hand-constructed inputs to the pure functions. No mock server needed.
They pin the correctness of the math itself.

### 1a. Percentile correctness (the highest-value tests)
The percentile function is the single most correctness-critical piece. Test it
against KNOWN answers, not against itself.

- `test_percentile_known_values`: input `[1,2,3,...,100]`.
  - Assert p50, p95, p99 match the documented method's known outputs for this input
    (compute the expected values by hand / from numpy with the pinned method, and
    hard-code them as literals — do not call the same function to generate expectations).
- `test_percentile_single_element`: `[42]` → p50 = p95 = p99 = 42.
- `test_percentile_two_elements`: `[10, 20]` → assert exact interpolated values.
- `test_percentile_empty_raises`: empty input raises.
- `test_percentile_unsorted_input`: function must sort internally OR document that it
  requires pre-sorted input; test whichever contract is chosen.
- `test_percentile_p0_p100`: p0 = min, p100 = max.

**Why hard-coded expectations:** if you generate the expected value by calling the
function under test, a wrong-but-consistent implementation passes. The expectation
must come from an independent source (hand calculation or numpy with pinned method).

### 1b. Warmup discard
- `test_warmup_discards_first_n`: 30 samples with recognizable ttft values
  (e.g. ttft = request_index), warmup=10. Assert the aggregate used samples 10..29
  (e.g. min ttft in population == 10), proving warmup discards by ORDER not by value.
- `test_warmup_larger_than_samples`: warmup=10, only 5 samples → run invalid, no crash.

### 1c. Min-sample rule
- `test_below_min_samples_invalid`: 99 post-warmup samples, min=100 → `valid == False`,
  p95/p99 not reported (NaN/None).
- `test_at_min_samples_valid`: exactly 100 → `valid == True`, tail percentiles present.

### 1d. TTFT / TPOT extraction from chunk sequences
Construct synthetic `ChunkEvent` lists with controlled `recv_time`s:
- `test_ttft_is_first_content_chunk`: sequence = [role@0ms, content@300ms, ...].
  Assert TTFT == 300ms, and that the role chunk did NOT set t_first.
- `test_role_chunk_excluded`: a role chunk with recv_time BEFORE the content chunk
  must not become TTFT.
- `test_tpot_gap_count`: K content chunks → exactly K−1 TPOT samples.
- `test_tpot_ignores_noncontent`: an empty-content chunk interleaved between content
  chunks must not create a bogus gap; gaps are between CONTENT chunks only.
- `test_final_chunk_excluded`: final chunk (finish_reason=stop, empty delta) not counted.
- `test_no_content_chunk`: role + final only, zero content → ttft None, error recorded,
  no crash.

### 1e. Parsing
- `test_parse_done_sentinel`: `data: [DONE]` → DONE sentinel.
- `test_parse_ignores_blank_and_comment`: blank line and `: comment` → None.
- `test_parse_malformed_json_raises`: `data: {not json` → raises (not silently skipped).
- `test_index_nonzero_raises`: chunk with `choices[0].index == 1` → raises (n>1 out of
  contract).
- `test_is_content_chunk_variants`: role chunk → False; empty content "" → False;
  whitespace-only content → decide + test the chosen rule; real content → True.

### 1f. Monotonic clock
- `test_uses_monotonic_clock`: assert the consumer uses perf_counter (e.g. via a
  patched/injected clock), so a wall-clock jump mid-run cannot corrupt gaps. If clock
  is injected, feed a clock that would go backwards under wall-time and confirm gaps
  stay sane.

---

## Tier 2 — Integration tests (against the live mock)

Spin up the mock, drive real HTTP, confirm the full consume→aggregate path.

- `test_end_to_end_fast_config`: mock at ttft=100/tpot=20, run ≥110 requests
  (10 warmup + 100 measured). Assert measured p50 TTFT within the hybrid band of 100ms
  and p50 TPOT within band of 20ms (bands per spec §4).
- `test_metadata_recorded`: the run's to_dict() contains config, counts, raw arrays,
  valid flag — all fields present and self-consistent (n_ttft_samples ==
  len(raw_ttft_ms)).
- `test_connection_pooling_active`: verify warm-connection path (e.g. TTFT does not
  include a per-request handshake spike after warmup). Can be a soft check: assert
  post-warmup TTFT variance is low for a stable config.

---

## Tier 3 — The deterministic eval (the bulletproof gate)

One parametrized test across all four locked configs. This is the gate that says
"the pipeline measures correctly." Run it in CI.

### Configs under test (spec §5)
| Config | ttft_ms | tpot_ms | Timing |
|---|---|---|---|
| fast | 100 | 20 | stable |
| slow | 500 | 100 | stable |
| bursty | 300 | 50 | stable |
| high-variance | 300 (mean) | 50 (mean) | heavy-tailed |

### For the THREE stable configs — `test_pipeline_correct[config]`
Run ≥110 requests through mock→(optionally router)→consumer. Then, per spec §4:
- **p50 TTFT** within `max(±15ms, ±10%)` of configured ttft_ms  ← tight pass/fail gate
- **p50 TPOT** within `max(±15ms, ±10%)` of configured tpot_ms  ← tight pass/fail gate
- **mean** within a wide band (≤ p50 + 3× the hybrid band) — loose skew flag
- **p99 TTFT** < 2× configured ttft_ms — loose upper bound (catches broken percentile)
- **run valid** (≥100 measured samples)

### For the HIGH-VARIANCE config — `test_tail_computation`
This is the ONLY config that proves the tail math. Stable configs would pass even
with a broken p99. Assertions:
- **p50 TTFT** still within the hybrid band of the base 300ms (the tail must NOT move
  the median — proves p50 is robust and percentiles separate correctly).
- **p99 TTFT meaningfully elevated above p50** — assert p99 > p50 × 1.5 (not an exact
  value; the tail is stochastic). **[CALIBRATE the multiplier once the injected tail
  magnitude is fixed — pick a threshold the true tail clears comfortably but a broken
  (flat) p99 fails.]**
- **p99 > p95 > p50** — strict ordering; a broken percentile impl often violates this.
- Seed the mock's RNG for reproducibility, OR run enough samples that the tail is
  statistically reliable and assert only the inequality (not a point value).

### Negative controls (prove the tests can FAIL)
Confidence in a test suite requires proving it catches bugs:
- `test_broken_percentile_would_fail`: inject a deliberately wrong percentile fn
  (e.g. one that returns the mean) and assert the high-variance eval FAILS. This
  proves the tail test has teeth. (Implement via monkeypatch in the test itself.)
- `test_leaked_ttft_into_tpot_would_fail`: a consumer variant that sleeps the TTFT
  wait into the first TPOT gap should push TPOT p50 out of band — confirm the eval
  catches it.

---

## Calibration task (run once, before finalizing tolerances)
- `eval_noise_floor`: run ONE stable config (e.g. fast) **200 times**, record p50
  TTFT each run, compute the run-to-run spread (stdev / min-max). Set the 15ms floor
  in the spec just above the observed jitter. Write the measured noise floor into
  BENCHMARKS.md. This converts the 15ms from a guess into a measured instrument
  property. **[CALIBRATE]**

---

## CI wiring
- Tier 1 (pure) + Tier 3 stable configs run on every commit (fast, deterministic).
- Tier 2 + high-variance run on every commit too if the mock starts quickly;
  otherwise nightly.
- The negative controls run in CI — they are the proof the gate has teeth.
- Fail the build on any Tier 1 or Tier 3 failure.

## Definition of done (tests)
- [ ] Percentile fn tested against independently-derived expected values
- [ ] Warmup-by-order and min-sample rules tested
- [ ] Role/final/empty chunks proven excluded from timing
- [ ] TPOT gap count == K−1 verified
- [ ] All four configs pass the deterministic eval within locked tolerances
- [ ] High-variance config proves tail separation (p99 > p95 > p50, p99 elevated)
- [ ] Negative controls prove the eval catches a broken percentile and TTFT/TPOT leak
- [ ] Noise floor measured (200 runs) and 15ms floor calibrated + documented

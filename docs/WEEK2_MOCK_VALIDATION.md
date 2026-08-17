# Week 2 Mock Validation — Procedure (V1-V5)

**Companion to `MOCK_TRUST_BOUNDARY.md`.** That doc is the *principle* (what
the mock is ever trusted for: request patterns, never latency under
concurrency). This doc is the *procedure* for Week 2: the five validations
that prove the loadgen (`loadgen/`) generates the request patterns it claims
to, each with a negative control that must go red on a deliberately broken
input before it's trusted to go green on the real one.

Ref: `WEEK2_PLAN.md` §4, `WEEK2_EXECUTION.md` Block B / Hard Stop 2.

**Hard pre-GPU gate:** all five validations, and all five negative controls,
must be green before any GPU spend (`WEEK2_EXECUTION.md` Hard Stop 4
re-affirms this). An unvalidated loadgen makes a bad GPU number ambiguous —
server or driver? — and this gate collapses that ambiguity before it costs
money.

---

## Test layout

```
tests/loadgen/
  _assertions.py                    shared assertion helpers (used by BOTH
                                     the positive tests below and their
                                     negative controls -- a control using a
                                     lookalike check would prove nothing)
  test_v1_arrival_distribution.py
  test_v2_open_loop_fidelity.py
  test_v3_concurrency_cap.py
  test_v4_corpus_faithfulness.py
  test_v5_logging_integrity.py
  test_negative_controls.py         all five controls, mirroring
                                     tests/eval/test_negative_controls.py
                                     and tests/router/test_negative_controls.py
```

Run: `pytest tests/loadgen -v` (marker: `loadgen`; live-mock tests are also
marked `integration`; the negative-control file is also marked
`negative_control`, matching the existing convention).

---

## V1 — Arrival distribution (offline, no sending)

**What:** the materialized schedule is a static artifact (`loadgen/schedule.py`),
so this is checked by inspecting it — no driving required.

- **Pass:** Poisson inter-arrival gaps at `(RPS, seed)` fit `Exponential(λ=RPS)`.
  Checked via a one-sample Kolmogorov-Smirnov test against the
  *fully-specified* exponential CDF (rate = the schedule's own target RPS, not
  fit from the sample) — `tests/loadgen/_assertions.py:assert_fits_exponential`.
  Plus a loose sanity check that the mean gap tracks `1/RPS`.
- **Determinism (free, same inspection):** same seed → byte-identical
  `(offset, prompt_id)` list; different seed → different list
  (`loadgen/schedule.py`'s dataclasses compare by value).
- **Negative control:** the **steady** schedule's gaps are constant by
  construction, so feeding them to `assert_fits_exponential` must raise
  `AssertionError` — a K-S test against a degenerate (constant) empirical
  distribution and a continuous exponential is maximally different. If this
  *didn't* fail, the check would be broken (e.g. a bug that only checks the
  mean, not the shape).

Files: `test_v1_arrival_distribution.py`; control in
`test_negative_controls.py::test_v1_steady_schedule_fails_exponential_fit`.

---

## V2 — Open-loop fidelity (THE load-bearing check)

**What:** requires driving the mock. This is the runtime companion to Hard
Stop 1's static architecture review — Hard Stop 1 proves the code *can't*
feed responses back into scheduling; V2 proves it *doesn't*, empirically.

- **Pass:** driven at target RPS against the **slow mock** (500ms TTFT), the
  per-send scheduling lag (`scheduled_offset` vs actual `send_time`) stays
  within a band, and achieved RPS tracks offered RPS.
- **Negative control (the single most important validation in this doc):**
  a deliberately **closed-loop** driver (send → wait for the full response →
  send again, no schedule at all) is run against both the `fast` (~180ms
  response) and `slow` (~900ms response) mock configs. Its achieved RPS
  necessarily diverges between the two (by construction — a closed loop's
  throughput *is* `1/response_time`), which is demonstrated first as a sanity
  check (ratio > 2x). Then the *real* `OpenLoopScheduler` is driven at the
  same target RPS against both configs, and its achieved RPS must stay
  **invariant** (within 20%) — if it didn't, response time would be leaking
  into send timing, i.e. a hidden closed-loop dependency.

Files: `test_v2_open_loop_fidelity.py`; control in
`test_negative_controls.py::test_v2_closed_loop_diverges_but_open_loop_is_invariant`.

**A real bug this caught while building it:** the first version of
`achieved_rps` divided sends by the wall-clock time to fully *drain* every
response (including the last few in-flight streams' response tail after the
last scheduled send), not by the *offered* window — which silently
under-counted achieved RPS for any config with response time comparable to
the window length, and would have produced a false "diverges" reading in
this exact control. Fixed in `loadgen/scheduler.py`: `achieved_rps` is now
`(n_sent + n_errored) / schedule.duration_s` (§2.5: "sent" for this purpose
means send_time was captured, whether or not the response later errored;
shed requests were never attempted and are excluded).

---

## V3 — Concurrency cap

**What:** against the slow mock, drive in-flight past the cap.

- **Pass:** over-cap sends record `shed` (fail-fast, non-blocking); the
  scheduler keeps firing on schedule for non-shed sends. The load-bearing
  assertion is that mean scheduling lag stays low (<100ms) *even while heavily
  shedding* — if the cap check blocked instead of failing fast, lag would blow
  up under heavy shedding instead of staying flat.
- **Negative control:** zero sheds below the cap. Below-cap run (fast config,
  low RPS, cap comfortably above plausible in-flight count) → `n_shed == 0`.
  A cap with an off-by-N enforcement bug (effectively admitting far fewer
  streams than configured) is simulated by driving the *same* concurrent load
  (slow config, high enough RPS that ~18 streams are typically open at once)
  against a genuinely smaller effective cap (5, vs the real 50) — it sheds
  where the correctly-configured cap doesn't. Calibration note: the offered
  RPS at which shedding *onsets* against the slow mock is the source for the
  `WEEK2_PLAN.md` §3.3 concurrency-cap `[CALIBRATE]` value (Block C, not this
  block).

Files: `test_v3_concurrency_cap.py`; control in
`test_negative_controls.py::test_v3_below_cap_zero_sheds_but_broken_cap_sheds_early`.

---

## V4 — Corpus faithfulness (offline)

**What:** inspect the schedule's prompt assignments and the pinned corpus
itself.

- **Pass:** every prompt in `corpus/baseline_prompts.jsonl` passes the
  validity filter (non-empty after `strip()`); draws come only from the
  pinned corpus (every drawn `prompt_id` resolves inside it); with-replacement
  draws are i.i.d. (loose diversity + population-mean sanity checks, not a
  rigorous uniformity test — enough to catch a badly broken draw function);
  same `corpus_rng` seed → identical draw sequence, different seed →
  different.
- **Negative control:** a filter-bypassed corpus (containing a
  whitespace-only and an empty-string entry — exactly what a skipped or
  broken validity filter would let through) must fail
  `assert_all_prompts_valid`, where the real committed corpus passes it first
  (sanity, so the control isn't "passing" because the helper is broken).

Files: `test_v4_corpus_faithfulness.py`; control in
`test_negative_controls.py::test_v4_filter_bypass_lets_junk_reach_assignment`.

---

## V5 — Logging / ordering integrity

**What:** every downstream number (percentiles, breach RPS, `BASELINE.md`)
reads the raw log, so its integrity is load-bearing for everything after it.

- **Pass:** every scheduled send appears exactly once with a status in
  `{sent, shed, errored}`; `scheduled == sent + shed + errored` reconciles;
  `send_time >= scheduled_offset` always (late allowed, early impossible) —
  checked by `tests/loadgen/_assertions.py:assert_log_reconciles`, run against
  a driven schedule with a deliberately tight cap so the mixed sent/shed path
  is exercised, not just all-sent.
- **Negative control:** a logger that silently drops the write for one
  specific `request_id` (simulating a lost log line, e.g. a crash mid-write)
  must trip `assert_log_reconciles` — the row-count check (`len(rows) ==
  n_scheduled`) catches it immediately.

Files: `test_v5_logging_integrity.py`; control in
`test_negative_controls.py::test_v5_dropped_log_write_trips_reconciliation`.

**A real bug this caught while building it:** the scheduler's original
sleep-until logic (`delay = target - time.monotonic(); if delay > 0: await
asyncio.sleep(delay)`) occasionally woke a few-to-15ms *before* its target on
this dev machine — the same class of platform timing imprecision that
motivated `mock/timing.py`'s busy-wait spin, just showing up as an occasional
undershoot here instead of an overshoot. Fixed the same way that fix did:
`loadgen/scheduler.py:_sleep_until` now coarse-sleeps then spins the final
`SPIN_MARGIN_S` against the monotonic clock, guaranteeing `send_time >=
scheduled_offset` by construction rather than hoping `asyncio.sleep` alone is
precise enough.

---

## Running the gate

```
pytest tests/loadgen -v
```

All 19 tests (5 V-checks' worth of positive assertions + 5 negative controls)
must be green, and — per `WEEK2_EXECUTION.md` Hard Stop 2 — **the human
verifies each control actually bites**, not just that "all tests pass." The
reds are the proof: temporarily breaking any of the five `assert_*` calls in
`_assertions.py`, or any of the deliberately-broken fixtures in
`test_negative_controls.py`, should make the corresponding control's sanity
assertion (the "real thing passes first" check) fail loudly, not the control
silently going green for the wrong reason.

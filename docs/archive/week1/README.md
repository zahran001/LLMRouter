# Week 1 archive

Completed, one-time process documents from Week 1 — agent task briefs and
the implementation/closeout runbooks. Kept for history and for the
in-code comments that still cite them by filename+section (e.g.
`WEEK1_ROUTER_IMPL.md §4.1`); moving them here doesn't break those
references since nothing imports these files, they're prose citations.

Each one's job is done:

- **`AGENT_METRICS_BRIEF.md`** — task brief for building `metrics/`. Module
  shipped; see `metrics/README.md` for what it actually is now.
- **`AGENT_TIMING_FIX_BRIEF.md`** — task brief for the mock's busy-wait
  timing fix. Shipped as `mock/timing.py: precise_sleep()`.
- **`CALIBRATION_TASK.md`** — task instructions for locking the two
  `[CALIBRATE]` tolerance constants. Done; values are in
  `WEEK1_MEASUREMENT_SPEC.md` with provenance.
- **`WEEK1_ROUTER_IMPL.md`** — Week 1 router implementation spec. Router
  shipped and merged to `main`; see `router/README.md` for current state.
- **`WEEK1_CLOSEOUT.md`** — the GPU-session runbook that closed out Week 1
  (the mock→vLLM faithfulness check). Fully executed; results are in
  `tests/fixtures/vllm_real_stream.txt` and
  `tests/faithfulness/test_real_fixture.py`. Its carry-forward items were
  extracted into `../../WEEK2_PLAN.md`.

**Not archived, still active/authoritative:**
`WEEK1_MEASUREMENT_SPEC.md`, `MOCK_TRUST_BOUNDARY.md`,
`METRICS_TEST_SUITE.md`, and `LOADGEN_PATTERN_VALIDATION.md` remain at the
repo root — despite the "Week 1" framing in some of them, they're cited by
section number throughout the actual code and tests as the still-locked
contract, or (for `LOADGEN_PATTERN_VALIDATION.md`) are explicitly Week-2
scoped. Don't move these without updating every citing comment.

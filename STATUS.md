# Status

Where the project currently is. `README.md` describes what the project *is*
and how it's built, and does not track progress — this file is the only place
that does, so it's the only place that goes stale.

**Current phase: Week 2 — load generation & baseline.**

## Phases

| Phase | Scope | State |
|---|---|---|
| Week 1 | Foundation & measurement: streaming contract, metrics pipeline, transparent router, mock↔vLLM faithfulness | **Closed** |
| Week 2 | Open-loop load generation, mock validation, and `BASELINE.md` — the naive single-replica breach curve | **In progress** |
| Week 3 | Token-count `prompt_len` for KV-cache math (deferred from Week 2 §3.4) | Not started |
| Weeks 4–8 | SLO-aware admission control and routing strategies, measured against Week 2's baseline | Not started |

## Week 1 — closed

Transparent router merged to `main`; measurement pipeline locked and
calibrated with provenance; mock→vLLM faithfulness confirmed against real
vLLM on GPU. Completed process docs are in `docs/archive/week1/`, with the
wrap-up in `docs/archive/week1/WEEK1_CLOSEOUT.md`.

The `router eval` badge in `README.md` is Week 1's gate: it runs the
fidelity, streaming, overhead and header/error tests **and** the two
deliberately-broken routers the eval must fail against, so it goes red both
when the router regresses and when the eval loses its teeth
(`docs/archive/week1/WEEK1_ROUTER_IMPL.md` §4–§5).

## Week 2 — in progress

Authoritative documents, which take precedence over this summary:

- **`WEEK2_PLAN.md`** — the decision record: what was decided and why, what is
  `LOCKED`, and every `[CALIBRATE]` value with its named source.
- **`WEEK2_EXECUTION.md`** — the execution order: blocks, hard stops, and
  definitions of done. Where the two appear to conflict on the same axis, that
  is a checkpoint to surface, not something to reconcile silently
  (`WEEK2_EXECUTION.md` §"Precedence rule").
- **`docs/WEEK2_GPU_PREFLIGHT.md`** — the Hard Stop 4 evidence checklist,
  standing between here and any GPU spend.
- **`docs/WEEK2_PRE_GPU_AUDIT.md`** — the pre-GPU audit trail: what the
  2026-08-17 audit found, and how each finding was closed.
- **`docs/WEEK2_REMEDIATION_REPORT.md`** — what was changed on 2026-08-18 and
  what it proved, including the Linux scheduler-spin calibration result and the
  hard-stop verdict.

Work proceeds in blocks separated by **hard stops** — blocking gates where the
agent produces evidence and a human renders the verdict. The summary table at
the end of `WEEK2_EXECUTION.md` lists all five and the failure mode each one
prevents.

### Deliverable

`BASELINE.md`, stating: *at X RPS, naive single-replica serving breaches the
500ms p99 TTFT SLO*, fully sourced and reproducible from the committed
schedule and corpus artifacts.

### `[CALIBRATE]` values

Tracked with their named sources in `WEEK2_PLAN.md` §8. **All resolved except
the per-point warmup N**, which is open *by design*:

| Value | State |
|---|---|
| Concurrency cap | **3000** (2026-08-17) |
| Offered-vs-achieved band | **±5%** (2026-08-18) |
| Measurement window Y | **120s** (2026-08-18) |
| Mock timing spin (Block 0) | **Resolved** — Windows-only fix (2026-08-16) |
| Loadgen scheduler spin | **Resolved** — platform-specific defaults (2026-08-18) |
| Per-point warmup N | **Open by design** — from Stage A's GPU transient, in Block F |

The warmup N is resolved post-GPU-session from the Stage A transient plot;
because the warmup filter is metrics-side and time-based, applying it is a
re-filter over the committed sidecars rather than another GPU run.

## Known issues

**None blocking.** The mock/vLLM faithfulness regression
(`test_real_stream_key_set_matches_mock`) is **fixed** as of 2026-08-18 — the
mock's three chunk kinds now carry the same key sets real vLLM 0.27.1 sends,
verified in both directions against the captured fixture, with the parser
contract untouched (`metrics/parse.py` still classifies an empty
`delta.content` as a non-content chunk).

*Historical note:* that failure was latent rather than new. `pytest tests`
previously died during collection — two test files shared the basename
`test_negative_controls.py` with no package markers — so the documented command
never reached the suite. Adding `__init__.py` to the test packages fixed
collection and surfaced it.

**One environment-only flake, not a regression:**
`tests/integration/test_end_to_end.py::test_end_to_end_fast_config` asserts the
mock delivers its configured 100ms TTFT within ±10ms. It passes standalone and
can exceed the band under full-suite contention on the Windows dev box, because
`mock_base_url` is session-scoped (`tests/conftest.py`) — one single-process
mock serves all tiers, including the loadgen tier's high-RPS sweeps. This is the
machine-drift signal `WEEK2_PLAN.md` §7 defers, and mock latency is outside the
trusted set (`MOCK_TRUST_BOUNDARY.md`) — it is not a Week 2 measurement input.
The tolerance has deliberately **not** been widened to hide it.

### Session-start decisions

Items deliberately left open for the human at the start of the metered GPU
session, rather than defaulted silently — `--enforce-eager` and the
output-token policy. Each is listed with its trade-off in
`docs/WEEK2_GPU_PREFLIGHT.md`. (The budget-alert ladder was previously on this
list; it is now resolved as $10 / $75 / $135 / $150.)

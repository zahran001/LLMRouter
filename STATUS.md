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

Work proceeds in blocks separated by **hard stops** — blocking gates where the
agent produces evidence and a human renders the verdict. The summary table at
the end of `WEEK2_EXECUTION.md` lists all five and the failure mode each one
prevents.

### Deliverable

`BASELINE.md`, stating: *at X RPS, naive single-replica serving breaches the
500ms p99 TTFT SLO*, fully sourced and reproducible from the committed
schedule and corpus artifacts.

### Open `[CALIBRATE]` values

Tracked with their named sources in `WEEK2_PLAN.md` §8. The warmup N is
resolved post-GPU-session from the Stage A transient plot; because the warmup
filter is metrics-side and time-based, applying it is a re-filter over the
committed sidecars rather than another GPU run.

## Known issues

**`tests/faithfulness/test_real_fixture.py::test_real_stream_key_set_matches_mock`
fails.** The mock's role chunk omits four keys real vLLM sends —
`choices[0].delta.content`, `choices[0].logprobs`, `prompt_token_ids`,
`prompt_text` — so the Layer 3 faithfulness check (mock chunk shape vs. a
captured real-vLLM fixture) goes red. The fix is named in the assertion
message: add them to `mock/app.py:_make_chunk`.

This was latent rather than new. `pytest tests` previously died during
collection — two test files shared the basename `test_negative_controls.py`
with no package markers — so the documented command never reached this suite.
Adding `__init__.py` to the test packages fixed collection and surfaced it.
The affected files were last touched in the Week 1 closeout (`67a62b1`).

Everything else passes: 105 of 106 tests green in a single `pytest tests` run.

### Session-start decisions

Items deliberately left open for the human at the start of the metered GPU
session, rather than defaulted silently — `--enforce-eager`, the output-token
policy, and the budget-alert thresholds. Each is listed with its trade-off in
`docs/WEEK2_GPU_PREFLIGHT.md`.

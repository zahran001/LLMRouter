# mock

Python mock replica that streams fake tokens in vLLM's OpenAI-compatible SSE
format, standing in for a real vLLM replica during local development and
benchmarking.

## Scope note

This is a minimal implementation, sized only to give the `metrics/` module's
integration and deterministic-eval tests (`METRICS_TEST_SUITE.md` Tiers 2-3)
real HTTP streaming to consume — it is not part of the metrics module brief
itself. It implements the streaming contract locked in
`WEEK1_MEASUREMENT_SPEC.md` §1 and the four configs from §5. It does not
implement request queueing, multi-replica behavior, or anything else a real
loadgen/router integration will eventually need — that's future work, not
this module's job.

## Run

```bash
uvicorn mock.app:app --port 9001
```

## API

`POST /v1/chat/completions?config=<name>&num_tokens=<N>&seed=<int>`

- `config`: one of `fast`, `slow`, `bursty`, `high-variance` (default `fast`).
  See `mock/configs.py` for the ttft_ms/tpot_ms pairs (spec §5).
- `num_tokens`: number of content chunks to emit (default 20).
- `seed`: optional RNG seed, for reproducible high-variance draws in tests.

Body: any JSON object; `model` is echoed back if present (OpenAI-style
request shape assumed, not validated).

Streams: role chunk -> wait `ttft_ms` -> `num_tokens` content chunks (with
`tpot_ms` gaps, heavy-tailed for `high-variance`) -> final chunk -> `[DONE]`.

`GET /health` for a liveness check (used by test fixtures to wait for
startup).

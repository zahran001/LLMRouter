# mock

Python mock replica that streams fake tokens in vLLM's OpenAI-compatible SSE
format, standing in for a real vLLM replica during local development and
benchmarking.

## Scope note

This is a minimal implementation, sized only to give the `metrics/` module's
integration and deterministic-eval tests (`METRICS_TEST_SUITE.md` Tiers 2-3)
— and, since Week 1's router work, the router eval (`tests/router/`) — real
HTTP streaming to consume. It is not part of the metrics module brief
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

`POST /v1/chat/completions?config=<name>&num_tokens=<N>&seed=<int>&echo_headers=1`

- `config`: one of `fast`, `slow`, `bursty`, `high-variance` (default `fast`).
  See `mock/configs.py` for the ttft_ms/tpot_ms pairs (spec §5).
- `num_tokens`: number of content chunks to emit (default 20).
- `seed`: optional RNG seed, for reproducible high-variance draws in tests.
  A seeded request is additionally **byte-reproducible**: its chat id is
  derived from the seed and `created` is fixed, so the same
  `(config, num_tokens, seed)` returns identical bytes every time. That is
  what gives the router's byte-identity test (F1) an oracle — two separate
  requests can be compared byte-for-byte. Unseeded requests keep a fresh
  uuid4 and the real epoch second, exactly as vLLM would.
  The id is drawn from its **own** `Random` instance, so the timing RNG's
  draw sequence is untouched; verified by comparing delay-draw sequences
  against the pre-change mock across five seeds (identical, including tail
  positions).
- `echo_headers`: debug affordance — returns JSON of the headers the mock
  received instead of streaming. Used by the router's H1 test to see what
  actually arrived through the proxy. It lives on this path because the
  Week 1 router only proxies `/v1/chat/completions`.

Body: any JSON object; `model` is echoed back if present (OpenAI-style
request shape assumed, not validated).

Streams: role chunk -> wait `ttft_ms` -> `num_tokens` content chunks (with
`tpot_ms` gaps, heavy-tailed for `high-variance`) -> final chunk -> `[DONE]`.

`GET /health` for a liveness check (used by test fixtures to wait for
startup).

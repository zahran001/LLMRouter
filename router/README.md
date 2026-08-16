# router

The Rust (axum + tokio) router. Week 1 scope: a **transparent single-replica
pass-through proxy** for vLLM's OpenAI-compatible streaming API, built to the
spec in `WEEK1_ROUTER_IMPL.md`. SLO-aware admission control and multi-replica
routing are later weeks.

## Scope note

The router is plumbing, not a measurement point — Week 1 timing is measured
client-side (`WEEK1_MEASUREMENT_SPEC.md` §2). So the whole Week 1 correctness
story is two claims:

1. **Fidelity** — bytes out == bytes in, so the mock→vLLM swap needs no code
   change (same standard the parser is held to).
2. **Streaming** — the router never *intentionally collects* the response
   body; chunks are forwarded as they become available.

`Body::from_stream()` does not promise that each upstream chunk becomes its
own TCP packet — hyper, socket buffering and the network sit below the
application. The router's responsibility is only that the application does
not collect the body, and that is what the eval asserts (coarse separation
bounds, never tight per-chunk timing).

Not built, deliberately: retries, graceful shutdown, resilience (Week 6);
response-stream inspection or per-chunk router logic (nothing in the roadmap
needs it).

## Run

```bash
export UPSTREAM_BASE_URL=http://127.0.0.1:9001   # required, no default
export ROUTER_PORT=8080                          # optional, defaults to 8080
cargo run --release
```

The router refuses to start if `UPSTREAM_BASE_URL` is unset or unparseable:
the mock→vLLM swap is a config change, not a code change, and a hardcoded
fallback is what lets a wrong upstream ship silently.

## Routes

| Route | Behaviour |
|---|---|
| `GET /health` | Local liveness check; does not touch the upstream. |
| `POST /v1/chat/completions` | Proxies to `<UPSTREAM_BASE_URL>/v1/chat/completions`, query string included, response body streamed. |

## Header policy

- **Request (allowlist):** `Content-Type`, `Accept`, `Authorization`.
  Everything else is dropped, including hop-by-hop and framing headers —
  forwarding those confuses the upstream. The HTTP client sets `Host` and
  `Content-Length` for the request it actually sends.
- **Response (denylist):** everything the upstream said about its payload is
  passed through (above all `Content-Type: text/event-stream`); hop-by-hop
  and framing headers are dropped so axum/hyper owns framing.

## Buffering: the direction asymmetry

The no-buffer rule is about the **response stream**. The **request** body is
read into memory (32 MiB cap) so the upstream receives a correct
`Content-Length`; this is by design and has no TTFT impact.

## Errors (Week 1)

| Situation | Behaviour |
|---|---|
| Upstream unreachable | `502`, and the router stays healthy. |
| Upstream drops mid-stream | The client's stream ends (truncated, honest) — no panic, no hang. |
| Request body unreadable | `400`. |

No retry, no fallback, no graceful shutdown — Week 6.

## The two wrong routers

`src/wrong.rs`, behind `--features wrong-routers` (off by default, so a
normal build contains neither the code nor its extra dependencies):

- **`WRONG_ROUTER_BUFFERS`** (`/__wrong__/buffers/v1/chat/completions`) —
  collects the whole body before returning it. S1, S2 and O1 **must fail**
  against it.
- **`WRONG_ROUTER_REEMIT`** (`/__wrong__/reemit/v1/chat/completions`) —
  re-serializes each SSE payload through JSON. F1 **must fail** against it
  while F2 still passes.

These are deliverables, not fixtures: the streaming eval's validity is
defined by failing against them (`WEEK1_ROUTER_IMPL.md` §4.2). Both reach the
upstream through the same `open_upstream` the real handler uses, so they
differ from it in exactly one respect — what they do with the body.

## Tests

```bash
cargo test                                  # unit: config parsing, header policy
cargo test --features wrong-routers         # + the re-emit chunk rewriter

PYTHON=../.venv/bin/python ../scripts/router_eval.sh     # the full gate
PYTHON=../.venv/bin/python ../scripts/router_eval.sh 5   # 5x determinism check
```

The eval itself lives in `tests/router/` (Python, driving the real binary
against the live mock); see `WEEK1_ROUTER_IMPL.md` §4 and
`tests/router/tolerances.py` for the calibrated bounds and their provenance.

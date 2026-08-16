# Week 1 — Measurement Pipeline: Locked Implementation Spec

This document is the authoritative definition of the Week 1 measurement pipeline.
Every numerical and structural boundary is fixed here. Build against this; do not
re-decide during implementation. Where a value needs empirical calibration, it is
marked **[CALIBRATE]**.

---

## 0. Guiding principle

The Rust proxy (axum + tokio) is the easy part. The engineering value of this phase
is a **measurement pipeline you can prove is correct** against a mock whose true
timing you control. Every decision below exists to make the pipeline bulletproof:
the deterministic tests must fail if the measurement is flawed, and pass only if it
is correct.

---

## 1. The Streaming Contract (LOCKED)

The mock replica mirrors vLLM's OpenAI-compatible `/v1/chat/completions` streaming
format **exactly**, so the router and parser cannot distinguish mock from real vLLM.

### Transport
- `Content-Type: text/event-stream; charset=utf-8`
- `Transfer-Encoding: chunked`
- Each event is a line: `data: {json}\n\n`
- Stream terminates with a literal `data: [DONE]\n\n`

### Chunk shape (FAITHFUL — emit the full realistic shape)
Every JSON chunk carries these fields:
```json
{
  "id": "chatcmpl-<uuid>",
  "object": "chat.completion.chunk",
  "created": 1234567890,
  "model": "meta-llama/Llama-3.2-3B-Instruct",
  "choices": [
    {
      "index": 0,
      "delta": { "content": "token text" },
      "finish_reason": null
    }
  ]
}
```

### Chunk sequence the mock MUST emit (in order)
1. **Role chunk** — emitted immediately, BEFORE the `ttft_ms` wait:
   `delta: {"role": "assistant"}`, no content field. `finish_reason: null`.
2. **[wait `ttft_ms`]**
3. **Content chunks** — N chunks, each `delta: {"content": "..."}`, `finish_reason: null`,
   with a `tpot_ms` gap between consecutive content chunks.
4. **Final chunk** — `delta: {}` (empty), `finish_reason: "stop"`.
5. **Terminator** — literal `data: [DONE]\n\n`.

### Parser rules (what the metrics side looks for)
- A "token chunk" = a `data:` line whose payload is not `[DONE]`, parses as JSON,
  and has non-empty `choices[0].delta.content`.
- The role chunk, the final `finish_reason` chunk, and any empty-content chunk are
  parsed but **excluded from timing** (they are not tokens).

### Locked boundary assumptions (document, do not implement)
- **`n = 1` only.** All chunks have `index: 0`. The parser does not handle
  multiplexed (`n > 1`) completions. If chunks with `index > 0` ever appear, that is
  out of contract.
- **Content is read from `delta.content`.** Reasoning models emit
  `delta.reasoning_content`; our models (Llama-3.2-3B, Llama-3.1-8B) are
  non-reasoning, so this field is out of scope for v1.

### Test-only mock affordances (do not affect this contract)
The mock carries two query parameters that exist solely for the router eval
(`WEEK1_ROUTER_IMPL.md` §4.5). Neither alters the contract above — chunk shape,
ordering, field set and terminator are unchanged, and a request that passes
neither parameter behaves exactly as specified here:

- **`?seed=`** additionally makes a response **byte-reproducible**: `id` is derived
  from the seed and `created` is fixed, so the same `(config, num_tokens, seed)`
  returns identical bytes. Needed because the router's byte-identity test compares
  two necessarily-separate requests. Unseeded requests keep a fresh `uuid4` and the
  real epoch second. The identity draw uses its own RNG instance and provably does
  not perturb the timing draw sequence (verified: BENCHMARKS.md, "Seed/timing RNG
  independence").
- **`?echo_headers=`** returns the received headers as JSON instead of streaming, so
  the router's header-forwarding test can see what actually reached the upstream.

---

## 2. Timestamp Definitions (LOCKED)

All timing is measured **client-side** (in the loadgen), because client-observed
latency is what a user experiences — it includes the network hop and router overhead.

- **`t0`** = captured immediately BEFORE awaiting the HTTP client's `.send()`.
  Deliberately includes connection + request-send time in TTFT.
  - **Connection pooling is required** so `t0`→`t_first` does not include TCP/TLS
    handshake on every request. Measure warm-connection latency (steady state).
    Warmup requests establish the pool.
- **`t_first`** = the moment the FIRST chunk with non-empty `delta.content` is parsed.
  NOT the first byte, NOT the first `data:` line, NOT the role chunk.
  - **TTFT = t_first − t0**  (one sample per request)
- **TPOT** = the gap between consecutive content-bearing chunks.
  - Each gap between two consecutive content chunks is one TPOT sample.
  - A response with K content chunks yields (K − 1) TPOT samples.
  - **Definition note (document in BENCHMARKS.md):** Week 1 measures inter-SSE-chunk
    gaps, NOT tokenizer-level per-token latency. For the mock (1 token/chunk) these
    are identical; real vLLM may batch multiple tokens per chunk. True per-token TPOT
    is out of Week 1 scope.

---

## 3. Sample Size & Warmup Rules (LOCKED)

- **Warmup:** discard the first **10** requests of every run (fixed count, not
  auto-detected — deterministic and reproducible).
- **Minimum samples:** require at least **100** measured (post-warmup) requests
  before computing p95 or p99. Fewer than 100 → the run is invalid; do not report
  tail percentiles.
- Rationale: p99 from < 100 samples is dominated by noise (one sample defines it).
  Fixed-count warmup keeps `reproduce.sh` deterministic across machines.
- These rules carry forward to real vLLM benchmarks, where warmup genuinely matters
  (first requests are slow while KV cache and CUDA graphs warm up).

---

## 4. Measurement Tolerances (LOCKED — for the deterministic MOCK test only)

These tolerances validate the PIPELINE against the mock's known timing. They are
**not** an accuracy claim about real vLLM measurement (real numbers have no ground
truth to check against).

### Target statistic
One test function, three assertions:
- **p50 — tight gate.** The pass/fail check. Measured p50 must be within the hybrid
  band (below) of the configured value.
- **mean — loose skew flag.** Assert mean is within a wide band of p50 (e.g. mean ≤
  p50 + 3× the hybrid band). A large p50/mean gap signals an unexpected heavy tail.
- **p99 — loose upper bound.** Assert p99 < 2× configured value. Catches a broken
  percentile implementation without flaking on legitimate tail noise.

### Tolerance band (hybrid)
`tolerance = max(±15ms, ±10% of configured value)`

| Configured | ±10% | Floor | Effective band |
|---|---|---|---|
| TPOT 20ms | ±2ms | ±15ms | ±15ms (floor) |
| TTFT 100ms | ±10ms | ±15ms | ±15ms (floor) |
| TTFT 300ms | ±30ms | ±15ms | ±30ms (%) |
| TTFT 500ms | ±50ms | ±15ms | ±50ms (%) |

- The **15ms floor is [CALIBRATE]**: before finalizing, run one mock config 200×,
  observe run-to-run p50 spread, set the floor just above observed jitter. Document
  the measured noise floor in BENCHMARKS.md (proves the instrument's noise was
  measured, not guessed).

---

## 5. Mock Test Configurations (LOCKED — four configs)

Coordinate pairs used to validate the pipeline across distribution shapes.

| Name | ttft_ms | tpot_ms | Timing | Purpose |
|---|---|---|---|---|
| fast | 100 | 20 | stable | Low-latency baseline; floor-dominated tolerance |
| slow | 500 | 100 | stable | High-latency; percentage-dominated tolerance |
| bursty | 300 | 50 | stable | Mid-range central case |
| **high-variance** | 300 (mean) | 50 (mean) | **heavy-tailed** | **Exercises the p95/p99 tail math** |

### high-variance config design
- Most chunks emit at/near the base timing; a minority (e.g. ~5–10%) inject a large
  extra delay (e.g. 3–5× base), producing a deliberate right tail.
- This is the ONLY config that meaningfully tests the tail percentile computation.
  The three stable configs would pass even with a broken p99 function; this one
  won't. It is the guard for the exact statistic the whole project depends on.
- For this config, assert on p50 tightly (it should stay near base — the tail
  shouldn't move the median), and assert p99 is elevated as expected (not a fixed
  value, but meaningfully above p50). This confirms percentiles separate correctly.

---

## 6. Faithfulness Confirmation (LOCKED)

"Faithful" = the mock→vLLM swap requires zero parser changes. Confirmed via:

### Layer 1 — Golden fixture (Step 4, GPU session, ~30s)
Capture real vLLM output once and commit it:
```
curl -N http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"meta-llama/Llama-3.2-3B-Instruct","messages":[{"role":"user","content":"count to five"}],"stream":true}' \
  > tests/fixtures/vllm_real_stream.txt
```
Prepend a version+date comment line: `# captured from vLLM <version> on <date>`.

### Layer 2 — Schema assertion (now, $0, runs in CI)
A test consuming the mock stream asserts every chunk's shape:
- data lines parse as JSON (except `[DONE]`)
- each chunk has `id`, `object == "chat.completion.chunk"`, `created`, `model`, `choices`
- `choices[0]` has `index == 0` and a `delta`
- role chunk appears first (`delta.role == "assistant"`, no content)
- first content chunk has non-empty `delta.content`
- final chunk has `finish_reason == "stop"`
- stream ends with literal `[DONE]`

### Layer 3 — Key-set diff (Step 4, ~2 min)
- Run the SAME Layer 2 assertion against `vllm_real_stream.txt`.
- Compare key SETS (not values) between a mock chunk and a real chunk, recursively
  into `choices[0]` and `delta`. Any key vLLM sends that the mock omits = a gap; add it.

### Definition of done (faithfulness)
- [ ] `vllm_real_stream.txt` captured, version-tagged, committed
- [ ] Schema assertion passes against the mock
- [ ] Same schema assertion passes against the golden fixture
- [ ] Key-set diff (mock vs real) is empty for parser-read fields
- [ ] mock→vLLM swap required ZERO parser changes  ← the real proof

### Version note
Faithful = faithful to the captured vLLM version. If vLLM is upgraded, re-capture
deliberately; drift is vLLM's change, not a mock bug.

---

## 7. Immediate-Implementation Habits (fold into the build)

- **Router overhead comparison:** verification script measures client→mock vs
  client→router→mock. Difference should be a small, roughly constant overhead. A
  large gap = the router is buffering (destroys TTFT) — fix before proceeding.
- **Metadata recording:** every output logs request count, warmup count, config
  settings, and the raw TTFT/TPOT sample arrays alongside the final percentiles.
- **Simulated-token caveat:** state explicitly in README/BENCHMARKS.md that Week 1
  measures simulated SSE chunk gaps, not tokenizer-level TPOT.
- **GPU discipline:** the cloud step is a connectivity + streaming smoke test only.
  Capture the fixture, confirm the swap is a no-op, tear down immediately.

---

## 8. Build order (each step de-risks the next)

1. **Mock replica** — faithful SSE, four configs, role chunk + wait + content + final.
2. **Metrics module** — parse stream, compute p50/p95/p99 TTFT & TPOT, warmup/min-sample rules.
3. **Deterministic tests** — validate metrics against all four mock configs with the locked tolerances.
4. **Rust router** — stream (never buffer) client → upstream → client.
5. **End-to-end verification** — loadgen → router → mock; router-overhead comparison.
6. **GPU smoke test** — capture fixture, faithfulness diff, confirm no-op swap, teardown.

---

## 9. Week 1 Definition of Done

- [ ] Mock streams faithful vLLM-format SSE with configurable ttft_ms/tpot_ms
- [ ] Four configs implemented (fast, slow, bursty, high-variance)
- [ ] Metrics compute p50/p95/p99 for TTFT and TPOT
- [ ] Warmup (discard 10) and min-sample (≥100 for tail) rules enforced
- [ ] Deterministic tests pass against all four configs within locked tolerances
- [ ] 15ms floor calibrated empirically; noise floor documented
- [ ] Rust router forwards stream without buffering
- [ ] Router-overhead comparison shows small constant overhead
- [ ] Metadata logged with every run
- [ ] Terminal dashboard shows live percentiles
- [ ] Golden fixture captured, faithfulness confirmed, swap was a no-op
- [ ] Simulated-token caveat documented
- [ ] Small, sensible commits throughout

# Week 1 — Transparent Router: Implementation & Eval Spec

Authoritative build + verification spec for the single-replica pass-through proxy
(axum + tokio). Companion to `WEEK1_MEASUREMENT_SPEC.md`. Same discipline: every
boundary fixed here, build against it, don't re-decide mid-implementation. Where a
value needs calibration it's marked **[CALIBRATE]**.

---

## 0. Guiding principle

The router is plumbing, not a measurement point. Week 1 timing is measured
**client-side** (per the measurement spec); the router's only job is to move the
stream through without corrupting it and without buffering it. Therefore the entire
correctness story reduces to two claims:

1. **Fidelity** — bytes out == bytes in (the mock→vLLM swap needs zero changes, same
   as the parser).
2. **Streaming** — the router does not *intentionally collect* the response body; it
   forwards chunks as they become available.

Everything below exists to make those two claims provable, and to make the eval
**bite** when either is violated.

---

## 1. Locked design decisions (the six)

These are the locked outcomes of the design pass. Rationale in §2.

| # | Decision |
|---|---|
| 1 | Upstream HTTP client: **`reqwest`** with the `stream` feature. |
| 2 | Body handling: `response.bytes_stream()` passed **directly** into axum `Body::from_stream()` — **no collecting the body**. Preserves streaming semantics; forwards chunks as they become available. |
| 3 | Request headers: forward `Content-Type`, `Accept`, `Authorization` (if present). **Do not copy hop-by-hop / connection-level headers** (`Host`, `Connection`, `Transfer-Encoding`, `Content-Length`, `Keep-Alive`, `Upgrade`, etc.). No header-translation system. |
| 4 | Response headers: preserve the application-level headers the streaming API needs (above all `Content-Type: text/event-stream`); let axum/hyper own HTTP framing / transfer-encoding. Do not hand-copy `Content-Length`. |
| 5 | Errors (Week 1 scope): upstream fails to connect → **502**; upstream drops mid-stream → **the stream just ends** (truncated, honest). **No retry, no graceful-shutdown, no resilience logic** — those are Week 6. |
| 6 | Configuration: upstream base URL from **env/config**, never hardcoded. mock→vLLM swap is a **config change, not a code change**. |

### Scope note carried from the design pass
`Body::from_stream()` does **not** guarantee that each upstream chunk becomes an
immediate TCP packet. Below the application there is hyper, OS socket buffering
(Nagle), and the network — none of which the router controls. The router's Week 1
responsibility is only that the **application** does not intentionally collect/buffer
the whole body. This directly constrains what the eval may assert (§4).

### Direction asymmetry (explicit)
The no-buffer rule applies to the **response stream only**. The request body is read
into memory (32 MiB cap) so the upstream receives a correct `Content-Length`; this is
by design and has no TTFT impact.

---

## 2. Rationale (why these, briefly)

- **`reqwest`/stream over raw `hyper`:** `bytes_stream()` is exactly the primitive
  needed; raw hyper is control you don't need in Week 1 and more surface area to get
  buffering wrong.
- **Direct `bytes_stream()` → `Body::from_stream()`:** this single combinator choice
  *is* the no-buffer rule. Any `.collect()`, `.bytes().await`, framed decoder, or
  intermediate `Vec<u8>` breaks it. Transparent forwarding also means the router
  cannot corrupt frame boundaries or normalize JSON — faithful by construction, no
  second faithfulness burden beyond the parser's.
- **Header allowlist + hop-by-hop drop:** hop-by-hop headers forwarded to the
  upstream can actively confuse it; dropping them is correctness, not polish. A full
  translation layer is out of scope.
- **Minimal errors:** resilience is tested/documented deliberately in Week 6. Building
  it now would be untested scope creep.
- **Config-driven upstream:** mirrors the mock-first philosophy — the swap is a no-op
  in code, so the one paid GPU session tests exactly one new thing.

---

## 3. Build order (each step de-risks the next)

Mirrors the measurement spec's staged build. Do not skip step 5's *timing*
demonstration — it's the whole point.

1. **Health-check route** (done). Confirms axum is up, routing works.
2. **Config plumbing.** Read `UPSTREAM_BASE_URL` (and any needed knobs) from env.
   Fail loudly at startup if unset. This lands first so nothing downstream is
   hardcoded.
3. **Proxy skeleton — no streaming yet.** One handler that opens the upstream request,
   forwards allowlisted request headers, and returns the upstream response. Prove a
   round-trip works against the mock (any config). Correctness of *routing*, not of
   *streaming*, at this stage.
4. **Streaming body.** Swap the response body to
   `Body::from_stream(upstream.bytes_stream())`. Preserve response `Content-Type`.
   Confirm a full response still arrives intact (fidelity — §4.1).
5. **Prove it streams, not buffers.** The timing demonstration (§4.2). This is the
   step that catches the library-default buffering mistakes. **Do not reduce it to
   "the bytes were correct."**
6. **Router-overhead comparison.** The measurement-spec requirement: client→mock vs
   client→router→mock, **strictly sequential**, small constant delta (§4.3).
7. **Only then** the GPU smoke test swap (config change per decision 6).

---

## 4. The eval — proving fidelity + streaming without flaking

The proxy's core property is a **negative, timing-based** property ("does not
buffer"). Naive timing assertions either flake on socket jitter or pass on a broken
router. The eval is designed so each test makes **one claim**, has **independent
ground truth**, and — critically — has a **negative control**: a deliberately-broken
router (or a deliberately-buffering handler) that the test **must fail against**. A
streaming test that can't distinguish a streaming router from a buffering one proves
nothing.

Four test groups: **fidelity**, **streaming (the hard one)**, **overhead**,
**headers/errors**.

### 4.1 Fidelity tests — bytes out == bytes in

**Claim:** the router forwards the response body byte-for-byte, and the mock→router
path is parser-indistinguishable from the direct-to-mock path.

- **F1 — byte-identity.** Capture the raw response body from client→mock directly, and
  from client→router→mock, for the same request. Assert the two byte sequences are
  **identical**. (Not "both parse the same" — *identical bytes*. Transparent
  forwarding must not re-serialize, re-order, or normalize whitespace.)
- **F2 — parser no-op.** Run the *existing metrics parser* (from the measurement
  module) over the router-proxied stream. Assert it extracts the same token count,
  same `t_first` gating behavior, same TPOT sample count as over the direct stream.
  This reuses your locked parser as an oracle — no new ground truth to derive.
- **F3 — all four mock configs.** F1+F2 across fast / slow / bursty / high-variance.
  The high-variance config matters here too: if the router ever coalesces chunks, the
  tail structure changes and F2's sample counts diverge.

**Negative control (must bite):** run F1/F2 against a **parse-and-re-emit** variant of
the handler (re-serializes each chunk through JSON). Byte-identity (F1) **must fail**
against it (JSON round-trip changes key order / whitespace), even though F2 might
still pass. This proves F1 is actually testing byte-identity and not just semantic
equivalence. Keep this variant in the test tree as a documented "wrong router."

### 4.2 Streaming tests — the router does not collect the body

This is the group that's easy to get wrong. The honest, non-flaky assertion is
**not** "first chunk arrives at exactly ttft_ms." Per the §1 scope note, the
application can't control per-chunk TCP delivery. The assertion that survives
lower-layer jitter is a **separation** assertion:

> Under a mock config whose total response takes much longer than its TTFT, a
> **streaming** router lets the client observe the first chunk **long before** the
> response completes; a **buffering** router makes the client wait until the whole
> response is done, so first-chunk-time ≈ completion-time.

The test measures the **gap between first-chunk arrival and last-chunk arrival** and
asserts it is **large** — i.e. the client genuinely received data incrementally.

- **S1 — incremental delivery.** Use a config with long total duration and many
  content chunks (e.g. slow: 500ms TTFT, 100ms TPOT, ≥20 content chunks → ~2.5s
  total). Record client-side arrival time of the **first** content chunk and the
  **last** content chunk. Assert:
  `(t_last_arrival − t_first_arrival)` **> [CALIBRATE] threshold** (should be close to
  the configured content-streaming duration, ~1.9s here; set the threshold well above
  socket-jitter noise but well below the true value — e.g. assert > 1.0s).
- **S2 — first chunk is early, not late.** Assert `t_first_arrival` is much closer to
  the configured TTFT than to the total completion time:
  `t_first_arrival < (t0 + TTFT + generous_margin)` where the margin is [CALIBRATE]
  but generous (buffering fails this by ~seconds; streaming passes with room). The
  point is a **coarse** bound that a buffering router blows through by orders of
  magnitude, not a tight timing check.

**Negative control (must bite) — the load-bearing test.** Build a **buffering
handler**: same routing, but it does `let body = upstream.bytes().await?;` (collect
the whole body) then returns it. Run S1 and S2 against it. **Both must fail:** S1's
first→last gap collapses toward zero (all bytes delivered at once at the end), and S2's
first-chunk-time balloons toward completion-time. If S1/S2 pass against the buffering
handler, they are worthless — the negative control is what proves they bite. Keep the
buffering handler permanently in the test tree, gated behind a test-only feature flag,
labeled `WRONG_ROUTER_BUFFERS`.

> This is the single most important eval decision in the router: **the streaming
> test's validity is defined by its failure against a known-buffering handler, not by
> its pass against the real one.** A green S1/S2 means nothing until you've watched it
> go red against the buffer.

### 4.3 Overhead test — small constant router cost

**Claim (measurement-spec requirement):** client→router→mock adds only a small,
roughly constant overhead vs. client→mock.

- **O1 — sequential overhead.** Strictly **sequential** (one request at a time — do
  **not** introduce concurrency here; it would mix router overhead with the mock's
  known concurrency artifact and produce an uninterpretable number). For N sequential
  requests each way, compare the **TTFT distributions** direct vs. proxied. Assert the
  **median** delta is below a small bound **[CALIBRATE]** (tie the bound to the noise
  floor you measure in the measurement-spec calibration — provenance, not a guess) and
  that the delta is roughly **constant** across configs (not growing with response
  size — growth would signal per-chunk work, i.e. hidden buffering/parsing).

**Negative control (must bite):** the buffering handler from §4.2. Its overhead is
**not** small/constant — it grows with total response duration (it waits for the whole
stream). O1 against it must show a delta that scales with response length, not a
constant. This proves O1 detects buffering *through the overhead signal* independently
of S1/S2 detecting it through the timing signal — two independent detectors of the
same failure.

### 4.4 Header + error tests

- **H1 — request header forwarding.** Assert the mock receives `Content-Type`,
  `Accept`, `Authorization` (when sent) and does **not** receive `Host`/`Connection`/
  `Transfer-Encoding` as forwarded from the client. (Have the mock echo received
  headers on a debug route, or assert via the mock's logs.)
- **H2 — response Content-Type preserved.** Client sees `text/event-stream` on the
  proxied response.
- **E1 — upstream down → 502.** Point the router at a dead address; assert the client
  gets a 502, not a hang or a 500-with-stacktrace.
- **E2 — mid-stream drop → clean truncation.** Kill the mock mid-response (or use a
  mock config that closes early); assert the client's stream **ends** without the
  router panicking or hanging. Behavior only — resilience is Week 6.

---

## 5. Eval rigor checklist (carried from the metrics-module standard)

- [ ] **One claim per test.** F/S/O/H/E each assert a single property.
- [ ] **Independent ground truth.** Fidelity uses the direct-to-mock stream and the
      existing locked parser as oracles — no re-derived expectations.
- [ ] **Negative controls that bite.** Two documented "wrong routers" live permanently
      in the test tree: `WRONG_ROUTER_BUFFERS` (collects the body) and a
      parse-and-re-emit variant. The streaming + overhead tests **must** fail against
      the buffering one; the byte-identity test **must** fail against the re-emit one.
      CI runs the negative controls and asserts they **fail** (a negative control that
      silently starts passing is itself a failure).
- [ ] **Provenance for every constant.** The S1 gap threshold, S2 margin, and O1
      overhead bound each trace to either the mock's configured timing or the measured
      noise floor — none are magic numbers. Document the trace inline.
- [ ] **Coarse where the layer is uncontrolled.** Streaming assertions are separation
      bounds (orders-of-magnitude gaps), never tight per-chunk timing — because
      per-chunk TCP delivery is below the application (§1 scope note).
- [ ] **Determinism.** Run the full router eval **5×**; sequential tests (fidelity,
      overhead) must be stable run-to-run. Streaming separation bounds are coarse
      enough to be deterministic.
- [ ] **Sequential isolation.** The overhead test is strictly sequential; no test in
      the Week 1 router suite issues concurrent load (that regime is untrusted until
      the Week 2 mock-concurrency question is resolved).

---

## 6. Definition of Done (router, Week 1)

- [ ] Config-driven upstream URL; startup fails loudly if unset.
- [ ] Proxy forwards allowlisted request headers; drops hop-by-hop.
- [ ] Response `Content-Type` preserved; framing left to axum/hyper.
- [ ] `bytes_stream()` → `Body::from_stream()`, body never collected.
- [ ] **F1–F3 pass** (byte-identity + parser no-op across all four configs).
- [ ] **S1–S2 pass against the real router AND fail against `WRONG_ROUTER_BUFFERS`.**
- [ ] **O1 passes** (small constant sequential overhead) **and fails against the
      buffering handler** (overhead scales with length).
- [ ] H1/H2/E1/E2 pass.
- [ ] Negative controls wired into CI as must-fail.
- [ ] Overhead bound + streaming thresholds calibrated and provenance-documented.
- [ ] 5× determinism check green.
- [ ] mock→vLLM swap confirmed a config-only change (GPU smoke test).

---

## 7. [CALIBRATE] values (set during build, document provenance)

| Value | Where | How to set |
|---|---|---|
| S1 first→last gap threshold | §4.2 | Well below configured content-stream duration, well above socket jitter. E.g. slow config ~1.9s true → assert > 1.0s. |
| S2 first-chunk margin | §4.2 | Generous bound above configured TTFT; buffering fails by seconds. |
| O1 overhead bound | §4.3 | Tie to the measurement-spec measured noise floor (same calibration run). Not a fresh guess. |

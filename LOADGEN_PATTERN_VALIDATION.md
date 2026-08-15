# Load Generator Request-Pattern Validation — Trace & Plan

Scope: whether the codebase, as it stands, captures enough to validate the
Week 2 load generators' **request patterns** (arrival distribution,
concurrency level, corpus sampling) when they run concurrently against the
mock — independent of the mock's response timing, which is untrusted under
concurrency. This document does not touch the router, percentile logic, or
the mock's timing fix.

---

## Part 1 — Trace: what is logged today

### What the metrics/consume path records per request

- `metrics/consume.py:consume_stream` produces one `RequestSample`
  (`metrics/types.py:33-49`) per request: `ttft_ms`, `tpot_samples_ms`,
  `content_chunk_count`, `error`. Nothing else per-request survives.
- `metrics/compute.py:aggregate` (`metrics/compute.py:90-146`) flattens a
  list of `RequestSample` into a `RunMetrics`: percentiles/mean for TTFT and
  TPOT, `n_requests`, `n_warmup_discarded`, `n_ttft_samples`,
  `n_tpot_samples`, `valid`, `config` (the dict passed in by the caller), and
  the raw arrays `raw_ttft_ms` / `raw_tpot_ms`.
- `RunMetrics.to_dict()` (`metrics/types.py:83-106`) is the on-disk record:
  one JSON object per **run**, containing `config`, counts, the four
  percentile/mean pairs, `valid`, and the two raw arrays. This confirms the
  brief's description — raw TTFT/TPOT sample arrays plus request count,
  warmup count, and config settings — and there is nothing beyond that: no
  per-request send timestamps, no request ids, no prompt data, no
  concurrency signal.

### Send-side signal (t0)

- `t0` is captured in the test driver, `tests/helpers.py:_drive_one`
  (`tests/helpers.py:21-28`), via `time.perf_counter()` immediately before
  `client.stream(...)` is awaited — matching the documented contract in
  `metrics/consume.py:29-34` and `WEEK1_MEASUREMENT_SPEC.md:79` ("`t0` =
  captured immediately BEFORE awaiting the HTTP client's `.send()`").
- `t0` is passed into `consume_stream(response, t0)` and used exactly once,
  inside `compute.request_sample_from_events` (`metrics/compute.py:67`), to
  compute `ttft_ms = (content_events[0].recv_time - t0) * 1000.0`.
- After that subtraction, `t0` is discarded. It is never stored on
  `RequestSample`, never appears in `RunMetrics`, and never reaches
  `to_dict()`. **It is used transiently to compute TTFT and is not
  retained in any output.**

### Concurrency-over-time

- `tests/helpers.py:drive_requests` (`tests/helpers.py:31-62`) bounds
  in-flight requests with an `asyncio.Semaphore(concurrency)`, but this only
  enforces an upper bound on concurrency at fire time — it does not log
  when each request opened or closed. There is no timestamp for
  request-start or request-end retained anywhere (see t0 above — dropped;
  and there is no "response fully consumed at time X" record either).
- Nothing in `metrics/types.py` or `metrics/compute.py` carries a start or
  end time per request. Concurrency-over-time (how many requests were open
  at a given instant) is **not reconstructable** from anything currently
  logged, because reconstructing it requires each request's open-interval
  (start time, end time), and neither endpoint is retained.

### Prompt payload / corpus

- `tests/helpers.py:_drive_one` sends a fixed body,
  `{"model": "mock", "messages": []}` (`tests/helpers.py:59`), with no
  prompt content and no length variation.
- `mock/app.py:chat_completions` (`mock/app.py:63-73`) reads `model` from
  the body but never reads `body["messages"]` — the mock is fully agnostic
  to prompt content. Token count is instead driven by the `num_tokens`
  query parameter (`mock/app.py:75`, `DEFAULT_NUM_TOKENS = 20`), not derived
  from any prompt.
- There is no ShareGPT reference, corpus loader, or prompt-id field
  anywhere in the codebase (`grep` for `ShareGPT|corpus` returns no hits
  outside this investigation). `loadgen/` currently contains only a README
  stub describing the intended steady/Poisson/adversarial generators — no
  implementation exists yet.
- **Prompt payload, prompt length, and corpus index/id are not captured
  anywhere today**, transiently or otherwise.

### Sequential-driver assumptions / per-request identity

- `RequestSample` (`metrics/types.py:33-49`) and `ChunkEvent`
  (`metrics/types.py:14-30`) carry no request id or index field.
- `drive_requests` preserves submission order only via
  `asyncio.gather(*tasks)` return order (`tests/helpers.py:61-62`), i.e.
  identity is purely positional/implicit, established by the Python list
  index at the driver layer — not by anything the metrics module logs. This
  works today only because the driver holds all samples in memory in one
  process and never emits a log line per in-flight request; nothing is
  overwritten because there is no shared mutable per-request log state.
- Concretely: nothing "breaks" under concurrency today only because nothing
  ties a log record to an individual request in the first place — nothing
  is written until the whole run completes and `aggregate()` flattens
  everything into pooled arrays. But that also means concurrent drivers
  produce **no artifact** from which per-request facts (its own t0, its own
  prompt, its own open-interval) could later be recovered or attributed.
  `raw_ttft_ms[i]` and `raw_tpot_ms` entries carry no link back to which
  request, which prompt, or when it was sent — they're pooled, unordered
  with respect to wall-clock time, by construction (`raw_tpot_ms` is a flat
  concatenation, `metrics/compute.py:122`).

### Verdicts

| Property | Reconstructable today? | Evidence |
|---|---|---|
| Arrival distribution (send timestamps) | **No** | `t0` computed in `tests/helpers.py:26` and consumed only inside `compute.py:67`; never stored on `RequestSample`/`RunMetrics`/`to_dict()`. |
| Concurrency level (overlapping open requests) | **No** | No start or end timestamp is retained per request anywhere; `asyncio.Semaphore` only bounds concurrency, doesn't log it. |
| Corpus sampling (prompts sent) | **No** | `messages` body is fixed/empty in the driver and unread by the mock (`mock/app.py`); no corpus, prompt-id, or length field exists in the codebase. |

None of the three properties is reconstructable from what's logged today.
Additionally, there is no per-request identity (no request id) anywhere in
the metrics types, which would be required before any of the above could be
safely logged under concurrent drivers without collision.

---

## Part 2 — Plan: minimal additions to close the gaps

All three properties are missing, so all three need an addition. Constraint
recap: generator-side only, raw per-request facts (not pre-aggregated),
each fact tagged with a per-request id, minimal and additive.

### 0. Per-request identity (prerequisite for the other three)

- **Add:** a `request_id` (e.g. a per-run monotonically increasing int, or
  a UUID) generated by the load generator at the moment it decides to fire
  a request — before `.send()`.
- **Where:** attached at the generator/driver layer (the future
  `loadgen/` code, analogous to today's `tests/helpers.py:_drive_one`), and
  threaded through into whatever record is written per request.
- **Why generator-side-only:** the id is assigned by the sender, not
  derived from the mock's response — a pure bookkeeping value, unaffected
  by response timing.
- Without this, concurrent requests' log records cannot be told apart —
  this is the piece that makes the rest of the plan safe under concurrency.

### 1. Arrival distribution — needs `send_time` retained

- **Gap:** `t0` already exists (`tests/helpers.py:26`) but is consumed and
  dropped inside `compute.request_sample_from_events` (`compute.py:67`);
  it never reaches output.
- **Add:** log `request_id, send_time` (the existing `t0` value, one row
  per request) to a per-request raw log, at the moment the generator
  captures `t0` — i.e. right where it's already captured today, just
  retained instead of discarded after the TTFT subtraction.
- **Why generator-side-only:** `send_time` is the generator's own clock
  read, taken before the request leaves the process; it says nothing about
  how the mock responds. The distribution to validate (steady/Poisson/
  adversarial) is a property of consecutive `send_time` gaps, computable
  entirely offline from this column.
- **Reconstructable, not pre-computed:** log the raw `send_time` per
  request, not a pre-computed "mean inter-arrival gap" — the specific
  distribution shape (evenly-spaced vs. Poisson vs. flood) is derived
  offline from the raw timestamps, consistent with the existing raw-sample
  stance in `metrics/types.py`.

### 2. Concurrency level — needs an open-interval per request

- **Gap:** no start or end timestamp is retained anywhere.
- **Add:** two fields per request: `send_time` (shared with #1) and
  `close_time` — a generator-side timestamp taken when the generator
  observes the request's stream end (i.e. when it stops waiting on that
  request), not a timing measurement of the mock's delivery *rate*.
- **Where:** `close_time` captured at the same call site that currently
  awaits the streamed response to completion in the driver (the
  `async with client.stream(...)` block, e.g. `tests/helpers.py:27-28`, or
  its Week 2 loadgen equivalent) — right after the response is fully
  drained, before discarding it.
- **Why generator-side-only:** concurrency level only needs to know *that a
  request was open* between two generator-observed instants — it does not
  require trusting that the mock's *internal pacing* (ttft/tpot delivery
  timing) was accurate. Overlap counting from `[send_time, close_time]`
  intervals is valid even if the mock's per-chunk timing drifted under
  load, because it only uses the two boundary events, not the timing
  in between.
- **Reconstructable, not pre-computed:** log the raw interval endpoints per
  request; concurrency-over-time is computed offline by sweeping
  `send_time`/`close_time` events, not logged as a pre-aggregated
  "concurrency chart."
- Note: this reuses `request_id` and `send_time` from items 0–1 — the only
  net-new field here is `close_time`.

### 3. Corpus sampling — needs prompt identity/length recorded

- **Gap:** the driver sends a fixed empty `messages` body; the mock doesn't
  read it; nothing about the actual ShareGPT corpus draw exists yet.
- **Add:** `request_id, prompt_id, prompt_len` per request — `prompt_id`
  being whatever index/key the generator used to draw from the ShareGPT
  corpus, `prompt_len` a cheap derived scalar (token or char count) logged
  alongside it for convenience.
- **Where:** captured by the generator at the moment it selects the prompt
  for a request (before building the HTTP body), the same place it will
  need to read the corpus anyway to build `messages`.
- **Why generator-side-only:** which prompt was chosen and how long it is
  are facts about the generator's own sampling step, fully determined
  before the request is ever sent — entirely independent of how the mock
  responds.
- **Reconstructable, not pre-computed:** log `prompt_id`/`prompt_len` raw
  per request rather than a pre-computed corpus histogram; the content and
  length distribution actually sent is derived offline by aggregating this
  column, so it validates the generator's real draws rather than its
  intended sampling plan.

### Where this lives

All of the above is additive and orthogonal to `metrics/types.py`'s
existing `RequestSample`/`RunMetrics` (which stay focused on TTFT/TPOT).
The natural home is a new, separate per-request raw log emitted by the
Week 2 loadgen itself (`loadgen/`, not yet implemented) — one row per
request with columns `request_id, send_time, close_time, prompt_id,
prompt_len` — written independent of, and never derived from, the mock's
response-timing path in `metrics/`. This keeps the "log raw samples,
compute stats separately" stance: all three distributions (arrival,
concurrency, corpus) are computed offline from these five raw columns.

---

**Summary: 5 new fields proposed** — `request_id`, `send_time`,
`close_time`, `prompt_id`, `prompt_len` — covering all three gaps
(arrival distribution, concurrency level, corpus sampling); no change
needed to the existing TTFT/TPOT logging path.

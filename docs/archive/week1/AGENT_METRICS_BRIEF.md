# Coding Agent Brief — Metrics Module (Week 1)

## Context
You are implementing the **metrics module** for LLMRouter, a project that measures
token-level latency SLOs for LLM inference. This module parses a streamed SSE
response (from a mock replica now, real vLLM later) and computes TTFT and TPOT
percentiles. It is the measurement instrument the entire project depends on, so
**correctness and testability are the priorities**, not performance.

The authoritative definitions are in `WEEK1_MEASUREMENT_SPEC.md`. This brief
implements them. Where they differ, the spec wins — flag any conflict.

## Design constraint: pure core + thin I/O shell
Split the module into two layers so the core logic is unit-testable without HTTP:
- **Pure functions** that take timestamp arrays / parsed chunks and return metrics.
  No I/O, no clock reads inside them — timestamps are passed in.
- **A thin streaming consumer** that reads an SSE response, records timestamps, and
  hands them to the pure functions.

This split is mandatory: the deterministic tests feed known inputs to the pure
functions directly. If timing logic is tangled with HTTP, it can't be tested cleanly.

---

## 1. Module structure

```
metrics/
  __init__.py
  parse.py        # SSE chunk parsing (pure)
  compute.py      # percentile + aggregation logic (pure)
  consume.py      # streaming consumer: reads response, stamps timestamps
  types.py        # dataclasses: ChunkEvent, RequestSample, RunMetrics
```

---

## 2. Data types (`types.py`)

Define dataclasses:

- `ChunkEvent`: `{ recv_time: float, is_content: bool, content: str | None, raw: dict }`
  - `recv_time` is a monotonic timestamp (see §4).
  - `is_content` is True only for chunks with non-empty `delta.content`.

- `RequestSample`: the per-request result:
  - `ttft_ms: float | None`  (None if the request produced no content chunk)
  - `tpot_samples_ms: list[float]`  (K−1 gaps for K content chunks)
  - `content_chunk_count: int`
  - `error: str | None`

- `RunMetrics`: the aggregate over a run:
  - `ttft_p50, ttft_p95, ttft_p99, ttft_mean: float`
  - `tpot_p50, tpot_p95, tpot_p99, tpot_mean: float`
  - `n_requests: int` (measured, post-warmup)
  - `n_warmup_discarded: int`
  - `n_ttft_samples: int`, `n_tpot_samples: int`
  - `valid: bool`  (False if below min-sample threshold; see §5)
  - `config: dict`  (echoes the run config for metadata logging)
  - `raw_ttft_ms: list[float]`, `raw_tpot_ms: list[float]`  (full sample arrays)

---

## 3. SSE parsing (`parse.py`) — pure

Implement `parse_sse_line(line: str) -> dict | None | "DONE"`:
- A line not starting with `data: ` → return None (ignore; e.g. blank lines, SSE comments starting with `:`).
- `data: [DONE]` → return the sentinel `"DONE"`.
- `data: {json}` → parse JSON and return the dict. On JSON parse failure, raise a
  clear error (a malformed chunk is a real bug, not something to silently skip).

Implement `is_content_chunk(chunk: dict) -> bool`:
- True iff `chunk["choices"][0]["delta"].get("content")` is a non-empty string.
- The role chunk (`delta.role`, no content), the final chunk (`delta` empty,
  `finish_reason == "stop"`), and any empty-content chunk → False.
- Assume `n = 1`: only read `choices[0]`. If `choices[0]["index"] != 0`, raise
  (out of contract per spec §1).

Implement `extract_content(chunk: dict) -> str | None`:
- Return `delta.content` if present and non-empty, else None.
- Note: content is read from `delta.content`. `delta.reasoning_content` is out of
  scope (non-reasoning models) — do not read it, but leave a code comment noting it.

---

## 4. Streaming consumer (`consume.py`)

Implement `async def consume_stream(response) -> RequestSample`:
- Iterate the response's lines/bytes as they arrive.
- **Use a monotonic clock** (`time.perf_counter()`), never wall-clock (`time.time()`),
  for all latency math — wall-clock can jump (NTP adjustments) and corrupt gaps.
- The caller records `t0` (before `.send()` is awaited) and passes it in, OR
  `consume_stream` accepts `t0` as an argument. **`t0` must be captured before the
  send is awaited** — document this in the function contract.
- For each parsed chunk, build a `ChunkEvent` with `recv_time = perf_counter()`.
- **TTFT** = `recv_time` of the FIRST content chunk − `t0`. Convert to ms.
  - If no content chunk ever arrives, `ttft_ms = None` and record an error.
- **TPOT samples** = consecutive differences between `recv_time`s of content chunks
  only (ignore role/final/empty chunks entirely in gap math). K content chunks →
  (K−1) samples, in ms.
- Return a `RequestSample`.

Critical: the role chunk and final chunk are parsed but must NOT enter TTFT or TPOT
timing. Only content chunks define timing.

---

## 5. Aggregation + percentiles (`compute.py`) — pure

Implement `percentile(sorted_samples: list[float], p: float) -> float`:
- Use a clearly-documented, standard method. **Linear interpolation between closest
  ranks** (equivalent to numpy's default `linear` / `method="linear"`). Document the
  exact formula in a docstring. Do NOT hand-roll an off-by-one nearest-rank variant
  without documenting it — the percentile method is a correctness-critical choice.
- Handle edge cases: empty list → raise; single element → returns that element;
  p at 0 or 100 → min / max.
- Prefer delegating to `numpy.percentile(a, p, method="linear")` and pin the method
  explicitly, rather than reimplementing, UNLESS the project wants zero numpy
  dependency (confirm; default: numpy is fine).

Implement `aggregate(samples: list[RequestSample], warmup: int, min_samples: int, config: dict) -> RunMetrics`:
- **Discard the first `warmup` (=10) samples** by request order (not by sorting).
- From the remaining measured samples:
  - Collect all non-None `ttft_ms` → TTFT population.
  - Flatten all `tpot_samples_ms` → TPOT population.
- **Min-sample rule:** if the count of measured (post-warmup) requests < `min_samples`
  (=100), set `valid = False` and DO NOT compute p95/p99 (leave them as NaN or None,
  and make `valid=False` obvious to the caller). p50/mean may still be computed for
  visibility, but the run is flagged invalid for tail reporting.
- Compute p50/p95/p99/mean for both TTFT and TPOT.
- Populate `raw_ttft_ms` / `raw_tpot_ms` with the full post-warmup arrays.
- Echo `config` into the result for metadata logging.

---

## 6. Metadata logging

Provide `run_metrics.to_dict()` producing a JSON-serializable record containing:
- config (ttft_ms, tpot_ms, config name, num_tokens, warmup, min_samples)
- n_requests, n_warmup_discarded, n_ttft_samples, n_tpot_samples, valid
- all percentiles + means
- the raw sample arrays

This record is what every benchmark run writes to disk. One run = one JSON record.

---

## 7. Explicit non-goals (do NOT implement)
- No HTTP client / loadgen loop (that's a separate component; this module is called
  by it). Provide `consume_stream` that accepts a response object; do not build the
  request driver here.
- No routing, admission control, or multi-replica logic.
- No plotting/dashboard (separate).
- Do not "helpfully" smooth, clip, or discard outliers beyond the fixed warmup — the
  tail is the signal; silently dropping it is a correctness bug.

## 8. Deliverables
- The four module files under `metrics/`.
- Docstrings on every pure function stating inputs, outputs, and the exact percentile
  method used.
- A short `metrics/README.md` documenting the pure-core/thin-shell split and the
  timing definitions (cross-reference WEEK1_MEASUREMENT_SPEC.md).
- Commit in small steps: types → parse → compute → consume → README.

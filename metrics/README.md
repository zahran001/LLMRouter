# metrics

Python metrics computation (TTFT/TPOT percentiles) for analyzing benchmark
results. This is the measurement instrument the rest of LLMRouter trusts —
see `WEEK1_MEASUREMENT_SPEC.md` (repo root) for the locked, authoritative
definitions this module implements, and `METRICS_TEST_SUITE.md` for how it's
proven correct.

## Pure core / thin shell split

The module is deliberately split so the timing math is unit-testable without
any HTTP:

| File | Layer | Reads a clock? | Does I/O? |
|---|---|---|---|
| `types.py` | data | no | no |
| `parse.py` | pure core | no | no |
| `compute.py` | pure core | no | no |
| `consume.py` | thin shell | yes (`time.perf_counter`) | yes |

- **`parse.py`** turns a raw SSE line into a parsed chunk, and classifies a
  parsed chunk as content or not, per the streaming contract. No timestamps
  involved at all.
- **`compute.py`** takes timestamps/samples that were already captured
  elsewhere and computes TTFT/TPOT/percentiles from them. In particular,
  `request_sample_from_events(events, t0)` derives one request's TTFT and
  TPOT samples from a list of already-timestamped `ChunkEvent`s — this is
  the function the Tier 1 tests feed synthetic chunk sequences to directly
  (`METRICS_TEST_SUITE.md` §1d), with no server involved.
- **`consume.py`** is the only place that reads a clock or touches an HTTP
  response. Its job is narrow: iterate the response, timestamp each parsed
  chunk with a monotonic clock, and hand the resulting `ChunkEvent` list to
  `compute.request_sample_from_events`. It contains no timing *logic* — only
  timing *capture*.

If you find yourself computing a gap or a percentile inside `consume.py`,
that's a sign the split has been violated — move it into `compute.py` and
have `consume.py` call it.

## Timing definitions (see WEEK1_MEASUREMENT_SPEC.md §2 for the authoritative text)

- **t0** is captured by the *caller* of `consume_stream`, immediately before
  awaiting the HTTP client's `.send()`/`.stream()` call — deliberately
  before this module ever runs. This includes connection + request-send
  time in TTFT, and is why connection pooling matters for steady-state
  measurement (warmup requests establish the pool).
- **TTFT** = time of the first chunk with non-empty `delta.content`, minus
  t0. The role chunk and any empty-content chunk cannot set TTFT.
- **TPOT samples** = gaps between consecutive *content* chunks only. K
  content chunks yield K-1 samples. Non-content chunks interleaved between
  content chunks (there aren't supposed to be any per the streaming
  contract, but the code doesn't assume that) do not create bogus gaps,
  because gaps are computed over the content-only subsequence.
- All latency math uses a **monotonic clock** (`time.perf_counter()`),
  injectable in `consume_stream` via the `clock=` parameter for testing.
  Never wall-clock (`time.time()`) — it can jump under NTP adjustment and
  corrupt gap measurements mid-run.

## Warmup and minimum samples

- The first **10** requests of a run are discarded by *order*, not by
  value — `aggregate()` drops `samples[:warmup]` regardless of what those
  samples measured.
- Below **100** measured (post-warmup) requests, `RunMetrics.valid` is
  `False` and p95/p99 are `NaN` for both TTFT and TPOT — a tail percentile
  computed from fewer than 100 samples is noise, not signal, and must not
  be reported as one. p50/mean are still computed for visibility.
- Outliers are never clipped, smoothed, or dropped beyond that fixed
  warmup. The tail is the signal `compute.aggregate` is built to preserve.

## Percentile method

`compute.percentile` uses **linear interpolation between closest ranks**
(numpy's `method="linear"`, delegated to `numpy.percentile` rather than
hand-rolled). See the function's docstring for the exact formula. This
choice is correctness-critical: it is pinned explicitly and the unit tests
assert against independently hand-computed / numpy-derived literals — never
against the function's own output.

## What this module does not do (see AGENT_METRICS_BRIEF.md §7)

No HTTP client / request driver (that's the loadgen's job — this module is
called by it via `consume_stream(response, t0)`), no routing or admission
control, no plotting/dashboards.

## Simulated-token caveat

Week 1 measures inter-SSE-chunk gaps, not tokenizer-level per-token
latency. For the mock (1 token per chunk) these coincide; real vLLM may
batch multiple tokens per chunk, so true per-token TPOT is out of scope
here (spec §2).

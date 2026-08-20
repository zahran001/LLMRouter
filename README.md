# LLMRouter

[![router eval](https://github.com/zahran001/LLMRouter/actions/workflows/router-eval.yml/badge.svg)](https://github.com/zahran001/LLMRouter/actions/workflows/router-eval.yml)

A Rust router that sits in front of a pool of vLLM inference replicas and
defends per-request latency SLOs — time-to-first-token (TTFT) and
time-per-output-token (TPOT) — through real-time admission control and
routing, under bursty and adversarial load.

> **Current progress lives in [`STATUS.md`](STATUS.md).** This file describes
> the project and how it is built; it deliberately says nothing about how far
> along it is.

---

## The problem

A single vLLM replica serving interactive traffic has a knee. Below it,
first-token latency is flat and boring. Above it, requests queue behind each
other, TTFT climbs, and the experience degrades — well before the GPU looks
saturated on a utilization graph.

The project is organized around one number:

> **At X RPS, naive single-replica serving breaches the 500ms p99 TTFT SLO.**

That sentence is the problem statement, and the router's job is to push the
breach to higher RPS. **500ms is a single SLO used everywhere in the project**
— it is both the threshold that defines the baseline breach and the target the
router later defends. That is deliberate: the naive curve's 500ms crossing
*is* the reference the routing work improves on, so there is no
re-baselining later and no "but the real SLO is different" seam. A 2s line is
recorded alongside it as a severe-degradation reference, plotted but never
used as a second breach definition.

## Approach

The project is built measurement-first. The router is the deliverable, but the
instrument that evaluates it is built, calibrated, and proven **before** the
thing it measures — because a routing improvement you cannot trust the
measurement of is not an improvement.

Four ideas drive most of the design:

**1. Measure the client's experience, not the server's self-report.** TTFT and
TPOT are captured client-side from the SSE stream, with `t0` taken before the
request is sent, so connection and request-send time are inside TTFT where the
user feels them.

**2. Open-loop load generation.** A closed-loop generator (send → wait for
response → send again) lets server latency feed back into arrival timing, so
it backs off exactly at the knee — and therefore *cannot observe the breach it
exists to find*. The load generator pre-materializes its entire arrival
schedule before sending anything, then fires against absolute wall-clock
targets and never waits for a response.

**3. A stated trust boundary for the mock.** Development runs against a Python
mock replica, but the mock is trusted for *sequential* timing fidelity only —
under concurrency its timing drifts, so it is trusted to validate what the
load generator **sends**, never how fast responses come **back**. Every latency
number the project reports comes from real vLLM on a GPU
(`MOCK_TRUST_BOUNDARY.md`).

**4. Tests that are proven to be able to fail.** A green test that never went
red proves nothing, and "make the test pass" and "make the test meaningfully
pass" look identical in a checkmark. So the important checks ship with
**negative controls** — deliberately broken variants that the check must go
red against. The router eval runs against two intentionally-wrong routers and
CI fails if the eval *passes* them; the load generator's validations each have
a paired control (a closed-loop scheduler, a broken concurrency cap, a dropped
log write) that must trip them.

### Calibration and provenance discipline

Two conventions appear throughout the planning documents and are worth knowing
before reading them:

- **`LOCKED`** marks a decision that is fixed, with its rationale recorded
  next to it. Expanding a locked artifact requires a provenance note naming
  the cause — so a later reader can tell a justified expansion from drift.
- **`[CALIBRATE]`** marks a constant that must come from a measurement, never
  a guess, and names the specific measurement it must come from. Timing
  tolerances, noise floors, warmup windows and concurrency caps are all
  calibrated values with recorded sources, not round numbers someone liked.

Empirical work is separated by **hard stops**: blocking gates where evidence
is produced and a human renders the verdict, rather than the implementation
self-certifying. This matters most right before spending money on GPUs.

## How it's implemented

### Components

| Directory | Language | Role |
|---|---|---|
| `router/` | Rust (axum + tokio) | The core deliverable. Streaming reverse proxy for vLLM's OpenAI-compatible API; SLO-aware admission control and multi-replica routing build on top of it. |
| `loadgen/` | Python | Open-loop traffic generators (steady, Poisson, adversarial) that drive the router or a replica directly. |
| `metrics/` | Python | The measurement instrument: SSE parsing, TTFT/TPOT derivation, percentiles, per-point baseline records. |
| `mock/` | Python (Starlette) | A mock replica streaming fake tokens in vLLM's SSE format, with configurable timing profiles, for development without a GPU. |
| `scripts/` | Bash + Python | Corpus building, calibration runs, offline analysis, and the metered GPU-session runbook. |

### The router

A transparent, streaming pass-through proxy is the foundation. Two properties
are treated as load-bearing and are asserted by the eval:

- **Fidelity** — bytes out equal bytes in, so swapping the mock for real vLLM
  is a configuration change (`UPSTREAM_BASE_URL`) and never a code change. Any
  required code change during a GPU session is recorded as a finding.
- **Streaming** — the router never collects the response body; chunks are
  forwarded as they become available. The eval asserts coarse separation
  bounds rather than tight per-chunk timing, because `Body::from_stream()`
  makes no promise that one upstream chunk becomes one TCP packet.

Deliberately absent for now: retries, graceful shutdown, and any per-chunk
response inspection. See `router/README.md`.

### The measurement instrument

`metrics/` is split so the timing math is unit-testable with no HTTP involved
at all:

| Layer | Files | Reads a clock? | Does I/O? |
|---|---|---|---|
| data | `types.py` | no | no |
| pure core | `parse.py`, `compute.py`, `point.py` | no | no |
| thin shell | `consume.py` | yes | yes |

Every timing decision lives in the pure core and is tested with synthetic
chunk sequences; `consume.py` is the only file that reads a clock or touches a
socket. `WEEK1_MEASUREMENT_SPEC.md` holds the authoritative definitions and
`METRICS_TEST_SUITE.md` describes how they are proven.

### The load generator

Per run, the generator pre-materializes an `(offset, prompt_id)` schedule from
a seeded RNG, commits it to disk **before sending anything**, and then drives
it. Arrival times and prompt draws come from independent RNG streams so they
cannot perturb each other. Prompts are drawn from a pinned ShareGPT subset
committed as a versioned artifact with a content hash, and a schedule refuses
to replay against a corpus whose hash does not match its provenance.

Each run emits three artifacts, written as each row is produced rather than
buffered until the end, so a crash mid-run does not lose what came before it:

| File | Contents |
|---|---|
| `<tag>.raw_log.jsonl` | one row per request: send/close times, prompt, and status (`sent`/`shed`/`errored`) |
| `<tag>.samples.jsonl` | one row per issued request: TTFT and per-token gaps |
| `<tag>.metrics.json` | the point record: percentiles, validity gates, breach verdict |

Two gates guard against the instrument quietly lying about its own input. A
point whose **achieved** send rate diverges from the **offered** rate beyond a
calibrated band is flagged and plotted at the rate the server actually saw,
never dropped — dropping flagged points would systematically remove data near
the breach, the worst place to lose it. And a point that fails to accumulate
enough post-warmup samples is marked tail-invalid, so its p99 is never
reported as a tail estimate.

### Reproducibility

A benchmark result is only worth as much as the ability to re-derive it. The
committed schedule and corpus artifacts pin the workload; a replay asserts
**workload identity** (byte-identical arrivals and prompt sequence) rather than
latency identity, since identical latency is exactly what a benchmark is
measuring and must be free to vary. Analysis runs offline against the durable
artifacts after the GPU is torn down, so no GPU time is ever spent computing a
percentile.

## Repo structure

```
router/          Rust axum+tokio router (core deliverable)
loadgen/         Open-loop load generators (steady, poisson, adversarial)
metrics/         Measurement instrument (SSE parse, TTFT/TPOT, percentiles)
mock/            Mock vLLM replica (Starlette, SSE, configurable timing)
corpus/          Pinned ShareGPT prompt subset + provenance
benchmarks/      Committed schedules and calibration data; run outputs (gitignored)
scripts/         Corpus build, calibration, offline analysis
scripts/gpu_session/   The metered GPU-session runbook (human-run)
tests/           Tiered suite: pure unit, live-mock integration, deterministic eval
docs/            Architecture notes, ADRs, GPU session notes
docs/adr/        Architecture Decision Records
docs/archive/    Completed per-week process docs
```

## Getting started

**Router** (Rust):

```bash
cd router
cargo build
UPSTREAM_BASE_URL=http://127.0.0.1:9001 cargo run   # GET /health returns "ok"
```

`UPSTREAM_BASE_URL` is required and has no default — the mock→vLLM swap is a
config change, not a code change.

**Python side** (`metrics/`, `loadgen/`, `mock/`, tests):

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on macOS/Linux
.venv/Scripts/python -m pytest tests            # full suite, ~11 min
.venv/Scripts/python -m pytest tests/unit       # pure timing logic, instant
```

The suite is tiered. `tests/unit` is pure — synthetic chunk sequences, no
clock, no socket — and runs in well under a second. The integration, eval,
router and load-generator tiers each start a live mock server, and the
deterministic eval tier accounts for most of the wall-clock time because it
drives real streams at configured timings. One known failure is listed in
[`STATUS.md`](STATUS.md).

**Run the mock replica** and drive traffic at it:

```bash
.venv/Scripts/python -m uvicorn mock.app:app --port 9001
.venv/Scripts/python -m loadgen.poisson --rps 8 --duration 30 --seed 1 \
    --base-url http://127.0.0.1:9001 --mock-config slow
```

**The router gate** (eval plus the must-fail negative controls, ~2 minutes) —
this is what CI runs:

```bash
PYTHON=.venv/Scripts/python scripts/router_eval.sh      # one pass, as CI runs it
PYTHON=.venv/Scripts/python scripts/router_eval.sh 5    # 5x determinism check
```

Standing up real vLLM on a GPU? Two files, in this order.
`docs/WEEK2_DOC_INDEX.md` tells you which documents govern the session — Week 2
carries two design generations and several superseded runbooks that would still
run. Then `docs/GPU_SESSION_NOTES.md`, which carries the exact working
`gcloud`/vLLM invocation plus several environment-specific failures already
worked out, each one hit for real rather than anticipated.

## Design decisions

Architecture Decision Records live in `docs/adr/`:

- **[0001](docs/adr/0001-priority-lanes-queue-level-only.md)** — priority lanes
  are queue-level only; no mid-generation preemption in v1.
- **[0002](docs/adr/0002-kv-aware-routing-worst-case-estimate.md)** — KV-aware
  routing uses a worst-case footprint estimate rather than modelling vLLM's
  internal scheduler, trading precision for capacity estimates that are stable
  and independent of vLLM internals.
- **[0003](docs/adr/0003-single-cloud-gcp.md)** — single cloud (GCP), so the
  whole benchmark environment is reproducible from one CLI.

## Document map

| Document | What it is |
|---|---|
| `STATUS.md` | Current phase and progress |
| `docs/WEEK2_DOC_INDEX.md` | **Which Week 2 documents govern** — authority, evidence, and what must not be executed |
| `docs/architecture.md` | System architecture |
| `WEEK1_MEASUREMENT_SPEC.md` | Authoritative TTFT/TPOT and streaming-contract definitions |
| `METRICS_TEST_SUITE.md` | How the measurement instrument is proven correct |
| `MOCK_TRUST_BOUNDARY.md` | What the mock is and is not trusted for |
| `BENCHMARKS.md` | Calibrated constants and their measured provenance |
| `WEEK2_PLAN.md` | Baseline and load-generator decision record (`LOCKED` / `[CALIBRATE]`) |
| `WEEK2_EXECUTION.md` | Execution order, blocks, and hard stops |
| `docs/WEEK2_GPU_SESSION_2_PLAN.md` | The current — and only — GPU-session runbook |
| `LOADGEN_PATTERN_VALIDATION.md` | Load-generator validation procedure |
| `docs/GPU_SESSION_NOTES.md` | Hard-won GCP + vLLM operational knowledge |

## License

MIT — see [LICENSE](LICENSE).

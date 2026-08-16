# LLMRouter

[![router eval](https://github.com/zahran001/LLMRouter/actions/workflows/router-eval.yml/badge.svg)](https://github.com/zahran001/LLMRouter/actions/workflows/router-eval.yml)

A Rust router that sits in front of a pool of vLLM inference replicas and protects per-request latency targets (time-to-first-token and time-per-output-token) through real-time admission and routing decisions, even under bursty or adversarial load.

## Status

Week 1 (foundation & measurement) is closed — see
`docs/archive/week1/` for the completed implementation/closeout docs and
`WEEK2_PLAN.md` for what's next. Work in progress — Week 2 (load
generation & baseline).

The `router eval` badge above is the Week 1 gate: it runs the fidelity, streaming, overhead and header/error tests **and** the two deliberately-broken routers the eval must fail against, so it goes red both when the router regresses and when the eval loses its teeth (`docs/archive/week1/WEEK1_ROUTER_IMPL.md` §4–§5).

## Planned architecture

- **`router/`** — the Rust axum+tokio router. The core deliverable: SLO-aware admission control and request routing in front of vLLM replicas. Week 1 ships the transparent single-replica pass-through proxy (streams, never buffers) — see `router/README.md`.
- **`mock/`** — a minimal Python Starlette mock replica that streams fake tokens in vLLM's SSE format, standing in for real vLLM instances during development. Implemented just enough to drive `metrics/`'s tests — see `mock/README.md`.
- **`loadgen/`** — Python load generators (steady, poisson, adversarial) that drive traffic against the router. Not yet implemented.
- **`metrics/`** — Python metrics computation for TTFT/TPOT percentiles and other benchmark analysis. Implemented (pure-core/thin-shell split); see `metrics/README.md`.

## Repo structure

```
router/          # Rust axum+tokio router (core deliverable)
loadgen/         # Python load generators (steady, poisson, adversarial)
mock/            # Python FastAPI mock replica
metrics/         # Python metrics computation (TTFT/TPOT percentiles)
scripts/         # Operational scripts (teardown, reproduce)
docs/            # Architecture notes, ADRs, GPU session notes
docs/adr/        # Architecture Decision Records
docs/archive/    # Completed per-week process docs (implementation briefs, closeout runbooks)
benchmarks/      # Output CSVs and generated charts (gitignored contents)
```

## Getting started

```bash
cd router
cargo build
UPSTREAM_BASE_URL=http://127.0.0.1:9001 cargo run   # GET /health returns "ok"
```

`UPSTREAM_BASE_URL` is required and has no default — the mock→vLLM swap is a
config change, not a code change.

For the Python side (`metrics/`, `mock/`, and their test suites):

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on macOS/Linux
.venv/Scripts/python -m pytest tests            # 26 pure unit tests + live-mock integration/eval tests
```

The Week 1 router gate (eval + must-fail negative controls, ~2 minutes) is:

```bash
PYTHON=.venv/Scripts/python scripts/router_eval.sh      # one pass, as CI runs it
PYTHON=.venv/Scripts/python scripts/router_eval.sh 5    # 5x determinism check
```

The load generator is not yet implemented — see `WEEK2_PLAN.md` for scope and `docs/` for architecture decisions.

Standing up a real vLLM GPU instance (needed for Week 2's `BASELINE.md` and beyond)? Read `docs/GPU_SESSION_NOTES.md` first — it has the exact working `gcloud`/vLLM invocation and several environment-specific gotchas already worked out.

## License

MIT — see [LICENSE](LICENSE).

# LLMRouter

A Rust router that sits in front of a pool of vLLM inference replicas and protects per-request latency targets (time-to-first-token and time-per-output-token) through real-time admission and routing decisions, even under bursty or adversarial load.

## Status

Work in progress — Week 1 (foundation & measurement).

## Planned architecture

- **`router/`** — the Rust axum+tokio router. The core deliverable: SLO-aware admission control and request routing in front of vLLM replicas.
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
docs/            # Architecture notes and ADRs
docs/adr/        # Architecture Decision Records
benchmarks/      # Output CSVs and generated charts (gitignored contents)
```

## Getting started

```bash
cd router
cargo build
cargo run   # starts the router; GET /health should return "ok"
```

For the Python side (`metrics/`, `mock/`, and their test suites):

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on macOS/Linux
.venv/Scripts/python -m pytest tests            # 26 pure unit tests + live-mock integration/eval tests
```

The load generator is not yet implemented — see `docs/` for planned architecture and scope decisions.

## License

MIT — see [LICENSE](LICENSE).

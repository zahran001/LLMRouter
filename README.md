# LLMRouter

A Rust router that sits in front of a pool of vLLM inference replicas and protects per-request latency targets (time-to-first-token and time-per-output-token) through real-time admission and routing decisions, even under bursty or adversarial load.

## Status

Work in progress — Week 1 (foundation & measurement).

## Planned architecture

- **`router/`** — the Rust axum+tokio router. The core deliverable: SLO-aware admission control and request routing in front of vLLM replicas.
- **`mock/`** — a Python FastAPI mock replica that streams fake tokens, standing in for real vLLM instances during development.
- **`loadgen/`** — Python load generators (steady, poisson, adversarial) that drive traffic against the router.
- **`metrics/`** — Python metrics computation for TTFT/TPOT percentiles and other benchmark analysis.

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

The rest of the stack (mock replica, load generators, metrics) is not yet implemented — see `docs/` for planned architecture and scope decisions.

## License

MIT — see [LICENSE](LICENSE).

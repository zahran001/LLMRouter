# Architecture

LLMRouter is a Rust router that sits in front of a pool of vLLM replicas and enforces token-level SLOs (TTFT/TPOT) by admitting, queuing, and routing requests based on estimated replica load, while a Python-based load generator and metrics pipeline are used to benchmark and validate its behavior under adversarial traffic.

<!-- architecture diagram goes here -->

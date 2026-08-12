# 0003. Single cloud: GCP

## Status

Accepted

## Context

The project needs GPU compute for vLLM replicas plus the surrounding infrastructure (orchestration, observability) to run benchmarks. Spanning multiple cloud providers would let the project avoid vendor lock-in, but it multiplies the operational surface area (separate quota/billing/IAM models, separate Kubernetes distributions, separate observability stacks) for a project whose goal is a reproducible benchmark environment, not a multi-cloud deployment story.

## Decision

The entire stack runs on **GCP**: Compute Engine L4 GPUs for replicas, GKE Autopilot for orchestration, and Cloud Operations for observability. No mixing cloud providers.

## Consequences

- The project is tied to GCP-specific quotas, pricing, and billing.
- In exchange, the whole environment is reproducible through a single `gcloud`/Helm path, which matters for a benchmark-focused, reviewer-friendly project where anyone should be able to stand up the same environment from one set of credentials and one CLI.

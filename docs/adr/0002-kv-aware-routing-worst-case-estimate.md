# 0002. KV-cache-aware routing: worst-case estimate

## Status

Accepted

## Context

Routing decisions need some notion of how much KV cache capacity a request will consume on a replica, so the router can avoid sending requests to replicas that are effectively full. Modeling vLLM's actual scheduler behavior (continuous batching, prefix caching, preemption/swap) precisely would let the router make near-optimal placement decisions, but it means re-implementing or closely tracking an internal, evolving scheduler. That is an unbounded amount of work, and the admission-control layer's core requirement is *predictable* capacity estimates, not maximally *precise* ones.

## Decision

KV-cache-aware routing uses a **worst-case full-KV footprint estimate**, computed from prompt tokens plus max output tokens. It does not model vLLM's internal scheduler, prefix caching, or preemption behavior.

## Consequences

- The router may over-provision KV capacity relative to what vLLM would actually use in practice (e.g. when prefix caching or early stopping reduces real usage), causing some avoidable utilization loss.
- In exchange, capacity estimates are simple, stable, and independent of vLLM internals, which gives much stronger SLO guarantees and a router that is easier to reason about and test.
- This precision-for-simplicity tradeoff is deliberate and is meant to be a visible, documented signal about how the admission-control layer is designed, not an oversight.

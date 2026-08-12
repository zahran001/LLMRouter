# 0001. Priority lanes: queue-level only

## Status

Accepted

## Context

LLMRouter needs to distinguish interactive requests (latency-sensitive, e.g. chat) from batch requests (throughput-sensitive, e.g. bulk summarization) so that batch traffic cannot starve interactive traffic of its latency SLOs. The most thorough way to enforce this is mid-generation preemption: pausing or evicting an in-flight batch request's generation to free capacity for an incoming interactive request. That is a hard distributed-systems problem, it touches vLLM's internal scheduler and KV cache state, and it is out of scope for v1.

## Decision

Priority handling (interactive vs. batch) is implemented at the **queue level only** for v1. Requests are prioritized before admission and dispatch, not during generation. There is no mid-generation preemption.

## Consequences

- Simpler, shippable for v1.
- Batch requests already dispatched to a replica are not interrupted once generation has started, even if a higher-priority interactive request arrives immediately after.
- Under sustained batch load, worst-case queueing delay for interactive requests is bounded by in-flight batch requests' remaining generation time, not by queue position alone.
- Mid-generation preemption is explicit v2 future work.

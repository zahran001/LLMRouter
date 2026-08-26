# Week 3 Cost Contract — Frozen Interfaces

> **STATUS: WEEK 3 — FROZEN CONTRACT (W3-0)**
>
> This document is the W3-0 deliverable required by
> `WEEK3_IMPLEMENTATION_README.md` §6 (hard stop `W3-COST-CONTRACT`):
> runtime implementation must not begin until the request contract,
> sidecar schema, provenance schema, and error/fail-closed semantics below
> are explicit. Both Python (`cost_model/`) and Rust
> (`router/src/cost/`) implementations must obey this document exactly.
> Formula derivation and constants live in
> `WEEK3_KV_REQUEST_COST_INVESTIGATION_REPORT.md`; this document is the
> implementation contract built on top of it.

---

## 1. Supported request contract (benchmark-exact)

A request is **supported** only if its JSON body matches exactly:

```text
top-level keys ⊆ {model, messages, max_tokens, stream}

model        : string, MUST equal the pinned model id exactly
                ("meta-llama/Llama-3.2-3B-Instruct")
messages     : array, length exactly 1
messages[0]  : object with EXACTLY the keys {role, content}
  role       : string, MUST equal "user"
  content    : string (plain text; not an array/object — rules out
                multimodal parts and tool-call structures)
max_tokens   : integer, present, > 0
stream       : optional; if present, must be a JSON boolean (value is
                not otherwise inspected by the cost path)
```

Any deviation — a missing field, an extra top-level key, `tools` present,
`messages[0].content` not a plain string, more than one message, a
non-"user" role, a missing or non-positive `max_tokens`, invalid JSON, or
the wrong `model` — makes the request **unsupported**.

This mirrors the actual payload `loadgen/scheduler.py:234` sends
(`{"model", "messages": [{"role": "user", "content": ...}], **extra_body}`,
with `stream: true` injected by default and `max_tokens` supplied only via
`extra_body`), so every request the Week 4 benchmark issues is supported
by construction, and nothing wider is accepted.

## 2. Unsupported-request semantics (locked, resolved 2026-08-25)

**Cost computation fails closed; router HTTP behavior is unchanged.**

- `compute_request_cost` returns `Result<RequestCost, RequestCostError>`
  (Rust) / raises a typed `RequestCostError` subclass (Python).
- The router's proxy behavior — forward the request upstream, stream the
  response back — is **identical** for supported and unsupported requests.
  A `RequestCostError` never becomes an HTTP error response and never
  blocks or alters what is forwarded.
- On success, the router attaches three response headers (see §4). On
  failure, it attaches none and proceeds exactly as it does today.
- Rationale: `WEEK3_IMPLEMENTATION_README.md` §1 lists "production
  admission control" as explicitly out of scope for Week 3, and §6 W3-3
  requires the router to "preserve the original forwarded request bytes"
  unconditionally. Gating the HTTP response on cost-computability would
  make Week 3 a de facto admission-control layer, which is a Week 4+
  decision, not a Week 3 one.

`RequestCostError` taxonomy (same variant names in both languages):

```text
NotJson                    body is not valid JSON
UnsupportedShape { reason } shape violates §1 (extra/missing/wrong-typed field)
WrongModel                  model id does not match the pinned identity
MissingMaxTokens             max_tokens absent
InvalidMaxTokens              max_tokens present but not a positive integer
```

## 3. `RequestCost` contract

```text
RequestCost {
    input_tokens:        u32   // exact rendered-input token count
    max_output_tokens:   u32   // == request's max_tokens
    reserved_tokens:     u32   // input_tokens + max_output_tokens
    estimated_kv_bytes:  u64   // reserved_tokens * logical_kv_bytes_per_token
}
```

- `input_tokens` means exactly: the token count of the request rendered
  through the pinned model's chat template (BOS, default system block,
  generation prompt included) and counted with the pinned tokenizer —
  never a character count, never a pre-template token count.
- All arithmetic is integer arithmetic. Rust uses `checked_mul`/
  `checked_add`, returning a defensive `RequestCostError::Overflow` on
  failure (not expected to ever fire — investigation report §8 showed
  u64 has enormous headroom — but the check is cheap and removes the
  failure mode entirely rather than trusting an argument).
- No floating-point arithmetic anywhere in the canonical byte estimate.

## 4. Response headers (Rust runtime, success case only)

```text
X-Request-Cost-Input-Tokens:        <input_tokens>
X-Request-Cost-Reserved-Tokens:     <reserved_tokens>
X-Request-Cost-Estimated-Kv-Bytes:  <estimated_kv_bytes>
```

Purpose: let HTTP-level tests assert Rust↔Python agreement over a live
request without the router touching a filesystem (see §6). These headers
are diagnostic/evidence-only in Week 3 — Week 4 routing code, when it
exists, consumes `RequestCost` directly in-process, not via its own HTTP
response headers.

## 5. Provenance manifest schema (`request_cost_provenance.v1.json`)

Written once per pinned model/serving identity by
`scripts/build_cost_provenance.py`, loaded by both the Python reference
and (via `include_str!`) the Rust runtime. Three sections, per
`WEEK3_IMPLEMENTATION_README.md` §4:

```json
{
  "schema_version": "1",
  "cost_model_version": "v1",
  "formula_version": "kv-worst-case-gqa-v1",

  "source_provenance": {
    "model_id": "meta-llama/Llama-3.2-3B-Instruct",
    "model_revision": "<gated repo commit sha>",
    "model_config_sha256": "<sha256>",
    "tokenizer_sha256": "<sha256>",
    "tokenizer_config_sha256": "<sha256>",
    "chat_template_sha256": "<sha256>"
  },

  "derived_architecture": {
    "num_hidden_layers": 28,
    "num_key_value_heads": 8,
    "head_dim": 128,
    "logical_kv_bytes_per_token": 114688
  },

  "serving_runtime": {
    "effective_kv_cache_dtype": "bfloat16",
    "bytes_per_kv_element": 2,
    "vllm_version": "0.27.1"
  }
}
```

Every field here must be traceable to `source_provenance` (a hash) or a
derivation shown in `WEEK3_KV_REQUEST_COST_INVESTIGATION_REPORT.md` §3–§6
— no unexplained magic numbers in code (README §2.6). `effective_kv_cache_dtype`
and `bytes_per_kv_element` are recorded as a **locked design decision**
(established for the historical Week 2 identity; Week 4+ additionally
pins and verifies it at startup per README §2.8), not re-derived from a
live server at manifest-build time.

## 6. Request-cost sidecar schema v1

**Owner: the Python `loadgen`, not the router** (locked, resolved
2026-08-25 — the router stays stateless plumbing per Week 1's design; the
loadgen already owns the per-run logging pipeline and already knows every
request's text and `max_tokens` before it is sent).

File: `<run>.request_cost.v1.jsonl`, one row per issued request:

```json
{"schema_version": "1", "request_id": 123, "input_tokens": 1127,
 "max_output_tokens": 512, "reserved_tokens": 1639,
 "estimated_kv_bytes": 187990016}
```

- `request_id` is the same id `loadgen/scheduler.py` assigns per request
  — the join key back to `<run>.raw_log.jsonl` / `<run>.samples.jsonl`.
- Units: `estimated_kv_bytes` is bytes. No MiB/GiB conversion in the
  sidecar — consumers convert as needed.
- The provenance manifest is referenced by `cost_model_version` +
  `formula_version`, not copied per-row (README §2.9: "large provenance
  data must not be redundantly copied into every request row").

## 7. Week 2 / Week 3 semantic boundary (never conflate)

```text
Week 2 raw-log `prompt_len`    = character count of the raw prompt text
                                  (scripts/build_baseline_corpus.py:102-105,
                                  unchanged by Week 3)
Week 3 `input_tokens`          = exact rendered-input token count under
                                  the pinned tokenizer + chat template
```

Week 3 code must never write to or redefine the `prompt_len` field. The
two are different quantities of different things (bare prompt vs.
rendered chat request) and are never directly comparable without the
chars-per-token ratio already characterized in
`benchmarks/workloads/week2_headline/tokenizer_capacity_report.json`.

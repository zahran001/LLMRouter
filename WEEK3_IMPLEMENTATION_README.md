# Week 3 Implementation README — Request-Cost Signal

> **STATUS: WEEK 3 IMPLEMENTATION CONTRACT**
>
> Week 2 is closed. This document defines the implementation scope, locked decisions, execution blocks, validation requirements, evidence requirements, and hard stops for Week 3.
>
> Week 3 is **signal only**. It does not implement or benchmark routing strategies.

---

## 0. Week 3 Objective

Week 3 builds and validates the **request-cost signal** that Week 4 routing will consume.

The Week 3 success statement is:

> For every supported request, LLMRouter can deterministically derive the exact rendered model-input token count under a pinned tokenizer/chat-template identity, reserve the request's full permitted output budget, convert that reservation into a versioned conservative logical KV-cost estimate, expose the result through a stable runtime interface, and record auditable evidence. The Python reference and Rust runtime agree exactly over the full pinned corpus plus edge cases and negative controls.

Week 3 does **not** attempt to prove that KV-aware routing is better.

The runtime concept is:

```text
Controlled Week 4 request
        │
        ▼
Validate supported request contract
        │
        ▼
Render with pinned model chat template
        │
        ▼
Exact tokenizer count
        │
        ├── input_tokens
        │
        ▼
Reserve full max_output_tokens
        │
        ├── reserved_tokens
        │
        ▼
Pinned logical KV-cost model
        │
        ├── estimated_kv_bytes
        │
        ▼
RequestCost
        │
        ├── Week 4 routing input
        └── versioned request-cost evidence
```

---

# 1. Explicit Week 3 Scope

## In scope

- exact rendered-input token counting
- pinned tokenizer and chat-template provenance
- pinned model-config provenance
- conservative logical KV footprint derivation
- runtime `RequestCost` abstraction
- benchmark-exact supported request validation
- fail-closed behavior for unsupported requests
- versioned request-cost sidecar
- Python reference implementation
- Rust runtime implementation
- exact Python ↔ Rust conformance
- full pinned-corpus validation
- edge cases
- negative controls
- CPU-side tokenization/cost overhead measurement
- Week 4 cost-model provenance and handoff artifacts

## Out of scope

Week 3 must **not** implement or evaluate:

- round-robin routing
- reactive least-loaded routing
- KV-aware routing decisions
- multi-replica serving comparisons
- breach-curve measurement
- GPU prompt-length sweeps
- claims that KV cost predicts TTFT
- claims that KV cost predicts queueing
- vLLM block allocation modeling
- allocator fragmentation
- continuous-batching internals
- prefix-cache sharing
- preemption
- swap behavior
- physical GPU-memory bookkeeping
- general OpenAI-compatible request support
- production admission control

If implementation work begins to require any of the above, stop and surface the scope expansion before proceeding.

---

# 2. Locked Decisions

The following decisions are authoritative for Week 3.

## 2.1 Scope

**LOCKED: Signal only.**

Week 3 produces the request-cost signal and validates it.

Routing-policy implementation and routing-policy benchmarks begin in Week 4.

---

## 2.2 Supported request contract

**LOCKED: benchmark-exact request contract.**

Week 3 supports only the controlled request shape required by the initial Week 4 benchmark.

The exact schema must be frozen before runtime implementation begins.

At minimum, the initial supported contract is expected to require:

- pinned model identity
- exactly the controlled benchmark message structure
- plain-text content
- explicit `max_tokens`
- no tools
- no multimodal content
- no unsupported structured message content

Do not silently widen the supported request contract during implementation.

---

## 2.3 Unsupported requests

**LOCKED: reject / fail closed.**

If an incoming request cannot be costed exactly under the supported Week 3 contract, it must not receive an approximate request cost.

Do not:

- substitute character count
- use an approximate tokenizer
- guess missing output reservation
- route through the cost-aware path with partial information

The exact response/error behavior should be defined in W3-0 and tested in W3-4.

---

## 2.4 Tokenizer and chat-template authority

**LOCKED: promote the existing pinned tokenizer + tokenizer config + chat template into the Week 3 authority.**

`input_tokens` means:

> the exact token count of the final rendered model input produced by the pinned model chat template and pinned tokenizer under the supported request contract.

It does **not** mean:

- prompt character count
- raw user-text token count before template rendering
- approximate token count
- token count from an unpinned tokenizer revision

The Python reference and Rust runtime must obey the same rendering and tokenization semantics.

---

## 2.5 Output reservation

**LOCKED: reserve the full `max_tokens`.**

```text
reserved_tokens = input_tokens + max_output_tokens
```

The Week 3 investigation found that exact logical KV occupancy at the generation boundary may be one token smaller, but Week 3 deliberately retains the simpler upper-bound formula.

Do **not** introduce a `-1` adjustment into the authoritative formula.

The one-token slack is documented intentional conservatism, not an error to optimize away.

---

## 2.6 KV request-cost model

**LOCKED: logical worst-case KV tensor footprint.**

The authoritative formula is:

```text
logical_kv_bytes_per_token
    = 2
      × num_hidden_layers
      × num_key_value_heads
      × head_dim
      × bytes_per_kv_element

estimated_kv_bytes
    = reserved_tokens × logical_kv_bytes_per_token
```

For the pinned `meta-llama/Llama-3.2-3B-Instruct` model identity:

```text
num_hidden_layers       = 28
num_key_value_heads     = 8
head_dim                = 128
kv_cache_dtype          = bfloat16
bytes_per_kv_element    = 2

logical_kv_bytes/token  = 114,688 bytes
                        = 112 KiB
```

These constants must come from durable provenance. They must not appear in code as unexplained magic numbers.

The formal semantic definition is:

> `estimated_kv_bytes` is a conservative logical upper bound on the K/V tensor storage associated with a request's full reserved sequence length under the pinned model architecture and KV-cache dtype.

---

## 2.7 Meaning and limitations of `estimated_kv_bytes`

`estimated_kv_bytes` is **not**:

- actual instantaneous GPU-memory consumption
- vLLM block allocation
- physical allocator reservation
- fragmentation-adjusted memory usage
- scheduler state
- continuous-batching behavior
- prefix-cache sharing
- preemption/swap behavior
- latency prediction
- queueing prediction
- exact free-capacity measurement

Legitimate Week 4 uses include:

- relative request-cost ranking
- conservative per-request demand signal
- routing input
- potential future admission-control input when paired with a separately defined capacity model

Do not introduce stronger claims.

---

## 2.8 Future serving KV-cache dtype

**LOCKED for Week 4+: explicit BF16 pin plus startup verification.**

Week 2 remains historically unchanged.

Week 2 did not explicitly set `--kv-cache-dtype`; the investigation established that the effective Week 2 KV-cache dtype was BF16.

For Week 4 and later serving experiments, explicitly launch with:

```text
--kv-cache-dtype bfloat16
```

Startup/preflight must additionally verify:

```text
requested KV-cache dtype = bfloat16
effective KV-cache dtype = bfloat16
```

An experiment must not proceed if the effective serving dtype disagrees with the cost-model provenance.

This future-serving requirement must not be retroactively attributed to Week 2.

---

## 2.9 Logging

**LOCKED: add a versioned request-cost sidecar.**

Do not change the historical Week 2 meaning of:

```text
prompt_len
```

Week 2 `prompt_len` remains **character count**.

Week 3 should introduce a versioned artifact such as:

```text
<run>.request_cost.v1.jsonl
```

Conceptual row:

```json
{
  "request_id": 123,
  "input_tokens": 1127,
  "max_output_tokens": 512,
  "reserved_tokens": 1639,
  "estimated_kv_bytes": 187990016
}
```

The exact final schema may be refined before implementation, but:

- schema version must be explicit
- units must be explicit
- `request_id` must provide a stable join key
- Week 2 raw-log semantics must remain unchanged
- large provenance data must not be redundantly copied into every request row

---

## 2.10 Validation

**LOCKED: full pinned corpus + edge cases + negative controls.**

Validation is deterministic software correctness, not statistical sampling.

The Week 3 runtime implementation must achieve exact Python-reference ↔ Rust-runtime equality for every supported corpus request.

No tolerances.

No percentile-based acceptance.

---

# 3. Authoritative Request-Cost Contract

The runtime abstraction should expose, at minimum:

```text
RequestCost {
    input_tokens,
    max_output_tokens,
    reserved_tokens,
    estimated_kv_bytes,
}
```

Recommended implementation types:

```text
input_tokens          integer large enough for model context lengths
max_output_tokens     integer large enough for model output limits
reserved_tokens       integer large enough for their sum
estimated_kv_bytes    u64-equivalent
```

`estimated_kv_bytes` must use integer arithmetic.

Do not use floating-point arithmetic for the canonical byte estimate.

---

# 4. Required Provenance

Week 3 must create durable provenance for every value that affects request cost.

At minimum record:

```text
cost_model_version
formula_version

model_id
model_revision
model_config_sha256

tokenizer_sha256
tokenizer_config_sha256
chat_template_sha256

num_hidden_layers
num_key_value_heads
head_dim

effective_kv_cache_dtype
bytes_per_kv_element
logical_kv_bytes_per_token

vllm_version
```

Separate the provenance artifact into:

## 4.1 Immutable/source provenance

Examples:

- model identifier
- model revision
- config hash
- tokenizer hash
- tokenizer-config hash
- chat-template hash

## 4.2 Derived architecture constants

Examples:

- `num_hidden_layers`
- `num_key_value_heads`
- `head_dim`
- `logical_kv_bytes_per_token`

## 4.3 Serving-runtime configuration

Examples:

- effective KV-cache dtype
- vLLM version
- relevant serving flags

The model `config.json` must be obtained and hash-pinned using a reproducible mechanism comparable to the existing tokenizer provenance path.

The architecture constants discovered in the Week 3 investigation must not exist only in prose.

---

# 5. Documentation Requirements

The following decisions must be documented explicitly during implementation.

Do not leave them implicit in:

- code
- tests
- launch scripts
- generated evidence
- comments alone

## 5.1 Request-cost formula

Document:

```text
reserved_tokens
    = input_tokens + max_output_tokens

logical_kv_bytes_per_token
    = 2
      × num_hidden_layers
      × num_key_value_heads
      × head_dim
      × bytes_per_kv_element

estimated_kv_bytes
    = reserved_tokens × logical_kv_bytes_per_token
```

Document the pinned-model result:

```text
logical_kv_bytes_per_token = 114,688 bytes = 112 KiB
```

Document that the full `max_output_tokens` reservation intentionally includes bounded conservative slack.

---

## 5.2 Provenance

Document all model/config/tokenizer/template sources and hashes.

Clearly distinguish:

- **Observed fact**
- **Derived value**
- **Locked design decision**
- **Implementation result**

Do not turn a derived observation into a serving invariant without documenting the transition.

---

## 5.3 Sidecar semantics

Document:

- schema version
- join semantics
- units
- field definitions
- compatibility with historical Week 2 raw logs

Explicitly state:

```text
Week 2 prompt_len = characters
Week 3 input_tokens = exact rendered model-input tokens
```

These fields must never be conflated.

---

## 5.4 BF16 serving requirement

Document that:

- Week 2 historically used automatic KV dtype resolution
- effective Week 2 dtype was established as BF16
- Week 4+ explicitly pins `--kv-cache-dtype bfloat16`
- Week 4+ startup/preflight verifies the effective dtype is BF16
- Week 2 artifacts and serving identity remain unchanged

---

## 5.5 ADR 0002

The Week 3 investigation confirms the core ADR decision.

Do not invalidate or replace ADR 0002.

If clarification is added, keep it minimal.

Recommended clarification:

> The estimate intentionally reserves `prompt_tokens + max_output_tokens`; it is a conservative logical upper bound rather than a model of exact realized KV occupancy.

Do not make the ADR dependent on decode-loop implementation details.

---

# 6. Implementation Blocks

Week 3 should be executed in the following order.

---

## W3-0 — Freeze the contract

### Goal

Convert all locked human decisions into explicit implementation contracts before code changes begin.

### Tasks

- create/confirm authoritative Week 3 plan/README
- freeze benchmark-exact supported request schema
- define explicit unsupported-request error behavior
- freeze `RequestCost` field names and units
- freeze request-cost sidecar schema version
- freeze provenance-manifest schema
- freeze formula version identifier
- identify exactly which Week 2 artifacts/docs are historical and must not be mutated
- update project status to indicate Week 3 is active without rewriting Week 2 history

### Hard stop: `W3-COST-CONTRACT`

Do not begin runtime implementation until:

- request contract is explicit
- sidecar schema is explicit
- provenance schema is explicit
- error/fail-closed semantics are explicit
- legacy Week 2 compatibility is explicit

---

## W3-1 — Build authoritative provenance and Python reference oracle

### Goal

Turn the existing Week 2 tokenizer-capacity work into a reusable authoritative reference path.

### Tasks

- reuse/refactor the existing pinned tokenizer acquisition path
- reuse the existing pinned chat-template semantics
- add a reproducible hash-pinned model `config.json` acquisition path
- verify model revision
- derive:
  - `num_hidden_layers`
  - `num_key_value_heads`
  - `head_dim`
  - BF16 bytes per element
  - logical KV bytes/token
- produce a versioned cost-model provenance manifest
- implement a Python reference function for:
  - request validation
  - chat-template rendering
  - exact input token count
  - output reservation
  - `estimated_kv_bytes`
- generate golden vectors for later Rust conformance

### Required evidence

- model config hash proof
- tokenizer/config/template hash proof
- formula derivation
- `114,688 B/token` derived result
- representative request-cost examples
- provenance manifest

### Hard stop: `W3-PROVENANCE`

Stop if any source identity, hash, architecture constant, dtype, or formula input is ambiguous.

Do not hard-code unresolved values.

---

## W3-2 — Define runtime schema and evidence schema

### Goal

Freeze the interfaces before wiring them into the router.

### Tasks

Define:

```text
RequestCost
RequestCostError
RequestCostProvenance
request-cost sidecar v1
```

Specify:

- types
- units
- schema versions
- join keys
- serialization behavior
- overflow behavior
- unsupported-request behavior

Prove via tests that historical Week 2 raw logs retain their original schema and meaning.

### Hard stop: `W3-SCHEMA`

Do not proceed if implementation would require redefining Week 2 `prompt_len`.

---

## W3-3 — Implement Rust runtime request costing

### Goal

Compute the request cost in the router before Week 4 routing decisions exist.

### Required architectural constraint

The router already buffers incoming request bytes before forwarding upstream.

Week 3 may inspect those bytes, but must preserve the original forwarded request bytes.

Do not deserialize and reserialize the request merely to forward it.

The intended seam is:

```text
original buffered request bytes
        │
        ├── parse/inspect for RequestCost
        │
        └── forward original bytes unchanged
```

### Tasks

- add the runtime tokenizer dependency/implementation needed for parity
- implement the supported request validator
- render the exact pinned chat template
- tokenize exactly
- extract explicit `max_tokens`
- calculate:
  - `input_tokens`
  - `max_output_tokens`
  - `reserved_tokens`
  - `estimated_kv_bytes`
- return structured error for unsupported/invalid request forms
- expose a stable `RequestCost` interface for Week 4
- emit versioned request-cost evidence where required
- preserve upstream request bytes
- preserve response streaming behavior

### Prohibited behavior

Do not:

- implement routing selection
- implement load-aware policy
- change upstream request representation
- approximate unsupported requests
- substitute char length
- use unpinned model/tokenizer semantics

---

## W3-4 — Conformance and negative controls

### Goal

Prove that the runtime signal is correct and that the validation system can detect known-invalid implementations.

### Required corpus validation

Run exact Python-reference ↔ Rust-runtime equality over the **full pinned corpus**.

For every supported request require exact equality for:

```text
input_tokens
max_output_tokens
reserved_tokens
estimated_kv_bytes
```

### Required edge cases

At minimum include:

- empty user content
- Unicode
- emoji
- newlines
- whitespace variants
- very long prompts
- special-token-like strings
- maximum supported output reservation
- invalid/missing fields
- unsupported message structures

### Required negative controls

Each control must demonstrably fail when injected.

At minimum:

1. character count mislabeled as token count
2. raw prompt tokenization without chat-template rendering
3. wrong tokenizer
4. altered tokenizer revision/hash
5. altered chat template
6. incorrect chat-template flags
7. omitted `max_output_tokens` reservation
8. `-1` formula substituted for the locked reservation contract
9. `num_attention_heads` used instead of `num_key_value_heads`
10. wrong `head_dim`
11. wrong KV dtype / element width
12. wrong byte units
13. runtime/provenance mismatch
14. unsupported request accidentally receiving a cost
15. request-cost extraction mutating forwarded request bytes

### Regression requirements

Confirm:

- router request fidelity remains intact
- streaming responses remain streaming
- Week 1/Week 2 protected behavior still passes relevant regression tests
- historical raw-log semantics remain unchanged

### Hard stop: `W3-VALIDATION`

Week 3 may not close unless:

- full-corpus equality passes
- required edge cases pass
- every required negative control is shown to bite
- request forwarding remains byte-faithful
- relevant streaming regression tests remain green

---

## W3-5 — Characterize cost distribution and runtime overhead

### Goal

Produce the cost characterization Week 4 will need without turning Week 3 into a routing experiment.

### Workload characterization

For the pinned corpus and canonical Week 4 workload material, report at minimum:

- exact `input_tokens` distribution
- `reserved_tokens` distribution
- `estimated_kv_bytes` distribution
- min
- p50
- p90
- p95
- p99
- max

Do not silently reuse character-based Week 2 length strata as KV-cost strata.

If Week 4 requires explicit short/medium/long token bands, define them separately and document their purpose before locking them.

### CPU overhead characterization

Because tokenization now sits on the request path, measure CPU-side cost computation overhead.

Report by input-length region where useful:

- render time
- tokenization time
- total request-cost computation time

This is not a GPU performance experiment.

The purpose is to detect pathological request-path overhead before Week 4.

Do not turn this into a TTFT or routing-performance claim.

---

## W3-6 — Closeout and Week 4 handoff

### Goal

Close Week 3 only when the request-cost signal is trustworthy and auditable.

Produce a final Week 3 evidence package documenting:

- locked request-cost formula
- supported request contract
- fail-closed semantics
- tokenizer/template provenance
- model-config provenance
- effective BF16 KV-cache dtype
- `114,688 B/token` derivation
- request-cost schema
- request-cost sidecar schema
- Python reference implementation identity
- Rust runtime implementation identity
- full-corpus conformance result
- edge-case results
- negative-control results
- request-fidelity regression result
- streaming regression result
- CPU overhead characterization
- cost-distribution characterization
- explicit limitations of `estimated_kv_bytes`
- confirmation that Week 2 artifact semantics were unchanged
- Week 4+ BF16 launch-pin requirement
- Week 4+ startup verification requirement

Update project status only after this evidence exists.

### Final hard stop: `W3-CLOSED`

Week 3 is closed only when the following statement is supported by evidence:

> For every supported request, LLMRouter deterministically computes the exact rendered-input token count under the pinned tokenizer/template identity, reserves the full permitted output budget, converts the reservation into the locked conservative logical KV-cost estimate, and exposes that signal through a stable runtime contract. The Rust runtime agrees exactly with the Python reference over the full pinned corpus and required edge cases, all required negative controls bite, and historical Week 2 semantics remain unchanged.

---

# 7. Evidence Discipline

Every important Week 3 claim must be classified as one of:

```text
OBSERVED FACT
DERIVED VALUE
LOCKED DESIGN DECISION
IMPLEMENTATION RESULT
```

Do not silently convert one category into another.

Examples:

```text
OBSERVED FACT:
config.json reports num_key_value_heads = 8

DERIVED VALUE:
logical_kv_bytes_per_token = 114,688

LOCKED DESIGN DECISION:
reserved_tokens = input_tokens + max_output_tokens

IMPLEMENTATION RESULT:
Rust and Python agreed on all 5,000 pinned corpus prompts
```

---

# 8. Compatibility Rules

Week 2 is historical evidence.

Week 3 implementation must not:

- rewrite Week 2 raw logs
- redefine Week 2 `prompt_len`
- add future BF16 launch flags retroactively to Week 2 identity
- reinterpret Week 2 measurements using Week 3 semantics
- overwrite preserved evidence

Week 3 may reference Week 2 artifacts as provenance or input material, but new semantics require new versioned artifacts.

---

# 9. No-GPU Default

Week 3 is designed to be completed offline/CPU-side.

Do not spend GPU time unless a concrete question is identified that cannot be answered from:

- repository evidence
- pinned model/config artifacts
- tokenizer/template artifacts
- deterministic conformance tests
- existing Week 2 GPU evidence

Any proposed Week 3 GPU use requires a separately documented question, justification, expected evidence, and hard stop.

---

# 10. Week 4 Handoff Contract

Week 4 should receive a stable interface equivalent to:

```text
Request
   │
   ▼
RequestCost {
    input_tokens,
    max_output_tokens,
    reserved_tokens,
    estimated_kv_bytes,
}
   │
   ▼
routing policy
```

Week 4 routing code must not need to know:

- tokenizer internals
- chat-template internals
- model architecture constants
- KV-byte formula internals

Those belong behind the Week 3 request-cost interface.

For Week 4+ serving:

```text
--kv-cache-dtype bfloat16
```

must be explicitly requested and startup/preflight must verify the effective resolved dtype is also BF16 before routing experiments begin.

---

# 11. Completion Checklist

Week 3 is not complete until all of the following are true:

- [ ] benchmark-exact request contract frozen
- [ ] unsupported-request fail-closed behavior frozen
- [ ] tokenizer/template authority pinned
- [ ] model config hash-pinned
- [ ] provenance manifest versioned
- [ ] request-cost formula implemented exactly as locked
- [ ] `logical_kv_bytes_per_token = 114,688` derived from provenance
- [ ] runtime `RequestCost` interface implemented
- [ ] versioned request-cost sidecar implemented
- [ ] Week 2 `prompt_len` semantics preserved
- [ ] Rust tokenizer/template semantics match Python reference
- [ ] full pinned corpus exact conformance passes
- [ ] edge cases pass
- [ ] all required negative controls bite
- [ ] request forwarding remains byte-faithful
- [ ] streaming regressions remain green
- [ ] CPU request-cost overhead characterized
- [ ] token/KV-cost distribution characterized
- [ ] final Week 3 evidence package written
- [ ] Week 4 BF16 explicit-pin requirement documented
- [ ] Week 4 BF16 startup verification requirement documented
- [ ] project status updated to Week 3 closed / Week 4 ready

---

# 12. Guiding Principle

Week 3 should optimize for **semantic trustworthiness**, not mechanism complexity.

The result should be boring, deterministic, versioned, auditable, and difficult to misuse.

Week 4 is where routing policy becomes interesting.

Week 3's job is to ensure that when Week 4 asks:

> "How expensive is this request?"

the router has one precise, reproducible, evidence-backed answer.

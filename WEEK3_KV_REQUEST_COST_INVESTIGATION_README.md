# Week 3 KV Request-Cost Model Investigation

## Purpose

This task investigates the unresolved Week 3 KV request-cost design for **LLMRouter**.

The goal is to determine whether `estimated_kv_bytes` should be defined as a **logical worst-case KV tensor footprint**, and to establish the exact, reproducible formula and provenance required for the pinned model and serving configuration.

This is an **evidence-gathering and design-validation task only**.

> **Do not implement the Week 3 cost model yet.**  
> **Do not modify production code, benchmark behavior, serving configuration, or authoritative docs.**

---

## Project Context

Week 2 is complete and closed.

### Canonical serving identity

- Model: `meta-llama/Llama-3.2-3B-Instruct`
- Serving engine: vLLM
- GPU: NVIDIA L4
- Eager mode: enabled
- Prefix caching: disabled
- Canonical Week 2 output reservation: `max_tokens=512`
- Week 2 baseline artifacts and semantics must remain unchanged

---

## Week 3 Decisions Already Locked

### 1. Scope

Week 3 is **signal only**.

It builds and validates the request-cost signal that Week 4 routing will consume.

Week 3 does **not** implement or benchmark routing policies.

### 2. Request contract

Support the **benchmark-exact** controlled Week 4 request shape first.

Do not attempt arbitrary OpenAI-compatible traffic.

### 3. Unsupported request shapes

Reject / fail closed.

### 4. Tokenization authority

Promote the existing pinned:

- tokenizer
- `tokenizer_config`
- chat template
- associated provenance

into the authoritative definition of exact `input_tokens`.

### 5. Output reservation

Reserve the full request `max_tokens`.

### 6. Exposed request-cost fields

The intended request-cost contract is:

```text
input_tokens
max_output_tokens
reserved_tokens
estimated_kv_bytes
```

with:

```text
reserved_tokens = input_tokens + max_output_tokens
```

### 7. Logging

Add a **versioned Week 3 request-cost sidecar**.

Do not redefine the historical Week 2 meaning of `prompt_len`.

### 8. Validation

The eventual runtime implementation must achieve:

- exact Python-reference ↔ Rust-runtime agreement
- over the full pinned corpus
- plus edge cases
- plus negative controls

---

# Unresolved Decision

The open design question is:

> Should `estimated_kv_bytes` represent the **logical worst-case KV tensor footprint**, and exactly how should that quantity be defined for the pinned model and serving configuration?

The current intended form is:

```text
reserved_tokens = input_tokens + max_output_tokens

estimated_kv_bytes =
    reserved_tokens * logical_kv_bytes_per_token
```

No numeric constants or exact formula are approved yet.

---

# Investigation Objective

Audit the repository, pinned model metadata, and effective Week 2 serving configuration to determine the technically correct and reproducible definition of the logical KV footprint.

The goal is **not** to model vLLM allocator behavior.

Unless evidence shows otherwise, the intended abstraction should exclude:

- vLLM block-allocation granularity
- allocator metadata
- fragmentation
- scheduler state
- continuous batching effects
- prefix-cache sharing
- preemption
- swapping
- physical GPU-memory bookkeeping

The target quantity is the **logical tensor storage required for the request's K/V state under the pinned model architecture and KV dtype**.

---

# A. Establish the Exact Model Architecture Inputs

Locate the authoritative model config for the exact model/revision being used.

Do **not** rely on remembered Llama-3.2-3B architecture constants.

Identify, with repository/artifact/source evidence:

- model revision / commit
- `config.json` provenance and hash, if already available
- `num_hidden_layers`
- `num_attention_heads`
- `num_key_value_heads`
- `hidden_size`
- `head_dim`
  - whether explicit
  - or derived
- any other architecture field that affects KV tensor shape
- whether GQA/MQA changes the formula relative to using `num_attention_heads`
- whether any model-specific behavior invalidates the generic KV formula

Explicitly derive:

1. K dimensionality for one token at one layer
2. V dimensionality for one token at one layer
3. combined K+V dimensionality at one layer
4. total dimensionality across all layers

Show every derivation step and unit.

---

# B. Determine the Correct Logical Bytes-per-Token Formula

Start from tensor shapes rather than from a remembered shortcut.

Verify whether the correct expression is equivalent to:

```text
logical_kv_bytes_per_token
  = 2
    * num_hidden_layers
    * num_key_value_heads
    * head_dim
    * bytes_per_kv_element
```

where `2` represents K and V.

Do **not** assume this expression is correct merely because it looks standard.

Prove or correct it using:

- the model architecture
- serving configuration
- vLLM source/config semantics where useful

Specifically investigate:

- grouped-query attention
- separate K/V dimensions, if any
- explicit vs derived `head_dim`
- tensor-parallel effects
- whether tensor parallelism changes total logical bytes or only partitions them across devices
- quantized model weights vs KV-cache dtype
- special attention behavior that changes logical KV element count

The final result must describe **total logical request KV footprint**, not per-device footprint, unless the current deployment semantics genuinely require otherwise.

---

# C. Audit the Effective KV-Cache Dtype

This is a critical part of the investigation.

Find the exact Week 2 vLLM launch configuration and vLLM version.

Determine:

- whether `kv_cache_dtype` was explicitly configured
- whether it used `auto`
- whether another implicit/default path was used
- the effective KV-cache dtype
- how vLLM resolves `auto` for this model/config/version
- whether model weight dtype and KV-cache dtype are necessarily the same here
- bytes per KV element
- whether this behavior could change across vLLM versions or hardware

Do **not** silently infer the answer.

Use repository launch commands/configuration and authoritative vLLM behavior/source/documentation where repository evidence is insufficient.

Then evaluate two possible Week 3 policies.

## Policy 4A-1

Allow vLLM automatic/default KV-dtype resolution, but resolve and record the effective dtype as provenance.

## Policy 4A-2

Explicitly pin `kv_cache_dtype` in the serving configuration so the request-cost model and serving identity cannot silently drift.

Report:

- which policy is stronger for reproducible experiments
- whether explicitly pinning the dtype would change the canonical Week 2 serving identity
- whether the pin should therefore apply only to Week 4 / future serving runs
- compatibility implications
- performance implications

Do **not** change the launch configuration during this task.

---

# D. Validate the Reservation Semantics

The current intended reservation is:

```text
reserved_tokens = input_tokens + max_output_tokens
```

Audit whether that is the correct conservative logical reservation.

Pay special attention to generation semantics.

Determine whether a request allowed to generate `max_output_tokens` can require logical KV state for exactly:

```text
input_tokens + max_output_tokens
```

or whether the final generated token is never inserted into KV before termination, making the actual maximum something like:

```text
input_tokens + max_output_tokens - 1
```

Do not optimize the formula prematurely.

The project intentionally wants a **conservative** estimate, but we still need to know whether the `+ max_output_tokens` formulation is:

- the exact maximum
- deliberately one-token conservative
- or incorrect for another reason

Also investigate:

- EOS / early stopping
- `max_tokens` semantics in the API/version used
- whether reservation should remain based on permitted output instead of realized output

The request-cost value must be computable **before routing**.

Realized output length must therefore not be required.

---

# E. Compute the Actual Value for the Pinned Model

After establishing the formula and effective dtype, calculate:

1. logical KV bytes per token
2. logical KV footprint for representative requests

Use:

| `input_tokens` | `max_tokens` |
|---:|---:|
| 36 | 512 |
| 66 | 512 |
| 600 | 512 |
| 2706 | 512 |
| 10482 | 512 |

These values correspond to known Week 2 tokenizer-capacity observations and are only illustrative.

For each example, show:

- `reserved_tokens`
- estimated bytes
- MiB equivalent
- GiB equivalent where meaningful

Use integer arithmetic.

State unit conventions explicitly:

- bytes
- KiB / MiB / GiB using powers of 1024

Also confirm whether `u64` is safely sufficient for all supported request sizes.

---

# F. Define What `estimated_kv_bytes` Means

Evaluate whether the following semantic statement is technically defensible:

> `estimated_kv_bytes` is the conservative logical K/V tensor storage corresponding to the request's full permitted sequence length under the pinned model architecture and effective KV-cache dtype.

Refine the wording if needed.

Explicitly explain why this value must **not** be interpreted as:

- actual instantaneous GPU memory consumption
- vLLM block allocation
- physical allocator reservation
- fragmentation-adjusted memory usage
- latency prediction
- queueing-pressure prediction
- exact available-capacity measurement
- a prefix-sharing model
- a preemption model
- a swap model

Also determine what Week 4 may legitimately use it for, such as:

- relative request-cost ranking
- conservative per-request demand signal
- routing input
- potential admission-control input when paired with a separately defined capacity model

Be precise about which claims are warranted.

---

# G. Check ADR 0002 Against the Findings

Read the existing KV-aware-routing ADR:

```text
0002-kv-aware-routing-worst-case-estimate*.md
```

Determine whether the investigation:

- confirms it
- reveals an ambiguity
- requires clarification
- contradicts an accepted statement

Do **not** edit the ADR during this investigation.

If clarification is warranted, propose the smallest wording change separately.

---

# H. Determine Week 3 Provenance Requirements

Recommend exactly which values must be pinned in the Week 3 cost-model provenance manifest.

At minimum evaluate:

- `cost_model_version`
- model identifier
- model revision
- model config SHA-256
- tokenizer SHA-256
- tokenizer config SHA-256
- chat-template SHA-256
- `num_hidden_layers`
- `num_key_value_heads`
- `head_dim`
- effective `kv_cache_dtype`
- `bytes_per_kv_element`
- formula/version identifier

Separate provenance into:

### 1. Immutable/source provenance

For example:

- model revision
- artifact hashes

### 2. Derived architecture constants

For example:

- KV heads
- head dimension
- logical KV bytes/token

### 3. Serving-runtime configuration

For example:

- effective KV-cache dtype
- vLLM version
- relevant serving flags

Avoid redundant per-request logging.

The per-request request-cost sidecar should remain small.

---

# I. Actively Try to Falsify the Design

Look for hidden ways the proposed model could be wrong.

At minimum investigate these failure modes:

- using attention heads instead of KV heads
- deriving `head_dim` incorrectly
- confusing model dtype with KV dtype
- confusing MB with MiB
- counting prompt characters instead of rendered tokens
- forgetting chat-template overhead
- double-counting output reservation
- under-counting output reservation
- tensor-parallel per-GPU vs total-byte confusion
- runtime config drifting from cost-model provenance
- vLLM version-dependent defaults
- integer overflow
- unsupported request shapes accidentally receiving a valid cost
- router tokenization differing from vLLM tokenization

If there is any way for the router and vLLM to render/tokenize the **same apparent request differently**, flag it prominently.

---

# Required Report Structure

Produce one investigation report with the following sections:

1. Executive conclusion
2. Evidence inspected
3. Exact model architecture relevant to KV
4. KV tensor-shape derivation
5. Logical KV bytes/token derivation
6. Effective KV dtype investigation
7. `max_tokens` reservation semantics
8. Example calculations
9. What `estimated_kv_bytes` means
10. What it explicitly does not model
11. ADR 0002 consistency check
12. Required provenance fields
13. Risks / unresolved questions
14. Recommendation for Decision 4
15. Exact decisions still requiring human approval

---

# Evidence Requirements

For every important factual claim, cite:

- repository file + line/function where possible
- artifact/hash where applicable
- authoritative external source only when repository evidence is insufficient

Clearly distinguish:

- **Observed fact**
- **Derived value**
- **Design recommendation**

Do not blur these categories.

---

# Hard Stops

Stop rather than guessing if any of the following cannot be established:

- exact model revision
- architecture constants needed by the formula
- effective Week 2 KV-cache dtype
- vLLM dtype-resolution behavior
- exact `max_tokens` semantics relevant to the KV reservation

If evidence conflicts, report the conflict.

Do **not** silently reconcile inconsistent sources.

Do **not** implement anything.

---

# Desired Outcome

The investigation should produce enough evidence for a human to decide whether to lock:

```text
Decision 4A:

estimated_kv_bytes =
    conservative logical worst-case KV tensor footprint
```

and, separately, whether future serving runs should:

```text
explicitly pin kv_cache_dtype
```

or:

```text
permit automatic resolution
while recording the resolved effective dtype
```

The two areas requiring the closest scrutiny are:

1. **effective KV-cache dtype**
2. **max_tokens reservation semantics**

The obvious formula is not enough. These two details must be established before the Week 3 design is sealed.

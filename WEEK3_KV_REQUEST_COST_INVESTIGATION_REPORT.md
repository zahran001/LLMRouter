# Week 3 KV Request-Cost Model — Investigation Report

> **STATUS: EVIDENCE / DESIGN-VALIDATION ONLY.** Produced against
> `WEEK3_KV_REQUEST_COST_INVESTIGATION_README.md`. No production code,
> serving configuration, benchmark behavior, or authoritative doc was
> modified to produce this report. Decision 4A and the `kv_cache_dtype`
> pin question remain open for human sign-off (§14–15).

---

## 1. Executive conclusion

`estimated_kv_bytes` **should** be defined as the conservative logical
worst-case KV tensor footprint, computed as:

```text
logical_kv_bytes_per_token = 2 * num_hidden_layers * num_key_value_heads
                              * head_dim * bytes_per_kv_element
                            = 2 * 28 * 8 * 128 * 2
                            = 114,688 bytes/token   (exactly 112 KiB/token)

reserved_tokens     = input_tokens + max_output_tokens
estimated_kv_bytes  = reserved_tokens * 114,688
```

The generic-looking formula in the README (§B) is **confirmed correct**
for the pinned model, and independently cross-checked against real vLLM
telemetry from GPU session #2 (§5, §6) — not just derived from
config.json. Two findings require explicit human sign-off before Week 3
is sealed:

1. **Effective KV-cache dtype (§6):** Week 2 never set `--kv-cache-dtype`.
   vLLM resolved `auto` → **bfloat16** (the model's own weight dtype),
   `bytes_per_kv_element = 2`. This is now **directly confirmed** (not
   inferred) by reproducing vLLM's own logged KV-cache-memory figure to
   the byte, using exactly this dtype. Policy 4A‑1 (record resolved
   dtype, don't pin) vs 4A‑2 (pin explicitly) is a real open decision —
   recommendation in §14.

2. **`max_tokens` reservation semantics (§7) — the formula is exact, not
   conservative, at the boundary, and off by exactly one token
   (over-reservation) in the interior.** First-principles trace of
   KV-cache-based autoregressive decoding shows the *true* maximum
   logical KV state reachable when a request is allowed to run to its
   full `max_output_tokens` is:

   ```text
   true_max_kv_tokens = input_tokens + max(max_output_tokens - 1, 0)
   ```

   `reserved_tokens = input_tokens + max_output_tokens` therefore
   **over-reserves by exactly one token** whenever `max_output_tokens ≥
   1`, and is **exact** (no slack) when `max_output_tokens = 0`. It is
   never an under-estimate. This is a **derived value**, reasoned from
   how KV caching works, not an assumption — see §7 for the full trace
   and why it does not depend on vLLM-internal scheduler behavior.

Both findings are new evidence, not present anywhere in the repository
before this investigation — flag as such to whoever reviews this report.

---

## 2. Evidence inspected

| # | Artifact | What it established |
|---|---|---|
| E1 | `BASELINE.md` (repo root) | Canonical Week 2 serving identity: model, vLLM 0.27.1 lineage, `--enforce-eager`, `--no-enable-prefix-caching`, `--max-model-len 20000`, `max_tokens=512` |
| E2 | `docs/adr/0002-kv-aware-routing-worst-case-estimate.md` | Existing accepted ADR: worst-case full-KV footprint from prompt + max output, deliberately not modeling scheduler/prefix-cache/preemption |
| E3 | `scripts/gpu_session/setup_and_launch_vllm.sh` | The actual Week 2 vLLM launch invocation (line 97–101): no `--kv-cache-dtype`, no `--dtype` flag anywhere |
| E4 | `benchmarks/evidence/week2/session_2/vllm.log` lines 190, 198, 216–218 | Resolved engine config as logged by vLLM itself at startup: `dtype=torch.bfloat16`, `kv_cache_dtype=auto`, `tensor_parallel_size=1`; plus **runtime KV-cache sizing telemetry**: `Available KV cache memory: 13.87 GiB` / `GPU KV cache size: 129,888 tokens` |
| E5 | `scripts/fetch_tokenizer.py`, `scripts/check_tokenizer_capacity.py` | Existing tokenizer provenance methodology (git-blob-SHA1 proof against the gated repo via public HF metadata API + ungated mirror) — reused in this investigation for `config.json` |
| E6 | `benchmarks/workloads/week2_headline/tokenizer_capacity_report.json` | `gated_repo_commit: 0cb88a4f764b7a12671c53f0838cd831a0843b95`, tokenizer/template hashes, empty-message chat-template overhead = 35 tokens |
| E7 | `router/Cargo.toml` | Confirms the Rust router currently has **no tokenizer dependency at all** (only `axum`, `reqwest`, `tokio`) — relevant to §H/§I Rust↔Python parity risk |
| E8 | `STATUS.md` | Week 3 = "Token-count `prompt_len` for KV-cache math" — **Not started**. Confirms no prior implementation exists to conflict with |
| E9 (external) | Hugging Face public metadata API, `meta-llama/Llama-3.2-3B-Instruct?blobs=true` | `config.json` git-blob-id `a5a40fa6da567ab026a5a2bf37125a90182be07d`, repo commit `0cb88a4f764b7a12671c53f0838cd831a0843b95` (same commit tokenizer provenance already pinned), `safetensors.parameters.BF16 = 3212749824` (weights stored as BF16, corroborating dtype) |
| E10 (external) | `alpindale/Llama-3.2-3B-Instruct` (ungated mirror), `config.json` | Fetched and **verified byte-identical** to E9's blob id (git blob SHA-1 match) — same proof method as `scripts/fetch_tokenizer.py`, applied here to `config.json` for the first time |
| E11 (external) | vLLM source, `vllm/config/cache.py` (v0.27.1, matching E4's version) | `CacheConfig.cache_dtype` docstring: *"If 'auto', will use model data type."* — authoritative statement of `auto` resolution rule |

No architecture constant in this report rests on memorized Llama-3.2-3B
values. §3 traces every number to E9/E10 (hash-verified) or to E4
(observed runtime behavior), and §5–§6 show the two agree to the byte.

---

## 3. Exact model architecture relevant to KV

**Observed fact**, from E10 (`config.json`, byte-verified against the
pinned gated repo commit `0cb88a4f764b7a12671c53f0838cd831a0843b95` via
git-blob-SHA1 `a5a40fa6da567ab026a5a2bf37125a90182be07d`, sha256
`39fb36dc5416f445ebc4e71cb71fbcf6727e80a35836d8ba1a1474c318467b7a`, 878
bytes):

```json
{
  "architectures": ["LlamaForCausalLM"],
  "head_dim": 128,
  "hidden_size": 3072,
  "num_attention_heads": 24,
  "num_hidden_layers": 28,
  "num_key_value_heads": 8,
  "torch_dtype": "bfloat16",
  "attention_bias": false
}
```

- `num_hidden_layers = 28` — **explicit**, observed fact.
- `num_attention_heads = 24` (query heads) — **explicit**, observed fact.
- `num_key_value_heads = 8` — **explicit**, observed fact. This is
  strictly less than `num_attention_heads` (24), so the model uses
  **grouped-query attention (GQA)** with a grouping ratio of 24/8 = 3
  query heads per KV head.
- `head_dim = 128` — **explicit field**, not derived. It happens to equal
  `hidden_size / num_attention_heads = 3072/24 = 128`, but the config
  carries it explicitly rather than requiring that division — a formula
  that assumes `head_dim` must always be derived this way would be wrong
  for architectures that set it independently. **Design recommendation:**
  the Week 3 formula should read `head_dim` directly from config rather
  than deriving it, precisely to avoid this class of bug (§I).
- `torch_dtype = "bfloat16"` — model weight storage dtype. No
  `quantization_config` key is present — **observed fact: this is an
  unquantized bf16 checkpoint**, corroborated by E9's
  `safetensors.parameters.BF16 = 3212749824`.

### Derivation (§A requirement)

1. **K dimensionality, one token, one layer:** GQA stores K per **KV
   head**, not per query head: `num_key_value_heads * head_dim = 8 * 128
   = 1024` elements.
2. **V dimensionality, one token, one layer:** identical shape to K in
   this architecture (no separate V head-count field in config; vLLM and
   HF's Llama implementation give K and V the same
   `num_key_value_heads * head_dim` shape): `1024` elements.
3. **Combined K+V, one layer:** `1024 + 1024 = 2048` elements =
   `2 * num_key_value_heads * head_dim`.
4. **Total across all layers:** `2048 * 28 = 57,344` elements/token.

**GQA changes the formula relative to a naive "use
`num_attention_heads`" version**: using 24 instead of 8 would give `2 *
24 * 128 * 28 = 172,032` elements/token — **3× too large**, and §5/§6
show this would be empirically falsified by vLLM's own reported KV-cache
sizing. Using `num_key_value_heads` is correct because K/V projections in
GQA are computed and cached once per KV-head group and *shared* across
the query heads in that group at attention time — the cache never stores
per-query-head copies.

No model-specific behavior beyond GQA (e.g. no MLA, no sliding-window
attention, no cross-layer KV sharing) is present in `config.json` for
this architecture, and none is required by `LlamaForCausalLM`.

---

## 4. KV tensor-shape derivation

Restated in units, one token:

```text
elements_per_token_per_layer (K)  = num_key_value_heads * head_dim
                                   = 8 * 128 = 1,024 elements
elements_per_token_per_layer (V)  = 1,024 elements   (same shape as K)
elements_per_token_per_layer (K+V)= 2,048 elements
elements_per_token_all_layers     = 2,048 * num_hidden_layers
                                   = 2,048 * 28
                                   = 57,344 elements
```

---

## 5. Logical KV bytes/token derivation

```text
logical_kv_bytes_per_token = elements_per_token_all_layers * bytes_per_kv_element
                            = 57,344 * bytes_per_kv_element
```

With `bytes_per_kv_element = 2` (bf16 — established in §6):

```text
logical_kv_bytes_per_token = 57,344 * 2 = 114,688 bytes/token
                            = 112 KiB/token exactly (114,688 / 1,024 = 112)
```

This is algebraically identical to the README's candidate formula
(`2 * num_hidden_layers * num_key_value_heads * head_dim *
bytes_per_kv_element`) — **confirmed correct**, not merely "looks
standard."

**Tensor-parallel effects (investigated, not applicable to current
deployment):** E4 line 198 logs `tensor_parallel_size=1,
pipeline_parallel_size=1, data_parallel_size=1`. At TP=1 there is no
partitioning to reason about. In general, TP shards KV heads across
devices (each of `tp_size` workers holds `num_key_value_heads / tp_size`
heads' worth of K/V), so **TP changes only how the fixed total logical
byte count is *partitioned* across devices — it does not change the
request's total logical KV footprint**, which is what
`estimated_kv_bytes` is defined to represent (README §B, "must describe
total logical request KV footprint, not per-device footprint"). This
matters only if a future deployment enables TP > 1; nothing here
requires acting on it now.

**Quantized weights vs. KV dtype:** independently-configurable
knobs — confirmed not conflated in this deployment (§6 shows model
weight dtype and effective KV dtype coincide *only* because `auto`
resolves KV dtype to the model's dtype; a future explicit
`--kv-cache-dtype fp8` would decouple them without changing model
weights at all).

---

## 6. Effective KV dtype investigation

**Observed fact (E3):** `scripts/gpu_session/setup_and_launch_vllm.sh`
line 97–101, the actual command Week 2 ran:

```bash
VLLM_USE_FLASHINFER_SAMPLER=0 ~/vllm-env/bin/vllm serve "$MODEL" \
  --port "$PORT" \
  "${eager_flag[@]}" \
  "${prefix_cache_flag[@]}" \
  --max-model-len "$MAX_MODEL_LEN"
```

No `--kv-cache-dtype` and no `--dtype` flag anywhere in this script (or
anywhere else in the repository — confirmed by repo-wide search).

**Observed fact (E4), vllm.log:190:**
`non-default args: {..., 'max_model_len': 20000, 'enforce_eager': True,
'enable_prefix_caching': False}` — vLLM's own log of which CLI args were
non-default. `kv_cache_dtype` is absent from this list, i.e. **vLLM
itself confirms it received no explicit KV-dtype override.**

**Observed fact (E4), vllm.log:198** (engine's fully-resolved config,
printed once at `EngineCore` init):

```text
dtype=torch.bfloat16, ..., kv_cache_dtype=auto, ...
```

So the **CLI-level** resolved value is literally the string `auto` —
vLLM has not yet turned this into a concrete byte width in this log
line. This is where an investigation that stops at "the log says `auto`"
would have to guess. This investigation does not stop there.

**Authoritative resolution rule (E11),** vLLM source
`vllm/config/cache.py`, `CacheConfig.cache_dtype`, matching the exact
v0.27.1 version this session ran (E4:186, `version 0.27.1`):

> *"If 'auto', will use model data type."*

Model data type, per the same log line, is `torch.bfloat16`. So the
resolution chain is: `kv_cache_dtype=auto` → "use model data type" →
`torch.bfloat16` → **`bytes_per_kv_element = 2`**.

**Independent empirical confirmation — this is the strongest evidence in
this report, and it is a falsification test, not just a plausibility
argument.** E4 lines 216–218:

```text
Available KV cache memory: 13.87 GiB
GPU KV cache size: 129,888 tokens
Maximum concurrency for 20,000 tokens per request: 6.49x
```

Using the derived §5 formula with bf16 (2 bytes/element):

```text
114,688 bytes/token * 129,888 tokens = 14,896,594,944 bytes
14,896,594,944 / 1,073,741,824 (GiB) = 13.8735... GiB  ≈ 13.87 GiB  ✓ exact match to vLLM's own reported precision
```

And the concurrency sanity check: `129,888 tokens / 20,000
tokens-per-request = 6.4944` ≈ vLLM's own reported `6.49x` ✓.

If the formula had instead used `num_attention_heads` (24) instead of
`num_key_value_heads` (8), predicted bytes/token would be `344,064`
(3×), predicting only **~43,300 tokens** of KV capacity from the same
13.87 GiB — contradicted by vLLM's logged 129,888. If it had used fp8 (1
byte/element) instead of bf16, predicted capacity would be **~259,700**
tokens — also contradicted. **The 8-KV-head, bf16 formula is the only
one of these candidates that reproduces vLLM's own reported number to
four significant figures.** This is a derived value, not a repository
citation, but it is derived from a direct empirical measurement, not
memory.

### Policy 4A-1 vs 4A-2

| | Policy 4A-1 (auto + record resolved dtype) | Policy 4A-2 (explicitly pin `--kv-cache-dtype`) |
|---|---|---|
| Reproducibility risk | `auto`'s resolution rule ("model data type") is vLLM-version-dependent behavior, not a config-file guarantee. A future vLLM release, or a different GPU/backend (E11 notes CUDA 11.8+/ROCm/Gaudi fp8 paths, and some models default to fp8), could silently change what `auto` resolves to without changing anything in this repo | Immune to `auto`-resolution drift by construction — the cost model and the server can never disagree about dtype as a *silent* consequence of a vLLM upgrade |
| Changes canonical Week 2 identity? | No — this is exactly what Week 2 already ran | **Yes.** `BASELINE.md`'s serving identity (E1) does not mention `kv_cache_dtype` at all; adding an explicit pin changes the launch command from what produced the Week 2 breach-interval numbers. Pinning must apply to **future (Week 4+) serving runs only**, never retroactively to Week 2 |
| Compatibility | None — no flag added | Low risk here specifically: pinning to `bfloat16` reproduces the exact status quo. Pinning to anything else (e.g. `fp8`) would be a genuine behavior change requiring its own evaluation (accuracy, throughput) — out of scope for this investigation |
| Performance | No effect | No effect *if* pinned to `bfloat16` (matches what already runs); pinning to `fp8` would roughly double effective KV capacity per GPU but is a separate, unevaluated decision |

**Design recommendation:** stronger policy for reproducible experiments
is **4A-2, scoped to Week 4+ only**: pin `--kv-cache-dtype bfloat16`
explicitly in whatever launches Week 4 serving, specifically *because*
it costs nothing (it reproduces current behavior exactly) while removing
a version-drift dependency the cost-model provenance manifest would
otherwise have to track indirectly. Week 2's `BASELINE.md` identity
should **not** be edited to add this — see README's own hard constraint
("Week 2 baseline artifacts and semantics must remain unchanged").

---

## 7. `max_tokens` reservation semantics

This is the second of the two areas the README flags for closest
scrutiny, and the investigation finds the naive formula is not exact.

**The question:** can a request generate at most `input_tokens +
max_output_tokens` tokens of actual logical KV state, or is the true
bound different?

**First-principles trace of KV-cache autoregressive decoding** (this
reasoning is about how transformer KV caching works generically — it
does not depend on vLLM-internal scheduler behavior, so it satisfies the
README's constraint that the reservation must be computable without
vLLM-internals modeling):

Let prefill cover input positions `1..n` (`n = input_tokens`). Prefill's
output logits at position `n` are used to sample the *first* generated
token, `token_{n+1}` — **no decode iteration is needed for this token**;
it comes free from the prefill forward pass.

Each subsequent decode iteration `j` (for `j = 1, 2, ...`):
- takes as input the token most recently sampled, `token_{n+j}`,
- computes that token's own K/V and **appends it to the cache** (this is
  an unavoidable side effect of computing self-attention at that
  position — a token attends to itself, so its own K/V must exist before
  its attention output can be computed),
- and produces the logits used to sample the **next** token,
  `token_{n+j+1}`.

To emit exactly `m = max_output_tokens` generated tokens
(`token_{n+1}..token_{n+m}`), the engine needs decode iterations
`1..(m-1)` — iteration `j` produces `token_{n+j+1}`, so iteration `m-1`
is what yields `token_{n+m}`, the *last* permitted token. **Decode
iteration `m` is never run**, because it would exist only to compute a
`token_{n+m+1}` that the request is not permitted to have (`max_tokens`
already reached, or in the EOS case, the model has already signaled
completion).

Consequence: `token_{n+m}` (the final generated token) is returned to
the caller, but **its own K/V entry is never written to the cache**,
because no decode iteration ever takes it as input. The KV cache at the
moment generation legitimately stops therefore covers positions
`1..(n+m-1)` — **`n + m - 1` tokens, not `n + m`.**

```text
true_max_kv_tokens = input_tokens + max_output_tokens - 1     (for max_output_tokens ≥ 1)
true_max_kv_tokens = input_tokens                              (for max_output_tokens = 0)
                    = input_tokens + max(max_output_tokens - 1, 0)
```

This holds **identically for the EOS-early-stop case**: whichever token
triggers the stop condition (hitting the `max_tokens` cap, or sampling
an EOS id) is the last token fed to a completed decode iteration; the
same off-by-one applies regardless of *which* stop condition ends the
request, so the analysis does not require knowing whether the request
will hit EOS early — consistent with the README's requirement that the
cost be computable **before** routing, without needing realized output
length. (An EOS-terminated request's *realized* KV usage is smaller
still, because it generates fewer than `m` tokens — but that only
matters for the realized/actual footprint, not for the *worst-case*
reservation, which must assume the request runs to its permitted
`max_output_tokens`.)

### Is `reserved_tokens = input_tokens + max_output_tokens` therefore wrong?

No — **it is a safe upper bound, deliberately or coincidentally
one-token conservative**:

```text
reserved_tokens (README formula) − true_max_kv_tokens
  = (input_tokens + max_output_tokens) − (input_tokens + max(max_output_tokens − 1, 0))
  = 1                          if max_output_tokens ≥ 1
  = 0                          if max_output_tokens = 0
```

It never under-reserves. This satisfies the project's explicit design
goal (README §D: "the project intentionally wants a conservative
estimate"). The answer to the README's own framing — "is the `+
max_output_tokens` formulation the exact maximum, deliberately
one-token-conservative, or incorrect for another reason" — is: **it is
not the exact maximum; it is conservative by exactly one token per
request whenever `max_output_tokens ≥ 1`, and exact when
`max_output_tokens = 0`.** This is a small, bounded, well-understood
slack — not a systemic error — and this investigation does not
recommend changing the formula on this basis (README §D: "do not
optimize the formula prematurely"). It is reported so the 1-token slack
is a documented, intentional fact rather than an unexamined accident.

**`max_tokens` API semantics (E1, `BASELINE.md`):** Week 2 locked
`max_tokens=512` as an output-token *budget*, i.e. an upper bound the
server enforces server-side — consistent with the standard
OpenAI-compatible `max_tokens` contract vLLM implements: generation
stops at the first of (a) an EOS/stop-sequence token, or (b)
`max_tokens` generated tokens. Both stop conditions are covered by the
single derivation above.

---

## 8. Example calculations

`logical_kv_bytes_per_token = 114,688 B = 112 KiB` (bf16, §5–§6). All
arithmetic below is integer arithmetic on `reserved_tokens =
input_tokens + max_output_tokens` (the README's formula, i.e. the
1-token-conservative upper bound from §7, not the exact `-1` value).
KiB/MiB/GiB use powers of 1024 throughout.

| `input_tokens` | `max_tokens` | `reserved_tokens` | `estimated_kv_bytes` | MiB | GiB |
|---:|---:|---:|---:|---:|---:|
| 36 | 512 | 548 | 62,849,024 | 59.9375 | 0.058533 |
| 66 | 512 | 578 | 66,289,664 | 63.21875 | 0.061737 |
| 600 | 512 | 1,112 | 127,533,056 | 121.625 | 0.118774 |
| 2,706 | 512 | 3,218 | 369,065,984 | 351.96875 | 0.343720 |
| 10,482 | 512 | 10,994 | 1,260,879,872 | 1,202.46875 | 1.174290 |

(`input_tokens=10,482` is the corpus's actual longest rendered prompt,
`prompt_id 790`, per E6 — not a synthetic extreme.)

**Sanity cross-check against E4's own numbers:** the pinned
`--max-model-len 20000` (E1) times `114,688` bytes/token = 2,293,760,000
bytes ≈ 2.14 GiB — far under the 13.87 GiB the server actually reserved
for KV cache (E4:216), consistent with vLLM reserving pool capacity for
**many concurrent** max-length requests (`129,888 / 20,000 ≈ 6.49`
concurrent slots, matching E4:218's own reported figure), not per-request
capacity. This is expected and is exactly the boundary `estimated_kv_bytes`
is meant to describe (a *single request's* logical footprint) versus what
it must not be read as (pool-level allocator state) — see §9–§10.

**`u64` sufficiency (§E requirement):** `bytes_per_kv_element` and the
architecture constants are fixed for this model, so
`estimated_kv_bytes` scales linearly in `reserved_tokens`. `u64::MAX ≈
1.8 × 10^19`. Even at `reserved_tokens = 10^12` (a value with no
plausible relationship to any real request), `estimated_kv_bytes =
1.14688 × 10^17`, still far under `u64::MAX`. **`u64` is safely
sufficient with enormous headroom** for any supported request size.
Note for §I: **`u32` would not be safe** — `u32::MAX ≈ 4.29 × 10^9`
bytes, and `reserved_tokens > 37,449` already overflows a `u32` byte
count at 114,688 B/token; the current `--max-model-len 20000` (E1)
happens to leave `u32` technically intact today (`20,000 * 114,688 =
2,293,760,000 < 4,294,967,295`), but with essentially no margin, and any
future increase to `max-model-len` (which E6/E5's own history shows has
already happened once, 20000 raised from an earlier estimate) would
silently overflow it. This is a concrete argument for `u64`, not a
hypothetical one.

---

## 9. What `estimated_kv_bytes` means

The README's proposed semantic statement:

> `estimated_kv_bytes` is the conservative logical K/V tensor storage
> corresponding to the request's full permitted sequence length under
> the pinned model architecture and effective KV-cache dtype.

**Is this technically defensible?** Yes, with one precision added by
this investigation (§7): "full permitted sequence length" should be
understood as `input_tokens + max_output_tokens` (the README's chosen
reservation), which this report has shown is **not** the request's
*exact* maximum KV-token count but a fixed one-token-conservative upper
bound on it. Refined wording:

> `estimated_kv_bytes` is a conservative logical upper bound on the K/V
> tensor storage a request could require, computed from
> `input_tokens + max_output_tokens` under the pinned model's KV tensor
> shape (`num_hidden_layers`, `num_key_value_heads`, `head_dim`) and the
> serving configuration's effective KV-cache element dtype. It is exact
> when `max_output_tokens = 0` and over-estimates true peak logical KV
> occupancy by exactly one token's worth of storage otherwise.

---

## 10. What it explicitly does not model

Per README's own list (§ "Investigation Objective") and confirmed by
this investigation — `estimated_kv_bytes` must **not** be interpreted
as:

- **Actual instantaneous GPU memory consumption** — E4:216–217 shows
  vLLM pre-reserves a fixed KV memory *pool* (13.87 GiB → 129,888
  tokens) at startup, sized independently of any individual request;
  per-request logical footprint and pool occupancy are different
  quantities.
- **vLLM block allocation** — vLLM allocates KV in fixed-size blocks
  with internal bookkeeping (not investigated here — README explicitly
  scopes this out).
- **Physical allocator reservation, fragmentation-adjusted usage,
  scheduler state, continuous-batching effects, prefix-cache sharing,
  preemption, or swap behavior** — all explicitly out of scope per the
  README, and this investigation introduced no evidence that would pull
  any of them back in.
- **Latency prediction or queueing-pressure prediction** — this is a
  size, not a time; `BASELINE.md`'s p99 TTFT numbers (E1) are a
  *consequence* of load and are not derivable from `estimated_kv_bytes`
  alone.
- **Exact available-capacity measurement** — capacity is a
  server/pool-level property (E4:216's 13.87 GiB); `estimated_kv_bytes`
  is a per-request demand number that would need to be compared against
  a *separately defined* capacity model to answer an admission question.

**Legitimate Week 4 uses** (README's own list, endorsed by this
investigation):

- **Relative request-cost ranking** — safe, since the formula is
  monotonic in `reserved_tokens` for a fixed model/dtype.
- **Conservative per-request demand signal** — safe, given the
  one-token-conservative (never under-conservative) property proven in
  §7.
- **Routing input** — safe, consistent with ADR 0002's accepted design
  (§11).
- **Admission-control input, paired with a separately defined capacity
  model** — conditionally safe; this investigation did not evaluate or
  design that capacity model (out of scope), only the per-request demand
  side.

---

## 11. ADR 0002 consistency check

`docs/adr/0002-kv-aware-routing-worst-case-estimate.md` (E2), status
Accepted, decides:

> "KV-cache-aware routing uses a **worst-case full-KV footprint
> estimate**, computed from prompt tokens plus max output tokens. It
> does not model vLLM's internal scheduler, prefix caching, or
> preemption behavior."

**This investigation confirms ADR 0002's decision and finds no
contradiction.** The "prompt tokens plus max output tokens" formulation
ADR 0002 already commits to is exactly `reserved_tokens = input_tokens +
max_output_tokens`, and §10 confirms none of the excluded behaviors
(scheduler, prefix caching, preemption) were pulled back into the
formula by this investigation.

**One ambiguity worth flagging, not correcting here** (README §G: "do
not edit the ADR"; "propose the smallest wording change separately"):
ADR 0002 calls this a "worst-case" estimate without qualification. §7 of
this report shows the formula is worst-case **up to a fixed, known,
one-token slack** — it is not the literal exact worst case, it
*exceeds* the exact worst case by one token. This is a strictly stronger
property than ADR 0002 claims (still worst-case, just not *tight*), so
there is no contradiction — but a future reader could misread "worst-case"
as "exact," which the smallest defensible wording fix would forestall.
**Proposed wording** (not applied): append to ADR 0002's Decision
section a parenthetical — *"(this bound is one token more conservative
than the true per-request KV-token maximum, a deliberate and
inexpensive slack — see Week 3 investigation)"*.

---

## 12. Required provenance fields

### 1. Immutable/source provenance

- Model identifier: `meta-llama/Llama-3.2-3B-Instruct`
- Model revision/commit: `0cb88a4f764b7a12671c53f0838cd831a0843b95` (E9,
  same commit already pinned for the tokenizer, E6)
- `config.json` sha256: `39fb36dc5416f445ebc4e71cb71fbcf6727e80a35836d8ba1a1474c318467b7a`
  (878 bytes; git-blob-SHA1 `a5a40fa6da567ab026a5a2bf37125a90182be07d`,
  verified in this investigation — not yet committed anywhere in-repo;
  see §13 gap)
- Tokenizer / tokenizer_config / chat-template SHA-256 — already
  captured in `benchmarks/workloads/week2_headline/tokenizer_capacity_report.json`
  (E6); Week 3 provenance manifest should reference/reuse these rather
  than re-hash

### 2. Derived architecture constants

- `num_hidden_layers = 28`, `num_key_value_heads = 8`, `head_dim = 128`
  (all read directly from `config.json`, not derived from other fields —
  §3)
- `bytes_per_kv_element = 2` (bf16) — derived from effective
  `kv_cache_dtype`, not a config.json field
- `logical_kv_bytes_per_token = 114,688` — fully derived (§5)
- **Formula/version identifier** — e.g. `kv_cost_formula_version:
  "v1-worst-case-gqa"` — so a future architecture change (e.g. adding
  MLA support) can't silently reinterpret an old provenance record

### 3. Serving-runtime configuration

- vLLM version: `0.27.1` (E4:186)
- Effective `kv_cache_dtype`: `bfloat16` (resolved from `auto` — §6;
  **must be recorded as the resolved value, not the literal string
  `"auto"`**, or the provenance record inherits the exact ambiguity this
  investigation had to resolve)
- `tensor_parallel_size: 1` (relevant per §5's TP discussion — becomes
  load-bearing the moment TP > 1 is ever introduced)
- Relevant flags: `--enforce-eager`, `--no-enable-prefix-caching`,
  `--max-model-len` (E1) — these don't change the KV-bytes-per-token
  formula, but changing `--max-model-len` changes the largest
  `reserved_tokens` the server can accept, which is why `check_tokenizer_capacity.py`
  (E5) exists

`cost_model_version` should be a top-level field distinct from the
formula-version identifier above, versioning the request-cost *contract*
(README §6's four exposed fields) rather than the KV-byte formula
specifically, since the two can evolve independently.

**Per-request sidecar (README §7, §H — keep small):** only
`input_tokens`, `max_output_tokens`, `reserved_tokens`,
`estimated_kv_bytes` need to appear per request (README's own §6
contract). Every value in this section belongs in a manifest logged
*once per serving configuration*, not per request.

---

## 13. Risks / unresolved questions

- **Gap: no in-repo hash pin for `config.json` yet.** Unlike the
  tokenizer (E6), nothing in the repository currently records
  `config.json`'s hash or the architecture constants derived from it.
  This investigation produced that evidence (§3, §12.1) but did not
  write it anywhere durable, per the README's "do not implement" /
  "do not modify... authoritative docs" constraint. **This is the single
  biggest actionability gap left by this report** — until a Week 3
  implementation task writes a `fetch_model_config.py` (mirroring
  `scripts/fetch_tokenizer.py`'s proof pattern) and a provenance
  manifest, the architecture constants exist only in this report and in
  this conversation's evidence trail.
- **Router↔vLLM tokenization mismatch is a real, currently-unmitigated
  risk (README §I, "flag prominently"):** `router/Cargo.toml` (E7) shows
  the Rust router has **no tokenizer dependency at all** today. Achieving
  "exact Python-reference ↔ Rust-runtime agreement" (README §8) will
  require adding one (the Rust `tokenizers` crate, from the same project
  as the Python `tokenizers` package `scripts/check_tokenizer_capacity.py`
  already uses, is the natural choice for byte-identical behavior) — this
  is unstarted work, not a hidden bug, but is called out because the
  README's validation bar (exact agreement) cannot be met by the current
  Rust dependency set.
- **Chat-template rendering must happen before tokenization, on both
  sides.** `check_tokenizer_capacity.py` (E5) explicitly renders the chat
  template before counting tokens (35-token overhead for an empty
  message, E6) because that is what vLLM actually tokenizes. Any Week 3
  Rust implementation that counts raw prompt tokens without applying the
  same Jinja chat template would systematically under-count
  `input_tokens` by at least this margin — this is the concrete form of
  the README's "forgetting chat-template overhead" failure mode.
- **`kv_cache_dtype=auto` resolution is confirmed for *this* vLLM
  version/GPU only.** E11's docstring itself notes fp8 defaults exist for
  some models/backends; nothing in this investigation guarantees `auto`
  resolves to bf16 on a future vLLM version or different accelerator.
  This is precisely why §6 recommends pinning explicitly for Week 4+.
- **The one-token conservative slack (§7) is unverified against vLLM's
  actual V1 scheduler code path** — it is derived from the generic
  mechanics of KV-cache decoding (true of essentially all
  transformer/KV-cache implementations, including vLLM's), not from
  reading vLLM's own scheduler source. The README explicitly scopes
  scheduler-internals modeling out, so this was not pursued further, but
  it is a derived value, not a citation-backed one the way §6's dtype
  finding is.
- **λ=0.5 / breach-interval material in `BASELINE.md` is unrelated to
  this investigation** and is cited here only for serving-identity
  provenance (E1) — no claim in this report depends on Week 2's
  breach-interval numbers themselves.

---

## 14. Recommendation for Decision 4

**Decision 4A (definition of `estimated_kv_bytes`):** Lock it as the
README proposes — `reserved_tokens * logical_kv_bytes_per_token`, with
`logical_kv_bytes_per_token = 114,688` bytes for the pinned model +
effective dtype — **using the refined wording in §9**, which makes the
one-token conservative property (§7) an explicit, documented part of the
definition rather than an implicit assumption.

**`kv_cache_dtype` pin decision:** Recommend **Policy 4A-2, scoped to
Week 4+ serving only** — explicitly pin `--kv-cache-dtype bfloat16` for
any future serving launch script, leaving `BASELINE.md`/Week 2's
artifacts and launch script untouched. Rationale: pinning costs nothing
here (§6 shows it reproduces exactly what already ran) and removes a
version-drift dependency that would otherwise have to be *revalidated*
(not just recorded) every time vLLM is upgraded.

---

## 15. Exact decisions still requiring human approval

1. **Approve or amend the refined `estimated_kv_bytes` wording (§9)** —
   specifically, whether to encode the "-1 exact / +1 conservative"
   property into the formal definition, or leave the definition as the
   README's original wording and treat §7's finding as an internal
   implementation note only.
2. **Approve Policy 4A-2 scoped to Week 4+ (§6, §14)** — explicit
   `--kv-cache-dtype bfloat16` pin for future serving, Week 2 left
   untouched — or choose 4A-1 instead.
3. **Approve the proposed ADR 0002 wording addition (§11)** — or decide
   no change is warranted, since no outright contradiction was found.
4. **Approve committing this investigation's `config.json` provenance
   (§3, §12.1, §13's gap)** into a durable, hash-pinned repository
   artifact — this report is not that artifact; a follow-up
   implementation task (out of scope here) would need to add something
   like `scripts/fetch_model_config.py` plus a committed manifest.
5. **Decide whether the Week 3 Rust tokenizer-parity work (§13) is
   in-scope for Week 3 or deferred** — the README's exposed
   request-cost contract (§6) cannot be validated to its own bar (exact
   Python↔Rust agreement) without it, but adding a tokenizer dependency
   to `router/Cargo.toml` is itself an implementation decision this
   investigation is not authorized to make.

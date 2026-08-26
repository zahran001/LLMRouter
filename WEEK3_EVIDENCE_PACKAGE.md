# Week 3 Evidence Package — Request-Cost Signal Closeout

> **STATUS: AUTHORITATIVE — WEEK 3 CLOSED 2026-08-25**
>
> Role: the closing evidence for `WEEK3_IMPLEMENTATION_README.md`'s final
> hard stop, `W3-CLOSED`. Read this to know whether the request-cost
> signal is trustworthy and auditable; read `WEEK3_COST_CONTRACT.md` for
> the frozen interfaces; read
> `WEEK3_KV_REQUEST_COST_INVESTIGATION_REPORT.md` for the formula
> derivation and hash-verified evidence the contract is built on.
>
> Work happened entirely on branch `week3-request-cost`. `main` and every
> Week 1/2 artifact are unchanged.

Every claim below is tagged, per README §7's discipline:

```text
OBSERVED FACT | DERIVED VALUE | LOCKED DESIGN DECISION | IMPLEMENTATION RESULT
```

---

## 1. Locked request-cost formula

**LOCKED DESIGN DECISION** (`WEEK3_IMPLEMENTATION_README.md` §2.5–2.6):

```text
reserved_tokens    = input_tokens + max_output_tokens
estimated_kv_bytes = reserved_tokens * logical_kv_bytes_per_token
```

Deliberately **not** `input_tokens + max_output_tokens - 1`, even though
the Week 3 investigation found that to be the exact logical-KV-occupancy
boundary for `max_output_tokens ≥ 1` — the one-token slack is documented
intentional conservatism, not an error. `tests/cost_model/test_negative_controls.py::test_control_8_minus_one_formula_forbidden`
and `router::cost::tests::control_minus_one_formula_diverges_from_the_locked_formula`
both prove the `-1` formula is not what ships.

**DERIVED VALUE**, for the pinned `meta-llama/Llama-3.2-3B-Instruct`
identity:

```text
logical_kv_bytes_per_token = 2 * num_hidden_layers * num_key_value_heads * head_dim * bytes_per_kv_element
                            = 2 * 28 * 8 * 128 * 2
                            = 114,688 bytes  (= 112 KiB exactly)
```

Full derivation, including the independent empirical falsification test
(reproducing vLLM's own logged KV-cache-sizing figure to the byte):
`WEEK3_KV_REQUEST_COST_INVESTIGATION_REPORT.md` §3–§6.

---

## 2. Supported request contract & fail-closed semantics

**LOCKED DESIGN DECISION** (`WEEK3_COST_CONTRACT.md` §1–2):

- Supported shape: top-level keys ⊆ `{model, messages, max_tokens,
  stream}`; `model` matches the pinned identity exactly; `messages` is
  exactly one `{role: "user", content: <string>}`; `max_tokens` present
  and a positive integer.
- **Unsupported requests never change router HTTP behavior.** Cost
  computation returns an internal `RequestCostError`; the request is
  forwarded upstream byte-identically regardless of whether it was
  supported, and the three `X-Request-Cost-*` response headers are
  attached only on success. This was one of two ambiguities in
  `WEEK3_IMPLEMENTATION_README.md` explicitly resolved with the user
  before implementation began (2026-08-25).

**IMPLEMENTATION RESULT:** `tests/router/test_cost_edge_cases.py`
confirms, against the live compiled router, that 10 distinct unsupported
shapes (missing/invalid `max_tokens`, wrong model, empty/multi-message,
non-user role, multimodal content, `tools` present, non-JSON body) all
receive zero cost headers while still returning HTTP 200 through the
proxy — proxy behavior provably unchanged.

---

## 3. Tokenizer, chat-template, and model-config provenance

**OBSERVED FACT**, hash-verified (git-blob-SHA1 against the gated
`meta-llama/Llama-3.2-3B-Instruct` repo's public metadata API, same
method for both):

| Artifact | SHA-256 | Source |
|---|---|---|
| `config.json` | `39fb36dc5416f445e...` | `scripts/fetch_model_config.py`, mirror `alpindale/Llama-3.2-3B-Instruct` |
| `tokenizer.json` | `79e3e522635f317...` | `scripts/fetch_tokenizer.py` (pre-existing, Week 2) |
| `tokenizer_config.json` | `9823dcfdc112186...` | `scripts/fetch_tokenizer.py` (pre-existing, Week 2) |
| chat template (extracted) | `5816fce10444e03...` | derived from `tokenizer_config.json`, hashed by `scripts/build_cost_provenance.py` |

Gated repo commit (same commit for all four artifacts, one repository
snapshot): `0cb88a4f764b7a12671c53f0838cd831a0843b95`.

**IMPLEMENTATION RESULT:** `scripts/fetch_model_config.py` makes the
`config.json` proof reproducible — previously a one-off manual step in
the investigation, now a committed, re-runnable script following the
exact pattern `scripts/fetch_tokenizer.py` already established.

---

## 4. Effective KV-cache dtype (Week 2, historical)

**LOCKED DESIGN DECISION**, recorded not re-derived
(`scripts/build_cost_provenance.py`): `effective_kv_cache_dtype =
"bfloat16"`, `bytes_per_kv_element = 2`. This is a recorded fact about a
specific historical GPU session
(`benchmarks/evidence/week2/session_2/vllm.log`), established in the Week
3 investigation by reproducing vLLM's own logged
`Available KV cache memory: 13.87 GiB` / `GPU KV cache size: 129,888
tokens` figure to the byte using exactly this dtype
(`WEEK3_KV_REQUEST_COST_INVESTIGATION_REPORT.md` §6). Week 2's launch
script never set `--kv-cache-dtype`; this is what `auto` resolved to.

**LOCKED DESIGN DECISION, Week 4+ only**
(`WEEK3_IMPLEMENTATION_README.md` §2.8, carried into `STATUS.md`'s Week 3
closeout entry): future serving must explicitly launch with
`--kv-cache-dtype bfloat16` and startup/preflight must verify the
effective resolved dtype is also `bfloat16` before any routing experiment
begins. **This requirement is not retroactively attributed to Week 2** —
`BASELINE.md` and Week 2's launch script are unchanged.

---

## 5. `RequestCost` and provenance-manifest schemas

**LOCKED DESIGN DECISION**, full schemas in `WEEK3_COST_CONTRACT.md` §3
and §5. Summary:

```text
RequestCost { input_tokens: u32, max_output_tokens: u32,
              reserved_tokens: u32, estimated_kv_bytes: u64 }
```

Provenance manifest (`benchmarks/workloads/week3_cost/request_cost_provenance.v1.json`,
committed, sha256 of its own bytes recorded by `metrics.artifacts.write_json_artifact`
at generation time) splits into `source_provenance` (hashes),
`derived_architecture` (KV-shape constants), `serving_runtime` (effective
dtype, vLLM version) — the exact three-part split
`WEEK3_IMPLEMENTATION_README.md` §4 requires. No architecture constant
appears as a magic number in either the Python or Rust implementation;
both read this one committed file (Python: `RequestCostProvenance.from_frozen`;
Rust: `include_str!` + `OnceLock`, parsed once at compile/first-use time).

---

## 6. Request-cost sidecar schema

**LOCKED DESIGN DECISION** (`WEEK3_COST_CONTRACT.md` §6, the second
ambiguity resolved with the user before implementation): the Python
`loadgen` owns `<run>.request_cost.v1.jsonl`, not the router — the router
stays stateless plumbing (Week 1's design), and `loadgen` already owns
the per-run logging pipeline and already knows every request's text and
`max_tokens` before sending it. The Rust router instead exposes its
per-request answer via `X-Request-Cost-*` response headers, which is what
`tests/router/test_cost_conformance.py` and `test_cost_edge_cases.py`
read to prove Rust↔Python agreement over live HTTP.

**Week 2 boundary, restated and enforced by test**
(`tests/cost_model/test_legacy_compatibility.py`): `prompt_len` in
`<run>.raw_log.jsonl` remains character count, unchanged, unrelated to
Week 3's `input_tokens`.

---

## 7. Python reference implementation identity

**IMPLEMENTATION RESULT.** `cost_model/` package:

- `tokenizer.py` — pinned-tokenizer loading and chat-template rendering,
  refactored out of `scripts/check_tokenizer_capacity.py` (not
  duplicated) so the Week 2 capacity-check path and the Week 3
  cost-reference path share one implementation. Re-ran
  `check_tokenizer_capacity.py` post-refactor: identical output to before
  the refactor (p50=66, p99=2706, max=10,482 at prompt_id 790).
- `types.py` — `RequestCost`, `RequestCostProvenance`, `RequestCostError`
  taxonomy, version constants (`cost_model_version = "v1"`,
  `formula_version = "kv-worst-case-gqa-v1"`).
- `reference.py` — `validate_supported_request` + `compute_request_cost`,
  the oracle.

Supporting scripts: `scripts/fetch_model_config.py`,
`scripts/build_cost_provenance.py`, `scripts/build_cost_golden_vectors.py`,
`scripts/characterize_cost_distribution.py`.

---

## 8. Rust runtime implementation identity

**IMPLEMENTATION RESULT.** `router/src/cost/` module, wired into the
existing proxy at `router/src/proxy.rs`:

- `tokenizer.rs` — `tokenizers` crate (HF's own Rust tokenizer library —
  the same library the Python `tokenizers` package binds to) +
  `minijinja` (Jinja2-compatible rendering, `trim_blocks`/`lstrip_blocks`
  set to match `cost_model/tokenizer.py` exactly) + `chrono` for
  `strftime_now`, matching Python's `datetime.strftime` semantics
  directly rather than reimplementing date formatting.
- `provenance.rs` — the same committed manifest, `include_str!`-embedded,
  parsed once into a `OnceLock`.
- `mod.rs` — `compute_request_cost`, byte-for-byte the same validation
  order and formula as the Python reference.

**Architectural seam** (`WEEK3_COST_CONTRACT.md`, README §6 W3-3's
required constraint): `proxy.rs::open_upstream` was refactored to take
already-buffered `Bytes` instead of `Body` — the request body is read
exactly once (`buffer_request_body`, shared by the real route and, via
`wrong.rs`, the two negative-control routes), and the identical buffer is
handed to both cost computation and upstream forwarding, so cost
inspection can never diverge from what is actually sent. This is the one
deliberate, documented break of Week 1 decision 2's "no JSON parser in
the real router" invariant (`serde_json` promoted from `wrong-routers`-only
to a plain dependency) — scoped entirely to the already-buffered
**request** path; the response stream (decision 2's actual concern,
`WEEK1_ROUTER_IMPL.md` §2) is untouched.

---

## 9. Full-corpus conformance result

**IMPLEMENTATION RESULT** (`WEEK3_IMPLEMENTATION_README.md` §2.10: exact
equality, no tolerances, no percentile-based acceptance).

`tests/router/test_cost_conformance.py::test_full_corpus_conformance`
drove the real compiled router with all **5,000** golden-vector requests
(`scripts/build_cost_golden_vectors.py`'s output, the Python reference run
over the full pinned corpus at `max_tokens=512`) and asserted the three
`X-Request-Cost-*` headers against the golden values.

**Result: 5,000/5,000 exact matches. Zero mismatches, zero missing
headers.**

---

## 10. Edge-case results

**IMPLEMENTATION RESULT.** `tests/router/test_cost_edge_cases.py`, 19
tests, all passing:

- Supported edge cases cross-checked live against the Python reference
  (not hand-computed literals): empty content, Unicode, emoji, mixed
  newlines/tabs, leading/trailing whitespace, plus the corpus's longest
  prompt (`prompt_id 790`, 44,445 chars → 10,482 input tokens) at the
  locked `max_tokens=512` policy — exact match:
  `input_tokens=10482, reserved_tokens=10994, estimated_kv_bytes=1260879872`.
- 10 unsupported-shape variants — see §2.

---

## 11. Negative-control results — all 15 required cases

**IMPLEMENTATION RESULT.** Every control demonstrably bites (raises/fails
when the described bug is injected):

| # | Control | Where | Result |
|---|---|---|---|
| 1 | char count as token count | `test_negative_controls.py::test_control_1` | bites |
| 2 | tokenize without chat-template rendering | `::test_control_2` | bites |
| 3 | wrong tokenizer | `::test_control_3` | bites |
| 4 | altered tokenizer hash | `::test_control_4` | bites |
| 5 | altered chat template | `::test_control_5` | bites |
| 6a | template flags (trim/lstrip_blocks) | `::test_control_6a` | **documented non-divergence** — see below |
| 6b | template flag (`add_generation_prompt`) | `::test_control_6b` | bites |
| 7 | omitted output reservation | `::test_control_7` | bites |
| 8 | `-1` formula substituted | `::test_control_8` (Python) + `router::cost::tests::control_minus_one_formula_diverges_from_the_locked_formula` (Rust) | bites, both languages |
| 9 | `num_attention_heads` instead of `num_key_value_heads` | `::test_control_9` (Python) + `router::cost::tests::control_wrong_head_count_does_not_match_locked_constant` (Rust) | bites, both languages |
| 10 | wrong `head_dim` | `::test_control_10` | bites |
| 11 | wrong KV element width (fp8, fp32) | `::test_control_11` | bites, both widths |
| 12 | MB vs MiB confusion | `::test_control_12` | bites |
| 13 | tampered provenance | `::test_control_13` | bites |
| 14 | unsupported request receiving a cost | `tests/router/test_cost_edge_cases.py::test_control_14_wrong_model_confirms_the_pinned_identity_matters` | bites |
| 15 | cost extraction mutating forwarded bytes | `::test_control_15_forwarded_bytes_are_byte_identical` (supported + unsupported) | bites |

**Real finding from control #6** (not a test-writing shortcut — a fact
about the pinned template): the Llama 3.2 chat template uses Jinja2's
`{%- ... -%}` manual whitespace-control dashes on essentially every block
tag, which fully determines whitespace independent of the rendering
environment's `trim_blocks`/`lstrip_blocks` settings. Confirmed by
`test_control_6a`: rendering the same input with those two flags on vs.
off produces byte-length-identical output. **`trim_blocks`/`lstrip_blocks`
are therefore provably not a viable divergence point for this specific
template** — control 6b (`add_generation_prompt`) is the chat-template
flag that actually matters and does produce a real, demonstrated
divergence.

---

## 12. Request-fidelity and streaming regression results

**IMPLEMENTATION RESULT.** Full `scripts/router_eval.sh` gate, re-run
after all Week 3 changes:

- `cargo test` — 18 passed (default build), 20 passed (`wrong-routers`
  feature), zero failures, both including the new `cost::` module tests.
- The 5 pre-existing Week 1/2 negative controls still bite (S1/S2/O1
  against `WRONG_ROUTER_BUFFERS`, F1 against `WRONG_ROUTER_REEMIT`, F2's
  pass against the same re-emit router).
- The real eval — fidelity (byte-identity, F1/F2), streaming (S1/S2, no
  buffering), overhead (O1), headers/errors (H1, E1, E2) — **40 passed**
  (up from 20: the 19 new edge-case tests + the 1 full-corpus conformance
  test now run in the same bucket), zero failures.
- Overhead delta with cost computation active: **-0.13ms to -0.50ms**
  (small num_tokens / large num_tokens arms) — within noise, not a
  measurable regression against the pre-Week-3 O1 baseline this test
  already gates on.

---

## 13. CPU overhead characterization

**OBSERVED FACT.** `router::cost::tests::characterize_cpu_overhead_by_input_length`
(`cargo test --release -- --ignored --nocapture`) times
`compute_request_cost` directly, in-process (isolated from
network/streaming noise), at five representative corpus points
(min/p50/p90/p99/max `input_tokens`), 200 iterations each:

| Region | prompt_id | input_tokens | min (µs) | mean (µs) | p99 (µs) |
|---|---:|---:|---:|---:|---:|
| min | 61 | 36 | 54 | 61 | 87 |
| p50 | 3242 | 66 | 94 | 98 | 145 |
| p90 | 536 | 594 | 715 | 1,266 | 2,362 |
| p99 | 77 | 2,691 | 3,455 | 4,648 | 7,813 |
| max | 790 | 10,482 | 14,027 | 17,841 | 28,060 |

**Not pathological** — even the single longest prompt in the entire
5,000-row corpus costs ~14–18ms of CPU time, far under the 500ms p99 TTFT
SLO `BASELINE.md` measures against, and the p99 region (2,691 tokens)
costs under 5ms mean. Scaling is roughly linear in input length, as
expected for tokenization + template rendering.

**Risk flagged for Week 4, not fixed here** (README §W3-5: "detect
pathological request-path overhead before Week 4," not fix it):
`compute_request_cost` runs synchronously inside the async `proxy()`
handler with no `spawn_blocking` — for the longest prompts (tens of
milliseconds), this blocks the tokio worker thread handling that request
for the duration, potentially delaying other requests scheduled on the
same worker under concurrent load. Not measured here (CPU-only, single
request at a time, per §9 constraint); worth a look if Week 4 routing
experiments show unexplained tail-latency correlation with prompt length.

---

## 14. Cost-distribution characterization

**DERIVED VALUE.** `scripts/characterize_cost_distribution.py`, full
5,000-row corpus, nearest-rank percentile (Week 2's locked convention,
`metrics.percentile.percentile_nearest_rank` — not a new convention
invented for Week 3):

| Field | min | p50 | p90 | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|---:|
| `input_tokens` | 36 | 66 | 593 | 1,185 | 2,672 | 10,482 |
| `reserved_tokens` | 548 | 578 | 1,105 | 1,697 | 3,184 | 10,994 |
| `estimated_kv_bytes` | 62,849,024 | 66,289,664 | 126,730,240 | 194,625,536 | 365,166,592 | 1,260,879,872 |

Computed at the locked `max_output_tokens=512` policy. Written to
`benchmarks/workloads/week3_cost/cost_distribution.v1.json`.

**Deliberately does not define short/medium/long KV-cost strata**
(`WEEK3_IMPLEMENTATION_README.md` §W3-5: do not silently reuse Week 2's
character-based strata as KV-cost strata). Any such banding is a
separate Week 4 decision.

---

## 15. Explicit limitations of `estimated_kv_bytes`

**LOCKED DESIGN DECISION**, restated from
`WEEK3_KV_REQUEST_COST_INVESTIGATION_REPORT.md` §9–§10 and confirmed
unchanged by implementation:

> `estimated_kv_bytes` is a conservative logical upper bound on the K/V
> tensor storage a request could require, computed from `input_tokens +
> max_output_tokens` under the pinned model's KV tensor shape and the
> serving configuration's effective KV-cache element dtype. It is exact
> when `max_output_tokens = 0` and over-estimates true peak logical KV
> occupancy by exactly one token's worth of storage otherwise.

It is **not**: actual instantaneous GPU memory consumption, vLLM block
allocation, physical allocator reservation, fragmentation-adjusted memory
usage, scheduler state, continuous-batching behavior, prefix-cache
sharing, preemption/swap behavior, latency prediction, queueing
prediction, or exact free-capacity measurement. Legitimate Week 4 uses:
relative request-cost ranking, conservative per-request demand signal,
routing input, potential future admission-control input paired with a
separately defined capacity model.

---

## 16. Week 2 semantics confirmed unchanged

**IMPLEMENTATION RESULT**, proven by test rather than asserted by prose:

- `tests/cost_model/test_legacy_compatibility.py` — `prompt_len` in a real
  Week 2 raw log remains an integer character count; the six-field raw-log
  schema is unchanged; `metrics/artifacts.py`'s `ARTIFACT_SUFFIXES` is
  unchanged; `corpus/baseline_prompts.jsonl`'s row shape is unchanged
  (5,000 rows, `char_len == len(text)`).
- `git diff` against `main` touches no file under `benchmarks/evidence/`,
  `benchmarks/workloads/week2_headline/`, or `corpus/` — Week 2's
  committed artifacts are byte-identical to before Week 3.
- `BASELINE.md`, `docs/adr/0002-*.md`'s Decision text, and Week 2's launch
  script (`scripts/gpu_session/setup_and_launch_vllm.sh`) are unmodified
  (ADR 0002 gained one parenthetical in its Decision section — see below
  — a clarification, not a rewrite).

---

## 17. ADR 0002 — clarification applied

Per the investigation report §11's proposal, `docs/adr/0002-kv-aware-routing-worst-case-estimate.md`'s
Decision section now reads (one added parenthetical, no other change):

> "...It does not model vLLM's internal scheduler, prefix caching, or
> preemption behavior. (This bound is one token more conservative than
> the true per-request KV-token maximum, a deliberate and inexpensive
> slack — see the Week 3 investigation,
> `WEEK3_KV_REQUEST_COST_INVESTIGATION_REPORT.md` section 7.)"

ADR 0002's core decision is **confirmed, not invalidated or replaced**.

---

## 18. Week 4 handoff — what carries forward

1. **Explicit `--kv-cache-dtype bfloat16` pin required for Week 4+
   serving**, with startup/preflight verification that the effective
   resolved dtype matches (§4 above). Week 2 remains historically
   unchanged.
2. **Week 4 routing consumes `RequestCost` only** — `input_tokens`,
   `max_output_tokens`, `reserved_tokens`, `estimated_kv_bytes` — and must
   not need tokenizer internals, chat-template internals, model
   architecture constants, or the KV-byte formula itself
   (`WEEK3_IMPLEMENTATION_README.md` §10). The Rust interface is
   `router::cost::compute_request_cost` / `router::cost::RequestCost`;
   nothing about how it's computed is Week 4's concern.
3. **The synchronous-tokenization risk flagged in §13** is unresolved and
   worth a look if long-prompt tail latency becomes visible under Week 4
   concurrency.
4. **No short/medium/long KV-cost strata exist yet** (§14) — define and
   document any such banding separately before locking it, rather than
   reusing Week 2's character-based strata.

---

## Completion checklist (`WEEK3_IMPLEMENTATION_README.md` §11)

- [x] benchmark-exact request contract frozen (`WEEK3_COST_CONTRACT.md` §1)
- [x] unsupported-request fail-closed behavior frozen (§2)
- [x] tokenizer/template authority pinned (§3, reused from Week 2)
- [x] model config hash-pinned (§3, new: `scripts/fetch_model_config.py`)
- [x] provenance manifest versioned (§5)
- [x] request-cost formula implemented exactly as locked (§1, §7, §8)
- [x] `logical_kv_bytes_per_token = 114,688` derived from provenance, not hardcoded (§1, §5)
- [x] runtime `RequestCost` interface implemented (§5, §8)
- [x] versioned request-cost sidecar schema defined (§6) — owned by `loadgen`, not yet wired into a live benchmark run (no Week 4 benchmark exists yet to generate one)
- [x] Week 2 `prompt_len` semantics preserved (§16)
- [x] Rust tokenizer/template semantics match Python reference (§9 — exact, 5,000/5,000)
- [x] full pinned corpus exact conformance passes (§9)
- [x] edge cases pass (§10)
- [x] all required negative controls bite (§11)
- [x] request forwarding remains byte-faithful (§2, §11 control #15, §12)
- [x] streaming regressions remain green (§12)
- [x] CPU request-cost overhead characterized (§13)
- [x] token/KV-cost distribution characterized (§14)
- [x] final Week 3 evidence package written (this document)
- [x] Week 4 BF16 explicit-pin requirement documented (§4, §18)
- [x] Week 4 BF16 startup verification requirement documented (§4, §18)
- [x] project status updated to Week 3 closed / Week 4 ready (`STATUS.md`)

**`W3-CLOSED` hard stop: satisfied.** For every supported request,
LLMRouter deterministically computes the exact rendered-input token count
under the pinned tokenizer/template identity, reserves the full permitted
output budget, converts the reservation into the locked conservative
logical KV-cost estimate, and exposes that signal through a stable
runtime contract. The Rust runtime agrees exactly with the Python
reference over the full pinned corpus and required edge cases, all
required negative controls bite, and historical Week 2 semantics remain
unchanged.

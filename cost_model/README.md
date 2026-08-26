# cost_model

Python reference ("oracle") implementation of the Week 3 request-cost
signal — `input_tokens`, `max_output_tokens`, `reserved_tokens`,
`estimated_kv_bytes`. See `WEEK3_COST_CONTRACT.md` (repo root) for the
frozen interfaces this module implements, and
`WEEK3_KV_REQUEST_COST_INVESTIGATION_REPORT.md` for the formula derivation
and hash-verified evidence behind the constants it reads. This is the
oracle the Rust runtime (`router/src/cost/`) must agree with exactly, over
the full pinned corpus plus edge cases (`WEEK3_IMPLEMENTATION_README.md`
§2.10 — no tolerances).

## Files

| File | Role |
|---|---|
| `types.py` | `RequestCost`, `RequestCostProvenance`, `RequestCostError` taxonomy, version constants. Pure data + (de)serialization, no formula logic. |
| `tokenizer.py` | Pinned-tokenizer loading and chat-template rendering. Refactored out of `scripts/check_tokenizer_capacity.py` (Week 2) so the two paths can never silently drift apart. |
| `reference.py` | `validate_supported_request` (the frozen contract check) and `compute_request_cost` (the formula itself). `load_reference_context` bundles a loaded tokenizer/renderer/provenance for batch use. |

## Provenance chain

Nothing in this module hard-codes an architecture constant. The chain is:

```text
scripts/fetch_tokenizer.py      -> .tokenizer_cache/.../PROVENANCE.json
scripts/fetch_model_config.py   -> .model_config_cache/.../PROVENANCE.json
scripts/build_cost_provenance.py -> benchmarks/workloads/week3_cost/request_cost_provenance.v1.json
```

`RequestCostProvenance.from_frozen()` reads only the last file. Re-running
`build_cost_provenance.py` after either cache changes regenerates it; the
two `fetch_*` scripts refuse to run against anything not byte-proven
identical to the pinned gated Hugging Face repo (git-blob-SHA1 comparison
against the public metadata API — see either script's docstring).

## The one hard-coded, documented exception

`scripts/build_cost_provenance.py` records `effective_kv_cache_dtype =
"bfloat16"` as a **locked design decision**, not a live re-derivation: it
is a recorded fact about a specific historical GPU session
(`benchmarks/evidence/week2/session_2/vllm.log`), established by
reproducing vLLM's own logged KV-cache-memory figure to the byte
(investigation report §6). Week 4+ serving additionally pins and verifies
this at server startup (`WEEK3_IMPLEMENTATION_README.md` §2.8) — this
module does not verify a live server.

## Formula

```text
reserved_tokens    = input_tokens + max_output_tokens
estimated_kv_bytes = reserved_tokens * logical_kv_bytes_per_token
```

Deliberately **not** `input_tokens + max_output_tokens - 1`, even though
the investigation found that to be the exact logical-KV-occupancy boundary
for `max_output_tokens >= 1` — the one-token slack is documented intentional
conservatism (`WEEK3_IMPLEMENTATION_README.md` §2.5), not an error to
optimize away. `tests/cost_model/test_negative_controls.py` control #8
exists specifically to prove the `-1` formula is *not* what ships.

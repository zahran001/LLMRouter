#!/usr/bin/env python
"""Build the Week 3 cost-model provenance manifest (WEEK3_COST_CONTRACT.md
section 5, `WEEK3_IMPLEMENTATION_README.md` section 4).

Reads the two independently hash-verified caches this repo already
maintains --

    .tokenizer_cache/meta-llama__Llama-3.2-3B-Instruct/     (scripts/fetch_tokenizer.py)
    .model_config_cache/meta-llama__Llama-3.2-3B-Instruct/  (scripts/fetch_model_config.py)

-- and the locked KV-dtype decision from
`WEEK3_KV_REQUEST_COST_INVESTIGATION_REPORT.md` section 6 (effective Week 2
KV-cache dtype was bfloat16, established by reproducing vLLM's own logged
KV-cache-memory figure to the byte -- not re-derived here, since it is a
recorded observation about a specific historical serving run, not something
this script can measure). Writes the versioned manifest every Python and
Rust cost-model implementation reads.

Every number in the output is either copied from a hash-verified cache file
or is the one locked, documented, non-code-embedded constant
(`effective_kv_cache_dtype`) -- no unexplained magic numbers.

Usage:
    .venv/Scripts/python.exe scripts/build_cost_provenance.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from cost_model.tokenizer import build_renderer, load_tokenizer  # noqa: E402
from cost_model.types import (  # noqa: E402
    COST_MODEL_VERSION,
    DEFAULT_PROVENANCE_PATH,
    FORMULA_VERSION,
    PROVENANCE_SCHEMA_VERSION,
)
from metrics.artifacts import write_json_artifact  # noqa: E402

MODEL_CONFIG_CACHE = REPO_ROOT / ".model_config_cache" / "meta-llama__Llama-3.2-3B-Instruct"
TOKENIZER_CACHE = REPO_ROOT / ".tokenizer_cache" / "meta-llama__Llama-3.2-3B-Instruct"

# LOCKED DESIGN DECISION (WEEK3_KV_REQUEST_COST_INVESTIGATION_REPORT.md
# section 6): Week 2 never set --kv-cache-dtype; vLLM resolved `auto` to
# the model's own dtype (bf16), confirmed by reproducing vLLM's logged
# "Available KV cache memory: 13.87 GiB / GPU KV cache size: 129,888
# tokens" to the byte using exactly this dtype. This is a recorded fact
# about a specific historical serving run (vllm.log), not something this
# script re-derives from a live server.
EFFECTIVE_KV_CACHE_DTYPE = "bfloat16"
BYTES_PER_KV_ELEMENT = 2
VLLM_VERSION = "0.27.1"


def main() -> None:
    if not MODEL_CONFIG_CACHE.exists():
        raise SystemExit(
            f"{MODEL_CONFIG_CACHE} not found -- run scripts/fetch_model_config.py first")

    config_path = MODEL_CONFIG_CACHE / "config.json"
    config_provenance = json.loads((MODEL_CONFIG_CACHE / "PROVENANCE.json").read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))

    tokenizer, tok_config, tok_provenance = load_tokenizer(TOKENIZER_CACHE)
    _render, template_src = build_renderer(tok_config)
    del tokenizer  # only needed to prove it loads; not used for provenance itself

    num_hidden_layers = int(config["num_hidden_layers"])
    num_key_value_heads = int(config["num_key_value_heads"])
    head_dim = int(config["head_dim"])
    logical_kv_bytes_per_token = (
        2 * num_hidden_layers * num_key_value_heads * head_dim * BYTES_PER_KV_ELEMENT
    )

    tok_files = {f["filename"]: f for f in tok_provenance["files"]}
    config_file_record = next(f for f in config_provenance["files"] if f["filename"] == "config.json")

    manifest = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "cost_model_version": COST_MODEL_VERSION,
        "formula_version": FORMULA_VERSION,
        "source_provenance": {
            "model_id": config_provenance["gated_repo"],
            "model_revision": config_provenance["gated_repo_commit"],
            "model_config_sha256": config_file_record["sha256"],
            "tokenizer_sha256": tok_files["tokenizer.json"]["sha256"],
            "tokenizer_config_sha256": tok_files["tokenizer_config.json"]["sha256"],
            "chat_template_sha256": hashlib.sha256(template_src.encode("utf-8")).hexdigest(),
        },
        "derived_architecture": {
            "num_hidden_layers": num_hidden_layers,
            "num_key_value_heads": num_key_value_heads,
            "head_dim": head_dim,
            "logical_kv_bytes_per_token": logical_kv_bytes_per_token,
        },
        "serving_runtime": {
            "effective_kv_cache_dtype": EFFECTIVE_KV_CACHE_DTYPE,
            "bytes_per_kv_element": BYTES_PER_KV_ELEMENT,
            "vllm_version": VLLM_VERSION,
        },
    }

    sha = write_json_artifact(DEFAULT_PROVENANCE_PATH, manifest)

    print(f"model:      {manifest['source_provenance']['model_id']} @ "
          f"{manifest['source_provenance']['model_revision'][:12]}...")
    print(f"config sha256:     {manifest['source_provenance']['model_config_sha256'][:16]}...")
    print(f"tokenizer sha256:  {manifest['source_provenance']['tokenizer_sha256'][:16]}...")
    print(f"num_hidden_layers={num_hidden_layers} num_key_value_heads={num_key_value_heads} "
          f"head_dim={head_dim} bytes_per_kv_element={BYTES_PER_KV_ELEMENT}")
    print(f"logical_kv_bytes_per_token = {logical_kv_bytes_per_token:,} "
          f"({logical_kv_bytes_per_token // 1024} KiB)")
    assert logical_kv_bytes_per_token == 114_688, (
        f"expected 114,688 B/token per the Week 3 investigation, got {logical_kv_bytes_per_token}")
    print(f"\nwritten: {DEFAULT_PROVENANCE_PATH.relative_to(REPO_ROOT)}  sha256={sha[:16]}...")


if __name__ == "__main__":
    main()

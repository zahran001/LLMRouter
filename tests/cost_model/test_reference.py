"""Direct tests of cost_model.reference against the frozen contract
(WEEK3_COST_CONTRACT.md) and against the golden vectors it was used to
generate. Full negative-control coverage (the 15 required cases) is
Phase W3-4's job, against both Python and Rust; this file is a fast
sanity pass on the Python reference alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cost_model.reference import compute_request_cost, load_reference_context, validate_supported_request
from cost_model.types import (
    InvalidMaxTokens,
    MissingMaxTokens,
    UnsupportedShape,
    WrongModel,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_VECTORS = REPO_ROOT / "benchmarks" / "workloads" / "week3_cost" / "golden_vectors.v1.jsonl"


@pytest.fixture(scope="module")
def ctx():
    return load_reference_context()


def _load_golden_rows():
    rows = []
    with GOLDEN_VECTORS.open(encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def test_formula_is_input_plus_max_tokens_never_minus_one(ctx):
    request = {
        "model": ctx.provenance.model_id,
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 100,
    }
    cost = ctx.compute(request)
    assert cost.reserved_tokens == cost.input_tokens + 100
    assert cost.estimated_kv_bytes == cost.reserved_tokens * ctx.provenance.logical_kv_bytes_per_token


def test_provenance_constants_match_the_investigation(ctx):
    assert ctx.provenance.num_hidden_layers == 28
    assert ctx.provenance.num_key_value_heads == 8
    assert ctx.provenance.head_dim == 128
    assert ctx.provenance.bytes_per_kv_element == 2
    assert ctx.provenance.logical_kv_bytes_per_token == 114_688


@pytest.mark.parametrize("row", _load_golden_rows()[:20], ids=lambda r: f"prompt_{r['prompt_id']}")
def test_golden_vector_spot_check(ctx, row):
    """Recompute a sample of golden rows directly -- catches drift between
    the generator script and the reference module itself."""
    from loadgen.corpus import load_corpus

    corpus = load_corpus()
    prompt = next(p for p in corpus.prompts if p.prompt_id == row["prompt_id"])
    request = {
        "model": ctx.provenance.model_id,
        "messages": [{"role": "user", "content": prompt.text}],
        "max_tokens": row["max_output_tokens"],
        "stream": True,
    }
    cost = ctx.compute(request)
    assert cost.input_tokens == row["input_tokens"]
    assert cost.reserved_tokens == row["reserved_tokens"]
    assert cost.estimated_kv_bytes == row["estimated_kv_bytes"]


def test_longest_corpus_prompt_matches_investigation_report(ctx):
    """prompt_id 790, 44,445 chars -> 10,482 input tokens, reserved 10,994,
    1,260,879,872 bytes -- WEEK3_KV_REQUEST_COST_INVESTIGATION_REPORT.md
    section 8, table row 5."""
    from loadgen.corpus import load_corpus

    corpus = load_corpus()
    prompt = next(p for p in corpus.prompts if p.prompt_id == 790)
    request = {
        "model": ctx.provenance.model_id,
        "messages": [{"role": "user", "content": prompt.text}],
        "max_tokens": 512,
    }
    cost = ctx.compute(request)
    assert cost.input_tokens == 10482
    assert cost.reserved_tokens == 10994
    assert cost.estimated_kv_bytes == 1_260_879_872


# ---------------------------------------------------------------------------
# Error taxonomy -- each must fail closed, never produce a partial/approximate cost.
# ---------------------------------------------------------------------------

PINNED_MODEL = "meta-llama/Llama-3.2-3B-Instruct"
GOOD = {"model": PINNED_MODEL, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 10}


def test_missing_max_tokens_is_rejected():
    bad = {k: v for k, v in GOOD.items() if k != "max_tokens"}
    with pytest.raises(MissingMaxTokens):
        validate_supported_request(bad, pinned_model_id=PINNED_MODEL)


@pytest.mark.parametrize("bad_value", [0, -1, "512", 1.5, True])
def test_invalid_max_tokens_is_rejected(bad_value):
    bad = {**GOOD, "max_tokens": bad_value}
    with pytest.raises(InvalidMaxTokens):
        validate_supported_request(bad, pinned_model_id=PINNED_MODEL)


def test_wrong_model_is_rejected():
    bad = {**GOOD, "model": "some-other-model"}
    with pytest.raises(WrongModel):
        validate_supported_request(bad, pinned_model_id=PINNED_MODEL)


def test_extra_top_level_field_is_rejected():
    bad = {**GOOD, "tools": []}
    with pytest.raises(UnsupportedShape):
        validate_supported_request(bad, pinned_model_id=PINNED_MODEL)


def test_multiple_messages_is_rejected():
    bad = {**GOOD, "messages": [GOOD["messages"][0], GOOD["messages"][0]]}
    with pytest.raises(UnsupportedShape):
        validate_supported_request(bad, pinned_model_id=PINNED_MODEL)


def test_non_user_role_is_rejected():
    bad = {**GOOD, "messages": [{"role": "system", "content": "hi"}]}
    with pytest.raises(UnsupportedShape):
        validate_supported_request(bad, pinned_model_id=PINNED_MODEL)


def test_multimodal_content_is_rejected():
    """content as a list of parts (the multimodal shape) must not be
    accepted as if it were plain text."""
    bad = {**GOOD, "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]}
    with pytest.raises(UnsupportedShape):
        validate_supported_request(bad, pinned_model_id=PINNED_MODEL)


def test_good_request_validates_cleanly():
    validate_supported_request(GOOD, pinned_model_id=PINNED_MODEL)  # must not raise

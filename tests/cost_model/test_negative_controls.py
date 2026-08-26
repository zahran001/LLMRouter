"""Week 3 negative controls (WEEK3_IMPLEMENTATION_README.md section 6
W3-4, controls #1-13; #14-15 live in tests/router/test_cost_edge_cases.py
since they need a real compiled router).

Each test deliberately breaks one thing the real request-cost path depends
on and asserts the SAME assertion helper the real conformance check uses
(_assertions.assert_matches_golden) goes RED against it -- this repo's
established negative-control pattern
(tests/loadgen/test_negative_controls.py, tests/eval/test_negative_controls.py).
A negative control that silently starts passing is itself a bug: it means
the thing it was supposed to guard stopped mattering.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from cost_model.reference import load_reference_context  # noqa: E402
from cost_model.tokenizer import DEFAULT_TOKENIZER_CACHE, build_renderer, load_tokenizer  # noqa: E402
from cost_model.types import RequestCost, RequestCostProvenance  # noqa: E402
from loadgen.corpus import load_corpus  # noqa: E402

from tests.cost_model._assertions import assert_matches_golden  # noqa: E402

pytestmark = pytest.mark.negative_control

PINNED_MODEL = "meta-llama/Llama-3.2-3B-Instruct"
GOLDEN_VECTORS = REPO_ROOT / "benchmarks" / "workloads" / "week3_cost" / "golden_vectors.v1.jsonl"


@pytest.fixture(scope="module")
def ref():
    return load_reference_context()


@pytest.fixture(scope="module")
def sample_case(ref):
    """A single golden-vector case (the corpus's longest prompt, prompt_id
    790) reused across most controls below -- large enough that a wrong
    formula's divergence is never accidentally within rounding of the
    correct answer."""
    corpus = load_corpus()
    prompt = next(p for p in corpus.prompts if p.prompt_id == 790)
    golden = None
    with GOLDEN_VECTORS.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["prompt_id"] == 790:
                golden = row
                break
    assert golden is not None
    return prompt, golden


# ---------------------------------------------------------------------------
# Sanity: the real reference passes its own check first. A control that
# breaks a check which was never green proves nothing.
# ---------------------------------------------------------------------------


def test_sanity_real_reference_matches_golden(ref, sample_case):
    prompt, golden = sample_case
    body = {"model": PINNED_MODEL, "messages": [{"role": "user", "content": prompt.text}],
            "max_tokens": golden["max_output_tokens"]}
    assert_matches_golden(ref.compute(body), golden)


# ---------------------------------------------------------------------------
# #1: character count mislabeled as token count.
# ---------------------------------------------------------------------------


def test_control_1_char_count_as_token_count(sample_case):
    prompt, golden = sample_case
    wrong_input_tokens = len(prompt.text)  # the bug: chars, not tokens
    wrong_reserved = wrong_input_tokens + golden["max_output_tokens"]
    wrong = RequestCost(
        input_tokens=wrong_input_tokens,
        max_output_tokens=golden["max_output_tokens"],
        reserved_tokens=wrong_reserved,
        estimated_kv_bytes=wrong_reserved * 114_688,
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(wrong, golden)


# ---------------------------------------------------------------------------
# #2: raw prompt tokenization without chat-template rendering.
# ---------------------------------------------------------------------------


def test_control_2_skips_chat_template_rendering(ref, sample_case):
    prompt, golden = sample_case
    # The bug: tokenize the bare prompt text, never call render().
    wrong_input_tokens = len(ref.tokenizer.encode(prompt.text, add_special_tokens=False).ids)
    wrong_reserved = wrong_input_tokens + golden["max_output_tokens"]
    wrong = RequestCost(
        input_tokens=wrong_input_tokens,
        max_output_tokens=golden["max_output_tokens"],
        reserved_tokens=wrong_reserved,
        estimated_kv_bytes=wrong_reserved * 114_688,
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(wrong, golden)


# ---------------------------------------------------------------------------
# #3: wrong tokenizer.
# ---------------------------------------------------------------------------


def test_control_3_wrong_tokenizer(ref, sample_case):
    prompt, golden = sample_case
    rendered = ref.render(prompt.text)
    # The bug: a real but different tokenization scheme (whitespace
    # splitting) standing in for the pinned BPE tokenizer.
    wrong_input_tokens = len(rendered.split())
    assert wrong_input_tokens != golden["input_tokens"], (
        "test setup bug: whitespace-split happened to match the real tokenizer's count"
    )
    wrong_reserved = wrong_input_tokens + golden["max_output_tokens"]
    wrong = RequestCost(
        input_tokens=wrong_input_tokens,
        max_output_tokens=golden["max_output_tokens"],
        reserved_tokens=wrong_reserved,
        estimated_kv_bytes=wrong_reserved * 114_688,
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(wrong, golden)


# ---------------------------------------------------------------------------
# #4: altered tokenizer revision/hash.
# ---------------------------------------------------------------------------


def test_control_4_altered_tokenizer_hash_is_detected(ref):
    real_bytes = (DEFAULT_TOKENIZER_CACHE / "tokenizer.json").read_bytes()
    real_sha256 = hashlib.sha256(real_bytes).hexdigest()
    assert real_sha256 == ref.provenance.tokenizer_sha256, (
        "sanity: the committed provenance manifest must match the cached tokenizer file"
    )

    tampered_sha256 = hashlib.sha256(real_bytes + b"\x00").hexdigest()  # the bug: drifted file
    with pytest.raises(AssertionError):
        assert tampered_sha256 == ref.provenance.tokenizer_sha256, (
            "a tampered tokenizer file must not appear to match the pinned provenance hash"
        )


# ---------------------------------------------------------------------------
# #5: altered chat template.
# ---------------------------------------------------------------------------


def test_control_5_altered_chat_template_changes_token_count(sample_case):
    prompt, golden = sample_case
    tokenizer, tok_config, _prov = load_tokenizer(DEFAULT_TOKENIZER_CACHE)
    real_render, real_template_src = build_renderer(tok_config)

    # The bug: template text altered (a stray literal character injected).
    tampered_config = dict(tok_config)
    tampered_config["chat_template"] = "TAMPERED " + tok_config["chat_template"]
    tampered_render, tampered_template_src = build_renderer(tampered_config)

    assert tampered_template_src != real_template_src
    wrong_input_tokens = len(
        tokenizer.encode(tampered_render(prompt.text), add_special_tokens=False).ids
    )
    wrong_reserved = wrong_input_tokens + golden["max_output_tokens"]
    wrong = RequestCost(
        input_tokens=wrong_input_tokens,
        max_output_tokens=golden["max_output_tokens"],
        reserved_tokens=wrong_reserved,
        estimated_kv_bytes=wrong_reserved * 114_688,
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(wrong, golden)


# ---------------------------------------------------------------------------
# #6: incorrect chat-template flags.
#
# Note: trim_blocks/lstrip_blocks turn out NOT to be a viable divergence
# point for THIS pinned template -- investigated and confirmed below in
# test_control_6a. The Llama 3.2 template uses Jinja2's manual `{%- ... -%}`
# whitespace-control dashes on essentially every block tag, which fully
# determines whitespace independent of the environment's trim_blocks/
# lstrip_blocks settings -- so those two settings are provably redundant
# for this specific template (real finding, not a test gap). The flag that
# DOES matter is `add_generation_prompt`, which is exercised in
# test_control_6b below.
# ---------------------------------------------------------------------------


def test_control_6a_trim_lstrip_blocks_are_redundant_for_this_template(ref):
    """Documents the finding above rather than asserting something false:
    render()'s trim_blocks/lstrip_blocks flags produce byte-length-identical
    output for the pinned template because it already dash-controls
    whitespace itself on every block tag."""
    import jinja2

    _tokenizer, tok_config, _prov = load_tokenizer(DEFAULT_TOKENIZER_CACHE)
    template_src = tok_config["chat_template"]
    bos = tok_config.get("bos_token", "<|begin_of_text|>")

    def render_with(trim_blocks: bool, lstrip_blocks: bool) -> str:
        env = jinja2.Environment(trim_blocks=trim_blocks, lstrip_blocks=lstrip_blocks)
        env.globals["raise_exception"] = lambda msg: (_ for _ in ()).throw(RuntimeError(msg))
        env.globals["strftime_now"] = lambda fmt: "FIXED_DATE"  # neutralize the one real time-of-day variable
        template = env.from_string(template_src)
        return template.render(
            messages=[{"role": "user", "content": "hello world"}],
            add_generation_prompt=True, bos_token=bos,
        )

    correct = render_with(True, True)
    flags_off = render_with(False, False)
    assert len(correct) == len(flags_off), (
        "trim_blocks/lstrip_blocks stopped being redundant for this template -- if this fails, "
        "the template changed and test_control_6 needs a real divergence test added back"
    )


def test_control_6b_wrong_add_generation_prompt_flag(ref, sample_case):
    """The chat-template flag that actually matters: add_generation_prompt.
    Omitting the assistant-turn generation prompt suffix
    (<|start_header_id|>assistant<|end_header_id|>\\n\\n) undercounts
    input_tokens by exactly that suffix's token length."""
    prompt, golden = sample_case
    # Re-render with add_generation_prompt=False via the same tokenizer/
    # template the reference uses, bypassing render()'s hardcoded True.
    tokenizer, tok_config, _prov = load_tokenizer(DEFAULT_TOKENIZER_CACHE)
    import jinja2

    env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
    env.globals["raise_exception"] = lambda msg: (_ for _ in ()).throw(RuntimeError(msg))
    env.globals["strftime_now"] = lambda fmt: __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).strftime(fmt)
    template = env.from_string(tok_config["chat_template"])
    bos = tok_config.get("bos_token", "<|begin_of_text|>")

    wrong_rendered = template.render(
        messages=[{"role": "user", "content": prompt.text}],
        add_generation_prompt=False,  # the bug
        bos_token=bos,
    )
    wrong_input_tokens = len(tokenizer.encode(wrong_rendered, add_special_tokens=False).ids)
    wrong_reserved = wrong_input_tokens + golden["max_output_tokens"]
    wrong = RequestCost(
        input_tokens=wrong_input_tokens,
        max_output_tokens=golden["max_output_tokens"],
        reserved_tokens=wrong_reserved,
        estimated_kv_bytes=wrong_reserved * 114_688,
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(wrong, golden)


# ---------------------------------------------------------------------------
# #7: omitted max_output_tokens reservation.
# ---------------------------------------------------------------------------


def test_control_7_omits_output_reservation(sample_case):
    _prompt, golden = sample_case
    # The bug: reserved_tokens = input_tokens only.
    wrong_reserved = golden["input_tokens"]
    wrong = RequestCost(
        input_tokens=golden["input_tokens"],
        max_output_tokens=golden["max_output_tokens"],
        reserved_tokens=wrong_reserved,
        estimated_kv_bytes=wrong_reserved * 114_688,
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(wrong, golden)


# ---------------------------------------------------------------------------
# #8: the `-1` formula substituted for the locked reservation contract.
# ---------------------------------------------------------------------------


def test_control_8_minus_one_formula_forbidden(sample_case):
    """WEEK3_IMPLEMENTATION_README.md section 2.5: 'Do not introduce a -1
    adjustment into the authoritative formula.' This proves the -1 formula
    -- even though it is the exact logical-KV boundary per the Week 3
    investigation -- is NOT what the locked contract produces."""
    _prompt, golden = sample_case
    wrong_reserved = golden["input_tokens"] + golden["max_output_tokens"] - 1
    wrong = RequestCost(
        input_tokens=golden["input_tokens"],
        max_output_tokens=golden["max_output_tokens"],
        reserved_tokens=wrong_reserved,
        estimated_kv_bytes=wrong_reserved * 114_688,
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(wrong, golden)


# ---------------------------------------------------------------------------
# #9: num_attention_heads (24) instead of num_key_value_heads (8).
# ---------------------------------------------------------------------------


def test_control_9_wrong_head_count(ref, sample_case):
    _prompt, golden = sample_case
    num_hidden_layers = ref.provenance.num_hidden_layers
    num_attention_heads_wrong = 24  # should be num_key_value_heads = 8
    head_dim = ref.provenance.head_dim
    bytes_per_kv_element = ref.provenance.bytes_per_kv_element

    wrong_bytes_per_token = 2 * num_hidden_layers * num_attention_heads_wrong * head_dim * bytes_per_kv_element
    assert wrong_bytes_per_token != ref.provenance.logical_kv_bytes_per_token

    wrong_reserved = golden["reserved_tokens"]
    wrong = RequestCost(
        input_tokens=golden["input_tokens"],
        max_output_tokens=golden["max_output_tokens"],
        reserved_tokens=wrong_reserved,
        estimated_kv_bytes=wrong_reserved * wrong_bytes_per_token,
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(wrong, golden)


# ---------------------------------------------------------------------------
# #10: wrong head_dim.
# ---------------------------------------------------------------------------


def test_control_10_wrong_head_dim(ref, sample_case):
    _prompt, golden = sample_case
    wrong_head_dim = 96  # should be 128 (explicit in config.json)
    wrong_bytes_per_token = (
        2 * ref.provenance.num_hidden_layers * ref.provenance.num_key_value_heads
        * wrong_head_dim * ref.provenance.bytes_per_kv_element
    )
    assert wrong_bytes_per_token != ref.provenance.logical_kv_bytes_per_token

    wrong_reserved = golden["reserved_tokens"]
    wrong = RequestCost(
        input_tokens=golden["input_tokens"],
        max_output_tokens=golden["max_output_tokens"],
        reserved_tokens=wrong_reserved,
        estimated_kv_bytes=wrong_reserved * wrong_bytes_per_token,
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(wrong, golden)


# ---------------------------------------------------------------------------
# #11: wrong KV dtype / element width.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wrong_bytes_per_element", [1, 4], ids=["fp8", "fp32"])
def test_control_11_wrong_kv_element_width(ref, sample_case, wrong_bytes_per_element):
    _prompt, golden = sample_case
    wrong_bytes_per_token = (
        2 * ref.provenance.num_hidden_layers * ref.provenance.num_key_value_heads
        * ref.provenance.head_dim * wrong_bytes_per_element
    )
    assert wrong_bytes_per_token != ref.provenance.logical_kv_bytes_per_token

    wrong_reserved = golden["reserved_tokens"]
    wrong = RequestCost(
        input_tokens=golden["input_tokens"],
        max_output_tokens=golden["max_output_tokens"],
        reserved_tokens=wrong_reserved,
        estimated_kv_bytes=wrong_reserved * wrong_bytes_per_token,
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(wrong, golden)


# ---------------------------------------------------------------------------
# #12: wrong byte units (MB vs MiB).
# ---------------------------------------------------------------------------


def test_control_12_mb_vs_mib_confusion(sample_case):
    """WEEK3_KV_REQUEST_COST_INVESTIGATION_REPORT.md section 8: units are
    powers of 1024 (KiB/MiB/GiB), never powers of 1000. Confirms the two
    conventions actually diverge for a real value -- prompt_id 790's
    1,260,879,872 bytes is 1,202.46875 MiB but 1,260.879872 (decimal) MB."""
    _prompt, golden = sample_case
    estimated_kv_bytes = golden["estimated_kv_bytes"]

    correct_mib = estimated_kv_bytes / (1024 * 1024)
    wrong_mb = estimated_kv_bytes / (1000 * 1000)  # the bug: decimal MB

    assert correct_mib == pytest.approx(1202.46875, abs=1e-6)
    with pytest.raises(AssertionError):
        assert wrong_mb == pytest.approx(correct_mib, abs=1e-6), (
            "MB (decimal) and MiB (binary) must not be treated as interchangeable"
        )


# ---------------------------------------------------------------------------
# #13: runtime/provenance mismatch -- provenance values must be load-bearing.
# ---------------------------------------------------------------------------


def test_control_13_tampered_provenance_changes_the_result(ref, sample_case):
    """If logical_kv_bytes_per_token were hardcoded instead of read from
    the provenance manifest, swapping in a tampered provenance would have
    no effect on the computed cost. It must have an effect."""
    prompt, golden = sample_case
    tampered_provenance = dataclasses.replace(
        ref.provenance, logical_kv_bytes_per_token=ref.provenance.logical_kv_bytes_per_token + 1
    )
    assert tampered_provenance.logical_kv_bytes_per_token != ref.provenance.logical_kv_bytes_per_token

    from cost_model.reference import compute_request_cost

    body = {"model": PINNED_MODEL, "messages": [{"role": "user", "content": prompt.text}],
            "max_tokens": golden["max_output_tokens"]}
    tampered_cost = compute_request_cost(
        body, tokenizer=ref.tokenizer, render=ref.render, provenance=tampered_provenance
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(tampered_cost, golden)

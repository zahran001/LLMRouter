"""Week 3 request-cost edge cases and the two negative controls that need a
live, compiled router rather than the Python reference alone
(WEEK3_IMPLEMENTATION_README.md section 6 W3-4):

  #14 an unsupported request must never receive a cost (no
      X-Request-Cost-* headers), while still being proxied through
      byte-identically -- WEEK3_COST_CONTRACT.md section 2.
  #15 request-cost extraction must never mutate the forwarded request
      bytes -- proven via the mock's `echo_body` debug affordance
      (mock/app.py, added for exactly this purpose), which returns the
      raw bytes it received, not a JSON round-trip.

Everything else here (empty content, Unicode/emoji, the longest corpus
prompt, malformed fields) is cross-checked against the live Python
reference computed for the same request, not hand-computed literals.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from cost_model.reference import load_reference_context  # noqa: E402
from cost_model.types import RequestCostError  # noqa: E402
from loadgen.corpus import load_corpus  # noqa: E402

pytestmark = pytest.mark.router

PINNED_MODEL = "meta-llama/Llama-3.2-3B-Instruct"
COST_HEADERS = (
    "x-request-cost-input-tokens",
    "x-request-cost-reserved-tokens",
    "x-request-cost-estimated-kv-bytes",
)


@pytest.fixture(scope="module")
def ref():
    return load_reference_context()


def _post_and_get_cost_headers(router_base_url: str, body: dict) -> dict | None:
    """POST body, return the three cost headers as ints if all present, else
    None. Closes without draining the SSE body (only headers matter here)."""
    with httpx.Client(timeout=10.0) as client:
        with client.stream("POST", f"{router_base_url}/v1/chat/completions", json=body) as resp:
            headers = resp.headers
            if not all(h in headers for h in COST_HEADERS):
                assert not any(h in headers for h in COST_HEADERS), (
                    f"partial cost headers present -- must be all-or-nothing: {dict(headers)}"
                )
                return None
            return {
                "input_tokens": int(headers["x-request-cost-input-tokens"]),
                "reserved_tokens": int(headers["x-request-cost-reserved-tokens"]),
                "estimated_kv_bytes": int(headers["x-request-cost-estimated-kv-bytes"]),
            }


# ---------------------------------------------------------------------------
# Supported edge cases -- cross-checked against the live Python reference.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("content,max_tokens", [
    ("", 10),
    ("héllo wörld — em dash, ünïcödé", 10),
    ("🎉🚀🔥 emoji only", 10),
    ("line one\nline two\n\nline four\ttabbed", 10),
    ("   leading and trailing whitespace   ", 10),
], ids=["empty", "unicode", "emoji", "newlines_tabs", "whitespace"])
def test_supported_edge_case_matches_python_reference(router_base_url, ref, content, max_tokens):
    body = {"model": PINNED_MODEL, "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens, "stream": True}
    expected = ref.compute(body)
    got = _post_and_get_cost_headers(router_base_url, body)
    assert got is not None, f"expected a cost for a supported edge case: {content!r}"
    assert got == {
        "input_tokens": expected.input_tokens,
        "reserved_tokens": expected.reserved_tokens,
        "estimated_kv_bytes": expected.estimated_kv_bytes,
    }


def test_longest_corpus_prompt_at_boundary_max_tokens(router_base_url, ref):
    """prompt_id 790, the corpus's longest prompt, at the --max-model-len
    boundary this session's tokenizer_capacity_report.json already proved
    fits (WEEK2 R4B: 10,482 input + up to margin)."""
    corpus = load_corpus()
    prompt = next(p for p in corpus.prompts if p.prompt_id == 790)
    body = {"model": PINNED_MODEL, "messages": [{"role": "user", "content": prompt.text}],
            "max_tokens": 512, "stream": True}
    expected = ref.compute(body)
    got = _post_and_get_cost_headers(router_base_url, body)
    assert got == {
        "input_tokens": expected.input_tokens,
        "reserved_tokens": expected.reserved_tokens,
        "estimated_kv_bytes": expected.estimated_kv_bytes,
    }
    assert got["input_tokens"] == 10482
    assert got["reserved_tokens"] == 10994
    assert got["estimated_kv_bytes"] == 1_260_879_872


# ---------------------------------------------------------------------------
# Unsupported shapes -- must never receive a cost, must still be proxied.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    {"model": PINNED_MODEL, "messages": [{"role": "user", "content": "hi"}]},  # missing max_tokens
    {"model": PINNED_MODEL, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 0},
    {"model": PINNED_MODEL, "messages": [{"role": "user", "content": "hi"}], "max_tokens": -5},
    {"model": "wrong-model", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 10},
    {"model": PINNED_MODEL, "messages": [], "max_tokens": 10},
    {"model": PINNED_MODEL, "messages": [{"role": "user", "content": "hi"}, {"role": "user", "content": "hi"}], "max_tokens": 10},
    {"model": PINNED_MODEL, "messages": [{"role": "system", "content": "hi"}], "max_tokens": 10},
    {"model": PINNED_MODEL, "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}], "max_tokens": 10},
    {"model": PINNED_MODEL, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 10, "tools": []},
    {"not_json_at_all": True},
], ids=[
    "missing_max_tokens", "zero_max_tokens", "negative_max_tokens", "wrong_model",
    "empty_messages", "two_messages", "system_role", "multimodal_content",
    "tools_present", "extra_and_no_required_fields",
])
def test_unsupported_shape_receives_no_cost_but_still_proxies(router_base_url, body):
    with httpx.Client(timeout=10.0) as client:
        with client.stream("POST", f"{router_base_url}/v1/chat/completions", json=body) as resp:
            status = resp.status_code
            headers = resp.headers

    assert not any(h in headers for h in COST_HEADERS), (
        f"unsupported request received a cost -- fail-closed contract violated: {body}"
    )
    # WEEK3_COST_CONTRACT.md section 2: proxy behavior is unchanged for an
    # unsupported request. The mock always answers 200 for any JSON body it
    # can parse (or an empty dict if it can't parse content-length 0/absent),
    # so this would only be non-200 if the router itself started rejecting
    # the request -- which it must not.
    assert status == 200, f"unsupported request changed router HTTP behavior: got {status}"


def test_control_14_wrong_model_confirms_the_pinned_identity_matters(router_base_url, ref):
    """If validate_supported_request's model check were a no-op, this
    wrong-model request would receive a cost. It must not."""
    body = {"model": "meta-llama/Llama-3.1-8B-Instruct",
            "messages": [{"role": "user", "content": "hi"}], "max_tokens": 10}
    with pytest.raises(RequestCostError):
        ref.compute(body)  # Python reference must also reject it
    got = _post_and_get_cost_headers(router_base_url, body)
    assert got is None


# ---------------------------------------------------------------------------
# #15: request-cost extraction must not mutate forwarded bytes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("body_obj", [
    {"model": PINNED_MODEL, "messages": [{"role": "user", "content": "byte fidelity check"}],
     "max_tokens": 10, "stream": True},
    # Unsupported shape too -- byte-fidelity must hold regardless of
    # whether costing succeeded.
    {"model": PINNED_MODEL, "messages": [{"role": "user", "content": "unsupported too"}]},
], ids=["supported", "unsupported"])
def test_control_15_forwarded_bytes_are_byte_identical(router_base_url, body_obj):
    """Send raw, pre-serialized bytes (not re-encoded by the client on
    every call) so the comparison is exact: what the mock's echo_body
    returns must equal exactly what was sent, whether or not costing
    succeeded for this request."""
    raw = json.dumps(body_obj).encode("utf-8")
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            f"{router_base_url}/v1/chat/completions?echo_body=1",
            content=raw,
            headers={"Content-Type": "application/json"},
        )
    assert resp.content == raw, (
        "request-cost extraction mutated the forwarded request body -- "
        f"sent {raw!r}, upstream received {resp.content!r}"
    )

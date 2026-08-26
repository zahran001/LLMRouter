"""Python reference implementation of the Week 3 request-cost formula.

WEEK3_COST_CONTRACT.md sections 1-3. This is the oracle the Rust runtime
(`router/src/cost/`) must agree with exactly, over the full pinned corpus
plus edge cases and negative controls
(`WEEK3_IMPLEMENTATION_README.md` section 2.10).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from cost_model.tokenizer import build_renderer, load_tokenizer
from cost_model.types import (
    InvalidMaxTokens,
    MissingMaxTokens,
    RequestCost,
    RequestCostProvenance,
    UnsupportedShape,
    WrongModel,
)

_ALLOWED_TOP_LEVEL_KEYS = frozenset({"model", "messages", "max_tokens", "stream"})
_ALLOWED_MESSAGE_KEYS = frozenset({"role", "content"})


def validate_supported_request(request: dict, *, pinned_model_id: str) -> None:
    """Raise a RequestCostError if `request` is not the frozen benchmark-exact
    supported shape (WEEK3_COST_CONTRACT.md section 1). Returns None (and
    does not modify `request`) if it is supported.
    """
    if not isinstance(request, dict):
        raise UnsupportedShape("request body is not a JSON object")

    extra_keys = set(request.keys()) - _ALLOWED_TOP_LEVEL_KEYS
    if extra_keys:
        raise UnsupportedShape(f"unsupported top-level field(s): {sorted(extra_keys)}")

    model = request.get("model")
    if model != pinned_model_id:
        raise WrongModel(model, pinned_model_id)

    messages = request.get("messages")
    if not isinstance(messages, list) or len(messages) != 1:
        raise UnsupportedShape("messages must be an array of exactly one message")

    message = messages[0]
    if not isinstance(message, dict) or set(message.keys()) != _ALLOWED_MESSAGE_KEYS:
        raise UnsupportedShape("messages[0] must have exactly {role, content}")
    if message.get("role") != "user":
        raise UnsupportedShape(f"messages[0].role must be \"user\", got {message.get('role')!r}")
    if not isinstance(message.get("content"), str):
        raise UnsupportedShape("messages[0].content must be a plain string")

    if "max_tokens" not in request:
        raise MissingMaxTokens()
    max_tokens = request["max_tokens"]
    # bool is an int subclass in Python -- reject True/False masquerading as
    # a token count explicitly, not just via the value check below.
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
        raise InvalidMaxTokens(max_tokens)

    if "stream" in request and not isinstance(request["stream"], bool):
        raise UnsupportedShape(f"stream must be a boolean, got {request['stream']!r}")


def compute_request_cost(
    request: dict,
    *,
    tokenizer,
    render: Callable[[str], str],
    provenance: RequestCostProvenance,
) -> RequestCost:
    """The Week 3 reference formula.

    Raises a RequestCostError subclass for anything outside the frozen
    supported-request contract -- fail closed, never an approximate cost
    (WEEK3_COST_CONTRACT.md section 2).
    """
    validate_supported_request(request, pinned_model_id=provenance.model_id)

    content = request["messages"][0]["content"]
    max_output_tokens = request["max_tokens"]

    rendered = render(content)
    input_tokens = len(tokenizer.encode(rendered, add_special_tokens=False).ids)

    # LOCKED DESIGN DECISION (WEEK3_IMPLEMENTATION_README.md section 2.5):
    # reserve the full max_tokens. The Week 3 investigation found the exact
    # logical-KV-occupancy boundary is one token smaller
    # (input_tokens + max_output_tokens - 1, for max_output_tokens >= 1) --
    # deliberately NOT applied here. This is documented intentional
    # conservatism, not a bug to fix.
    reserved_tokens = input_tokens + max_output_tokens
    estimated_kv_bytes = reserved_tokens * provenance.logical_kv_bytes_per_token

    return RequestCost(
        input_tokens=input_tokens,
        max_output_tokens=max_output_tokens,
        reserved_tokens=reserved_tokens,
        estimated_kv_bytes=estimated_kv_bytes,
    )


@dataclass
class ReferenceContext:
    """Bundles the loaded tokenizer/renderer/provenance so callers (batch
    scripts, tests) load them once rather than per request."""

    tokenizer: object
    render: Callable[[str], str]
    provenance: RequestCostProvenance

    def compute(self, request: dict) -> RequestCost:
        return compute_request_cost(
            request, tokenizer=self.tokenizer, render=self.render, provenance=self.provenance)


def load_reference_context(
    *,
    tokenizer_cache_dir: Path | None = None,
    provenance_path: Path | str | None = None,
) -> ReferenceContext:
    from cost_model.types import DEFAULT_PROVENANCE_PATH
    from cost_model.tokenizer import DEFAULT_TOKENIZER_CACHE

    cache_dir = tokenizer_cache_dir or DEFAULT_TOKENIZER_CACHE
    prov_path = provenance_path or DEFAULT_PROVENANCE_PATH

    tokenizer, tok_config, _tok_provenance = load_tokenizer(cache_dir)
    render, _template_src = build_renderer(tok_config)
    provenance = RequestCostProvenance.from_frozen(prov_path)

    return ReferenceContext(tokenizer=tokenizer, render=render, provenance=provenance)

"""Request-cost types, version constants, and provenance schema.

Pure data holders and their (de)serialization -- no I/O beyond
`RequestCostProvenance.from_frozen`'s read of a committed manifest, no
formula logic. Mirrors the `@dataclass(frozen=True)` + `to_dict()` +
`from_frozen()` convention already used by `metrics/classification.py`'s
`RepeatPolicy`/`HeadlineEvidenceSpec` -- see WEEK3_COST_CONTRACT.md for the
frozen schema this module implements.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# A "*_VERSION" constant lives beside the thing it versions (this repo's
# established convention, e.g. HEADLINE_POINT_RECORD_VERSION in
# metrics/headline_point.py) so an emitted record can stamp it and a
# consumer can assert equality rather than assume compatibility.
COST_MODEL_VERSION = "v1"
FORMULA_VERSION = "kv-worst-case-gqa-v1"
PROVENANCE_SCHEMA_VERSION = "1"
SIDECAR_SCHEMA_VERSION = "1"

DEFAULT_PROVENANCE_PATH = (
    Path(__file__).resolve().parent.parent
    / "benchmarks" / "workloads" / "week3_cost" / "request_cost_provenance.v1.json"
)


class RequestCostError(Exception):
    """Base for every reason a request cannot be costed exactly.

    WEEK3_COST_CONTRACT.md section 2: a RequestCostError must never become
    an approximate cost and must never block the request from being
    proxied -- it is purely an internal signal.
    """


class NotJson(RequestCostError):
    def __init__(self, detail: str = "request body is not valid JSON"):
        super().__init__(detail)


class UnsupportedShape(RequestCostError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"unsupported request shape: {reason}")


class WrongModel(RequestCostError):
    def __init__(self, got: str | None, expected: str):
        self.got = got
        self.expected = expected
        super().__init__(f"model {got!r} does not match pinned identity {expected!r}")


class MissingMaxTokens(RequestCostError):
    def __init__(self):
        super().__init__("max_tokens is required and was not present")


class InvalidMaxTokens(RequestCostError):
    def __init__(self, got):
        self.got = got
        super().__init__(f"max_tokens must be a positive integer, got {got!r}")


@dataclass(frozen=True)
class RequestCost:
    """The Week 3 request-cost signal (WEEK3_COST_CONTRACT.md section 3).

    All fields are integers; estimated_kv_bytes is computed with integer
    arithmetic only, never floating point.
    """

    input_tokens: int
    max_output_tokens: int
    reserved_tokens: int
    estimated_kv_bytes: int

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "reserved_tokens": self.reserved_tokens,
            "estimated_kv_bytes": self.estimated_kv_bytes,
        }

    @classmethod
    def from_dict(cls, row: dict) -> "RequestCost":
        return cls(
            input_tokens=int(row["input_tokens"]),
            max_output_tokens=int(row["max_output_tokens"]),
            reserved_tokens=int(row["reserved_tokens"]),
            estimated_kv_bytes=int(row["estimated_kv_bytes"]),
        )


@dataclass(frozen=True)
class RequestCostProvenance:
    """The versioned cost-model provenance manifest, typed.

    WEEK3_COST_CONTRACT.md section 5. Every architecture constant here must
    trace to a hash in `source_provenance` or a derivation in
    WEEK3_KV_REQUEST_COST_INVESTIGATION_REPORT.md -- this type only reads a
    committed manifest, it never invents a value.
    """

    schema_version: str
    cost_model_version: str
    formula_version: str

    model_id: str
    model_revision: str
    model_config_sha256: str
    tokenizer_sha256: str
    tokenizer_config_sha256: str
    chat_template_sha256: str

    num_hidden_layers: int
    num_key_value_heads: int
    head_dim: int
    logical_kv_bytes_per_token: int

    effective_kv_cache_dtype: str
    bytes_per_kv_element: int
    vllm_version: str

    @classmethod
    def from_frozen(cls, path: Path | str = DEFAULT_PROVENANCE_PATH) -> "RequestCostProvenance":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        src = raw["source_provenance"]
        arch = raw["derived_architecture"]
        runtime = raw["serving_runtime"]
        return cls(
            schema_version=raw["schema_version"],
            cost_model_version=raw["cost_model_version"],
            formula_version=raw["formula_version"],
            model_id=src["model_id"],
            model_revision=src["model_revision"],
            model_config_sha256=src["model_config_sha256"],
            tokenizer_sha256=src["tokenizer_sha256"],
            tokenizer_config_sha256=src["tokenizer_config_sha256"],
            chat_template_sha256=src["chat_template_sha256"],
            num_hidden_layers=int(arch["num_hidden_layers"]),
            num_key_value_heads=int(arch["num_key_value_heads"]),
            head_dim=int(arch["head_dim"]),
            logical_kv_bytes_per_token=int(arch["logical_kv_bytes_per_token"]),
            effective_kv_cache_dtype=runtime["effective_kv_cache_dtype"],
            bytes_per_kv_element=int(runtime["bytes_per_kv_element"]),
            vllm_version=runtime["vllm_version"],
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "cost_model_version": self.cost_model_version,
            "formula_version": self.formula_version,
            "source_provenance": {
                "model_id": self.model_id,
                "model_revision": self.model_revision,
                "model_config_sha256": self.model_config_sha256,
                "tokenizer_sha256": self.tokenizer_sha256,
                "tokenizer_config_sha256": self.tokenizer_config_sha256,
                "chat_template_sha256": self.chat_template_sha256,
            },
            "derived_architecture": {
                "num_hidden_layers": self.num_hidden_layers,
                "num_key_value_heads": self.num_key_value_heads,
                "head_dim": self.head_dim,
                "logical_kv_bytes_per_token": self.logical_kv_bytes_per_token,
            },
            "serving_runtime": {
                "effective_kv_cache_dtype": self.effective_kv_cache_dtype,
                "bytes_per_kv_element": self.bytes_per_kv_element,
                "vllm_version": self.vllm_version,
            },
        }

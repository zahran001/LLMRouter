"""Week 3 must not redefine Week 2 semantics
(`WEEK3_IMPLEMENTATION_README.md` section 8 "Compatibility Rules";
`WEEK3_COST_CONTRACT.md` section 7).

Two things could regress by accident while building the cost model:
  1. `metrics/artifacts.py`'s known artifact suffix set changing shape
     (would silently reinterpret which files are which kind of evidence).
  2. `prompt_len` in a Week 2 raw-log row quietly stopping being a
     character count.

Each guard is paired with a control that shows it goes red, matching this
repo's established negative-control convention
(`tests/redesign/test_legacy_compatibility.py`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from loadgen.log import read_log

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# One representative committed Week 2 raw log -- any would do; this one is
# small and already promoted evidence.
SAMPLE_RAW_LOG = (
    REPO_ROOT / "benchmarks" / "evidence" / "week2" / "session_2"
    / "sustained_scout" / "headline_r1_rps0.5.raw_log.jsonl"
)

EXPECTED_RAW_LOG_FIELDS = {
    "request_id", "send_time", "close_time", "prompt_id", "prompt_len", "status",
}


def test_corpus_row_schema_is_unchanged():
    """scripts/build_baseline_corpus.py:102-105 defines the row shape Week 3
    reads via loadgen.corpus.load_corpus() -- if this changed shape, the
    Week 3 golden vectors would silently key on the wrong things."""
    from loadgen.corpus import load_corpus

    corpus = load_corpus()
    assert len(corpus) == 5000, "corpus row count changed -- golden vectors were built over a different corpus"
    sample = corpus.prompts[0]
    assert sample.char_len == len(sample.text), (
        "char_len is no longer character count -- this is the exact quantity "
        "Week 2 prompt_len means and Week 3 input_tokens must never be confused with"
    )


def test_artifact_suffix_set_is_unchanged():
    """cost_model writes its own new suffixes (golden_vectors.v1.jsonl,
    request_cost_provenance.v1.json) via metrics.artifacts.write_json_artifact,
    but must never touch the Week 2 ARTIFACT_SUFFIXES set itself."""
    from metrics.artifacts import ARTIFACT_SUFFIXES

    assert ARTIFACT_SUFFIXES == (
        ".raw_log.jsonl", ".samples.jsonl", ".metrics.json", ".schedule.json",
    )


def test_week2_raw_log_keeps_its_six_field_schema_and_prompt_len_is_int():
    rows = read_log(SAMPLE_RAW_LOG)
    assert rows, f"empty raw log fixture: {SAMPLE_RAW_LOG}"
    for row in rows[:50]:
        assert set(row) == EXPECTED_RAW_LOG_FIELDS, (
            f"raw-log field set changed: {set(row)} != {EXPECTED_RAW_LOG_FIELDS}"
        )
        assert isinstance(row["prompt_len"], int), (
            "prompt_len must remain an integer character count -- Week 3 input_tokens "
            "is a distinct, separately-logged quantity (WEEK3_COST_CONTRACT.md section 7)"
        )


def test_control_a_seventh_field_would_be_caught(tmp_path):
    """If the field-set check could not see an added/renamed field, the
    six-field-schema guard above would be decorative."""
    import json

    tampered = tmp_path / "tampered.raw_log.jsonl"
    row = {
        "request_id": 0, "send_time": 0.0, "close_time": 0.1,
        "prompt_id": 0, "prompt_len": 42, "status": "sent",
        "input_tokens": 17,  # the bug: Week 3 semantics leaking into Week 2's schema
    }
    tampered.write_text(json.dumps(row) + "\n", encoding="utf-8")

    rows = read_log(tampered)
    with pytest.raises(AssertionError):
        assert set(rows[0]) == EXPECTED_RAW_LOG_FIELDS

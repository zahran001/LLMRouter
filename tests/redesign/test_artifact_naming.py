"""Fractional-RPS artifact discovery, with the control that proves it bites
(Redesign README §6 "Fractional RPS"; handoff §11).

The first session's completeness checker recovered a point tag with
`name.split(".")[0]`, so `poisson_rps1.5.raw_log.jsonl` was filed under the
point `poisson_rps1` -- whose sidecar and metrics did not exist, because the
point did not exist. It reported a healthy fractional point as unusable on
the meter. Stage B resolves the breach with fractional RPS, so every point
that matters next session is exactly the shape this bug mangles.

The control here is the OLD rule: it is run against the same filenames and
must produce the wrong answer. A test that only exercised the new rule would
pass just as happily if the bug had never been fixed.
"""

from __future__ import annotations

import json

import pytest

from metrics.artifacts import (
    ARTIFACT_SUFFIXES,
    METRICS_SUFFIX,
    RAW_LOG_SUFFIX,
    SAMPLES_SUFFIX,
    discover_tags,
    tag_for,
)

FRACTIONAL_TAGS = ("poisson_rps1.5", "poisson_rps2.5", "poisson_rps0.75", "steady_rps1.25")
INTEGER_TAGS = ("poisson_rps2", "poisson_rps10", "poisson_rps80")


def _old_buggy_tag(name: str) -> str:
    """The first session's rule, preserved verbatim as the control input."""
    return name.split(".")[0]


# ---------------------------------------------------------------------------
# The control: the old rule must go RED on exactly the names that broke it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tag", FRACTIONAL_TAGS)
def test_control_old_rule_truncates_fractional_tags(tag):
    name = f"{tag}{RAW_LOG_SUFFIX}"
    assert _old_buggy_tag(name) != tag, (
        "the old rule did NOT truncate this name -- then it is not the bug the handoff "
        "described and this control is testing nothing"
    )
    # And it truncates into a *plausible* neighbouring point, which is why it
    # was mistaken for a missing artifact rather than an obvious parse error.
    assert _old_buggy_tag(name) == tag.split(".")[0]


@pytest.mark.parametrize("tag", INTEGER_TAGS)
def test_control_old_rule_happens_to_work_on_integer_tags(tag):
    """Why it survived to the meter: every pre-session point was an integer
    RPS, so the checker was green right up until the first fractional point."""
    assert _old_buggy_tag(f"{tag}{RAW_LOG_SUFFIX}") == tag


# ---------------------------------------------------------------------------
# The real rule: green on both shapes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tag", FRACTIONAL_TAGS + INTEGER_TAGS)
@pytest.mark.parametrize("suffix", ARTIFACT_SUFFIXES)
def test_tag_for_round_trips_every_suffix(tag, suffix):
    assert tag_for(f"{tag}{suffix}") == tag


def test_tag_for_rejects_an_unknown_suffix():
    """A silent fallback would invent a phantom point in the completeness
    table -- the same class of failure, pointing the other way."""
    with pytest.raises(ValueError, match="no known per-point artifact suffix"):
        tag_for("vllm.log")


def test_discover_tags_finds_fractional_points(tmp_path):
    for tag in FRACTIONAL_TAGS + INTEGER_TAGS:
        (tmp_path / f"{tag}{RAW_LOG_SUFFIX}").write_text("", encoding="utf-8")
        (tmp_path / f"{tag}{SAMPLES_SUFFIX}").write_text("", encoding="utf-8")
        (tmp_path / f"{tag}{METRICS_SUFFIX}").write_text("{}", encoding="utf-8")

    assert discover_tags(tmp_path) == sorted(FRACTIONAL_TAGS + INTEGER_TAGS)

    # The completeness question the checker actually asks: does every
    # discovered tag have all three artifacts? Under the old rule the
    # fractional tags answered "no" while all three files sat on disk.
    for tag in discover_tags(tmp_path):
        assert (tmp_path / f"{tag}{SAMPLES_SUFFIX}").exists()
        assert (tmp_path / f"{tag}{METRICS_SUFFIX}").exists()

    old_tags = sorted({_old_buggy_tag(p.name) for p in tmp_path.glob(f"*{RAW_LOG_SUFFIX}")})
    missing_under_old_rule = [
        t for t in old_tags if not (tmp_path / f"{t}{SAMPLES_SUFFIX}").exists()
    ]
    assert missing_under_old_rule, "the old rule must still report false-missing points here"


def test_discover_tags_on_the_real_first_session_evidence(first_session_dir):
    """The 1.5-RPS point that was reported incomplete on the meter, against
    the artifacts that were actually intact."""
    tags = discover_tags(first_session_dir)
    assert "poisson_rps1.5" in tags

    samples = first_session_dir / f"poisson_rps1.5{SAMPLES_SUFFIX}"
    metrics = first_session_dir / f"poisson_rps1.5{METRICS_SUFFIX}"
    assert samples.exists() and metrics.exists()

    n_samples = sum(1 for _ in samples.open(encoding="utf-8"))
    record = json.loads(metrics.read_text(encoding="utf-8"))
    assert n_samples == record["n_issued_total"] == 182, "handoff 11: 182/182, 0 errors"
    assert record["n_errored_total"] == 0

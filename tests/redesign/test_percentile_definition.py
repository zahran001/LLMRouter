"""The percentile lock (R4 README L5; `WEEK2_PLAN.md` §10.5).

A lock is only worth having if the thing it forbids would otherwise happen.
So the first test here is the control: on the first session's own
near-boundary sample, four standard percentile conventions disagree, and two
of them land on the opposite side of the 500ms SLO from the other two. If
that stopped being true, this lock would be decorative and could be dropped.

The rest assert that the redesigned path always returns nearest-rank, that
live and offline computation cannot disagree because they call the same
function, and that historical records are NOT recomputed under the new
convention.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from metrics.compute import percentile as legacy_percentile
from metrics.percentile import (
    LEGACY_PERCENTILE_METHOD,
    PERCENTILE_METHOD,
    PERCENTILE_METHOD_VERSION,
    percentile_nearest_rank,
    percentile_provenance,
    top_k_support,
)

pytestmark = pytest.mark.redesign

SLO_MS = 500.0


@pytest.fixture(scope="module")
def near_boundary_sample(first_session_dir):
    """The 225 post-warmup TTFT values from the first session's 2-RPS point."""
    path = first_session_dir / "poisson_rps2.samples.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    return [r["ttft_ms"] for r in rows
            if r["send_time"] >= 10.0 and r.get("ttft_ms") is not None]


# ---------------------------------------------------------------------------
# The control: without a lock, the convention decides the verdict.
# ---------------------------------------------------------------------------


def test_control_conventions_disagree_across_the_slo_on_a_real_sample(near_boundary_sample):
    values = np.array(near_boundary_sample, dtype=float)
    assert len(values) == 225

    by_method = {m: float(np.percentile(values, 99, method=m))
                 for m in ("linear", "lower", "higher", "nearest", "midpoint")}
    verdicts = {m: "OVER" if v >= SLO_MS else "UNDER" for m, v in by_method.items()}

    assert len(set(verdicts.values())) == 2, (
        f"all conventions now agree ({verdicts}) -- if that is genuinely true for this sample, "
        "the percentile lock is no longer load-bearing and this control should be revisited "
        "rather than silently kept")
    spread = max(by_method.values()) - min(by_method.values())
    assert spread > 100.0, f"convention spread collapsed to {spread:.1f}ms"


def test_control_a_crafted_small_sample_also_splits_the_verdict():
    """Not dependent on the promoted evidence being present: the same failure
    reproduces on a constructed sample with a sparse tail."""
    values = [100.0] * 97 + [450.0, 480.0, 900.0]
    by_method = {m: float(np.percentile(np.array(values), 99, method=m))
                 for m in ("linear", "lower", "higher", "nearest")}
    verdicts = {"OVER" if v >= SLO_MS else "UNDER" for v in by_method.values()}
    assert verdicts == {"OVER", "UNDER"}


# ---------------------------------------------------------------------------
# The redesigned path always returns nearest-rank.
# ---------------------------------------------------------------------------


def test_nearest_rank_returns_an_observed_value(near_boundary_sample):
    result = percentile_nearest_rank(near_boundary_sample, 99)
    assert result in near_boundary_sample, (
        "nearest-rank must return a latency some request actually experienced; an interpolated "
        "value is a number nothing observed")


def test_nearest_rank_matches_the_definition_r4_states():
    import math

    for n in (1, 3, 10, 99, 100, 225, 4000):
        values = [float(i) for i in range(1, n + 1)]
        for p in (0.0, 50.0, 95.0, 99.0, 100.0):
            expected_rank = max(1, min(math.ceil(p / 100.0 * n), n))
            assert percentile_nearest_rank(values, p) == float(expected_rank)


def test_nearest_rank_is_order_independent_and_handles_duplicates():
    import random

    values = [5.0, 1.0, 3.0, 3.0, 9.0, 2.0, 3.0]
    reference = percentile_nearest_rank(values, 99)
    for _ in range(20):
        shuffled = values[:]
        random.shuffle(shuffled)
        assert percentile_nearest_rank(shuffled, 99) == reference


def test_nearest_rank_refuses_an_empty_sample():
    with pytest.raises(ValueError, match="empty sample"):
        percentile_nearest_rank([], 99)


def test_nearest_rank_rejects_a_percentile_out_of_range():
    with pytest.raises(ValueError, match=r"\[0, 100\]"):
        percentile_nearest_rank([1.0], 101)


def test_provenance_names_the_convention():
    prov = percentile_provenance()
    assert prov["percentile_method"] == PERCENTILE_METHOD == "nearest_rank"
    assert prov["percentile_method_version"] == PERCENTILE_METHOD_VERSION
    assert LEGACY_PERCENTILE_METHOD in prov["note"], (
        "provenance must name the legacy convention too, or a reader cannot tell which "
        "records were produced under which"
    )


def test_live_and_offline_use_the_same_function(near_boundary_sample):
    """The first session's floor and its Stage A points disagreed because two
    code paths each picked their own convention. One function is the fix."""
    from metrics.headline_point import headline_point_metrics

    warmup = 0.0
    raw = [{"request_id": i, "send_time": float(i), "close_time": float(i) + 1.0,
            "prompt_id": i, "prompt_len": 10, "status": "sent"}
           for i in range(len(near_boundary_sample))]
    samples = [{"request_id": i, "send_time": float(i), "ttft_ms": v,
                "tpot_samples_ms": [], "content_chunk_count": 1, "error": None}
               for i, v in enumerate(near_boundary_sample)]
    schedule_provenance = {
        "nominal_lambda_rps": 2.0, "warmup_boundary_s": warmup,
        "materialized_schedule_count": len(raw),
        "materialized_post_warmup_count": len(raw),
        "post_warmup_target_count": len(raw),
        "materialized_schedule_duration_s": float(len(raw)),
    }
    record = headline_point_metrics(raw, samples, schedule_provenance, warmup_n_s=warmup)

    assert record["ttft_p99_ms"] == percentile_nearest_rank(near_boundary_sample, 99)
    assert record["percentile"]["percentile_method"] == "nearest_rank"


# ---------------------------------------------------------------------------
# History keeps its own convention.
# ---------------------------------------------------------------------------


def test_legacy_percentile_still_interpolates(near_boundary_sample):
    """`metrics.compute.percentile` must NOT be quietly switched to
    nearest-rank: every first-session record was produced with it, and
    changing it would rewrite what those artifacts mean."""
    legacy = legacy_percentile(near_boundary_sample, 99)
    redesigned = percentile_nearest_rank(near_boundary_sample, 99)
    assert legacy != redesigned
    assert abs(legacy - float(np.percentile(np.array(near_boundary_sample), 99,
                                            method="linear"))) < 1e-9


def test_legacy_point_records_are_not_recomputed(first_session_dir):
    committed = json.loads(
        (first_session_dir / "poisson_rps2.metrics.json").read_text(encoding="utf-8"))
    assert abs(committed["ttft_p99_ms"] - 524.5720889199937) < 1e-6, (
        "the committed legacy p99 changed -- historical records must keep their historical "
        "convention (WEEK2_PLAN.md 10.5)")


# ---------------------------------------------------------------------------
# Tail support: the number that made n>=100 inadequate.
# ---------------------------------------------------------------------------


def test_top_k_support_explains_the_first_session(near_boundary_sample):
    assert top_k_support(len(near_boundary_sample), 99.0) == 3, (
        "the 2-RPS point's p99 rested on 3 observations, which is why excluding one prompt "
        "flipped it")
    assert top_k_support(4000, 99.0) == 41
    assert top_k_support(0, 99.0) == 0

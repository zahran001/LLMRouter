"""The unloaded floor is a real, executable session #2 stage (Phase C).

Session #1's floor is classified `CACHE_INFLUENCED_DIAGNOSTIC` and cannot be
cited. The runbook's §2 step 3 replaces it — and until now that step had no
command behind it at all: `analyze_floor_cache_state.py` and
`analyze_prompt_cost.py` read session #1's artifacts offline, and nothing in
the repository could produce new ones.

What the replacement has to be, and what these tests pin:

  - the **canonical headline membership**, all 4,000 prompts, so the p99 it
    produces is the floor the headline curve actually starts from rather than
    an estimate from some other draw. Session #1's floor sampled 248 prompts
    from one schedule's realized draw;
  - **concurrency 1, sequential**, not a low-λ Poisson point. Poisson arrivals
    collide even at a low mean rate, and the collisions land in the tail --
    the only part of the distribution the floor is read for;
  - **prefix caching verified disabled**, because a warm cache is precisely
    what invalidated the floor this one replaces.

Driven against the mock with `--limit`, because 4,000 sequential requests is a
seven-minute test that would prove nothing the truncated run does not. The
population is deliberately NOT truncated with it, which gives the incomplete
case a distinct shape instead of letting it look like a clean floor over a
smaller workload.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GPU_SESSION = REPO_ROOT / "scripts" / "gpu_session"
WORKLOAD = REPO_ROOT / "benchmarks" / "workloads" / "week2_headline" / "canonical_v1.json"

pytestmark = pytest.mark.redesign

HEADLINE_MEMBERSHIP = "a49ecdd8071920303f240fcf0b8da42dbbc66da593ae88e3c07aa246c4b5aa7b"
CANONICAL_N = 4000


@pytest.fixture(scope="module")
def floor_driver():
    spec = importlib.util.spec_from_file_location(
        "_drive_unloaded_floor", GPU_SESSION / "drive_unloaded_floor.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cache_verdict(tmp_path) -> Path:
    path = tmp_path / "prefix_cache_verdict.json"
    path.write_text(json.dumps({"verdict": "PREFIX_CACHING_DISABLED", "min_ratio": 0.99}),
                    encoding="utf-8")
    return path


def _drive(floor_driver, out_dir, base_url, verdict, extra=()):
    argv = ["drive_unloaded_floor.py",
            "--out-dir", str(out_dir),
            "--base-url", base_url,
            "--model", "mock",
            "--prefix-cache-verdict", str(verdict),
            *extra]
    old = sys.argv
    sys.argv = argv
    try:
        floor_driver.main()
    finally:
        sys.argv = old
    return json.loads((Path(out_dir) / "floor.metrics.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The command exists and is reachable the way the runbook says.
# ---------------------------------------------------------------------------


def test_the_floor_command_is_wired_end_to_end():
    local = (GPU_SESSION / "run_on_instance.sh").read_text(encoding="utf-8")
    remote = (GPU_SESSION / "remote_loadgen.sh").read_text(encoding="utf-8")

    assert "floor)" in local and "cmd_floor" in local
    assert "floor)" in remote and "cmd_floor" in remote
    assert "drive_unloaded_floor.py" in remote, (
        "the remote floor command must reach the dedicated sequential driver")
    assert (GPU_SESSION / "drive_unloaded_floor.py").exists()


def test_the_floor_does_not_route_through_an_arrival_process():
    """§2 step 3 is not a Poisson point at a low rate. If the driver ever
    grows a schedule, the floor has acquired queueing it is defined to
    exclude."""
    source = (GPU_SESSION / "drive_unloaded_floor.py").read_text(encoding="utf-8")
    for forbidden in ("OpenLoopScheduler", "build_poisson_schedule",
                      "build_steady_schedule", "load_headline_schedule",
                      "drive_redesign_point"):
        assert forbidden not in source, (
            f"the unloaded floor uses {forbidden}; it must not depend on an arrival process")


# ---------------------------------------------------------------------------
# Identity and population.
# ---------------------------------------------------------------------------


def test_the_floor_defaults_to_the_canonical_headline_workload():
    source = (GPU_SESSION / "drive_unloaded_floor.py").read_text(encoding="utf-8")
    assert 'week2_headline' in source and 'canonical_v1.json' in source

    workload = json.loads(WORKLOAD.read_text(encoding="utf-8"))
    assert workload["membership_id"] == HEADLINE_MEMBERSHIP
    assert len(workload["membership"]) == CANONICAL_N, (
        "the floor's population is the canonical membership; if this is not 4,000 the "
        "runbook's step 3 no longer describes what runs")


def test_control_concurrency_above_one_is_refused():
    """The floor is *defined* at concurrency 1. A record computed at any other
    concurrency is a loaded measurement wearing the floor's name."""
    from metrics.floor_point import floor_point_metrics

    with pytest.raises(ValueError, match="defined at concurrency 1"):
        floor_point_metrics([], [], membership=[1], membership_id="x",
                            corpus_sha256="y", concurrency=2)


def test_control_a_missing_prefix_cache_verdict_refuses_the_floor(floor_driver, tmp_path):
    """L6 applies here more than anywhere: a warm cache is exactly what made
    session #1's floor uncitable."""
    with pytest.raises(SystemExit, match="no prefix-cache verdict"):
        _drive(floor_driver, tmp_path / "out", "http://127.0.0.1:1",
               tmp_path / "absent.json", extra=["--limit", "1"])


def test_control_an_enabled_prefix_cache_refuses_the_floor(floor_driver, tmp_path):
    verdict = tmp_path / "v.json"
    verdict.write_text(json.dumps({"verdict": "PREFIX_CACHING_ENABLED", "min_ratio": 0.2}),
                       encoding="utf-8")
    with pytest.raises(SystemExit, match="not PREFIX_CACHING_DISABLED"):
        _drive(floor_driver, tmp_path / "out", "http://127.0.0.1:1", verdict,
               extra=["--limit", "1"])


# ---------------------------------------------------------------------------
# Driven, against the mock.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_the_floor_drives_and_produces_session_2_artifacts(
        floor_driver, tmp_path, mock_base_url, cache_verdict):
    out_dir = tmp_path / "floor"
    record = _drive(floor_driver, out_dir, mock_base_url, cache_verdict,
                    extra=["--limit", "25"])

    for suffix in ("raw_log.jsonl", "samples.jsonl", "metrics.json"):
        assert (out_dir / f"floor.{suffix}").exists(), f"missing floor.{suffix}"

    # Identity travelled with the frozen workload.
    assert record["canonical_prompt_membership_id"] == HEADLINE_MEMBERSHIP
    assert record["corpus_sha256"]
    assert record["concurrency"] == 1
    assert record["measurement_membership_basis"] == "canonical_membership"

    # The population is the canonical membership even though only 25 ran.
    assert record["expected_measurement_n"] == CANONICAL_N
    assert record["percentile_population_n"] == CANONICAL_N
    assert record["reconciled_measurement_n"] == 25

    # A real measurement came out.
    assert record["n_ttft_observed"] == 25
    assert record["ttft_p99_ms"] is not None
    assert record["ttft_p50_ms"] <= record["ttft_p99_ms"]
    assert record["slo_headroom_ms"] is not None
    assert record["percentile"]["percentile_method"] == "nearest_rank", (
        "the floor must use the same percentile convention as the curve it is the "
        "starting point of")

    # Provenance the artifact gate asks for.
    prov = record["provenance"]
    assert prov["prefix_cache_verdict"] == "PREFIX_CACHING_DISABLED"
    assert prov["limit_applied"] == 25
    assert "benchmark_sha" in prov
    assert "process_epoch" in prov
    assert prov["model"] == "mock"
    assert prov["driven_at"]


@pytest.mark.integration
def test_control_a_truncated_floor_reports_itself_incomplete(
        floor_driver, tmp_path, mock_base_url, cache_verdict):
    """The failure this shape exists to make visible: a floor that covered
    part of the workload must not read like a floor that covered all of it."""
    record = _drive(floor_driver, tmp_path / "floor2", mock_base_url, cache_verdict,
                    extra=["--limit", "10"])

    assert record["membership_complete"] is False
    assert record["floor_complete"] is False
    assert record["n_missing_prompts"] == CANONICAL_N - 10
    assert record["missing_prompt_ids"], "the record must name what it did not serve"
    assert record["evidence_class"] == "floor_diagnostic"
    assert record["may_define_headline_breach"] is False


@pytest.mark.integration
def test_a_floor_record_cannot_classify_as_headline_evidence(
        floor_driver, tmp_path, mock_base_url, cache_verdict):
    """The floor is the curve's starting point, not a point on it."""
    from metrics.classification import (
        HeadlineEvidenceSpec,
        NotHeadlineEvidence,
        RepeatPolicy,
        classify_point,
    )

    record = _drive(floor_driver, tmp_path / "floor3", mock_base_url, cache_verdict,
                    extra=["--limit", "5"])
    record["nominal_lambda_rps"] = 0.0
    policy = RepeatPolicy(min_valid_repeats=1, headline=HeadlineEvidenceSpec(
        membership_id=HEADLINE_MEMBERSHIP, percentile_population_n=CANONICAL_N))

    with pytest.raises(NotHeadlineEvidence):
        classify_point([record], policy)


@pytest.mark.integration
def test_a_censored_request_is_recorded_not_dropped(
        floor_driver, tmp_path, mock_base_url, cache_verdict):
    """A request that returns no content is censored, not fast. Letting it
    vanish would bias the floor downward -- the same survivorship failure that
    produced session #1's near-60s 'p99' values."""
    from metrics.floor_point import floor_point_metrics

    raw = [{"request_id": i, "send_time": 0.0, "close_time": 1.0, "prompt_id": i,
            "prompt_len": 10, "status": "sent" if i else "errored"} for i in range(10)]
    samples = [{"request_id": i, "send_time": 0.0, "prompt_id": i,
                "ttft_ms": None if i == 0 else 100.0, "tpot_samples_ms": [],
                "content_chunk_count": 0 if i == 0 else 1,
                "error": "RuntimeError: stream produced no content chunk" if i == 0 else None}
               for i in range(10)]

    record = floor_point_metrics(raw, samples, membership=list(range(10)),
                                 membership_id="x", corpus_sha256="y")
    assert record["n_censored"] == 1
    assert record["n_ttft_observed"] == 9
    assert record["ttft_censoring_rate"] == pytest.approx(0.1)
    assert record["error_categories"] == {"RuntimeError": 1}
    assert record["ttft_p99_ms"] is None, (
        "10% censoring is past the 5% hard gate; no ordinary p99 may be published")


def test_control_the_floor_refuses_a_non_headline_workload(floor_driver, tmp_path,
                                                           cache_verdict):
    """The floor is the headline curve's starting point, so `--workload` is not
    a choice.

    Pointing it at the 500-prompt scout workload finishes in ~50s instead of
    ~7 minutes and produces a record that passes every §11 checkbox --
    `membership_complete: true`, `floor_complete: true` -- while being a floor
    over a different multiset. That is precisely the defect (a floor over some
    other draw) that §2 step 3 exists to replace.
    """
    scout_workload = (REPO_ROOT / "benchmarks" / "workloads" / "week2_scout"
                      / "canonical_v1.json")
    with pytest.raises(SystemExit, match="canonical HEADLINE membership"):
        _drive(floor_driver, tmp_path / "out", "http://127.0.0.1:1", cache_verdict,
               extra=["--limit", "1", "--workload", str(scout_workload)])


def test_control_a_truncated_floor_may_not_publish_its_p99():
    """`floor_complete` disclosed truncation, but the field literally named
    "may I publish this" said yes anyway -- and a prefix truncation drops the
    long prompts at the end of the id-sorted membership, which is where the
    floor's tail lives."""
    from metrics.floor_point import floor_point_metrics

    raw = [{"request_id": i, "send_time": 0.0, "close_time": 1.0, "prompt_id": i,
            "prompt_len": 10, "status": "sent"} for i in range(5)]
    samples = [{"request_id": i, "send_time": 0.0, "prompt_id": i, "ttft_ms": 100.0,
                "tpot_samples_ms": [], "content_chunk_count": 1, "error": None}
               for i in range(5)]

    complete = floor_point_metrics(raw, samples, membership=list(range(5)),
                                   membership_id="x", corpus_sha256="y")
    assert complete["publish_ordinary_p99"] is True

    truncated = floor_point_metrics(raw, samples, membership=list(range(20)),
                                    membership_id="x", corpus_sha256="y")
    assert truncated["membership_complete"] is False
    assert truncated["publish_ordinary_p99"] is False
    assert truncated["ttft_p99_ms"] is not None, "the number is still recorded, just not blessed"

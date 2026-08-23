"""The sustained-scout tier (attempt 2, locked 2026-08-22).

Replaces attempt 1's N=500 Tier A scout as the tool for locating the
sustained crossing: Tier A read lambda=1 as clean UNDER over ~5.5 minutes;
Tier B's real N=4000 confirmation at the adjacent lambda=1.5 came back 36%
censored over ~45 minutes. A short window cannot see a queue that is only
slowly diverging, so this family freezes on whichever binds last of a
MINIMUM duration (45 min) and a MINIMUM count (2000), not a fixed N
(`loadgen/headline_schedule.py`'s `materialize_min_duration_and_count`).

It draws from the 4000-prompt HEADLINE canonical workload, not the 500-prompt
scout workload -- the scout pool is too small for the count floor. That means
it shares BOTH scheme (`headline-schedule-v2`) and membership with the real
headline family; `workload_class="sustained_scout_controlled"` is the only
thing left to keep `scenario_contract.py` from confusing the two, which is
exactly what the misrouting tests below exist to prove still holds.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GPU_SESSION = REPO_ROOT / "scripts" / "gpu_session"
SUSTAINED_SCOUT_DIR = (REPO_ROOT / "benchmarks" / "schedules" / "week2_redesign"
                      / "sustained_scout")
HEADLINE_DIR = REPO_ROOT / "benchmarks" / "schedules" / "week2_redesign" / "headline"
SCOUT_DIR = REPO_ROOT / "benchmarks" / "schedules" / "week2_redesign" / "scout"

pytestmark = pytest.mark.redesign

# The committed sustained-scout family's frozen contract, per
# repeat_policy.json's `sustained_scout` block. Written out rather than read
# from the artifact so a silent regeneration would fail this file rather than
# agree with itself.
HEADLINE_MEMBERSHIP = "a49ecdd8071920303f240fcf0b8da42dbbc66da593ae88e3c07aa246c4b5aa7b"
WARMUP_S = 60.0
MIN_DURATION_S = 2700.0
MIN_COUNT = 2000
LAMBDAS = (0.5, 0.75, 1.0, 1.25)


# ---------------------------------------------------------------------------
# The frozen family's own contract.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("nominal_lambda", LAMBDAS)
def test_every_committed_sustained_scout_schedule_meets_its_thresholds(nominal_lambda):
    path = SUSTAINED_SCOUT_DIR / f"headline_r1_rps{nominal_lambda:g}.schedule.json"
    prov = json.loads(path.read_text(encoding="utf-8"))["provenance"]
    assert prov["schedule_scheme_version"] == "headline-schedule-v2"
    assert prov["workload_class"] == "sustained_scout_controlled"
    assert prov["schedule_generation_rule"] == "min_duration_and_count"
    assert prov["warmup_boundary_s"] == WARMUP_S
    assert prov["canonical_prompt_membership_id"] == HEADLINE_MEMBERSHIP, (
        "sustained scout draws from the 4000-prompt HEADLINE workload, not the 500-prompt "
        "scout one -- the count floor exceeds scout's pool")
    assert prov["post_warmup_target_min_count"] == MIN_COUNT
    assert prov["post_warmup_target_min_duration_s"] == MIN_DURATION_S
    # Both thresholds must actually be satisfied by the realized schedule --
    # not just declared -- and per the "freeze at the FIRST arrival where both
    # hold" rule, at least one of them binds tightly (within one arrival gap).
    assert prov["materialized_post_warmup_count"] >= MIN_COUNT
    assert prov["materialized_post_warmup_duration_s"] >= MIN_DURATION_S
    # Self-consistency: `loadgen/redesign_point.py`'s exact-N replay guard
    # only checks materialized == target, so the threshold schedule's target
    # is the realized count itself, not the minimum.
    assert prov["post_warmup_target_count"] == prov["materialized_post_warmup_count"]


def test_the_sustained_scout_workload_is_the_headline_one_not_the_scout_one():
    headline = json.loads(
        (HEADLINE_DIR / "headline_r1_rps2.schedule.json").read_text(encoding="utf-8")
    )["provenance"]
    scout = json.loads(
        (SCOUT_DIR / "headline_r1_rps2.schedule.json").read_text(encoding="utf-8")
    )["provenance"]
    assert headline["canonical_prompt_membership_id"] == HEADLINE_MEMBERSHIP
    assert scout["canonical_prompt_membership_id"] != HEADLINE_MEMBERSHIP


# ---------------------------------------------------------------------------
# check_scenario.py: the new tier must be routable, and must not be confused
# with the two existing families it shares a scheme (and, uniquely, a
# membership) with.
# ---------------------------------------------------------------------------


def _check(scenario: str, schedule: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GPU_SESSION / "check_scenario.py"),
         "--scenario", scenario, "--schedule", str(schedule)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("nominal_lambda", LAMBDAS)
def test_sustained_scout_schedules_are_accepted_under_their_own_scenario(nominal_lambda):
    schedule = SUSTAINED_SCOUT_DIR / f"headline_r1_rps{nominal_lambda:g}.schedule.json"
    proc = _check("sustained-scout", schedule)
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_a_sustained_scout_schedule_is_refused_as_headline():
    """The pair scenario_contract.py names explicitly: same scheme, same
    membership -- workload_class is the only thing separating them."""
    schedule = SUSTAINED_SCOUT_DIR / "headline_r1_rps1.schedule.json"
    proc = _check("headline", schedule)
    assert proc.returncode != 0
    assert "REFUSED" in proc.stderr


def test_a_sustained_scout_schedule_is_refused_as_scout():
    schedule = SUSTAINED_SCOUT_DIR / "headline_r1_rps1.schedule.json"
    proc = _check("scout", schedule)
    assert proc.returncode != 0
    assert "REFUSED" in proc.stderr


def test_a_headline_schedule_is_refused_as_sustained_scout():
    schedule = HEADLINE_DIR / "headline_r1_rps2.schedule.json"
    proc = _check("sustained-scout", schedule)
    assert proc.returncode != 0
    assert "REFUSED" in proc.stderr


def test_a_scout_schedule_is_refused_as_sustained_scout():
    schedule = SCOUT_DIR / "headline_r1_rps2.schedule.json"
    proc = _check("sustained-scout", schedule)
    assert proc.returncode != 0
    assert "REFUSED" in proc.stderr


# ---------------------------------------------------------------------------
# Runtime wiring: the command exists in both dispatch scripts.
# ---------------------------------------------------------------------------


def test_the_sustained_scout_command_exists_in_both_scripts():
    local = (GPU_SESSION / "run_on_instance.sh").read_text(encoding="utf-8")
    remote = (GPU_SESSION / "remote_loadgen.sh").read_text(encoding="utf-8")
    assert "sustained-scout)" in local and "cmd_scenario sustained-scout" in local
    assert "sustained-scout)" in remote and "cmd_v2_scenario sustained-scout" in remote


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"_{name}", GPU_SESSION / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_drive_scenario_point_actually_accepts_sustained_scout_on_its_cli(monkeypatch, tmp_path):
    """The literal defect found live on GPU session #2 attempt 2: both dispatch
    scripts (checked above) and `scenario_contract.py` (CONTRACTS table) knew
    about 'sustained-scout', but `drive_scenario_point.py`'s own argparse
    `choices` list was never updated off its original `["scout", "steady"]`
    and rejected the value with a SystemExit before a single request could be
    sent -- on the meter, after the instance was already up and billing.

    `check_scenario.py` derives its choices from `sorted(CONTRACTS)`, which is
    why the misrouting tests above (via `_check`) passed despite this: they
    never went through THIS script's CLI. This test drives the real committed
    schedule through the real entrypoint, with only the network call stubbed
    out, so a regression here fails loudly rather than only showing up live.
    """
    driver = _load_script("drive_scenario_point")

    captured: list[dict] = []

    def _capture(_sched, _corpus, **kwargs):
        captured.append(kwargs)
        return {
            "ttft_p99_ms": 1.0, "point_state": "UNDER", "ttft_censoring_rate": 0.0,
            "exact_n_honoured": True, "schedule_delivery_ok": True, "n_shed_total": 0,
            "evidence_class": kwargs["evidence_class"], "may_define_headline_breach": False,
            "canonical_prompt_membership_id": "irrelevant-for-this-test",
            "nominal_lambda_rps": 0.5, "warmup_boundary_s": 60.0,
            "post_warmup_target_count": 2000,
            "provenance": {"n_sent": 1, "n_errored": 0, "n_scheduled_driven": 1, "n_shed": 0},
        }

    monkeypatch.setattr(driver, "drive_redesign_point", _capture)

    verdict = tmp_path / "prefix_cache_verdict.json"
    verdict.write_text(json.dumps({"verdict": "PREFIX_CACHING_DISABLED", "min_ratio": 0.99}),
                       encoding="utf-8")
    real_schedule = SUSTAINED_SCOUT_DIR / "headline_r1_rps0.5.schedule.json"
    old_argv = sys.argv
    sys.argv = ["drive_scenario_point.py", "--scenario", "sustained-scout",
                "--schedule", str(real_schedule), "--out-dir", str(tmp_path / "out"),
                "--base-url", "http://127.0.0.1:1", "--model", "mock",
                "--process-epoch", "test-epoch",
                "--prefix-cache-verdict", str(verdict)]
    try:
        driver.main()
    finally:
        sys.argv = old_argv

    assert len(captured) == 1, "sustained-scout must reach drive_redesign_point, not exit early"
    assert captured[0]["evidence_class"] == "scout_diagnostic"


# ---------------------------------------------------------------------------
# Driven end to end, against the mock -- a small synthetic schedule so the
# mechanism is exercised quickly rather than replaying a full ~45min family
# member's thousands of requests in the suite.
# ---------------------------------------------------------------------------


def _tiny_sustained_scout_schedule(tmp_path, corpus, *, warmup_s=10.0, min_count=20,
                                   min_duration_s=0.5, rps=40.0):
    import hashlib

    from loadgen.canonical import CANONICAL_SCHEME_VERSION, membership_id
    from loadgen.headline_schedule import (
        RepeatIdentity,
        build_thresholded_headline_schedule,
        save_headline_schedule,
    )

    members = [p.prompt_id for p in corpus.prompts[:200]]
    workload = {
        "scheme_version": CANONICAL_SCHEME_VERSION,
        "membership_id": membership_id(members),
        "membership": members,
        "locks": {"N": len(members), "L_pct": 99.0, "L_chars": 11471.37, "k": 6, "N_max": 5000},
        "corpus": {
            "sha256": hashlib.sha256(corpus.source_path.read_bytes()).hexdigest(),
            "size": len(corpus),
        },
    }
    identity = RepeatIdentity(canonical_membership_id=workload["membership_id"],
                              repeat_id=1, arrival_seed=5252, assignment_seed=9494)
    schedule = build_thresholded_headline_schedule(
        canonical=workload, corpus=corpus, identity=identity,
        nominal_lambda_rps=rps, warmup_s=warmup_s,
        min_duration_s=min_duration_s, min_count=min_count,
        workload_class="sustained_scout_controlled")
    directory = tmp_path / "frozen"
    directory.mkdir(parents=True, exist_ok=True)
    path, _digest = save_headline_schedule(schedule, directory)
    return path, schedule


@pytest.mark.integration
def test_a_sustained_scout_point_drives_and_produces_a_diagnostic_record(tmp_path, mock_base_url):
    from loadgen.corpus import load_corpus
    from loadgen.redesign_point import drive_redesign_point

    corpus = load_corpus()
    schedule_path, schedule = _tiny_sustained_scout_schedule(tmp_path, corpus)
    tag = schedule_path.name[: -len(".schedule.json")]
    record = drive_redesign_point(
        schedule, corpus, out_dir=tmp_path / "out", tag=tag,
        evidence_class="scout_diagnostic", base_url=mock_base_url, model="mock",
        process_epoch="test-epoch")

    for suffix in ("raw_log.jsonl", "samples.jsonl", "metrics.json"):
        assert (tmp_path / "out" / f"{tag}.{suffix}").exists()

    prov = schedule.provenance
    assert record["exact_n_honoured"] is True
    assert record["schedule_delivery_ok"] is True
    assert record["post_warmup_target_count"] == prov["post_warmup_target_count"]
    assert record["evidence_class"] == "scout_diagnostic"
    assert record["may_define_headline_breach"] is False


@pytest.mark.integration
def test_a_driven_sustained_scout_record_is_refused_by_classification(tmp_path, mock_base_url):
    """It shares the headline membership, so identity alone cannot save it
    from the diagnostic-only refusal -- only `evidence_class` does."""
    from loadgen.corpus import load_corpus
    from loadgen.redesign_point import drive_redesign_point
    from metrics.classification import HeadlineEvidenceSpec, RepeatPolicy, classify_point

    corpus = load_corpus()
    schedule_path, schedule = _tiny_sustained_scout_schedule(tmp_path, corpus)
    tag = schedule_path.name[: -len(".schedule.json")]
    record = drive_redesign_point(
        schedule, corpus, out_dir=tmp_path / "out2", tag=tag,
        evidence_class="scout_diagnostic", base_url=mock_base_url, model="mock",
        process_epoch="test-epoch")

    spec = HeadlineEvidenceSpec(membership_id=record["canonical_prompt_membership_id"],
                                percentile_population_n=record["percentile_population_n"])
    with pytest.raises(ValueError, match="not session #2 headline evidence"):
        classify_point([record], RepeatPolicy(min_valid_repeats=1, headline=spec))

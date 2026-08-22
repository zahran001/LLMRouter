"""Tier A drives frozen Session #2 schedules through Session #2 semantics.

The defect this suite exists to prevent was not a wrong number — it was a
Tier A command that could not start. The documented scout invocation routed a
`headline-schedule-v2` artifact through the legacy `loadgen/_cli.py` runner,
which:

  1. demanded `provenance.master_seed`, a key only the v1 format carries, and
     died with a `KeyError` under `set -euo pipefail` before sending anything;
  2. would have applied the legacy 10s warmup placeholder to a schedule whose
     boundary is frozen at 60s, leaving 50s of transient inside the measured
     window;
  3. would have emitted a record with neither `exact_n_honoured` nor
     `schedule_delivery_ok` — the two gates the runbook (§3) tells a human to
     read at every scout point.

Only (1) is loud. (2) and (3) produce artifacts where every number looks
plausible, which is why the tests below assert on the *record's* fields rather
than on the command exiting zero.

The shape being defended:

    frozen v2 schedule -> loadgen/redesign_point.py -> metrics/headline_point.py
                              /                \\
                        scout (N=500)      headline (N=4000)
                        diagnostic         evidence

Same interpretation, same gates, different authority. Tests are grouped by
which half they pin.
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
SCOUT_DIR = REPO_ROOT / "benchmarks" / "schedules" / "week2_redesign" / "scout"
SECONDARY = (REPO_ROOT / "benchmarks" / "schedules" / "week2_redesign"
             / "secondary_natural" / "secondary_rps2.schedule.json")

pytestmark = pytest.mark.redesign

# The committed scout family's frozen contract, per WEEK2_GPU_SESSION_2_PLAN.md
# §0/§3 and repeat_policy.json. Written out rather than read from the artifact
# so a silent regeneration would fail this file rather than agree with itself.
SCOUT_MEMBERSHIP = "e9470f8f85f228358567c61ae4b0b67040942f4858747cc6076ecea94237de67"
SCOUT_WARMUP_BOUNDARY_S = 60.0
SCOUT_N = 500


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"_{name}", GPU_SESSION / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def scout_driver():
    return _load_script("drive_scenario_point")


@pytest.fixture(scope="module")
def corpus():
    from loadgen.corpus import load_corpus
    return load_corpus()


@pytest.fixture
def cache_verdict(tmp_path) -> Path:
    """A DISABLED verdict, so L6 is satisfied without a live server.

    The refusal itself is covered in `test_headline_driver.py`; both drivers
    now call the same implementation in `loadgen/prefix_cache.py`.
    """
    path = tmp_path / "prefix_cache_verdict.json"
    path.write_text(json.dumps({"verdict": "PREFIX_CACHING_DISABLED", "min_ratio": 0.99}),
                    encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Root cause: the seam no longer asks a v2 schedule for a v1 key.
# ---------------------------------------------------------------------------


def test_the_runner_never_asks_any_schedule_for_master_seed():
    """The literal defect. `master_seed` belongs to `loadgen-schedule-v1`
    provenance; the redesign generator writes `arrival_seed`/`assignment_seed`
    instead, and a replay needs neither -- the frozen entries ARE the
    workload."""
    remote = (GPU_SESSION / "remote_loadgen.sh").read_text(encoding="utf-8")
    assert "master_seed" not in remote, (
        "remote_loadgen.sh extracts master_seed from a schedule's provenance. Redesign "
        "schedules do not carry it, so this dies with a KeyError under `set -e` before the "
        "first request is sent.")


def test_the_committed_scout_schedules_really_lack_master_seed():
    """Pins the premise of the test above, so it cannot pass vacuously if the
    schedule format ever grows the key back."""
    for path in sorted(SCOUT_DIR.glob("*.schedule.json")):
        prov = json.loads(path.read_text(encoding="utf-8"))["provenance"]
        assert "master_seed" not in prov, f"{path.name} unexpectedly carries master_seed"
        assert prov["arrival_seed"] is not None
        assert prov["assignment_seed"] is not None


def test_replaying_a_frozen_schedule_does_not_require_generation_seeds():
    """Generation inputs and replay inputs are separated, rather than a
    `master_seed = arrival_seed` compatibility fiction."""
    from loadgen.corpus import load_corpus
    from loadgen.schedule import build_poisson_schedule
    import argparse

    from loadgen._cli import add_common_args, build_or_load_schedule

    parser = argparse.ArgumentParser()
    add_common_args(parser)

    schedule = build_poisson_schedule(2.0, 20.0, 42, load_corpus())
    frozen = REPO_ROOT / "benchmarks" / "runs" / "_pytest_replay.schedule.json"
    frozen.parent.mkdir(parents=True, exist_ok=True)
    try:
        schedule.save(frozen)
        args = parser.parse_args(["--schedule-in", str(frozen)])
        assert args.seed is None and args.rps is None and args.duration_s is None
        loaded, _corpus = build_or_load_schedule(args, "poisson")
        # Filled from the artifact, not from a CLI default.
        assert args.rps == 2.0
        assert args.duration_s == pytest.approx(20.0)
        assert len(loaded.entries) == len(schedule.entries)
    finally:
        frozen.unlink(missing_ok=True)


def test_control_generating_a_schedule_still_requires_its_seed():
    """Loosening the replay path must not loosen generation: a schedule built
    without a recorded seed is not reproducible."""
    import argparse

    from loadgen._cli import add_common_args, build_or_load_schedule

    parser = argparse.ArgumentParser()
    add_common_args(parser)
    args = parser.parse_args(["--rps", "2", "--duration", "20"])
    with pytest.raises(SystemExit, match="--seed"):
        build_or_load_schedule(args, "poisson")


def test_control_a_replay_may_not_restate_what_was_offered():
    """A flag that contradicts the frozen artifact is refused rather than
    silently winning -- otherwise the point record and the schedule it names
    would disagree about the offered RPS."""
    import argparse

    from loadgen.corpus import load_corpus
    from loadgen.schedule import build_poisson_schedule
    from loadgen._cli import add_common_args, build_or_load_schedule

    parser = argparse.ArgumentParser()
    add_common_args(parser)

    frozen = REPO_ROOT / "benchmarks" / "runs" / "_pytest_conflict.schedule.json"
    frozen.parent.mkdir(parents=True, exist_ok=True)
    try:
        build_poisson_schedule(2.0, 20.0, 42, load_corpus()).save(frozen)
        args = parser.parse_args(["--schedule-in", str(frozen), "--rps", "9"])
        with pytest.raises(SystemExit, match="contradicts the frozen schedule"):
            build_or_load_schedule(args, "poisson")
    finally:
        frozen.unlink(missing_ok=True)


@pytest.mark.integration
def test_the_legacy_secondary_replay_still_drives_without_a_seed(tmp_path, mock_base_url):
    """The v1 path is what drives the natural-random secondary points on the
    meter, and making `--seed` optional touched it. So it is driven, not just
    argument-parsed.

    Duration is >10s because the legacy reader's warmup placeholder is 10s and
    a shorter schedule leaves no measurement window -- which is the very
    difference between the two formats this change is about.
    """
    from loadgen.corpus import load_corpus
    from loadgen.schedule import build_poisson_schedule

    frozen = tmp_path / "secondary_probe.schedule.json"
    build_poisson_schedule(5.0, 12.0, 4242, load_corpus()).save(frozen)

    proc = subprocess.run(
        [sys.executable, "-m", "loadgen.poisson",
         "--schedule-in", str(frozen),
         "--base-url", mock_base_url, "--model", "mock",
         "--log-dir", str(tmp_path / "out"), "--schedule-dir", str(tmp_path / "out"),
         "--tag", "secondary_probe"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300)

    assert proc.returncode == 0, f"legacy replay failed:\n{proc.stderr[-2000:]}"
    record = json.loads((tmp_path / "out" / "secondary_probe.metrics.json")
                        .read_text(encoding="utf-8"))
    # Offered RPS came off the frozen artifact, not off a flag.
    assert record["offered_rps"] == 5.0
    # And it is still read by the LEGACY reader, which has no session #2 gates.
    assert "exact_n_honoured" not in record
    assert record["warmup_n_s"] == 10.0


# ---------------------------------------------------------------------------
# The documented seam: which command the runbook names, and what it dispatches.
# ---------------------------------------------------------------------------


def test_the_runbook_tier_a_command_exists_in_both_scripts():
    runbook = (REPO_ROOT / "WEEK2_GPU_SESSION_2_PLAN.md").read_text(encoding="utf-8")
    local = (GPU_SESSION / "run_on_instance.sh").read_text(encoding="utf-8")
    remote = (GPU_SESSION / "remote_loadgen.sh").read_text(encoding="utf-8")

    assert "run_on_instance.sh scout \\" in runbook, (
        "the runbook's Tier A step must name the command that actually drives a scout point")
    assert "scout)" in local and "cmd_scenario" in local
    assert "scout)" in remote and "cmd_v2_scenario" in remote
    assert "drive_scenario_point.py" in remote, (
        "the remote scout command must reach the session #2 driver")


def test_the_runbook_no_longer_routes_tier_a_through_the_legacy_runner():
    """The exact regression: `run <scout schedule>` in the runbook."""
    runbook = (REPO_ROOT / "WEEK2_GPU_SESSION_2_PLAN.md").read_text(encoding="utf-8")
    flattened = " ".join(runbook.split())
    assert "run_on_instance.sh run benchmarks/schedules/week2_redesign/scout" not in flattened, (
        "the runbook drives a Tier A scout schedule through the legacy `run` command")


def _run_remote(tmp_path, *argv) -> subprocess.CompletedProcess:
    """Invoke the real remote-side script the way the ssh command does."""
    return subprocess.run(
        ["bash", str(GPU_SESSION / "remote_loadgen.sh"), *argv],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        env={**dict(__import__("os").environ),
             "VENV_DIR": str(REPO_ROOT / ".venv"),
             "REPO_DIR": str(REPO_ROOT),
             "ARTIFACT_ROOT": str(tmp_path / "artifacts")},
    )


def test_control_run_refuses_a_session_2_schedule(tmp_path):
    """The legacy runner must not accept a v2 artifact at all. Before this
    change it accepted one and died on a KeyError; a silent success would be
    worse."""
    proc = _run_remote(tmp_path, "run",
                       str(SCOUT_DIR / "headline_r1_rps1.schedule.json"), "probe")
    assert proc.returncode != 0
    assert "Session #2 schedule" in proc.stderr
    assert "scout" in proc.stderr, "the refusal must name the command that does work"


def test_control_scout_refuses_a_legacy_schedule(tmp_path):
    """And the reverse: a v1 artifact has no frozen warmup boundary to read,
    so the session #2 path must not pretend it does."""
    proc = _run_remote(tmp_path, "scout", str(SECONDARY), "probe")
    assert proc.returncode != 0
    assert "not headline-schedule-v2" in proc.stderr


# ---------------------------------------------------------------------------
# The frozen scout family's own contract.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(p.name for p in SCOUT_DIR.glob("*.schedule.json")))
def test_every_committed_scout_schedule_is_frozen_at_60s_and_n500(name):
    prov = json.loads((SCOUT_DIR / name).read_text(encoding="utf-8"))["provenance"]
    assert prov["schedule_scheme_version"] == "headline-schedule-v2"
    assert prov["warmup_boundary_s"] == SCOUT_WARMUP_BOUNDARY_S
    assert prov["post_warmup_target_count"] == SCOUT_N
    assert prov["materialized_post_warmup_count"] == SCOUT_N
    assert prov["canonical_prompt_membership_id"] == SCOUT_MEMBERSHIP, (
        "the scout family is separately namespaced so it can never be mistaken for headline "
        "evidence")


def test_the_scout_workload_is_not_the_headline_workload():
    headline = json.loads(
        (REPO_ROOT / "benchmarks" / "schedules" / "week2_redesign" / "headline"
         / "headline_r1_rps2.schedule.json").read_text(encoding="utf-8"))["provenance"]
    assert headline["canonical_prompt_membership_id"] != SCOUT_MEMBERSHIP
    assert headline["post_warmup_target_count"] == 4000


# ---------------------------------------------------------------------------
# Shared semantics: one reader, two authorities.
# ---------------------------------------------------------------------------


def test_neither_driver_reimplements_the_measurement_path():
    """The architectural constraint, checked structurally rather than trusted.

    If either script constructs its own scheduler or calls the point reader
    directly, the two tiers can drift on exactly the semantics that must not
    differ."""
    for script in ("drive_scenario_point.py", "drive_headline_family.py"):
        source = (GPU_SESSION / script).read_text(encoding="utf-8")
        assert "OpenLoopScheduler(" not in source, (
            f"{script} builds its own scheduler instead of using "
            "loadgen/redesign_point.py")
        assert "headline_point_metrics(" not in source, (
            f"{script} calls the point reader directly instead of using "
            "loadgen/redesign_point.py")
        assert "drive_redesign_point" in source


def test_evidence_class_changes_authority_and_nothing_else():
    """The same inputs read as scout and as headline must differ in exactly
    two fields. This is the proof that Tier A's bracket is expressed in the
    units Tier B confirms in."""
    from metrics.headline_point import (
        HEADLINE_EVIDENCE,
        SCOUT_DIAGNOSTIC,
        headline_point_metrics,
    )

    prov = {
        "nominal_lambda_rps": 2.0,
        "warmup_boundary_s": 60.0,
        "materialized_schedule_count": 606,
        "materialized_post_warmup_count": 500,
        "post_warmup_target_count": 500,
        "materialized_schedule_duration_s": 312.85,
        "canonical_prompt_membership_id": SCOUT_MEMBERSHIP,
        "repeat_id": 1,
        "arrival_seed": 20260819001,
        "assignment_seed": 20260819501,
    }
    raw = [{"request_id": i, "status": "sent", "send_time": 60.0 + i * 0.5}
           for i in range(500)]
    samples = [{"request_id": i, "send_time": 60.0 + i * 0.5, "ttft_ms": 100.0 + i}
               for i in range(500)]

    offsets = [60.0 + i * 0.5 for i in range(500)]
    as_scout = headline_point_metrics(raw, samples, prov, 60.0, offsets,
                                      evidence_class=SCOUT_DIAGNOSTIC)
    as_headline = headline_point_metrics(raw, samples, prov, 60.0, offsets,
                                         evidence_class=HEADLINE_EVIDENCE)

    differing = {k for k in as_scout if as_scout[k] != as_headline[k]}
    assert differing == {"evidence_class", "may_define_headline_breach"}, (
        f"scout and headline records differ in {differing - {'evidence_class', 'may_define_headline_breach'}} "
        "-- the measurement semantics must be identical")
    assert as_scout["ttft_p99_ms"] == as_headline["ttft_p99_ms"]
    assert as_scout["warmup_boundary_s"] == 60.0


def test_both_tiers_enter_the_shared_path_with_schedule_derived_arguments(
        scout_driver, corpus, tmp_path, monkeypatch):
    """Captured at the seam: whatever each tier passes into the shared driver.

    Everything that describes the workload must be the schedule's, and both
    tiers must hand over the same thing. The only argument permitted to differ
    is the evidence class."""
    headline_driver = _load_script("drive_headline_family")
    schedule_path, schedule = _tiny_scout_schedule(tmp_path, corpus)

    captured: list[dict] = []

    def _capture(sched, _corpus, **kwargs):
        captured.append({"provenance": sched.provenance, **kwargs})
        return {  # enough for the callers' reporting to run
            "ttft_p99_ms": 1.0, "point_state": "UNDER", "ttft_censoring_rate": 0.0,
            "exact_n_honoured": True, "schedule_delivery_ok": True,
            "n_shed_total": 0, "evidence_class": kwargs["evidence_class"],
            "may_define_headline_breach": kwargs["evidence_class"] == "headline_evidence",
            "canonical_prompt_membership_id": sched.provenance[
                "canonical_prompt_membership_id"],
            "nominal_lambda_rps": sched.provenance["nominal_lambda_rps"],
            "warmup_boundary_s": sched.provenance["warmup_boundary_s"],
            "post_warmup_target_count": sched.provenance["post_warmup_target_count"],
            "materialized_post_warmup_count": sched.provenance[
                "materialized_post_warmup_count"],
            "schedule_delivery_divergence_pct": 0.0,
            "provenance": {"n_sent": 1, "n_errored": 0, "n_scheduled_driven": 1, "n_shed": 0},
        }

    monkeypatch.setattr(scout_driver, "drive_redesign_point", _capture)
    monkeypatch.setattr(headline_driver, "drive_redesign_point", _capture)

    import argparse
    tier_b_args = argparse.Namespace(
        base_url="http://127.0.0.1:1", model="mock", concurrency_cap=3000,
        timeout_s=60.0, extra_body=None, warmup_n_s=None, process_epoch="test-epoch",
        schedule_dir=str(schedule_path.parent))
    headline_driver.drive_point(schedule, corpus, tier_b_args, tmp_path / "b", "tag_b")

    verdict = tmp_path / "v.json"
    verdict.write_text(json.dumps({"verdict": "PREFIX_CACHING_DISABLED", "min_ratio": 0.99}),
                       encoding="utf-8")
    # A COMMITTED scout schedule, because the driver validates membership
    # against the scenario contract. Nothing is actually sent -- the stub above
    # replaced the driving core -- so this costs no time.
    real_scout = SCOUT_DIR / "headline_r1_rps1.schedule.json"
    old_argv = sys.argv
    sys.argv = ["drive_scenario_point.py", "--scenario", "scout",
                "--schedule", str(real_scout),
                "--out-dir", str(tmp_path / "a"), "--base-url", "http://127.0.0.1:1",
                "--model", "mock", "--prefix-cache-verdict", str(verdict)]
    try:
        scout_driver.main()
    finally:
        sys.argv = old_argv

    assert len(captured) == 2
    tier_b, tier_a = captured
    assert tier_b["evidence_class"] == "headline_evidence"
    assert tier_a["evidence_class"] == "scout_diagnostic"

    # Every workload-describing value came off the schedule each tier was
    # handed -- not from a CLI default, and not from the tier's identity. The
    # two sides were handed DIFFERENT schedules here, so this also shows the
    # values track the artifact rather than the command.
    assert tier_b["provenance"]["post_warmup_target_count"] == \
        schedule.provenance["post_warmup_target_count"]
    assert tier_b["provenance"]["warmup_boundary_s"] == \
        schedule.provenance["warmup_boundary_s"]
    assert tier_a["provenance"]["post_warmup_target_count"] == SCOUT_N
    assert tier_a["provenance"]["warmup_boundary_s"] == SCOUT_WARMUP_BOUNDARY_S

    for key in ("warmup_n_s", "concurrency_cap", "timeout_s", "model"):
        assert tier_a[key] == tier_b[key], f"tiers disagree on {key}"
    assert tier_a["warmup_n_s"] is None, (
        "neither tier may pass a warmup value; the shared path reads the frozen boundary")


def test_control_an_unknown_evidence_class_is_refused():
    from metrics.headline_point import headline_point_metrics

    with pytest.raises(ValueError, match="unknown evidence_class"):
        headline_point_metrics([], [], {
            "nominal_lambda_rps": 1.0, "warmup_boundary_s": 60.0,
            "materialized_schedule_count": 1, "materialized_post_warmup_count": 1,
            "post_warmup_target_count": 1, "materialized_schedule_duration_s": 100.0,
        }, 60.0, [60.0], evidence_class="probably_fine")


# ---------------------------------------------------------------------------
# Diagnostic-only: scout records cannot become a breach verdict.
# ---------------------------------------------------------------------------


def _spec(membership=SCOUT_MEMBERSHIP, n=SCOUT_N):
    from metrics.classification import HeadlineEvidenceSpec
    return HeadlineEvidenceSpec(membership_id=membership, percentile_population_n=n)


def _policy(**kw):
    from metrics.classification import RepeatPolicy
    kw.setdefault("headline", _spec())
    return RepeatPolicy(**kw)


def _record(evidence_class, repeat_id=1, state="UNDER"):
    """A record complete enough to be *accepted*, so a rejection test is
    isolating the one field it removed rather than passing on a technicality."""
    return {
        "record_version": "headline-point-v1",
        "evidence_class": evidence_class,
        "may_define_headline_breach": evidence_class == "headline_evidence",
        "schedule_scheme_version": "headline-schedule-v2",
        "process_epoch": "vllm-start-1000",
        "percentile_population_n": SCOUT_N,
        "repeat_id": repeat_id,
        "nominal_lambda_rps": 2.0,
        "canonical_prompt_membership_id": SCOUT_MEMBERSHIP,
        "arrival_seed": 1000 + repeat_id,
        "assignment_seed": 2000 + repeat_id,
        "point_state": state,
        "point_state_reason": "synthetic",
        "ttft_p99_ms": 410.0,
        "ttft_censoring_rate": 0.0,
        "schedule_delivery_ok": True,
        "exact_n_honoured": True,
        "tail_censoring_warning": False,
    }


def test_control_classification_refuses_scout_records():
    """The gate that makes 'diagnostic only' structural rather than a caption.

    A scout record carries the same `point_state` vocabulary as a headline one
    and its filenames (`headline_r1_rps2...`) look the same on disk, so the
    refusal cannot rest on either."""
    from metrics.classification import classify_point
    from metrics.headline_point import SCOUT_DIAGNOSTIC

    records = [_record(SCOUT_DIAGNOSTIC, r) for r in (1, 2, 3)]
    with pytest.raises(ValueError, match="not session #2 headline evidence"):
        classify_point(records, _policy())


def test_control_one_scout_record_poisons_an_otherwise_headline_family():
    """The realistic failure: two headline repeats plus a scout point pulled in
    from the neighbouring directory to make up the third."""
    from metrics.classification import classify_point
    from metrics.headline_point import HEADLINE_EVIDENCE, SCOUT_DIAGNOSTIC

    records = [_record(HEADLINE_EVIDENCE, 1), _record(HEADLINE_EVIDENCE, 2),
               _record(SCOUT_DIAGNOSTIC, 3)]
    with pytest.raises(ValueError, match="not session #2 headline evidence"):
        classify_point(records, _policy())


def test_headline_records_still_classify():
    """The paired positive: the gate must not have made classification
    impossible."""
    from metrics.classification import classify_point
    from metrics.headline_point import HEADLINE_EVIDENCE

    records = [_record(HEADLINE_EVIDENCE, r) for r in (1, 2, 3)]
    aggregate = classify_point(records, _policy(min_valid_repeats=3))
    assert aggregate.state == "UNDER"
    assert all(r["evidence_class"] == HEADLINE_EVIDENCE
               for r in aggregate.to_dict()["per_repeat"])


# ---------------------------------------------------------------------------
# Driven end to end, against the mock.
# ---------------------------------------------------------------------------


# Deliberately NOT 60. The driver must read the boundary off the schedule, and
# a test that used the real value would pass just as happily against a driver
# that hard-coded it.
#
# 10s rather than something smaller because the client's own startup transient
# -- first connections, mock warm-up -- lags the earliest sends by a few
# hundred ms. A boundary inside that transient sees arrivals scheduled just
# before it get *sent* just after, which counts them into the measured window
# and fails the ±5% delivery gate for a reason that is the fixture's, not the
# driver's. Measured: a 2s boundary lands +11.7%, a 10s boundary +0.00%. The
# real 60s boundary is far clear of it, which is part of why 60 was chosen.
FIXTURE_WARMUP_S = 10.0


def _tiny_scout_schedule(tmp_path, corpus, *, warmup_s=FIXTURE_WARMUP_S, n=40, rps=10.0):
    """A real v2 schedule from the real generator, sized to be drivable.

    Not a hand-written dict: `build_headline_schedule` is what produced the
    committed family, so this exercises the same materialization. Only the
    boundary and N are small.
    """
    import hashlib

    from loadgen.canonical import CANONICAL_SCHEME_VERSION, membership_id
    from loadgen.headline_schedule import (
        RepeatIdentity,
        build_headline_schedule,
        save_headline_schedule,
    )

    members = [p.prompt_id for p in corpus.prompts[:n]]
    workload = {
        "scheme_version": CANONICAL_SCHEME_VERSION,
        "membership_id": membership_id(members),
        "membership": members,
        "locks": {"N": n, "L_pct": 99.0, "L_chars": 11471.37, "k": 6, "N_max": 5000},
        "corpus": {
            "sha256": hashlib.sha256(corpus.source_path.read_bytes()).hexdigest(),
            "size": len(corpus),
        },
    }
    identity = RepeatIdentity(canonical_membership_id=workload["membership_id"],
                              repeat_id=1, arrival_seed=4242, assignment_seed=8484)
    schedule = build_headline_schedule(
        canonical=workload, corpus=corpus, identity=identity,
        nominal_lambda_rps=rps, warmup_s=warmup_s)
    directory = tmp_path / "frozen"
    directory.mkdir(parents=True, exist_ok=True)
    path, _digest = save_headline_schedule(schedule, directory)
    return path, schedule


def _drive_real(scout_driver, schedule_path, out_dir, base_url, verdict, extra=()):
    """Through the documented command, for a COMMITTED schedule.

    `drive_scenario_point.py` validates the artifact against the scenario
    contract, which includes membership -- so it only accepts a real frozen
    workload. That is the behaviour under test in the seam cases; the
    synthetic-schedule cases below use `_drive_core` instead.
    """
    argv = ["drive_scenario_point.py",
            "--scenario", "scout",
            "--schedule", str(schedule_path),
            "--out-dir", str(out_dir),
            "--base-url", base_url,
            "--model", "mock",
            "--prefix-cache-verdict", str(verdict),
            *extra]
    old = sys.argv
    sys.argv = argv
    try:
        scout_driver.main()
    finally:
        sys.argv = old
    tag = Path(schedule_path).name[: -len(".schedule.json")]
    return json.loads((Path(out_dir) / f"{tag}.metrics.json").read_text(encoding="utf-8"))


def _drive_core(schedule, corpus, out_dir, tag, base_url, evidence_class="scout_diagnostic",
                **kw):
    """The shared measurement core, for a synthetic schedule.

    Exercises exactly what the scenario driver delegates to -- the scheduler,
    the membership rule and the record -- without the contract check, which a
    synthetic workload cannot satisfy and is not what these cases are about.
    """
    from loadgen.redesign_point import drive_redesign_point

    return drive_redesign_point(
        schedule, corpus, out_dir=Path(out_dir), tag=tag, evidence_class=evidence_class,
        base_url=base_url, model="mock", process_epoch="test-epoch", **kw)


@pytest.mark.integration
def test_a_scout_point_drives_and_produces_the_session_2_record(
        scout_driver, corpus, tmp_path, mock_base_url, cache_verdict):
    """The whole seam, end to end: frozen v2 schedule in, three artifacts and
    a gated record out."""
    schedule_path, schedule = _tiny_scout_schedule(tmp_path, corpus)
    out_dir = tmp_path / "scout"
    tag = schedule_path.name[: -len(".schedule.json")]
    record = _drive_core(schedule, corpus, out_dir, tag, mock_base_url)

    prov = schedule.provenance

    # The three artifacts the runbook's §11 gate requires per driven point.
    for suffix in ("raw_log.jsonl", "samples.jsonl", "metrics.json"):
        assert (out_dir / f"{tag}.{suffix}").exists(), f"missing {suffix}"

    # Warmup came off the schedule, not off a CLI default. The legacy path
    # would have recorded 10.0 here.
    assert record["warmup_boundary_s"] == prov["warmup_boundary_s"] == FIXTURE_WARMUP_S
    assert record["warmup_n_s_applied"] == FIXTURE_WARMUP_S
    assert FIXTURE_WARMUP_S != SCOUT_WARMUP_BOUNDARY_S, (
        "the fixture must not use the real boundary, or this cannot tell a driver that "
        "reads the schedule from one that hard-codes 60")

    # The session #2 validity gates exist AND pass on a clean run.
    assert record["exact_n_honoured"] is True
    assert record["schedule_delivery_ok"] is True
    assert record["post_warmup_target_count"] == prov["post_warmup_target_count"]
    assert record["n_shed_total"] == 0
    assert record["ttft_censoring_rate"] == 0.0

    # Identity travelled with the schedule.
    assert record["canonical_prompt_membership_id"] == prov["canonical_prompt_membership_id"]
    assert record["arrival_seed"] == prov["arrival_seed"]
    assert record["assignment_seed"] == prov["assignment_seed"]
    # Same percentile convention Tier B classifies under -- on a near-boundary
    # sample the convention alone flips UNDER/OVER, so a bracket read under a
    # different one would not be a bracket Tier B can use.
    assert record["percentile"]["percentile_method"] == "nearest_rank"

    # Diagnostic, and it says so.
    assert record["evidence_class"] == "scout_diagnostic"
    assert record["may_define_headline_breach"] is False


@pytest.mark.integration
def test_a_driven_scout_record_is_refused_by_classification(
        scout_driver, corpus, tmp_path, mock_base_url, cache_verdict):
    """Not a synthetic record this time -- the actual file the driver wrote."""
    from metrics.classification import classify_point

    schedule_path, schedule = _tiny_scout_schedule(tmp_path, corpus)
    record = _drive_core(schedule, corpus, tmp_path / "scout2",
                         schedule_path.name[: -len(".schedule.json")], mock_base_url)
    spec = _spec(membership=record["canonical_prompt_membership_id"],
                 n=record["percentile_population_n"])
    # Even with a policy whose spec matches this record's OWN workload and N,
    # it is refused -- the refusal rests on declared authority, not identity.
    with pytest.raises(ValueError, match="not session #2 headline evidence"):
        classify_point([record], _policy(min_valid_repeats=1, headline=spec))


@pytest.mark.integration
def test_control_a_shedding_point_fails_the_delivery_gate(
        scout_driver, corpus, tmp_path, mock_base_url, cache_verdict):
    """Negative control for `schedule_delivery_ok`.

    Same driver, same schedule, one knob: a concurrency cap of 1 makes the
    driver shed nearly everything it was supposed to send. If the gate did not
    bite, a point that never delivered its schedule would still read as valid
    evidence."""
    schedule_path, schedule = _tiny_scout_schedule(tmp_path, corpus, n=40, rps=40.0)
    record = _drive_core(schedule, corpus, tmp_path / "shed",
                         schedule_path.name[: -len(".schedule.json")], mock_base_url,
                         concurrency_cap=1)

    assert record["n_shed_total"] > 0, "the cap did not bite; the control proves nothing"
    assert record["schedule_delivery_ok"] is False
    assert record["schedule_delivery_divergence_pct"] < -5.0


@pytest.mark.integration
def test_tier_b_still_drives_and_still_produces_headline_evidence(
        corpus, tmp_path, mock_base_url):
    """Tier B was refactored onto the shared path; this drives it for real.

    The expensive tier is the one that must not have moved, so its record is
    checked field by field against the same gates Tier A now reports — and its
    evidence class must still be the one classification accepts."""
    import argparse

    from metrics.classification import classify_point

    headline_driver = _load_script("drive_headline_family")
    schedule_path, schedule = _tiny_scout_schedule(tmp_path, corpus)
    out_dir = tmp_path / "tier_b"
    args = argparse.Namespace(
        base_url=mock_base_url, model="mock", concurrency_cap=3000, timeout_s=60.0,
        extra_body=None, warmup_n_s=None, process_epoch="test-epoch",
        schedule_dir=str(schedule_path.parent))

    tag = schedule_path.name[: -len(".schedule.json")]
    record = headline_driver.drive_point(schedule, corpus, args, out_dir, tag)

    for suffix in ("raw_log.jsonl", "samples.jsonl", "metrics.json"):
        assert (out_dir / f"{tag}.{suffix}").exists()
    assert record["warmup_boundary_s"] == schedule.provenance["warmup_boundary_s"]
    assert record["exact_n_honoured"] is True
    assert record["schedule_delivery_ok"] is True
    assert record["evidence_class"] == "headline_evidence"
    assert record["may_define_headline_breach"] is True

    # And it is still classifiable, which is the whole point of the tier.
    spec = _spec(membership=record["canonical_prompt_membership_id"],
                 n=record["percentile_population_n"])
    assert classify_point([record], _policy(min_valid_repeats=1,
                                            headline=spec)).state in ("UNDER", "OVER")


def test_control_a_broken_exact_n_schedule_is_refused_before_sending(tmp_path, corpus):
    """Exact-N is checked against the frozen artifact before any request goes
    out, in both tiers -- driving it would spend meter time on a point that
    classification must exclude anyway."""
    from loadgen.redesign_point import RedesignScheduleError, require_exact_n

    _path, schedule = _tiny_scout_schedule(tmp_path, corpus)
    prov = dict(schedule.provenance)
    require_exact_n("clean", prov)  # the paired positive

    prov["materialized_post_warmup_count"] = prov["post_warmup_target_count"] - 1
    with pytest.raises(RedesignScheduleError, match="exact-N contract is broken"):
        require_exact_n("tampered", prov)


# ---------------------------------------------------------------------------
# The real committed artifact, driven.
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
def test_the_real_committed_scout_schedule_drives_at_60s_and_n500(
        scout_driver, tmp_path, mock_base_url, cache_verdict):
    """Everything above uses a small schedule so the contract can be tested
    quickly. This one drives the artifact that will actually run on the meter.

    λ=16 is chosen because it is the shortest committed scout point (88.9s);
    the contract does not depend on λ, but the frozen 60s boundary and N=500
    do, and those are the two values the fast tests deliberately cannot pin.
    """
    schedule_path = SCOUT_DIR / "headline_r1_rps16.schedule.json"
    out_dir = tmp_path / "real_scout"
    record = _drive_real(scout_driver, schedule_path, out_dir, mock_base_url, cache_verdict)

    assert record["warmup_boundary_s"] == SCOUT_WARMUP_BOUNDARY_S
    assert record["warmup_n_s_applied"] == SCOUT_WARMUP_BOUNDARY_S
    assert record["post_warmup_target_count"] == SCOUT_N
    assert record["materialized_post_warmup_count"] == SCOUT_N
    assert record["exact_n_honoured"] is True
    assert record["schedule_delivery_ok"] is True

    # Exactly N, not "within the band". Before membership became
    # schedule-based this run measured 510 sends at or after the boundary
    # against a frozen N of 500 (+2.0%) -- ten warmup arrivals that lag had
    # pushed across it. The population is now a property of the committed
    # artifact, so a clean run reconciles perfectly.
    assert record["actual_sent_count"] == SCOUT_N
    assert record["percentile_population_n"] == SCOUT_N
    assert record["reconciled_measurement_n"] == SCOUT_N
    assert record["schedule_delivery_divergence_pct"] == 0.0
    assert record["late_warmup_sends"] > 0, (
        "this fixture is only meaningful while the dev box still lags at the boundary -- "
        "if it stops, the test no longer proves membership survived the lag")
    assert record["canonical_prompt_membership_id"] == SCOUT_MEMBERSHIP
    assert record["evidence_class"] == "scout_diagnostic"
    assert record["may_define_headline_breach"] is False

    tag = schedule_path.name[: -len(".schedule.json")]
    for suffix in ("raw_log.jsonl", "samples.jsonl", "metrics.json"):
        assert (out_dir / f"{tag}.{suffix}").exists()
    assert (out_dir / f"{tag}.scout_report.json").exists()

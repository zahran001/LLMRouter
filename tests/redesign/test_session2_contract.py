"""The runbook is an executable system, stage by stage (Phase E).

The original failure this whole remediation descends from was not a wrong
number. It was a **documented command that had never been run**: the runbook
named `run_on_instance.sh run <scout schedule>`, the command looked entirely
plausible, and it died on a `KeyError` before sending a single request. Every
individual function it called was tested. The seam between them was not.

So this file tests the runbook as a system. For each stage it asks the four
questions a session actually depends on:

    1. is there a real command?
    2. is there a committed input it accepts?
    3. does the input carry the role that stage requires?
    4. does the stage produce the artifacts the §11 gate demands, with the
       right evidence authority?

and then the cross-role controls: every way one stage's input could be fed to
another stage. Those are the cases where both the command and the artifact are
individually valid, which is exactly when a wrong pairing produces a complete,
plausible, wrong result.

GPU-free. The drivable stages run against the mock; the rest are checked as
command/artifact contracts.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GPU_SESSION = REPO_ROOT / "scripts" / "gpu_session"
SCHEDULE_ROOT = REPO_ROOT / "benchmarks" / "schedules" / "week2_redesign"
RUNBOOK = REPO_ROOT / "WEEK2_GPU_SESSION_2_PLAN.md"

sys.path.insert(0, str(GPU_SESSION))

pytestmark = pytest.mark.redesign

LOCAL = GPU_SESSION / "run_on_instance.sh"
REMOTE = GPU_SESSION / "remote_loadgen.sh"


# Every stage of §2's sequence: the command, the committed input it drives,
# and the evidence class the resulting record must carry.
STAGES = [
    ("verify-cache", None, None,
     "L6 gate. No point of any kind may run before it passes."),
    ("floor", None, "floor_diagnostic",
     "Unloaded intrinsic floor over the canonical membership, concurrency 1."),
    ("scout", "scout/headline_r1_rps1.schedule.json", "scout_diagnostic",
     "Tier A. Locates the crossing region."),
    ("headline", "headline/headline_r1_rps2.schedule.json", "headline_evidence",
     "Tier B. Defines the breach."),
    ("secondary", "secondary_natural/secondary_rps2.schedule.json", "secondary_diagnostic",
     "Natural-random realism check."),
    ("steady", "secondary_steady/secondary_steady_rps2.schedule.json", "secondary_diagnostic",
     "Steady arrival-process reference."),
    ("adversarial", "adversarial/adversarial_rps2.schedule.json", "adversarial_diagnostic",
     "Long-context flood. Runs LAST."),
]


# ---------------------------------------------------------------------------
# 1-9. Every stage has a command.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", [s[0] for s in STAGES])
def test_every_stage_has_a_command_in_both_scripts(command):
    local = LOCAL.read_text(encoding="utf-8")
    remote = REMOTE.read_text(encoding="utf-8")
    assert f"  {command})" in local, f"run_on_instance.sh cannot dispatch '{command}'"
    assert f"  {command})" in remote, f"remote_loadgen.sh cannot dispatch '{command}'"


@pytest.mark.parametrize("command,rel,_evidence,_role", STAGES)
def test_every_stage_has_a_committed_input(command, rel, _evidence, _role):
    if rel is None:
        return  # verify-cache and floor take no schedule; covered separately
    path = SCHEDULE_ROOT / rel
    assert path.exists(), f"stage '{command}' names an input that is not committed: {rel}"


def test_the_stages_without_a_schedule_have_their_own_frozen_input():
    """`verify-cache` and `floor` both read the canonical headline workload
    rather than a schedule -- so their input still has to be committed."""
    workload = REPO_ROOT / "benchmarks" / "workloads" / "week2_headline" / "canonical_v1.json"
    assert workload.exists()
    for script in ("verify_prefix_cache_disabled.py", "drive_unloaded_floor.py"):
        source = (GPU_SESSION / script).read_text(encoding="utf-8")
        assert "week2_headline" in source and "canonical_v1.json" in source


def test_the_artifact_pull_and_teardown_stages_exist():
    assert (GPU_SESSION / "pull_artifacts.sh").exists()
    assert (GPU_SESSION / "teardown_week2.sh").exists()
    pull = (GPU_SESSION / "pull_artifacts.sh").read_text(encoding="utf-8")
    assert "completeness check" in pull
    assert "discover_tags" in pull, (
        "the completeness check must handle fractional tags like rps1.5 -- every session #2 "
        "headline tag is fractional or repeat-tagged")


def test_the_teardown_dry_run_resolves_the_week_2_instance():
    proc = subprocess.run(
        ["bash", str(GPU_SESSION / "teardown_week2.sh")],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300,
        env={**dict(__import__("os").environ), "DRY_RUN": "1"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "llmrouter-vllm-l4-week2" in proc.stdout, (
        "the wrapper must own Week 2's instance name; bare teardown.sh defaults to Week 1's "
        "and would leave the meter running")


# ---------------------------------------------------------------------------
# Every documented command actually exists.
# ---------------------------------------------------------------------------


def test_every_command_the_runbook_names_is_dispatchable():
    """The literal regression. The runbook named a command that had never been
    exercised against a real session #2 artifact."""
    import re

    runbook = RUNBOOK.read_text(encoding="utf-8")
    local = LOCAL.read_text(encoding="utf-8")

    named = set(re.findall(r"run_on_instance\.sh\s+([a-z][a-z-]*)", runbook))
    assert named, "the runbook names no commands at all -- the regex has drifted"

    for command in sorted(named):
        assert f"  {command})" in local, (
            f"the runbook tells an operator to run '{command}', and run_on_instance.sh "
            "cannot dispatch it")


def test_every_schedule_the_runbook_names_is_committed():
    import re

    runbook = RUNBOOK.read_text(encoding="utf-8")
    named = set(re.findall(r"(benchmarks/schedules/\S+\.schedule\.json)", runbook))
    assert named, "the runbook names no schedules -- the regex has drifted"
    for rel in sorted(named):
        assert (REPO_ROOT / rel).exists(), f"the runbook names an uncommitted schedule: {rel}"


# ---------------------------------------------------------------------------
# Cross-role controls: the pairings that are individually valid.
# ---------------------------------------------------------------------------


def _check_scenario(scenario: str, rel: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/gpu_session/check_scenario.py",
         "--scenario", scenario, "--schedule", str(SCHEDULE_ROOT / rel)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300)


def _run_remote(tmp_path, *argv) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(REMOTE), *argv],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=600,
        env={**dict(__import__("os").environ),
             "VENV_DIR": str(REPO_ROOT / ".venv"),
             "REPO_DIR": str(REPO_ROOT),
             "ARTIFACT_ROOT": str(tmp_path / "artifacts")})


def test_control_a_v2_scout_schedule_is_rejected_by_the_legacy_run(tmp_path):
    proc = _run_remote(tmp_path, "run",
                       str(SCHEDULE_ROOT / "scout" / "headline_r1_rps1.schedule.json"), "x")
    assert proc.returncode != 0
    assert "Session #2 schedule" in proc.stderr


def test_control_a_v1_schedule_is_rejected_by_scout(tmp_path):
    proc = _run_remote(tmp_path, "scout",
                       str(SCHEDULE_ROOT / "secondary_natural" / "secondary_rps2.schedule.json"),
                       "x")
    assert proc.returncode != 0
    assert "not headline-schedule-v2" in proc.stderr


def test_control_scout_input_cannot_be_driven_as_headline():
    """Same scheme, same workload_class, same filename. Membership is the only
    discriminator, and it is checked."""
    proc = _check_scenario("headline", "scout/headline_r1_rps2.schedule.json")
    assert proc.returncode != 0
    assert "REFUSED" in proc.stderr


def test_control_headline_input_cannot_be_driven_as_scout():
    proc = _check_scenario("scout", "headline/headline_r1_rps2.schedule.json")
    assert proc.returncode != 0


def test_control_a_headline_input_stamped_scout_can_never_classify():
    """The end-to-end version of the authority rule.

    Even if a headline schedule were somehow driven through a diagnostic path,
    the record it produced would carry the diagnostic stamp -- and the
    classifier refuses it. Authority travels with the record, not with the
    workload it happened to measure.
    """
    from metrics.classification import (
        HeadlineEvidenceSpec,
        NotHeadlineEvidence,
        RepeatPolicy,
        classify_point,
    )

    headline_membership = json.loads(
        (REPO_ROOT / "benchmarks" / "workloads" / "week2_headline" / "canonical_v1.json")
        .read_text(encoding="utf-8"))["membership_id"]

    record = {
        "record_version": "headline-point-v1",
        "evidence_class": "scout_diagnostic",       # the stamp
        "may_define_headline_breach": False,
        "schedule_scheme_version": "headline-schedule-v2",
        "process_epoch": "vllm-start-1",
        "percentile_population_n": 4000,            # the headline workload
        "canonical_prompt_membership_id": headline_membership,
        "repeat_id": 1, "arrival_seed": 1, "assignment_seed": 2,
        "nominal_lambda_rps": 2.0, "point_state": "UNDER", "ttft_p99_ms": 400.0,
        "ttft_censoring_rate": 0.0, "schedule_delivery_ok": True, "exact_n_honoured": True,
    }
    policy = RepeatPolicy(min_valid_repeats=1, headline=HeadlineEvidenceSpec(
        membership_id=headline_membership, percentile_population_n=4000))
    with pytest.raises(NotHeadlineEvidence, match="evidence_class"):
        classify_point([record], policy)


@pytest.mark.parametrize("scenario,rel", [
    ("steady", "adversarial/adversarial_rps2.schedule.json"),
    ("adversarial", "secondary_steady/secondary_steady_rps2.schedule.json"),
    ("secondary", "secondary_steady/secondary_steady_rps2.schedule.json"),
    ("steady", "secondary_natural/secondary_rps2.schedule.json"),
])
def test_control_secondary_scenarios_cannot_be_misrouted(scenario, rel):
    proc = _check_scenario(scenario, rel)
    assert proc.returncode != 0, f"'{scenario}' accepted {rel}"


# ---------------------------------------------------------------------------
# The prefix-cache gate blocks every stage that requires it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script,extra", [
    ("drive_scenario_point.py",
     ["--scenario", "scout", "--schedule",
      "benchmarks/schedules/week2_redesign/scout/headline_r1_rps1.schedule.json"]),
    ("drive_unloaded_floor.py", ["--limit", "1"]),
    ("drive_headline_family.py", ["--lambdas", "2"]),
])
def test_control_a_missing_prefix_cache_verdict_blocks_the_stage(script, extra, tmp_path):
    """L6 is structural in every driver, not a step someone remembers."""
    proc = subprocess.run(
        [sys.executable, f"scripts/gpu_session/{script}",
         "--out-dir", str(tmp_path / "out"),
         "--prefix-cache-verdict", str(tmp_path / "absent.json"),
         "--base-url", "http://127.0.0.1:1", *extra],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300)
    assert proc.returncode != 0
    assert "no prefix-cache verdict" in proc.stderr, proc.stderr[-500:]


# ---------------------------------------------------------------------------
# Nothing routes through session #1 measurement semantics.
# ---------------------------------------------------------------------------


def test_no_session_2_stage_reads_through_the_legacy_point_reader():
    """`metrics/point.py` is frozen at session #1 semantics: a 10s warmup
    placeholder, linear percentiles, `tail_valid` instead of censoring, and no
    exact-N gate. No session #2 driver may import it."""
    for script in ("drive_scenario_point.py", "drive_headline_family.py",
                   "drive_unloaded_floor.py"):
        source = (GPU_SESSION / script).read_text(encoding="utf-8")
        assert "metrics.point" not in source, f"{script} imports the frozen legacy reader"
        assert "point_metrics" not in source or "headline_point_metrics" in source or \
            "floor_point_metrics" in source


def test_the_superseded_stage_a_sweep_still_requires_a_typed_confirmation():
    local = LOCAL.read_text(encoding="utf-8")
    assert "SUPERSEDED fixed-duration Stage A sweep" in local
    assert "replay-session-1" in local


def test_the_runbook_never_tells_an_operator_to_generate_a_schedule():
    """Phase D's whole purpose. `bootstrap` refuses a dirty or unpushed tree,
    so generating on the meter costs a commit, a push and a new benchmark SHA
    mid-session."""
    runbook = RUNBOOK.read_text(encoding="utf-8")
    flattened = " ".join(runbook.split())
    for generator in ("generate_headline_schedules.py", "generate_secondary_scenarios.py",
                      "generate_schedules.py"):
        if generator in flattened:
            index = flattened.index(generator)
            window = flattened[max(0, index - 400):index + 200]
            assert any(marker in window for marker in
                       ("offline", "Generated offline", "forbidden", "frozen", "staged")), (
                f"{generator} appears in the runbook without saying it is an offline step")


# ---------------------------------------------------------------------------
# The artifact gate reads the records the session actually produces.
# ---------------------------------------------------------------------------


def _gate_line(tmp_path, record: dict) -> str:
    """Run pull_artifacts.sh's completeness check over one synthetic record."""
    import re as _re

    dest = tmp_path / "runs"
    dest.mkdir(parents=True, exist_ok=True)
    tag = "headline_r1_rps2"
    (dest / f"{tag}.raw_log.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    (dest / f"{tag}.samples.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    (dest / f"{tag}.metrics.json").write_text(json.dumps(record), encoding="utf-8")

    script = (GPU_SESSION / "pull_artifacts.sh").read_text(encoding="utf-8")
    body = script[script.index("python - \"$DEST_DIR\" \"$REPO_ROOT\" <<'PYEOF'")
                  + len("python - \"$DEST_DIR\" \"$REPO_ROOT\" <<'PYEOF'"):]
    body = body[:body.index("\nPYEOF")]
    checker = tmp_path / "checker.py"
    checker.write_text(body, encoding="utf-8")

    proc = subprocess.run([sys.executable, str(checker), str(dest), str(REPO_ROOT)],
                          capture_output=True, text=True, timeout=300)
    return proc.stdout


def test_control_the_artifact_gate_does_not_misreport_a_session_2_point(tmp_path):
    """The gate read `tail_valid` and `breach_500ms` -- fields only the frozen
    session #1 reader writes. Against a session #2 record both were absent and
    therefore falsy, so a BREACHING point printed "under" and every valid point
    printed "TAIL-INVALID". Wrong in both fields, on the meter, at the moment
    §11 asks a human to read the line."""
    breaching = {
        "record_version": "headline-point-v1",
        "evidence_class": "headline_evidence",
        "point_state": "OVER", "ttft_p99_ms": 612.4,
        "percentile_population_n": 4000,
        "exact_n_honoured": True, "schedule_delivery_ok": True,
        "ttft_censoring_rate": 0.0, "n_shed_total": 0,
    }
    out = _gate_line(tmp_path, breaching)
    assert "OVER" in out, f"a breaching session #2 point was not reported as OVER:\n{out}"
    assert "under" not in out, f"a breaching point was reported as 'under':\n{out}"
    assert "TAIL-INVALID" not in out, f"a valid session #2 point was called TAIL-INVALID:\n{out}"
    assert "N=4000" in out


def test_the_artifact_gate_still_reads_a_session_1_record(tmp_path):
    """The paired positive: session #1's promoted artifacts are still read
    under their own semantics."""
    legacy = {"tail_valid": True, "ttft_p99_ms": 402.0, "breach_500ms": False,
              "n_samples_window": 248}
    out = _gate_line(tmp_path, legacy)
    assert "legacy" in out
    assert "under" in out
    assert "TAIL-INVALID" not in out


def test_control_the_gate_no_longer_recommends_the_forbidden_refilter(tmp_path):
    """It used to close with `compute_point_metrics.py --warmup-n <resolved N>`
    -- lock 4A's forbidden post-hoc re-filter, asking for a value that no
    longer exists as a concept."""
    script = (GPU_SESSION / "pull_artifacts.sh").read_text(encoding="utf-8")
    # Executable lines only. The comment explaining WHY the recommendation was
    # removed necessarily names it, and a raw substring check would forbid
    # recording the reason -- which is how the provenance gets deleted to make
    # a test green.
    executable = [line for line in script.splitlines()
                  if line.strip() and not line.lstrip().startswith("#")]
    offenders = [line for line in executable
                 if "--warmup-n" in line or "compute_point_metrics" in line]
    assert not offenders, (
        "the artifact gate recommends the post-hoc warmup re-filter lock 4A forbids: "
        + "; ".join(offenders))
    assert "metrics/classification.py" in script, (
        "it must point at the offline classifier instead")


def test_control_the_pull_command_requires_a_session_tag():
    """It defaulted to session #1's `stage_a`, so a bare invocation pulled a
    session #1 directory and reported it complete while the session #2 points
    stayed on an instance about to be deleted."""
    proc = subprocess.run(["bash", str(GPU_SESSION / "pull_artifacts.sh")],
                          cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300,
                          env={k: v for k, v in __import__("os").environ.items()
                               if k != "SESSION_TAG"})
    assert proc.returncode != 0
    assert "SESSION_TAG is required" in proc.stderr


def test_control_run_refuses_an_artifact_that_has_a_named_scenario(tmp_path):
    """`run` applies no scenario check. Both session #2 v1 families are
    `loadgen-schedule-v1`, so its scheme gate cannot tell them apart --
    `run <adversarial schedule>` under SESSION_TAG=secondary would have driven
    happily and filed the result under a scenario it never measured."""
    for rel, named in [("adversarial/adversarial_rps2.schedule.json", "adversarial"),
                       ("secondary_natural/secondary_rps2.schedule.json", "secondary")]:
        proc = _run_remote(tmp_path, "run", str(SCHEDULE_ROOT / rel), "x")
        assert proc.returncode != 0, f"run accepted {rel}"
        assert named in proc.stderr


def test_the_runbook_states_the_lambda_selection_rule():
    """Tier A's ladder and the frozen headline family do not span the same
    range, so a scout bracket can land where no headline schedule exists. That
    is a value the operator would otherwise have to invent on the meter."""
    runbook = RUNBOOK.read_text(encoding="utf-8")
    flat = " ".join(runbook.split())
    assert "MUST come from {1.5, 2, 2.5, 3, 4}" in flat
    assert "fewer than two frozen headline" in flat, (
        "the no-improvisation matrix needs a row for a bracket outside the frozen family")
    assert "rps5" not in flat or "there is no" in flat

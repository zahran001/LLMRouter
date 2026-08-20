"""The on-instance headline driver's refusals (R4 README R9/L6).

`scripts/gpu_session/drive_headline_family.py` is the piece that sequences a
metered session. Everything it refuses to do is something that would otherwise
produce artifacts that look fine:

- driving with a live prefix cache (the control silently stops controlling);
- driving schedules from two different canonical memberships (the repeats are
  not comparable, but every point record still parses);
- driving a schedule whose post-warmup count is not exactly `N` (the frozen
  contract is already broken before the meter starts).

The drain probe is tested here too, because it is the one part whose obvious
implementation is inert: `OpenLoopScheduler.run()` awaits every send task
before returning, so a client-side in-flight count is always zero by then. The
probe therefore reads the SERVER, and must fail closed when it cannot.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.redesign


@pytest.fixture(scope="module")
def driver():
    spec = importlib.util.spec_from_file_location(
        "_drive_headline_family",
        REPO_ROOT / "scripts" / "gpu_session" / "drive_headline_family.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# L6, enforced by the driver rather than by the human remembering.
# ---------------------------------------------------------------------------


def test_control_a_missing_prefix_cache_verdict_refuses_the_session(driver, tmp_path):
    with pytest.raises(SystemExit, match="no prefix-cache verdict"):
        driver.require_prefix_cache_disabled(tmp_path / "absent.json")


def test_control_an_enabled_prefix_cache_refuses_the_session(driver, tmp_path):
    path = tmp_path / "verdict.json"
    path.write_text(json.dumps({"verdict": "PREFIX_CACHING_ENABLED", "min_ratio": 0.20}),
                    encoding="utf-8")
    with pytest.raises(SystemExit, match="not PREFIX_CACHING_DISABLED"):
        driver.require_prefix_cache_disabled(path)


def test_control_an_ambiguous_verdict_also_refuses(driver, tmp_path):
    """'Not obviously cached' is not evidence of 'not cached'."""
    path = tmp_path / "verdict.json"
    path.write_text(json.dumps({"verdict": "AMBIGUOUS", "min_ratio": 0.80}), encoding="utf-8")
    with pytest.raises(SystemExit, match="not PREFIX_CACHING_DISABLED"):
        driver.require_prefix_cache_disabled(path)


def test_a_disabled_verdict_is_accepted(driver, tmp_path):
    path = tmp_path / "verdict.json"
    path.write_text(json.dumps({"verdict": "PREFIX_CACHING_DISABLED", "min_ratio": 0.98}),
                    encoding="utf-8")
    assert driver.require_prefix_cache_disabled(path)["verdict"] == "PREFIX_CACHING_DISABLED"


# ---------------------------------------------------------------------------
# Family consistency, checked before any request is sent.
# ---------------------------------------------------------------------------


def _write_family(tmp_path: Path, specs: list[dict]) -> Path:
    """Minimal v2 schedules -- enough provenance for discovery to judge them."""
    directory = tmp_path / "headline"
    directory.mkdir(parents=True, exist_ok=True)
    for spec in specs:
        rps = f"{spec['lam']:g}"
        payload = {
            "provenance": {
                "schedule_scheme_version": "headline-schedule-v2",
                "repeat_id": spec["repeat_id"],
                "nominal_lambda_rps": spec["lam"],
                "canonical_prompt_membership_id": spec.get("membership", "m" * 64),
                "arrival_seed": 1000 + spec["repeat_id"],
                "assignment_seed": 2000 + spec["repeat_id"],
                "warmup_boundary_s": 60.0,
                "post_warmup_target_count": spec.get("target", 10),
                "materialized_post_warmup_count": spec.get("materialized", 10),
                "materialized_schedule_count": spec.get("materialized", 10),
                "materialized_schedule_duration_s": 100.0,
            },
            "entries": [{"scheduled_offset": 61.0 + i, "prompt_id": i}
                        for i in range(spec.get("materialized", 10))],
        }
        (directory / f"headline_r{spec['repeat_id']}_rps{rps}.schedule.json").write_text(
            json.dumps(payload), encoding="utf-8")
    return directory


def test_discovery_accepts_a_consistent_family(driver, tmp_path):
    directory = _write_family(tmp_path, [
        {"repeat_id": r, "lam": lam} for r in (1, 2) for lam in (1.5, 2.0)])
    found = driver.discover(directory, [1, 2], [1.5, 2.0])
    assert len(found) == 4


def test_control_a_missing_point_refuses(driver, tmp_path):
    directory = _write_family(tmp_path, [{"repeat_id": 1, "lam": 1.5}])
    with pytest.raises(SystemExit, match="missing schedules"):
        driver.discover(directory, [1], [1.5, 2.0])


def test_control_mixed_canonical_memberships_refuse(driver, tmp_path):
    """Two repeats built against different workloads are not repeats."""
    directory = _write_family(tmp_path, [
        {"repeat_id": 1, "lam": 1.5, "membership": "a" * 64},
        {"repeat_id": 2, "lam": 1.5, "membership": "b" * 64},
    ])
    with pytest.raises(SystemExit, match="canonical memberships"):
        driver.discover(directory, [1, 2], [1.5])


def test_control_a_broken_exact_n_contract_refuses(driver, tmp_path):
    """If the frozen artifact already violates exact-N, driving it would spend
    meter time producing a point that classification must exclude anyway."""
    directory = _write_family(tmp_path, [
        {"repeat_id": 1, "lam": 1.5, "target": 10, "materialized": 9}])
    with pytest.raises(SystemExit, match="exact-N contract is broken"):
        driver.discover(directory, [1], [1.5])


def test_control_a_legacy_v1_schedule_is_not_discoverable_as_headline(driver, tmp_path):
    from loadgen.corpus import load_corpus
    from loadgen.schedule import build_poisson_schedule

    directory = tmp_path / "headline"
    directory.mkdir(parents=True)
    legacy = build_poisson_schedule(2.0, 30.0, 42, load_corpus())
    legacy.save(directory / "headline_r1_rps2.schedule.json")

    from loadgen.headline_schedule import HeadlineScheduleError

    with pytest.raises(HeadlineScheduleError, match="schedule_scheme_version"):
        driver.discover(directory, [1], [2.0])


# ---------------------------------------------------------------------------
# The drain probe reads the server, and fails closed.
# ---------------------------------------------------------------------------


METRICS_BUSY = """\
vllm:num_requests_running{model_name="m"} 12.0
vllm:num_requests_waiting{model_name="m"} 5.0
"""

METRICS_IDLE = """\
vllm:num_requests_running{model_name="m"} 0.0
vllm:num_requests_waiting{model_name="m"} 0.0
"""


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeClient:
    def __init__(self, text):
        self._text = text
        self.closed = False

    def get(self, _url):
        if isinstance(self._text, Exception):
            raise self._text
        return _FakeResponse(self._text)

    def close(self):
        self.closed = True


def _probe(driver, text):
    probe = driver.ServerInflightProbe("http://127.0.0.1:8000")
    probe.client.close()
    probe.client = _FakeClient(text)
    return probe


def test_probe_sums_running_and_waiting(driver):
    assert _probe(driver, METRICS_BUSY)() == 17


def test_probe_reports_idle(driver):
    assert _probe(driver, METRICS_IDLE)() == 0


def test_control_the_probe_fails_closed_when_counters_are_absent(driver):
    """A vLLM build without these metrics must not be able to certify the
    server idle. Returning 0 here would make the drain gate permanently
    green -- worse than having no gate, because it would look like one."""
    with pytest.raises(RuntimeError, match="cannot verify the server is idle"):
        _probe(driver, "vllm:something_else{model_name=\"m\"} 1.0\n")()


def test_the_probe_drives_the_real_drain_gate(driver):
    """Wire the probe to the runner and confirm a busy server blocks a repeat.

    This is the pairing that makes R9 real on the instance: the runner's
    refusal was already tested against a fake counter, and the probe was
    tested against fake metrics text -- this checks they compose.
    """
    from loadgen.repeat_runner import RepeatOverlapError, RepeatPlan, RepeatRunner

    probe = _probe(driver, METRICS_BUSY)
    runner = RepeatRunner(run_point=lambda plan, lam: {}, inflight_probe=probe,
                          sleep=lambda _s: None, clock=lambda: 0.0)
    with pytest.raises(RepeatOverlapError, match="still in flight"):
        runner.run([RepeatPlan(1, 101, 201, [2.0])])


# ---------------------------------------------------------------------------
# The superseded session-#1 sweep is fenced off.
# ---------------------------------------------------------------------------


def test_stage_a_command_warns_and_requires_confirmation():
    """`stage-a` drives the fixed-duration design that cost the first session
    its breach number. It must not be the thing someone runs by muscle
    memory in session #2."""
    script = (REPO_ROOT / "scripts" / "gpu_session"
              / "run_on_instance.sh").read_text(encoding="utf-8")
    assert "SUPERSEDED fixed-duration Stage A sweep" in script
    assert "replay-session-1" in script, "stage-a must require an explicit confirmation"
    assert "run_on_instance.sh headline" in script, (
        "the warning must name the command that replaces it")


def test_the_headline_command_is_wired_end_to_end():
    local = (REPO_ROOT / "scripts" / "gpu_session"
             / "run_on_instance.sh").read_text(encoding="utf-8")
    remote = (REPO_ROOT / "scripts" / "gpu_session"
              / "remote_loadgen.sh").read_text(encoding="utf-8")

    assert "headline)" in local and "cmd_headline" in local
    assert "headline)" in remote and "cmd_headline" in remote
    assert "drive_headline_family.py" in remote
    assert "verify-cache" in local and "verify-cache" in remote, (
        "the L6 gate needs a session command, or it will not be run")

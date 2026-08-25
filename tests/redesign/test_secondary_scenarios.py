"""Steady and adversarial are frozen, committed, and cannot be misrouted
(Phase D).

Lock 6A keeps four scenarios in Week 2's scope. Two of them had no committed
artifact: `loadgen/steady.py` and `loadgen/adversarial.py` could generate one
at runtime, but `run_on_instance.sh bootstrap` refuses a dirty or unpushed
tree, so generating on the meter costs a commit, a push and a new benchmark
SHA mid-session. The GPU session drives frozen inputs only — that is the rule
the lock 5A fallback schedules were committed to satisfy, and it applies here
for the same reason.

The misrouting risk is sharper than it looks. `benchmarks/schedules/week2_redesign/`
now holds five families, and the two that matter most — headline and scout —
are indistinguishable by everything except membership:

    headline/headline_r1_rps2.schedule.json   v2, headline_controlled, a49ecdd8...
    scout/headline_r1_rps2.schedule.json      v2, headline_controlled, e9470f8f...

Same filename. Same scheme. Same workload_class. Only the membership differs,
because a scout point genuinely IS a controlled Poisson draw. So the runtime
validates against the artifact's provenance and never against its path.
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
STEADY_DIR = SCHEDULE_ROOT / "secondary_steady"
ADVERSARIAL_DIR = SCHEDULE_ROOT / "adversarial"
MANIFEST = SCHEDULE_ROOT / "SECONDARY_SCENARIOS_MANIFEST.json"

sys.path.insert(0, str(GPU_SESSION))

pytestmark = pytest.mark.redesign

STEADY_LAMBDAS = [1.5, 2.0, 2.5, 3.0, 4.0, 0.5, 0.75, 1.0, 1.25]
STEADY_N = 500
STEADY_WARMUP_S = 60.0
SCOUT_MEMBERSHIP = "e9470f8f85f228358567c61ae4b0b67040942f4858747cc6076ecea94237de67"
HEADLINE_MEMBERSHIP = "a49ecdd8071920303f240fcf0b8da42dbbc66da593ae88e3c07aa246c4b5aa7b"


# ---------------------------------------------------------------------------
# The artifacts exist, are frozen, and reproduce.
# ---------------------------------------------------------------------------


def test_the_steady_family_is_committed_at_the_decided_lambdas():
    paths = sorted(STEADY_DIR.glob("*.schedule.json"))
    assert len(paths) == len(STEADY_LAMBDAS), f"expected {len(STEADY_LAMBDAS)} steady schedules"

    got = []
    for path in paths:
        prov = json.loads(path.read_text(encoding="utf-8"))["provenance"]
        got.append(prov["nominal_lambda_rps"])
        assert prov["schedule_scheme_version"] == "headline-schedule-v2"
        assert prov["arrival_process"] == "steady"
        assert prov["workload_class"] == "secondary_steady_reference"
        assert prov["warmup_boundary_s"] == STEADY_WARMUP_S
        assert prov["post_warmup_target_count"] == STEADY_N
        assert prov["materialized_post_warmup_count"] == STEADY_N
        assert prov["canonical_prompt_membership_id"] == SCOUT_MEMBERSHIP
        assert prov["never_defines_headline_breach"] is True
        assert prov["corpus_sha256"]
    # Order in STEADY_LAMBDAS matches generator index/seed assignment, not
    # sort order (the new lower anchors are appended, not sorted in, so the
    # original five keep their seeds) -- compare as sets of values.
    assert sorted(got) == sorted(STEADY_LAMBDAS)


def test_steady_gaps_really_are_constant():
    """Otherwise it is not the low-variance reference §2.1 asks for -- it is a
    second Poisson curve with a different seed."""
    path = STEADY_DIR / "secondary_steady_rps2.schedule.json"
    entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
    gaps = [round(b["scheduled_offset"] - a["scheduled_offset"], 9)
            for a, b in zip(entries, entries[1:])]
    assert len(set(gaps)) == 1, f"steady gaps are not constant: {sorted(set(gaps))[:5]}"
    assert gaps[0] == pytest.approx(0.5), "lambda=2 means a 0.5s gap"


def test_the_adversarial_scenario_is_committed_as_one_point():
    paths = sorted(ADVERSARIAL_DIR.glob("*.schedule.json"))
    assert len(paths) == 1, (
        "adversarial is ONE scenario, not a sweep -- WEEK2_PLAN.md §2.2 defers "
        "length-as-independent-variable to Week 3")

    prov = json.loads(paths[0].read_text(encoding="utf-8"))["provenance"]
    assert prov["schedule_scheme_version"] == "loadgen-schedule-v1"
    assert prov["workload_class"] == "adversarial_long_context"
    assert prov["long_context"] is True
    assert prov["target_rps"] == 2.0
    assert prov["duration_s"] == 600.0
    assert prov["never_defines_headline_breach"] is True
    assert "q90" in prov["long_context_selection"]


def test_the_adversarial_draw_really_comes_from_the_long_context_tail():
    """The selection rule is what makes this adversarial. If the draw were the
    natural spread, the scenario would just be a slow Poisson point."""
    from loadgen.corpus import load_corpus

    corpus = load_corpus()
    by_id = {p.prompt_id: p for p in corpus.prompts}
    lengths = sorted(p.char_len for p in corpus.prompts)
    q90 = lengths[int(0.90 * len(lengths))]

    entries = json.loads(
        (ADVERSARIAL_DIR / "adversarial_rps2.schedule.json").read_text(encoding="utf-8"))["entries"]
    drawn = [by_id[e["prompt_id"]].char_len for e in entries]

    assert min(drawn) >= q90 * 0.95, (
        f"adversarial drew a {min(drawn)}-char prompt against a q90 of ~{q90}")
    natural_mean = sum(p.char_len for p in corpus.prompts) / len(corpus.prompts)
    assert sum(drawn) / len(drawn) > natural_mean * 3, (
        "the adversarial draw is not meaningfully longer than the natural spread")


def test_every_committed_scenario_hash_is_in_a_manifest():
    import hashlib

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    listed = {row["path"]: row["sha256"]
              for family in ("steady", "adversarial")
              for row in manifest[family]["schedules"]}

    on_disk = sorted(list(STEADY_DIR.glob("*.schedule.json"))
                     + list(ADVERSARIAL_DIR.glob("*.schedule.json")))
    for path in on_disk:
        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        assert rel in listed, f"{rel} is committed but absent from the manifest"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == listed[rel], f"{rel}: bytes do not match the manifest"
    assert len(listed) == len(on_disk)


def test_the_generator_reproduces_the_committed_bytes():
    """A freeze that cannot be reproduced is a snapshot, not a freeze."""
    proc = subprocess.run(
        [sys.executable, "scripts/generate_secondary_scenarios.py", "--verify"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "VERIFY OK" in proc.stdout


def test_the_headline_and_scout_families_were_not_disturbed():
    """The v2 builder gained a steady mode. The Poisson families must be
    byte-identical to what it produced before."""
    import hashlib

    for manifest_name, families in [("MANIFEST.json", ("headline", "secondary")),
                                    ("SCOUT_MANIFEST.json", ("headline",))]:
        manifest = json.loads((SCHEDULE_ROOT / manifest_name).read_text(encoding="utf-8"))
        for family in families:
            for row in manifest[family]["schedules"]:
                digest = hashlib.sha256((REPO_ROOT / row["path"]).read_bytes()).hexdigest()
                assert digest == row["sha256"], f"{row['path']} changed"


# ---------------------------------------------------------------------------
# The runtime rejects mismatched scenario/schedule pairs.
# ---------------------------------------------------------------------------


def _check(scenario: str, schedule: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/gpu_session/check_scenario.py",
         "--scenario", scenario, "--schedule", str(schedule)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300)


CORRECT = [
    ("headline", "headline/headline_r1_rps2.schedule.json"),
    ("scout", "scout/headline_r1_rps2.schedule.json"),
    ("steady", "secondary_steady/secondary_steady_rps2.schedule.json"),
    ("secondary", "secondary_natural/secondary_rps2.schedule.json"),
    ("adversarial", "adversarial/adversarial_rps2.schedule.json"),
]

MISROUTED = [
    # The pair that shares scheme AND workload_class -- membership is the only
    # thing that separates them, and the filenames are identical.
    ("headline", "scout/headline_r1_rps2.schedule.json"),
    ("scout", "headline/headline_r1_rps2.schedule.json"),
    # v2 scenarios that differ by workload_class.
    ("steady", "scout/headline_r1_rps2.schedule.json"),
    ("scout", "secondary_steady/secondary_steady_rps2.schedule.json"),
    # The two v1 scenarios, which `run` cannot tell apart at all.
    ("adversarial", "secondary_natural/secondary_rps2.schedule.json"),
    ("secondary", "adversarial/adversarial_rps2.schedule.json"),
    # Across the format boundary.
    ("steady", "secondary_natural/secondary_rps2.schedule.json"),
    ("secondary", "secondary_steady/secondary_steady_rps2.schedule.json"),
]


@pytest.mark.parametrize("scenario,rel", CORRECT)
def test_a_scenario_accepts_its_own_schedule(scenario, rel):
    proc = _check(scenario, SCHEDULE_ROOT / rel)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "scenario OK" in proc.stdout


@pytest.mark.parametrize("scenario,rel", MISROUTED)
def test_control_a_scenario_refuses_another_scenarios_schedule(scenario, rel):
    proc = _check(scenario, SCHEDULE_ROOT / rel)
    assert proc.returncode != 0, (
        f"'{scenario}' accepted {rel} -- scenario roles must come from the artifact")
    assert "REFUSED" in proc.stderr


def test_the_contract_table_covers_every_committed_family():
    """A family with no contract could only be driven through `run`, which
    performs no role check at all."""
    from scenario_contract import CONTRACTS

    families = {p.name for p in SCHEDULE_ROOT.iterdir() if p.is_dir()}
    covered = set()
    for name in families:
        schedules = sorted((SCHEDULE_ROOT / name).glob("*.schedule.json"))
        if not schedules:
            continue
        prov = json.loads(schedules[0].read_text(encoding="utf-8"))["provenance"]
        workload_class = prov["workload_class"]
        membership = prov.get("canonical_prompt_membership_id")
        match = [c for c in CONTRACTS.values()
                 if c.workload_class == workload_class
                 and (c.expected_membership() is None
                      or c.expected_membership() == membership)]
        assert match, f"{name}/ has workload_class {workload_class!r} with no scenario contract"
        covered.update(c.name for c in match)

    # `floor` drives no schedule -- it measures the canonical membership
    # directly -- so it has no family here. It is in the table because the
    # table is what pins which workload each stage measures, and the floor's
    # membership is the one the driver enforces.
    schedule_driving = {name for name, c in CONTRACTS.items() if c.scheme is not None}
    assert covered == schedule_driving, f"contracts never matched: {schedule_driving - covered}"
    assert "floor" in CONTRACTS, "the floor's workload must be pinned by the same table"


# ---------------------------------------------------------------------------
# Commands exist and are wired.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", ["scout", "steady", "secondary", "adversarial"])
def test_every_scenario_has_a_wired_command(scenario):
    local = (GPU_SESSION / "run_on_instance.sh").read_text(encoding="utf-8")
    remote = (GPU_SESSION / "remote_loadgen.sh").read_text(encoding="utf-8")
    assert f"  {scenario})" in local, f"run_on_instance.sh has no '{scenario}' command"
    assert f"  {scenario})" in remote, f"remote_loadgen.sh has no '{scenario}' command"


def test_the_v1_scenarios_validate_before_driving():
    remote = (GPU_SESSION / "remote_loadgen.sh").read_text(encoding="utf-8")
    assert "check_scenario.py" in remote, (
        "the legacy v1 path drives through loadgen/_cli.py, which knows nothing about "
        "scenario roles -- without this check `adversarial` would happily drive the "
        "natural-random schedule")


def test_no_scenario_needs_live_generation():
    """The whole point of Phase D: every scenario in the runbook can be driven
    from something already committed."""
    # headline/secondary_steady expanded 2026-08-22: Tier B repeat 1 showed
    # lambda=1.5 already CENSORED (36.2%) at N=4000, so lower anchors
    # {0.5, 0.75, 1.0, 1.25} were added to both families (9 lambdas x 3
    # headline repeats = 27; steady is one schedule per lambda = 9).
    # headline expanded again 2026-08-24 (D-SESSION3-1): session #2 attempt 2
    # left the interval open below 0.75 (NO_UNDER_ANCHOR), so {0.4, 0.6, 0.3}
    # were added to the threshold family (12 lambdas x 3 headline repeats =
    # 36). secondary_steady/secondary_natural/adversarial/scout are NOT
    # re-driven for this extension (WEEK2_CLOSEOUT_PLAN.md Scope Control --
    # they already served their diagnostic purpose), so their counts hold.
    for directory, expected in [("headline", 36), ("scout", 6), ("secondary_natural", 9),
                                ("secondary_steady", 9), ("adversarial", 1)]:
        found = sorted((SCHEDULE_ROOT / directory).glob("*.schedule.json"))
        assert len(found) == expected, f"{directory}/ has {len(found)}, expected {expected}"


def test_every_scenario_artifact_is_actually_tracked_by_git():
    """On DISK is not the property that matters -- `bootstrap` pins the
    instance to a commit and the instance clones from the remote, so an
    untracked schedule does not exist as far as the session is concerned.

    The count test above passes green on a fully untracked tree, which is
    exactly the state this repository was in while claiming "all four drive
    from committed artifacts".
    """
    tracked = subprocess.run(["git", "ls-files", "benchmarks/schedules/week2_redesign"],
                             cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300)
    assert tracked.returncode == 0, tracked.stderr
    known = {line.strip() for line in tracked.stdout.splitlines() if line.strip()}

    untracked = []
    for path in sorted(SCHEDULE_ROOT.rglob("*.json")):
        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        if rel not in known:
            untracked.append(rel)

    assert not untracked, (
        "these session #2 inputs are on disk but not committed, so the GPU instance could "
        f"never clone them: {untracked}")

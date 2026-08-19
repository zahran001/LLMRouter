"""The generic schedule-generation CLI (scripts/generate_schedules.py).

Why this is tested rather than just eyeballed: Stage B's fine schedules are
generated mid-session, on the meter, from a bracket that is only known then.
`run_on_instance.sh bootstrap` pins the instance to a commit and refuses a
dirty tree, so a generator that needed a source edit would either block the
session or cost the "which code drove this sweep" answer BASELINE.md owes.
These tests pin the two argument styles, the argument errors that would
otherwise surface as a confusing traceback mid-session, and -- most
importantly -- that going generic did not loosen any workload lock
(WEEK2_PLAN.md §3.2/§3.4/§5).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

from loadgen.corpus import load_corpus
from loadgen.rng import RNG_SCHEME_VERSION
from loadgen.schedule import SCHEDULE_SCHEME_VERSION, Schedule, build_poisson_schedule
from scripts.generate_schedules import (
    BASELINE_SEED,
    DURATION_S,
    frange,
    generate,
    resolve_rps_points,
)

pytestmark = pytest.mark.loadgen

REPO_ROOT = Path(__file__).resolve().parents[2]


def _args(**kw) -> argparse.Namespace:
    base = {"rps": None, "rps_start": None, "rps_stop": None, "rps_step": None}
    base.update(kw)
    return argparse.Namespace(**base)


# ---------------------------------------------------------------------------
# Argument parsing -- explicit points, ranges, and the conflicts between them
# ---------------------------------------------------------------------------


def test_explicit_points_parse_in_order():
    assert resolve_rps_points(_args(rps=[32.0, 34.0, 36.0, 38.0])) == [32.0, 34.0, 36.0, 38.0]


def test_range_is_inclusive_of_stop():
    """A fine sweep "between 30 and 40" that silently dropped 40 would leave
    the bracket's upper end unmeasured -- the one point explicitly asked for."""
    assert resolve_rps_points(_args(rps_start=30.0, rps_stop=40.0, rps_step=2.0)) == [
        30.0, 32.0, 34.0, 36.0, 38.0, 40.0
    ]


def test_range_excludes_a_stop_that_is_not_on_a_step_boundary():
    assert resolve_rps_points(_args(rps_start=30.0, rps_stop=37.0, rps_step=2.0)) == [
        30.0, 32.0, 34.0, 36.0
    ]


def test_fractional_step_does_not_leak_float_noise_into_points():
    """0.1-style steps must not produce 30.000000000000004, which would end
    up verbatim in a filename and in the provenance header."""
    points = frange(30.0, 30.5, 0.1)
    assert points == [30.0, 30.1, 30.2, 30.3, 30.4, 30.5]


def test_both_modes_at_once_is_rejected():
    with pytest.raises(SystemExit, match="EITHER"):
        resolve_rps_points(_args(rps=[32.0], rps_start=30.0, rps_stop=40.0, rps_step=2.0))


def test_no_mode_at_all_is_rejected():
    with pytest.raises(SystemExit, match="no RPS points given"):
        resolve_rps_points(_args())


def test_partial_range_is_rejected_naming_the_missing_flags():
    with pytest.raises(SystemExit, match="--rps-step"):
        resolve_rps_points(_args(rps_start=30.0, rps_stop=40.0))


def test_non_positive_rps_is_rejected():
    with pytest.raises(SystemExit, match="positive"):
        resolve_rps_points(_args(rps=[10.0, 0.0]))
    with pytest.raises(SystemExit, match="positive"):
        resolve_rps_points(_args(rps_start=0.0, rps_stop=10.0, rps_step=2.0))


def test_backwards_range_is_rejected():
    with pytest.raises(SystemExit, match="must be >="):
        resolve_rps_points(_args(rps_start=40.0, rps_stop=30.0, rps_step=2.0))


def test_zero_or_negative_step_is_rejected():
    with pytest.raises(SystemExit, match="step must be positive"):
        resolve_rps_points(_args(rps_start=30.0, rps_stop=40.0, rps_step=0.0))


# ---------------------------------------------------------------------------
# Both modes route through ONE implementation
# ---------------------------------------------------------------------------


def test_explicit_and_range_modes_produce_byte_identical_artifacts(tmp_path):
    """The two argument styles are two ways to name the same points, not two
    generators. If they ever diverged, a Stage B bracket would depend on how
    the operator happened to type it."""
    points = [32.0, 34.0, 36.0]
    explicit = tmp_path / "explicit"
    ranged = tmp_path / "ranged"

    generate(resolve_rps_points(_args(rps=points)), explicit)
    generate(resolve_rps_points(_args(rps_start=32.0, rps_stop=36.0, rps_step=2.0)), ranged)

    for rps in points:
        a = (explicit / f"poisson_rps{rps:g}.schedule.json").read_bytes()
        b = (ranged / f"poisson_rps{rps:g}.schedule.json").read_bytes()
        assert a == b, f"rps={rps:g} differs between explicit-point and range mode"


# ---------------------------------------------------------------------------
# Workload locks survive the genericization (WEEK2_PLAN.md §3.2/§3.4/§5)
# ---------------------------------------------------------------------------


def test_generated_provenance_carries_every_locked_field(tmp_path):
    (rps, path, _), = generate([32.0], tmp_path)
    prov = json.loads(path.read_text(encoding="utf-8"))["provenance"]

    assert prov["master_seed"] == BASELINE_SEED
    assert prov["rng_scheme_version"] == RNG_SCHEME_VERSION
    assert prov["schedule_scheme_version"] == SCHEDULE_SCHEME_VERSION
    assert prov["target_rps"] == 32.0
    assert prov["arrival_process"] == "poisson"
    assert prov["duration_s"] == DURATION_S
    assert prov["long_context"] is False
    assert prov["n_scheduled"] > 0
    # §5's reproducibility contract: schedule + pinned corpus BY VERSION.
    assert len(prov["corpus_sha256"]) == 64
    assert prov["corpus_size"] == len(load_corpus())
    assert prov["corpus_build_provenance"]["selection_seed"] == 20260816


def test_generated_schedule_matches_the_library_builder_exactly(tmp_path):
    """The CLI must be a thin shell over loadgen.schedule, not a second
    implementation -- otherwise the RNG scheme, the arrival/corpus stream
    independence and the materialization-time prompt assignment would all be
    re-established here, where nothing guards them."""
    corpus = load_corpus()
    direct = build_poisson_schedule(32.0, DURATION_S, BASELINE_SEED, corpus)
    (_, path, via_cli), = generate([32.0], tmp_path)

    assert via_cli.entries == direct.entries
    assert Schedule.load(path).entries == direct.entries


def test_generated_schedule_is_replay_compatible(tmp_path):
    """§5: a frozen artifact must load back byte-identically and validate the
    corpus it was built against."""
    (_, path, original), = generate([32.0], tmp_path)
    reloaded = Schedule.load(path)

    assert reloaded.entries == original.entries
    assert reloaded.provenance == original.provenance
    reloaded.validate_corpus_version(load_corpus())  # must not raise


def test_steady_arrival_process_is_supported(tmp_path):
    """§6.2 step 5's reference curve comes from the same generator."""
    (_, path, sched), = generate([32.0], tmp_path, arrival_process="steady")
    assert path.name == "steady_rps32.schedule.json"
    assert json.loads(path.read_text(encoding="utf-8"))["provenance"]["arrival_process"] == "steady"


def _committed_blob(rel_path: str) -> bytes:
    """The bytes git STORES for a tracked file.

    Not the same thing as the bytes on disk. With `core.autocrlf=true` on
    Windows, a tracked text file is checked out CRLF while its blob is LF, so
    the working-tree copy is a platform-local rendering of the artifact rather
    than the artifact itself. The frozen-workload contract is about the
    committed bytes -- that is what a Linux GPU instance clones and drives --
    so that is what a byte-identity check must compare against
    (R4 README P2).
    """
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"HEAD:{rel_path}"],
        capture_output=True, check=True,
    ).stdout


def test_stage_a_points_regenerate_byte_identically_through_the_generic_path(tmp_path):
    """The committed Stage A artifacts are frozen inputs. Routing Stage A
    through the generic implementation must not have perturbed them -- if it
    had, every replay comparison against them would silently be against a
    different file.

    Compared against the committed blob rather than the working-tree file.
    This used to compare on-disk bytes and passed on both platforms for a
    coincidental reason: the writer applied the same newline translation that
    git had applied on checkout, so two platform-dependent transformations
    cancelled. `metrics.artifacts.write_json_artifact` now pins LF on every
    platform, which removes the writer's half -- and makes the check
    genuinely platform-independent instead of accidentally symmetric.
    """
    from scripts.generate_stage_a_schedules import STAGE_A_RPS_POINTS

    written = generate(STAGE_A_RPS_POINTS, tmp_path)
    assert len(written) == len(STAGE_A_RPS_POINTS)
    for _, path, _ in written:
        rel = f"benchmarks/schedules/stage_a/{path.name}"
        committed = _committed_blob(rel)
        assert committed, f"{path.name} is not among the committed Stage A schedules"
        assert path.read_bytes() == committed, (
            f"{path.name} no longer regenerates byte-identically to the committed artifact"
        )
        assert b"\r\n" not in path.read_bytes(), (
            f"{path.name} was written with CRLF -- frozen artifacts must be byte-stable "
            "across platforms (R4 README P2)"
        )


# ---------------------------------------------------------------------------
# The end-to-end path Block E actually types (no source edit required)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra_args",
    [
        pytest.param(["--rps", "32", "34", "36", "38"], id="explicit-points"),
        pytest.param(["--rps-start", "32", "--rps-stop", "38", "--rps-step", "2"], id="range"),
    ],
)
def test_cli_end_to_end_generates_a_stage_b_bracket(extra_args, tmp_path):
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "generate_schedules.py"),
         "--out-dir", str(tmp_path), *extra_args],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    produced = sorted(p.name for p in tmp_path.glob("*.schedule.json"))
    assert produced == [
        "poisson_rps32.schedule.json", "poisson_rps34.schedule.json",
        "poisson_rps36.schedule.json", "poisson_rps38.schedule.json",
    ]

"""Fixtures for the redesign regression suite.

Everything here reads the promoted first-session evidence
(`benchmarks/evidence/week2/first_session/`). If it has not been promoted,
the tests SKIP rather than fail: the artifacts live on the machine that ran
the session, and a fresh clone without them has not regressed anything --
it just cannot check this. The promotion script is the fix, and the skip
message names it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVIDENCE_ROOT = REPO_ROOT / "benchmarks" / "evidence" / "week2" / "first_session"

_MISSING = (
    "first-session evidence not promoted on this machine -- run "
    "scripts/promote_first_session_evidence.py (Redesign README R0)"
)


@pytest.fixture(scope="session")
def evidence_root() -> Path:
    if not EVIDENCE_ROOT.exists():
        pytest.skip(_MISSING)
    return EVIDENCE_ROOT


@pytest.fixture(scope="session")
def first_session_dir(evidence_root) -> Path:
    stage_a = evidence_root / "stage_a"
    if not stage_a.exists():
        pytest.skip(_MISSING)
    return stage_a


@pytest.fixture(scope="session")
def legacy_fixtures(evidence_root) -> dict:
    path = evidence_root / "LEGACY_FIXTURES.json"
    if not path.exists():
        pytest.skip(
            "LEGACY_FIXTURES.json not captured -- run scripts/capture_legacy_fixtures.py "
            "(Redesign README R0.6)"
        )
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def frozen_workload() -> dict:
    """The frozen canonical workload, if it has been built on this machine.

    Skips rather than fails when absent, for the same reason the evidence
    fixtures do: a fresh clone has not regressed anything by not having run
    the builder yet, and the skip message names the command."""
    from loadgen.canonical import load_frozen

    path = REPO_ROOT / "benchmarks" / "workloads" / "week2_headline" / "canonical_v1.json"
    if not path.exists():
        pytest.skip("canonical workload not frozen -- run "
                    "scripts/build_canonical_workload.py --emit-candidate, then "
                    "scripts/check_tokenizer_capacity.py, then --freeze")
    return load_frozen(path)


@pytest.fixture(scope="session")
def promotion_manifest(evidence_root) -> dict:
    path = evidence_root / "MANIFEST.json"
    if not path.exists():
        pytest.skip(_MISSING)
    return json.loads(path.read_text(encoding="utf-8"))

"""Promotion preserves; it never overwrites (Redesign README R0.4 "Do not
rewrite raw first-session artifacts", R0.5 "Record hashes when promoting").

The failure this guards against is mundane and fatal: a second run of the
promotion script -- against a re-pulled, re-generated or partially-copied
source -- quietly replaces a promoted artifact, and the diagnostic evidence
the redesign is built on is now something else with the same filename. There
is no second copy to compare against; the instance was deleted.

So the script must refuse on differing bytes rather than win. Both directions
are checked here: it must refuse the changed file, and it must stay silent
(idempotent) on the identical one, or every re-run would look like a
tampering alarm and the alarm would stop meaning anything.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_promoter(monkeypatch, src_root: Path, dest_root: Path):
    """Import the promotion script as a module with its roots redirected at
    tmp dirs -- the real evidence tree is never a test subject."""
    spec = importlib.util.spec_from_file_location(
        "_promote_first_session_evidence",
        REPO_ROOT / "scripts" / "promote_first_session_evidence.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SRC_ROOT", src_root)
    monkeypatch.setattr(module, "DEST_ROOT", dest_root)
    monkeypatch.setattr(module, "SUBDIRS", {"stage_a": "stage_a"})
    return module


@pytest.fixture
def promoter(monkeypatch, tmp_path):
    src = tmp_path / "runs"
    (src / "stage_a").mkdir(parents=True)
    (src / "stage_a" / "poisson_rps1.5.raw_log.jsonl").write_text(
        '{"request_id": 1, "status": "sent"}\n', encoding="utf-8"
    )
    dest = tmp_path / "evidence"
    return _load_promoter(monkeypatch, src, dest), src, dest


def test_promotion_writes_bytes_and_a_hash_manifest(promoter):
    module, src, dest = promoter
    assert module.promote(verify_only=False) == 0

    promoted = dest / "stage_a" / "poisson_rps1.5.raw_log.jsonl"
    assert promoted.read_bytes() == (src / "stage_a" / "poisson_rps1.5.raw_log.jsonl").read_bytes()

    manifest = json.loads((dest / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["file_count"] == 1
    assert manifest["classification"].startswith("diagnostic")
    assert manifest["files"][0]["sha256"] == module.sha256_file(promoted)


def test_promotion_is_idempotent_on_identical_bytes(promoter, capsys):
    module, _src, _dest = promoter
    assert module.promote(verify_only=False) == 0
    assert module.promote(verify_only=False) == 0
    assert "1 already present and identical" in capsys.readouterr().out


def test_control_promotion_refuses_to_overwrite_differing_bytes(promoter, capsys):
    """The control: change the SOURCE after promotion and the script must go
    red instead of replacing the promoted copy."""
    module, src, dest = promoter
    assert module.promote(verify_only=False) == 0
    promoted = dest / "stage_a" / "poisson_rps1.5.raw_log.jsonl"
    original = promoted.read_bytes()

    (src / "stage_a" / "poisson_rps1.5.raw_log.jsonl").write_text(
        '{"request_id": 1, "status": "errored"}\n', encoding="utf-8"
    )

    assert module.promote(verify_only=False) == 1, "promotion did NOT refuse a differing artifact"
    assert "REFUSED" in capsys.readouterr().out
    assert promoted.read_bytes() == original, "the promoted artifact was overwritten anyway"


def test_control_verify_catches_a_tampered_promoted_copy(promoter, capsys):
    module, _src, dest = promoter
    assert module.promote(verify_only=False) == 0

    (dest / "stage_a" / "poisson_rps1.5.raw_log.jsonl").write_text(
        '{"request_id": 2, "status": "sent"}\n', encoding="utf-8"
    )
    assert module.promote(verify_only=True) == 1, "--verify did NOT notice the edited copy"
    assert "VERIFY FAILED" in capsys.readouterr().out


def test_verify_is_green_on_an_untouched_promotion(promoter, capsys):
    module, _src, _dest = promoter
    assert module.promote(verify_only=False) == 0
    assert module.promote(verify_only=True) == 0
    assert "VERIFY OK" in capsys.readouterr().out

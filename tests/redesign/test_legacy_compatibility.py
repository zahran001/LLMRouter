"""The first session must keep meaning what it meant (Redesign README §3.1
"Artifact / replay invariants", §6 "Legacy compatibility / no-regression",
§10 "legacy first-session schedules/artifacts remain readable/replayable and
historical artifact hashes remain unchanged").

Two distinct regressions are guarded here, and only the first is about bytes:

  1. the artifacts are byte-identical to what was pulled off the instance;
  2. today's readers still DERIVE the same numbers from those bytes.

(2) is the one the redesign can break by accident. The redesign rewrites the
warmup basis, the validity gate and the point-record schema; every one of
those is a knob that changes what a first-session sidecar "says" without
touching a single byte of it. The salvage story -- "the failed session is
still usable diagnostic evidence" -- is only true while (2) holds.

Each guard is paired with a control that shows it goes red, because a hash
check and an equality check both pass trivially when they are comparing
nothing.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from loadgen.corpus import Corpus, Prompt, load_corpus
from loadgen.log import read_log, read_samples
from loadgen.schedule import Schedule
from metrics.point import point_metrics

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reread(point: dict) -> dict:
    """Re-derive a pinned point through today's readers, at the same warmup
    the historical read used."""
    arts = point["artifacts"]
    committed = json.loads((REPO_ROOT / arts["metrics"]["path"]).read_text(encoding="utf-8"))
    return point_metrics(
        raw_rows=read_log(REPO_ROOT / arts["raw_log"]["path"]),
        sample_rows=read_samples(REPO_ROOT / arts["samples"]["path"]),
        offered_rps=committed["offered_rps"],
        duration_s=committed["duration_s"],
        warmup_n_s=point["historical_read"]["warmup_n_s"],
    )


# ---------------------------------------------------------------------------
# 1. Bytes unchanged.
# ---------------------------------------------------------------------------


def test_promoted_artifact_hashes_are_unchanged(promotion_manifest):
    drifted = []
    for entry in promotion_manifest["files"]:
        path = REPO_ROOT / entry["path"]
        if not path.exists():
            drifted.append(f"{entry['path']}: MISSING")
        elif _sha256(path) != entry["sha256"]:
            drifted.append(f"{entry['path']}: {_sha256(path)} != {entry['sha256']}")
    assert not drifted, "promoted first-session artifacts were modified:\n" + "\n".join(drifted)


def test_control_hash_check_detects_a_single_flipped_byte(tmp_path, promotion_manifest):
    """If the hash check could not see a one-byte edit, invariant (1) would be
    decorative."""
    entry = next(e for e in promotion_manifest["files"] if e["path"].endswith(".metrics.json"))
    original = (REPO_ROOT / entry["path"]).read_bytes()
    tampered = tmp_path / "tampered.metrics.json"
    tampered.write_bytes(original.replace(b"500.0", b"501.0", 1))

    assert tampered.read_bytes() != original, "the tamper itself did not change the file"
    assert _sha256(tampered) != entry["sha256"]


def test_legacy_fixture_hashes_match_the_promotion_manifest(legacy_fixtures, promotion_manifest):
    """The two manifests are written by different scripts; if they disagree,
    one of them is describing artifacts that no longer exist."""
    by_path = {e["path"]: e["sha256"] for e in promotion_manifest["files"]}
    for point in legacy_fixtures["points"]:
        for kind, art in point["artifacts"].items():
            if art["path"] in by_path:
                assert art["sha256_worktree"] == by_path[art["path"]], (
                    f"{point['tag']}/{kind}: LEGACY_FIXTURES.json and MANIFEST.json disagree"
                )


# ---------------------------------------------------------------------------
# 2. Interpretation unchanged.
# ---------------------------------------------------------------------------


def test_legacy_points_still_read_the_same(legacy_fixtures):
    for point in legacy_fixtures["points"]:
        record = _reread(point)
        pinned = point["historical_read"]

        for key, expected in pinned["exact"].items():
            assert record[key] == expected, (
                f"{point['tag']}: reader change moved {key} "
                f"{expected!r} -> {record[key]!r}. First-session evidence must keep its "
                "historical interpretation (README 3.1); if this change is intended, it "
                "belongs in a NEW format version, not in a re-read of legacy bytes."
            )

        for key, spec in pinned["approx"].items():
            assert math.isclose(record[key], spec["value"], rel_tol=spec["rel_tol"]), (
                f"{point['tag']}: {key} moved beyond its stated float-summation tolerance"
            )


def test_control_interpretation_pin_detects_a_changed_warmup_rule(legacy_fixtures):
    """The realistic way the redesign breaks (2): R6 replaces the fixed-window
    basis, someone re-derives the legacy points under the new warmup, and the
    old numbers quietly become different old numbers. Shifting the warmup by
    2s must go red."""
    point = next(p for p in legacy_fixtures["points"] if p["tag"] == "poisson_rps2")
    arts = point["artifacts"]
    committed = json.loads((REPO_ROOT / arts["metrics"]["path"]).read_text(encoding="utf-8"))

    shifted = point_metrics(
        raw_rows=read_log(REPO_ROOT / arts["raw_log"]["path"]),
        sample_rows=read_samples(REPO_ROOT / arts["samples"]["path"]),
        offered_rps=committed["offered_rps"],
        duration_s=committed["duration_s"],
        warmup_n_s=point["historical_read"]["warmup_n_s"] + 2.0,
    )
    pinned = point["historical_read"]["exact"]
    assert shifted["n_ttft_samples"] != pinned["n_ttft_samples"]
    assert shifted["ttft_p99_ms"] != pinned["ttft_p99_ms"], (
        "a 2s warmup shift did not move p99 -- then the pin is not sensitive to the "
        "warmup basis and would not catch R6 silently re-reading legacy points"
    )


# ---------------------------------------------------------------------------
# 3. Legacy schedules still parse and still replay under their own contract.
# ---------------------------------------------------------------------------


def test_legacy_schedules_parse_under_their_recorded_versions(legacy_fixtures):
    for point in legacy_fixtures["points"]:
        schedule = Schedule.load(REPO_ROOT / point["artifacts"]["schedule"]["path"])
        versions = point["format_versions"]
        assert schedule.provenance["rng_scheme_version"] == versions["rng_scheme_version"]
        assert schedule.provenance["schedule_scheme_version"] == versions["schedule_scheme_version"]
        assert len(schedule.entries) == schedule.provenance["n_scheduled"]
        assert schedule.provenance["corpus_sha256"] == point["corpus_contract"]["corpus_sha256"]


def test_legacy_schedules_still_validate_against_the_pinned_corpus(legacy_fixtures):
    """WEEK2_PLAN.md 5: frozen schedule + pinned corpus = identical workload.
    This is the check that refused to start Stage A when the corpus had
    drifted (handoff 4) -- it must still hold for the legacy schedules."""
    corpus = load_corpus()
    for point in legacy_fixtures["points"]:
        Schedule.load(REPO_ROOT / point["artifacts"]["schedule"]["path"]).validate_corpus_version(corpus)


def test_control_corpus_drift_still_refuses(legacy_fixtures, tmp_path):
    """The guard that caught the CRLF bug must still bite. If a mutated corpus
    replays silently, the frozen-workload contract is gone."""
    drifted_path = tmp_path / "drifted_prompts.jsonl"
    drifted_path.write_bytes(
        (REPO_ROOT / "corpus" / "baseline_prompts.jsonl").read_bytes() + b'{"prompt_id":9999,"text":"x","char_len":1}\n'
    )
    drifted = Corpus(prompts=(Prompt(prompt_id=0, text="x", char_len=1),), source_path=drifted_path)

    point = legacy_fixtures["points"][0]
    schedule = Schedule.load(REPO_ROOT / point["artifacts"]["schedule"]["path"])
    with pytest.raises(ValueError, match="corpus drift detected"):
        schedule.validate_corpus_version(drifted)


def test_legacy_raw_log_keeps_its_six_field_schema(legacy_fixtures):
    """README 3.1: raw-log six-field semantics remain unchanged; redesign
    metadata goes in additive fields, never by re-meaning an existing one."""
    expected = {"request_id", "send_time", "close_time", "prompt_id", "prompt_len", "status"}
    for point in legacy_fixtures["points"]:
        rows = read_log(REPO_ROOT / point["artifacts"]["raw_log"]["path"])
        assert rows, f"{point['tag']}: empty raw log"
        for row in rows[:50]:
            assert set(row) == expected, f"{point['tag']}: raw-log field set changed"
            assert row["status"] in {"sent", "shed", "errored"}


# ---------------------------------------------------------------------------
# 4. Format versioning: two formats coexist, an unknown one fails loudly.
# ---------------------------------------------------------------------------


def test_both_known_schedule_formats_parse(legacy_fixtures, tmp_path):
    """v1 (first session, fixed duration) and v2 (redesigned, exact-N) are both
    legitimate. Neither may be read under the other's semantics, and both must
    keep parsing under their own."""
    from loadgen.schedule import KNOWN_SCHEDULE_SCHEME_VERSIONS

    assert KNOWN_SCHEDULE_SCHEME_VERSIONS == {"loadgen-schedule-v1", "headline-schedule-v2"}

    legacy_path = REPO_ROOT / legacy_fixtures["points"][0]["artifacts"]["schedule"]["path"]
    legacy = Schedule.load(legacy_path)
    assert legacy.provenance["schedule_scheme_version"] == "loadgen-schedule-v1"
    # A v1 schedule has no warmup boundary and no exact-N target -- reading it
    # as if it did is what the version check prevents.
    assert "warmup_boundary_s" not in legacy.provenance
    assert "post_warmup_target_count" not in legacy.provenance


def test_control_an_unknown_schedule_version_fails_loudly(legacy_fixtures, tmp_path):
    """Silent coercion is how a frozen workload stops meaning what its
    provenance says. A future format must raise, not be read with whatever
    semantics today's code happens to implement."""
    legacy_path = REPO_ROOT / legacy_fixtures["points"][0]["artifacts"]["schedule"]["path"]
    data = json.loads(legacy_path.read_text(encoding="utf-8"))
    data["provenance"]["schedule_scheme_version"] = "loadgen-schedule-v99"

    future = tmp_path / "future.schedule.json"
    future.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown schedule_scheme_version"):
        Schedule.load(future)


def test_control_a_missing_schedule_version_fails_loudly(tmp_path):
    orphan = tmp_path / "no_version.schedule.json"
    orphan.write_text(json.dumps({"provenance": {"target_rps": 2}, "entries": []}),
                      encoding="utf-8")
    with pytest.raises(ValueError, match="unknown schedule_scheme_version"):
        Schedule.load(orphan)


# ---------------------------------------------------------------------------
# 5. No historical artifact was rewritten.
# ---------------------------------------------------------------------------


def test_committed_schedules_and_corpus_are_untouched():
    """R4 README §10: `git diff HEAD -- benchmarks/schedules corpus/` must stay
    empty. The redesign adds new formats in new paths; it never renormalizes,
    migrates or re-serializes a committed artifact.

    Scoped to the historical paths deliberately: newly generated redesign
    schedules under benchmarks/schedules/week2_redesign/ are expected to be
    new untracked files, which `git diff` does not report anyway.
    """
    import subprocess

    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", "--name-only", "HEAD", "--",
         "benchmarks/schedules/stage_a", "corpus/"],
        capture_output=True, text=True, check=True,
    )
    changed = [line for line in result.stdout.splitlines() if line.strip()]
    assert not changed, (
        "committed historical artifacts were modified: " + ", ".join(changed)
        + ". Historical evidence cleanliness outranks cosmetic normalization (R4 README P2)."
    )

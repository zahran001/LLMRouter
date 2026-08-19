#!/usr/bin/env python
"""Pin the first session's artifacts as immutable legacy fixtures
(Redesign README R0.6, §3.1 "Artifact / replay invariants", §6 legacy block).

A hash manifest proves the BYTES did not change. That is necessary and not
sufficient: the redesign edits the readers, and a reader can keep reading the
same bytes while silently reinterpreting them (a changed warmup rule, a
changed percentile method, a new validity gate applied retroactively). This
manifest therefore pins two things per fixture:

  1. the bytes            -- sha256, worktree and (when tracked) committed blob
  2. the interpretation   -- what today's readers derive from those bytes

`tests/redesign/test_legacy_compatibility.py` re-derives (2) and fails if any
updated reader changes its historical reading. That is the regression the
salvage story depends on: the first session is diagnostic evidence only if it
still means in month three what it meant on the day it was pulled.

One fixture set per R2 source point (1.5 and 2 RPS), each covering all four
artifact kinds the README names: schedule, raw log, sidecar, metrics record.

Usage:
    .venv/Scripts/python.exe scripts/capture_legacy_fixtures.py
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from loadgen.log import read_log, read_samples  # noqa: E402
from metrics.point import point_metrics  # noqa: E402

EVIDENCE = REPO_ROOT / "benchmarks" / "evidence" / "week2" / "first_session"
SCHEDULES = REPO_ROOT / "benchmarks" / "schedules" / "stage_a"
OUT = EVIDENCE / "LEGACY_FIXTURES.json"

# Both R2 source points. 2 RPS is the classification-unstable near-boundary
# point; 1.5 RPS is the sparser clean low-load one. Pinning both means the
# regression test covers the two arrays the calibration actually consumes.
POINTS = ("poisson_rps1.5", "poisson_rps2")

# The exact values every legacy reader must keep reproducing. TTFT is the
# headline metric, so its percentiles are pinned bit-for-bit.
PINNED_EXACT = (
    "n_scheduled", "n_issued_total", "n_issued_window", "n_shed_total",
    "n_errored_total", "n_samples_window", "n_ttft_samples", "n_tpot_samples",
    "achieved_rps", "divergence_pct", "flagged", "plot_rps", "plot_rps_basis",
    "tail_valid", "ttft_p50_ms", "ttft_p95_ms", "ttft_p99_ms", "ttft_mean_ms",
    "tpot_p50_ms", "tpot_p95_ms", "tpot_p99_ms",
    "breach_500ms", "severe_2s",
)

# tpot_mean_ms is deliberately NOT in PINNED_EXACT. The live session summed
# the TPOT population in completion order; the offline reader sums it in
# request_id order. Same multiset, different float summation order, so the
# two disagree in the last few ULPs (~1e-13 relative) while meaning exactly
# the same thing. Pinning it exactly would fail for a reason that is not a
# regression -- so it is pinned with a stated tolerance instead of quietly
# dropped.
PINNED_APPROX = {"tpot_mean_ms": 1e-9}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def blob_sha256(path: Path) -> str | None:
    """sha256 of the file's COMMITTED bytes, which on Windows differ from the
    worktree bytes whenever core.autocrlf rewrote them on checkout. Recorded
    separately so a hash comparison run on Linux and one run on Windows are
    comparing the same thing -- the distinction that cost the first session
    its Stage A start (handoff §4)."""
    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "show", f"HEAD:{rel}"],
            capture_output=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return hashlib.sha256(out.stdout).hexdigest()


def describe(path: Path, kind: str) -> dict:
    worktree = sha256_file(path)
    blob = blob_sha256(path)
    return {
        "kind": kind,
        "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256_worktree": worktree,
        "sha256_committed_blob": blob,
        "worktree_matches_blob": None if blob is None else (blob == worktree),
    }


def capture_point(tag: str) -> dict:
    schedule_path = SCHEDULES / f"{tag}.schedule.json"
    raw_path = EVIDENCE / "stage_a" / f"{tag}.raw_log.jsonl"
    samples_path = EVIDENCE / "stage_a" / f"{tag}.samples.jsonl"
    metrics_path = EVIDENCE / "stage_a" / f"{tag}.metrics.json"

    for p in (schedule_path, raw_path, samples_path, metrics_path):
        if not p.exists():
            raise SystemExit(f"{tag}: missing {p.relative_to(REPO_ROOT)} -- run "
                             "scripts/promote_first_session_evidence.py first")

    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    committed = json.loads(metrics_path.read_text(encoding="utf-8"))

    record = point_metrics(
        raw_rows=read_log(raw_path),
        sample_rows=read_samples(samples_path),
        offered_rps=committed["offered_rps"],
        duration_s=committed["duration_s"],
        warmup_n_s=committed["warmup_n_s"],
    )

    return {
        "tag": tag,
        "nominal_rps": committed["offered_rps"],
        "artifacts": {
            "schedule": describe(schedule_path, "frozen schedule (workload input)"),
            "raw_log": describe(raw_path, "raw 6-field log (run record)"),
            "samples": describe(samples_path, "TTFT/TPOT sidecar (breach metric source)"),
            "metrics": describe(metrics_path, "per-point metrics record (session-time)"),
        },
        "format_versions": {
            "rng_scheme_version": schedule["provenance"].get("rng_scheme_version"),
            "schedule_scheme_version": schedule["provenance"].get("schedule_scheme_version"),
            "raw_log_schema": "6-field: request_id, send_time, close_time, prompt_id, "
                              "prompt_len, status (WEEK2_PLAN.md 3.1)",
            "samples_schema": "request_id, send_time, ttft_ms, tpot_samples_ms, "
                              "content_chunk_count, error (WEEK2_PLAN.md 3.1)",
            "point_record_version": committed.get("record_version", "legacy-unversioned"),
        },
        "corpus_contract": {
            "corpus_sha256": schedule["provenance"].get("corpus_sha256"),
            "corpus_size": schedule["provenance"].get("corpus_size"),
        },
        "historical_read": {
            "reader": "metrics.point.point_metrics via loadgen.log.read_log/read_samples",
            "warmup_n_s": committed["warmup_n_s"],
            "warmup_n_is_placeholder": True,
            "percentile_method": "numpy linear interpolation (metrics.compute.percentile)",
            "exact": {k: record[k] for k in PINNED_EXACT},
            "approx": {k: {"value": record[k], "rel_tol": tol} for k, tol in PINNED_APPROX.items()},
        },
    }


def main() -> None:
    manifest = {
        "what": "Immutable legacy fixtures from the first Week 2 GPU session (2026-08-18).",
        "why": (
            "The redesign changes schedule/metrics formats and readers. These fixtures pin both "
            "the bytes and today's interpretation of them, so a reader change that silently "
            "reinterprets first-session evidence fails a test instead of rewriting history."
        ),
        "classification": "diagnostic / failed-experiment evidence -- NOT baseline evidence",
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hash_algorithm": "sha256",
        "note_on_two_hashes": (
            "sha256_worktree hashes the bytes on this disk; sha256_committed_blob hashes what git "
            "stores. They differ for any tracked text file that core.autocrlf rewrote on checkout "
            "-- the schedules are checked out CRLF on Windows while their blobs are LF. Regression "
            "tests must compare like with like."
        ),
        "points": [capture_point(tag) for tag in POINTS],
    }
    OUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO_ROOT)} ({len(manifest['points'])} fixture point(s))")
    for pt in manifest["points"]:
        h = pt["historical_read"]["exact"]
        print(f"  {pt['tag']:<16} n={h['n_ttft_samples']:>4}  p99={h['ttft_p99_ms']:.4f}ms  "
              f"breach={h['breach_500ms']}")
        for name, art in pt["artifacts"].items():
            if art["worktree_matches_blob"] is False:
                print(f"    NOTE {name}: worktree bytes != committed blob (line-ending rewrite)")


if __name__ == "__main__":
    main()

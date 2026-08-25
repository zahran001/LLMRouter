#!/usr/bin/env python
"""Promote GPU session #3's new artifacts into tracked evidence
(WEEK2_CLOSEOUT_PLAN.md; WEEK2_GPU_SESSION_3_REPORT.md 7/9).

Session #3 reused session #2's shared local artifact directories
(benchmarks/runs/sustained_scout/, benchmarks/runs/headline/) rather than
fresh ones, so those directories now hold BOTH session #2's already-promoted
points and session #3's new ones side by side. Unlike
promote_session_2_evidence.py (which promoted whole subdirectories),
this script promotes an explicit filename allowlist -- only the 8 new
points session #3 actually drove (2 sustained-scout + 6 headline, at
lambda in {0.4, 0.6}) -- so it never re-touches or duplicates session #2's
files.

This is the session that closed the breach interval: session #2 left it
open (NO_UNDER_ANCHOR); session #3 found lambda=0.4 UNDER (3/3 unanimous)
and lambda=0.6 OVER (3/3 unanimous), so `resolve_breach` now returns
RESOLVED with breach_interval (0.4, 0.6].

Preserve, do not overwrite: a destination file that already exists with
DIFFERENT bytes is a refusal, never a silent replace. Identical bytes are a
no-op, so the script is idempotent and `--verify` re-checks a promotion made
later.

Usage:
    .venv/Scripts/python.exe scripts/promote_session_3_evidence.py
    .venv/Scripts/python.exe scripts/promote_session_3_evidence.py --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

SRC_ROOT = REPO_ROOT / "benchmarks" / "runs"
DEST_ROOT = REPO_ROOT / "benchmarks" / "evidence" / "week2" / "session_3"

SESSION_DATE = "2026-08-25"

# Explicit filename allowlist per subdir -- NOT whole-directory promotion,
# because sustained_scout/ and headline/ are shared with session #2's
# already-promoted points (same local directories, reused across sessions).
NEW_LAMBDAS = ("0.4", "0.6")

FLOOR_FILES = ["floor.metrics.json", "floor.raw_log.jsonl", "floor.samples.jsonl"]

SUSTAINED_SCOUT_FILES = [
    f"headline_r1_rps{lam}.{ext}"
    for lam in NEW_LAMBDAS
    for ext in ("metrics.json", "raw_log.jsonl", "samples.jsonl", "scout_report.json")
]

HEADLINE_FILES = [
    f"headline_r{r}_rps{lam}.{ext}"
    for r in (1, 2, 3)
    for lam in NEW_LAMBDAS
    for ext in ("metrics.json", "raw_log.jsonl", "samples.jsonl")
] + ["family_report.json"]  # last invocation only (repeat 3) -- noted in the manifest

PREFLIGHT_FILES = ["prefix_cache_verdict.json"]

# (source subdir, dest subdir, filename allowlist)
SUBDIRS = [
    ("floor", "floor", FLOOR_FILES),
    ("sustained_scout", "sustained_scout", SUSTAINED_SCOUT_FILES),
    ("headline", "headline", HEADLINE_FILES),
    ("preflight", "preflight", PREFLIGHT_FILES),
]


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git_head_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _promote_one(src: Path, dest: Path, verify_only: bool,
                  entries: list[dict], refusals: list[str]) -> tuple[int, int]:
    digest = sha256_file(src)

    if dest.exists():
        dest_digest = sha256_file(dest)
        if dest_digest != digest:
            refusals.append(
                f"REFUSED {rel(dest)}: already promoted with a DIFFERENT "
                f"hash (promoted={dest_digest[:12]}..., source={digest[:12]}...). "
                "Session #3 artifacts are never rewritten in place."
            )
            return 0, 0
        entries.append({"path": rel(dest), "source_path": rel(src),
                         "sha256": digest, "bytes": src.stat().st_size})
        return 0, 1

    if verify_only:
        refusals.append(f"MISSING {rel(dest)}: not promoted yet")
        return 0, 0

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())
    entries.append({"path": rel(dest), "source_path": rel(src),
                     "sha256": digest, "bytes": src.stat().st_size})
    return 1, 0


def promote(verify_only: bool) -> int:
    if not SRC_ROOT.exists():
        raise SystemExit(
            f"no {SRC_ROOT} -- session #3's artifacts are not on this machine. "
            "They were pulled there by scripts/gpu_session/pull_artifacts.sh before "
            "teardown; without them there is nothing to promote."
        )

    entries: list[dict] = []
    refusals: list[str] = []
    copied = 0
    unchanged = 0

    for src_name, dest_name, filenames in SUBDIRS:
        src_dir = SRC_ROOT / src_name
        dest_dir = DEST_ROOT / dest_name
        for filename in filenames:
            src = src_dir / filename
            if not src.exists():
                refusals.append(f"missing source file: {src}")
                continue
            dest = dest_dir / filename
            c, u = _promote_one(src, dest, verify_only, entries, refusals)
            copied += c
            unchanged += u

    for r in refusals:
        print(r)
    if refusals and verify_only:
        print(f"\nVERIFY FAILED: {len(refusals)} problem(s)")
        return 1
    if refusals:
        print(f"\nPROMOTION INCOMPLETE: {len(refusals)} refusal(s) above -- resolve before continuing")
        return 1

    manifest = {
        "what": "GPU session #3 artifacts, promoted as headline evidence -- closed the breach interval.",
        "classification": "headline evidence -- lambda=0.4 classifies UNDER (3/3 unanimous), "
                           "lambda=0.6 classifies OVER (3/3 unanimous); resolution RESOLVED, "
                           "breach_interval (0.4, 0.6]",
        "session_date": SESSION_DATE,
        "resolution": "RESOLVED",
        "under_lambdas": [0.4],
        "over_lambdas": [0.6],
        "breach_interval": [0.4, 0.6],
        "note": (
            "See WEEK2_GPU_SESSION_3_REPORT.md for the full record. Only session #3's "
            "NEW points are listed here (lambda in {0.4, 0.6}) -- sustained_scout/ and "
            "headline/ also hold session #2's already-promoted points in the same local "
            "directories (benchmarks/evidence/week2/session_2/), not duplicated here. "
            "headline/family_report.json reflects only the LAST drive_headline_family.py "
            "invocation (repeat 3, lambda 0.4+0.6) -- it is not a cross-repeat aggregate."
        ),
        "promoted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "promoted_from": rel(SRC_ROOT),
        "repo_head_at_promotion": git_head_sha(),
        "hash_algorithm": "sha256",
        "file_count": len(entries),
        "files": sorted(entries, key=lambda e: e["path"]),
    }

    manifest_path = DEST_ROOT / "MANIFEST.json"
    if verify_only:
        if not manifest_path.exists():
            print(f"VERIFY FAILED: no {rel(manifest_path)}")
            return 1
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        prior_hashes = {e["path"]: e["sha256"] for e in prior["files"]}
        now_hashes = {e["path"]: e["sha256"] for e in entries}
        if prior_hashes != now_hashes:
            drifted = [p for p in set(prior_hashes) | set(now_hashes)
                       if prior_hashes.get(p) != now_hashes.get(p)]
            print("VERIFY FAILED: manifest hash drift on:")
            for p in sorted(drifted):
                print(f"  {p}: manifest={prior_hashes.get(p)} actual={now_hashes.get(p)}")
            return 1
        print(f"VERIFY OK: {len(entries)} promoted artifact(s) match {manifest_path.name}")
        return 0

    DEST_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"promoted {copied} new file(s), {unchanged} already present and identical")
    print(f"manifest: {rel(manifest_path)} ({len(entries)} files)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verify", action="store_true",
                        help="re-hash the promoted copies against MANIFEST.json and write nothing")
    args = parser.parse_args()
    raise SystemExit(promote(args.verify))


if __name__ == "__main__":
    main()

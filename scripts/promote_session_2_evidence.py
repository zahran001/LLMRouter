#!/usr/bin/env python
"""Promote GPU session #2 attempt-2's artifacts into tracked evidence
(WEEK2_GPU_SESSION_2_PLAN.md §12; WEEK2_GPU_SESSION_2_ATTEMPT_2_REPORT.md §10).

The 2026-08-23 session's artifacts were pulled off the instance before
teardown into `benchmarks/runs/`, which is gitignored -- so they exist only
on one laptop, for an instance that no longer exists. This copies them,
byte-for-byte, into `benchmarks/evidence/week2/session_2/`, which the
.gitignore negations deliberately re-include, and records a hash manifest so
"the same bytes" stops being a claim and becomes a check. Same pattern as
`promote_first_session_evidence.py`, adapted for session #2's directory
layout (floor/sustained_scout/headline/secondary/steady/adversarial/preflight
plus a top-level vllm.log, instead of session #1's stage_a/unloaded_floor).

This is the real headline-defining session: sustained-scout is diagnostic
only, but the headline/, secondary/, steady/ and adversarial/ points here are
what `resolve_breach` actually classified (0.75 -> OVER, 0.5 -> UNCERTAIN,
resolution NO_UNDER_ANCHOR). The promoted README says so.

Preserve, do not overwrite: a destination file that already exists with
DIFFERENT bytes is a refusal, never a silent replace. Identical bytes are a
no-op, so the script is idempotent and `--verify` re-checks a promotion made
later.

Usage:
    .venv/Scripts/python.exe scripts/promote_session_2_evidence.py
    .venv/Scripts/python.exe scripts/promote_session_2_evidence.py --verify
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
DEST_ROOT = REPO_ROOT / "benchmarks" / "evidence" / "week2" / "session_2"

# Source subdirectory -> destination subdirectory. Everything under each
# source dir is promoted; nothing is filtered, for the same reason as session
# #1's script: which artifact turns out to matter is not knowable now.
SUBDIRS = {
    "floor": "floor",
    "sustained_scout": "sustained_scout",
    "headline": "headline",
    "secondary": "secondary",
    "steady": "steady",
    "adversarial": "adversarial",
    "preflight": "preflight",
}

# Top-level files (not under a subdir) -> destination relative path.
FILES = {
    "vllm.log": "vllm.log",
}

SESSION_DATE = "2026-08-23"


def rel(path: Path) -> str:
    """Repo-relative POSIX path for display and for the manifest, falling back
    to the absolute path when the file sits outside the repo (which is how the
    tests exercise this script against throwaway roots)."""
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
    """Returns (copied, unchanged) deltas for this single file."""
    digest = sha256_file(src)

    if dest.exists():
        dest_digest = sha256_file(dest)
        if dest_digest != digest:
            refusals.append(
                f"REFUSED {rel(dest)}: already promoted with a DIFFERENT "
                f"hash (promoted={dest_digest[:12]}..., source={digest[:12]}...). "
                "Session #2 artifacts are never rewritten in place."
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
            f"no {SRC_ROOT} -- session #2's artifacts are not on this machine. "
            "They were pulled there by scripts/gpu_session/pull_artifacts.sh before "
            "teardown; without them there is nothing to promote."
        )

    entries: list[dict] = []
    refusals: list[str] = []
    copied = 0
    unchanged = 0

    for src_name, dest_name in SUBDIRS.items():
        src_dir = SRC_ROOT / src_name
        if not src_dir.exists():
            refusals.append(f"missing source subdir: {src_dir}")
            continue
        dest_dir = DEST_ROOT / dest_name
        for src in sorted(p for p in src_dir.rglob("*") if p.is_file()):
            dest = dest_dir / src.relative_to(src_dir)
            c, u = _promote_one(src, dest, verify_only, entries, refusals)
            copied += c
            unchanged += u

    for src_name, dest_name in FILES.items():
        src = SRC_ROOT / src_name
        if not src.exists():
            refusals.append(f"missing source file: {src}")
            continue
        dest = DEST_ROOT / dest_name
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
        "what": "GPU session #2 attempt-2 artifacts, promoted as headline evidence.",
        "classification": "headline evidence -- 0.75 RPS classifies OVER (unanimous), "
                           "0.5 RPS classifies UNCERTAIN (2 OVER, 1 UNDER); "
                           "resolution is NO_UNDER_ANCHOR (no confirmed UNDER in range)",
        "session_date": SESSION_DATE,
        "resolution": "NO_UNDER_ANCHOR",
        "over_lambdas": [0.75],
        "unresolved_lambdas": [0.5],
        "note": (
            "See WEEK2_GPU_SESSION_2_ATTEMPT_2_REPORT.md for the full record. "
            "headline/ contains 9 points: 3 repeats x {0.5, 0.75} from this session, "
            "plus 3 legacy lambda in {1.5, 2, 2.5} repeat-1 points carried over from "
            "attempt 1 (CENSORED, kept for continuity, not re-driven this session). "
            "sustained_scout/ is Tier A diagnostic evidence only -- it never enters "
            "classification (scenario_contract.py: workload_class sustained_scout_controlled)."
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

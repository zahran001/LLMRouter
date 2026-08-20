#!/usr/bin/env python
"""Promote the first GPU session's artifacts into tracked diagnostic evidence
(Redesign README Block R0; redesign handoff §12/§17C, removed 2026-08-20).

The 2026-08-18 session's artifacts were pulled off the instance before
teardown into `benchmarks/runs/`, which is gitignored -- so they exist only
on one laptop. This copies them, byte-for-byte, into
`benchmarks/evidence/week2/first_session/`, which the .gitignore negations
deliberately re-include, and records a hash manifest so "the same bytes"
stops being a claim and becomes a check.

They are promoted as DIAGNOSTIC / FAILED-EXPERIMENT evidence, not baseline
evidence: the session produced no defensible breach RPS (handoff §13). The
label lives in the promoted README so a later reader cannot mistake the two.

Preserve, do not overwrite: a destination file that already exists with
DIFFERENT bytes is a refusal, never a silent replace. Identical bytes are a
no-op, so the script is idempotent and `--verify` re-checks a promotion made
months earlier.

Usage:
    .venv/Scripts/python.exe scripts/promote_first_session_evidence.py
    .venv/Scripts/python.exe scripts/promote_first_session_evidence.py --verify
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
DEST_ROOT = REPO_ROOT / "benchmarks" / "evidence" / "week2" / "first_session"

# Source subdirectory -> destination subdirectory. Everything under each
# source dir is promoted; nothing is filtered, because "which artifact turns
# out to matter" is not knowable now (the 1.5/2-RPS sidecars mattered only
# after the session exposed the prompt-tail confound).
SUBDIRS = {
    "stage_a": "stage_a",
    "unloaded_floor": "unloaded_floor",
    "session_logs": "session_logs",
}

SESSION_DATE = "2026-08-18"


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


def promote(verify_only: bool) -> int:
    if not SRC_ROOT.exists():
        raise SystemExit(
            f"no {SRC_ROOT} -- the first-session artifacts are not on this machine. "
            "They were pulled there by scripts/gpu_session/pull_artifacts.sh before teardown; "
            "without them R0 cannot be completed and R2 has no TTFT source arrays."
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
            rel_in_subdir = src.relative_to(src_dir)
            dest = dest_dir / rel_in_subdir
            digest = sha256_file(src)

            if dest.exists():
                dest_digest = sha256_file(dest)
                if dest_digest != digest:
                    refusals.append(
                        f"REFUSED {rel(dest)}: already promoted with a DIFFERENT "
                        f"hash (promoted={dest_digest[:12]}..., source={digest[:12]}...). "
                        "First-session artifacts are never rewritten in place (R0.4)."
                    )
                    continue
                unchanged += 1
            elif verify_only:
                refusals.append(f"MISSING {rel(dest)}: not promoted yet")
                continue
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(src.read_bytes())
                copied += 1

            entries.append({
                "path": rel(dest),
                "source_path": rel(src),
                "sha256": digest,
                "bytes": src.stat().st_size,
            })

    for r in refusals:
        print(r)
    if refusals and verify_only:
        print(f"\nVERIFY FAILED: {len(refusals)} problem(s)")
        return 1
    if refusals:
        print(f"\nPROMOTION INCOMPLETE: {len(refusals)} refusal(s) above -- resolve before continuing")
        return 1

    manifest = {
        "what": "First Week 2 GPU session artifacts, promoted as DIAGNOSTIC evidence.",
        "classification": "diagnostic / failed-experiment evidence -- NOT baseline evidence",
        "session_date": SESSION_DATE,
        "no_final_breach_rps": True,
        "note": (
            "The 2026-08-18 session produced no defensible breach RPS "
            "(WEEK2_GPU_REDESIGN_HANDOFF.md §13). These artifacts are the record of what "
            "falsified the original design -- the prompt-tail confound, the n>=100 "
            "insufficiency, and the timeout censoring -- and the source arrays for the "
            "R2 p99 sample-size calibration. Do not cite them as baseline results."
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

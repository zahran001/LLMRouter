#!/usr/bin/env python
"""Fetch the pinned model's `config.json`, and PROVE it is the pinned model's
(Week 3 cost-model provenance, `WEEK3_IMPLEMENTATION_README.md` W3-1).

Same problem as `scripts/fetch_tokenizer.py` (R4B), one file later:
`meta-llama/Llama-3.2-3B-Instruct` is a gated repository, but the KV
request-cost formula needs `config.json`'s exact architecture constants
(`num_hidden_layers`, `num_key_value_heads`, `head_dim`) with the same
byte-identity guarantee the tokenizer already has -- "close enough" is not
a category this script accepts, per
`WEEK3_KV_REQUEST_COST_INVESTIGATION_REPORT.md` (which did this fetch
manually, once, to derive the formula; this script makes it reproducible).

Same method as `scripts/fetch_tokenizer.py`:
    1. read the gated repo's blob id for config.json from the public API
    2. download that file from an ungated mirror
    3. compute the git blob id of what arrived
    4. require them to be equal, or refuse

Usage:
    .venv/Scripts/python.exe scripts/fetch_model_config.py
    .venv/Scripts/python.exe scripts/fetch_model_config.py --verify-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# The exact served model, from the pinned Week 2 serving identity (BASELINE.md).
GATED_REPO = "meta-llama/Llama-3.2-3B-Instruct"

# Ungated mirrors, tried in order. Membership in this list buys nothing: a
# mirror is only used if its file hashes to the gated repo's blob id.
# `alpindale/Llama-3.2-3B-Instruct` was already manually verified
# byte-identical for config.json during the Week 3 investigation.
MIRRORS = (
    "alpindale/Llama-3.2-3B-Instruct",
    "chuanli11/Llama-3.2-3B-Instruct-uncensored",
    "unsloth/Llama-3.2-3B-Instruct",
)

FILES = ("config.json",)

# Deliberately outside the repo tree, same rationale as .tokenizer_cache: a
# build input, not evidence -- the hash proof lives in the manifest.
CACHE_DIR = REPO_ROOT / ".model_config_cache" / GATED_REPO.replace("/", "__")
MANIFEST = CACHE_DIR / "PROVENANCE.json"

USER_AGENT = "LLMRouter-week3-cost-model/1.0"


def git_blob_sha1(data: bytes) -> str:
    """Git's object id for a blob: sha1(b'blob <len>\\0' + content)."""
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


def http_get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def gated_file_index() -> dict:
    """Blob ids and sizes for the gated repo's files, from the public API."""
    data = json.loads(http_get(f"https://huggingface.co/api/models/{GATED_REPO}?blobs=true"))
    index = {}
    for sibling in data.get("siblings", []):
        name = sibling.get("rfilename")
        if name in FILES:
            index[name] = {
                "blob_id": sibling.get("blobId"),
                "size": sibling.get("size"),
                "lfs_oid": (sibling.get("lfs") or {}).get("oid"),
            }
    missing = [f for f in FILES if f not in index]
    if missing:
        raise SystemExit(f"{GATED_REPO} does not list {missing} -- cannot establish a target hash")
    return {"repo_sha": data.get("sha"), "gated": data.get("gated"), "files": index}


def fetch_verified(filename: str, target_blob: str) -> tuple[bytes, str]:
    """Download `filename` from the first mirror whose bytes hash correctly."""
    attempts = []
    for mirror in MIRRORS:
        url = f"https://huggingface.co/{mirror}/resolve/main/{filename}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as response:
                data = response.read()
        except Exception as exc:
            attempts.append(f"{mirror}: unreachable ({type(exc).__name__})")
            continue
        got = git_blob_sha1(data)
        if got == target_blob:
            return data, mirror
        attempts.append(f"{mirror}: blob {got[:12]}... != {target_blob[:12]}...")

    raise SystemExit(
        f"no mirror served a byte-identical {filename}. The cost-model provenance must not "
        f"run against an approximate config, so this is a halt, not a fallback.\n  "
        + "\n  ".join(attempts))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verify-only", action="store_true",
                        help="re-check the cached file against the gated repo, download nothing")
    args = parser.parse_args()

    index = gated_file_index()
    print(f"gated repo {GATED_REPO} @ {index['repo_sha'][:12]}...  (gated={index['gated']})")

    records = []
    for filename in FILES:
        target = index["files"][filename]["blob_id"]
        dest = CACHE_DIR / filename

        if args.verify_only or dest.exists():
            if not dest.exists():
                raise SystemExit(f"{dest} not cached -- run without --verify-only first")
            data = dest.read_bytes()
            got = git_blob_sha1(data)
            if got != target:
                raise SystemExit(
                    f"{dest} no longer matches {GATED_REPO}: blob {got} != {target}")
            source = "cache"
            if not args.verify_only:
                print(f"  {filename:<24} cached, blob verified {got[:12]}...")
        else:
            data, mirror = fetch_verified(filename, target)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            source = mirror
            print(f"  {filename:<24} {len(data):>9,} bytes from {mirror}, "
                  f"blob {target[:12]}... VERIFIED")

        records.append({
            "filename": filename,
            "path": str(dest).replace("\\", "/"),
            "bytes": len(data),
            "git_blob_sha1": git_blob_sha1(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "matches_gated_repo": True,
            "downloaded_from": source,
        })

    if args.verify_only:
        print(f"VERIFY OK: {len(records)} file(s) still byte-identical to {GATED_REPO}")
        return

    manifest = {
        "what": "Model config.json for the pinned served model, hash-proven against the gated "
                "repository without needing access to it.",
        "gated_repo": GATED_REPO,
        "gated_repo_commit": index["repo_sha"],
        "verification": (
            "Each file's git blob SHA-1 was compared against the blob id the public Hugging "
            "Face metadata API reports for that path in the gated repo. Equal blob ids means "
            "byte-identical contents."
        ),
        "mirrors_tried_in_order": list(MIRRORS),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": records,
    }
    MANIFEST.write_bytes(json.dumps(manifest, indent=2).encode("utf-8"))
    print(f"\nmanifest: {MANIFEST}")


if __name__ == "__main__":
    main()

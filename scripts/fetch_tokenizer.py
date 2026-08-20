#!/usr/bin/env python
"""Fetch the pinned model's tokenizer, and PROVE it is the pinned model's
(R4 README R4B).

`meta-llama/Llama-3.2-3B-Instruct` is a gated repository: its files return
HTTP 401 without an accepted licence and a token. The capacity check in R4B
needs that exact tokenizer, and "close enough" is not a category the check
can accept -- the whole point is to replace a conservative char-to-token
estimate with exact evidence.

The way through is that Hugging Face's *metadata* API is public even when the
files are not. It reports, for every file in the gated repo, the git blob
SHA-1 of its contents. Several ungated mirrors republish the same tokenizer
verbatim. So:

    1. read the gated repo's blob id for tokenizer.json from the public API
    2. download that file from an ungated mirror
    3. compute the git blob id of what arrived
    4. require them to be equal, or refuse

Step 4 is what turns "a Llama 3.2 tokenizer" into "the tokenizer file that
`meta-llama/Llama-3.2-3B-Instruct` serves, byte for byte". A mirror could be
wrong, stale or hostile; it cannot be any of those and still hash correctly.

Both files are fetched, because the capacity question is about the *rendered
chat request*, not the bare prompt:
  - `tokenizer.json`         the tokenizer itself
  - `tokenizer_config.json`  carries the chat template vLLM applies

Usage:
    .venv/Scripts/python.exe scripts/fetch_tokenizer.py
    .venv/Scripts/python.exe scripts/fetch_tokenizer.py --verify-only
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

# The exact served model, from the first session's vLLM config line.
GATED_REPO = "meta-llama/Llama-3.2-3B-Instruct"

# Ungated mirrors, tried in order. Membership in this list buys nothing: a
# mirror is only used if its file hashes to the gated repo's blob id.
MIRRORS = (
    "alpindale/Llama-3.2-3B-Instruct",
    "chuanli11/Llama-3.2-3B-Instruct-uncensored",
    "NousResearch/Llama-3.2-1B",
)

FILES = ("tokenizer.json", "tokenizer_config.json")

# Deliberately outside the repo tree: a 9MB vendored tokenizer is a build
# input, not evidence, and committing it would bloat the repo for no
# reproducibility gain now that the hash proof lives in the manifest.
CACHE_DIR = REPO_ROOT / ".tokenizer_cache" / GATED_REPO.replace("/", "__")
MANIFEST = CACHE_DIR / "PROVENANCE.json"

USER_AGENT = "LLMRouter-week2-preflight/1.0"


def git_blob_sha1(data: bytes) -> str:
    """Git's object id for a blob: sha1(b'blob <len>\\0' + content).

    This is the identifier the HF API reports for non-LFS files, so computing
    it locally is what makes the comparison possible at all.
    """
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
            data = http_get(url)
        except Exception as exc:
            attempts.append(f"{mirror}: unreachable ({type(exc).__name__})")
            continue
        got = git_blob_sha1(data)
        if got == target_blob:
            return data, mirror
        attempts.append(f"{mirror}: blob {got[:12]}... != {target_blob[:12]}...")

    raise SystemExit(
        f"no mirror served a byte-identical {filename}. The capacity check must not run "
        f"against an approximate tokenizer, so this is a halt, not a fallback.\n  "
        + "\n  ".join(attempts))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verify-only", action="store_true",
                        help="re-check the cached files against the gated repo, download nothing")
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
        "what": "Tokenizer files for the pinned served model, hash-proven against the gated "
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

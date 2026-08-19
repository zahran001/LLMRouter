"""Per-point artifact naming and byte-stable artifact writing
(WEEK2_GPU_REDESIGN_HANDOFF.md §11/§17B; R4 README P2).

Two concerns, both about the *files* rather than their contents: recovering
a point tag from a filename, and writing an artifact whose bytes do not
depend on which platform wrote it.

## Getting the point tag back out of a filename

A point writes three files that share a tag:

    poisson_rps1.5.raw_log.jsonl
    poisson_rps1.5.samples.jsonl
    poisson_rps1.5.metrics.json

The completeness check in `scripts/gpu_session/pull_artifacts.sh` used to
recover the tag with `name.split(".")[0]`, which reads `poisson_rps1.5...`
as `poisson_rps1` -- so a fractional point looked like a *different*,
incomplete point whose sidecar and metrics were missing. The 1.5-RPS
artifacts were intact; the checker was wrong, on the meter, while the
instance was still up and the "missing" point looked re-drivable.

The corrected rule is to strip a KNOWN suffix rather than to cut at the
first dot, because a point tag legitimately contains dots and an artifact
suffix never does anything else. Stage B resolves the breach with fractional
RPS points, so this is a precondition of the next session, not cleanup.

## Writing an artifact whose bytes are a contract

`Path.write_text` opens in text mode with `newline=None`, so on Windows every
LF becomes CRLF on the way to disk. A frozen schedule generated on
Windows and one generated on Linux then differ in every line while meaning
exactly the same thing -- and a frozen workload that is only byte-reproducible
on the platform that froze it is not frozen. This is the same failure that
stopped Stage A on the meter, one layer up: there it was git rewriting the
corpus on checkout, here it is Python rewriting the artifact on write.

`write_json_artifact` pins the encoding, the newline and the JSON formatting,
so regeneration is byte-exact across platforms. Verified against history:
re-serialising `poisson_rps2.schedule.json` reproduces the committed blob
byte-for-byte.

Pair it with a `-text` entry in `.gitattributes` for the artifact's path.
Both halves are needed: this one stops the *writer* translating newlines,
that one stops *git* translating them on checkout.
"""

from __future__ import annotations

import json
from pathlib import Path

# Every per-point artifact suffix. Longest-first is not required (none is a
# suffix of another) but the tuple order is the discovery order.
RAW_LOG_SUFFIX = ".raw_log.jsonl"
SAMPLES_SUFFIX = ".samples.jsonl"
METRICS_SUFFIX = ".metrics.json"
SCHEDULE_SUFFIX = ".schedule.json"

ARTIFACT_SUFFIXES = (RAW_LOG_SUFFIX, SAMPLES_SUFFIX, METRICS_SUFFIX, SCHEDULE_SUFFIX)


def tag_for(path: Path | str, suffixes: tuple[str, ...] = ARTIFACT_SUFFIXES) -> str:
    """The point tag a per-point artifact belongs to.

    Raises on a filename that carries no known artifact suffix: a silent
    fallback (e.g. returning the whole name) would let an unrelated file
    invent a phantom point in a completeness table, which is the same class
    of failure as the truncation this replaces.
    """
    name = Path(path).name
    for suffix in suffixes:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    raise ValueError(
        f"{name!r} carries no known per-point artifact suffix "
        f"({', '.join(suffixes)}) -- cannot derive a point tag from it"
    )


def discover_tags(directory: Path | str, suffix: str = RAW_LOG_SUFFIX) -> list[str]:
    """Sorted point tags in a run directory, keyed off one artifact kind.

    Keyed off the raw log by default: a point that produced no raw log did
    not run at all, whereas a missing sidecar is a real point with a real
    problem -- and the caller needs to see the second case rather than have
    it vanish from the listing.
    """
    directory = Path(directory)
    return sorted({tag_for(p, (suffix,)) for p in directory.glob(f"*{suffix}")})


def json_artifact_bytes(obj, indent: int = 2) -> bytes:
    """The exact bytes an artifact should have on every platform.

    Separated from the write so callers can hash or compare a candidate
    artifact without touching the filesystem -- which is what makes
    "regeneration reproduces the frozen bytes" a check rather than a claim.

    `ensure_ascii=True` is deliberate and load-bearing, not a leftover default.
    The committed Stage A schedules were serialized with it (their embedded
    corpus provenance contains section signs, stored as `\\u00a7`), so writing
    UTF-8 directly would make regeneration differ from history at the first
    non-ASCII character while every line looked identical. Pure-ASCII output is
    also one fewer encoding assumption for anything that reads these files.
    """
    return json.dumps(obj, indent=indent, ensure_ascii=True).encode("ascii")


def write_json_artifact(path: Path | str, obj, indent: int = 2) -> str:
    """Write a JSON artifact byte-stably. Returns the sha256 of what landed."""
    import hashlib

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json_artifact_bytes(obj, indent=indent)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()

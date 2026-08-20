"""Pre-materialize the full arrival schedule before any sending starts
(WEEK2_PLAN.md §3.2).

The failure mode this avoids: lazily drawing arrival gaps inline lets the
arrival RNG interleave with prompt selection, so draw order becomes
runtime-timing-dependent and the "deterministic" schedule silently isn't.
Instead: draw the whole `(scheduled_offset, prompt_id)` list up front, from
independent `arrival_rng` / `corpus_rng` streams (loadgen/rng.py), write it to
disk before sending begins, and have the send loop do zero RNG work.

One continuous schedule covers warmup + measurement window -- the schedule
does not know about warmup; the metrics filter discards the first N seconds
by timestamp (§2.4). Warmup load is therefore statistically identical to
measured load.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from loadgen.corpus import Corpus, draw_prompt_id, draw_prompt_id_long_context
from loadgen.rng import RNG_SCHEME_VERSION, derive_streams
from metrics.artifacts import write_json_artifact

# Bump on any change to how a schedule's entries are generated (arrival math,
# corpus draw function, truncation rule) -- distinct from RNG_SCHEME_VERSION,
# which covers only the seed -> stream derivation. Both are recorded so a
# stale archived schedule can be told apart from a current one.
SCHEDULE_SCHEME_VERSION = "loadgen-schedule-v1"

# Every format this reader accepts. v1 is the first session's fixed-duration
# schedule; v2 is the redesigned exact-N headline family
# (`loadgen/headline_schedule.py`). Listed here rather than imported to keep
# the dependency pointing one way -- headline_schedule imports this module.
KNOWN_SCHEDULE_SCHEME_VERSIONS = frozenset({
    SCHEDULE_SCHEME_VERSION,
    "headline-schedule-v2",
})


@dataclass(frozen=True)
class ScheduleEntry:
    scheduled_offset: float  # seconds from t_start
    prompt_id: int


@dataclass
class Schedule:
    provenance: dict
    entries: list[ScheduleEntry]

    def to_dict(self) -> dict:
        return {
            "provenance": self.provenance,
            "entries": [asdict(e) for e in self.entries],
        }

    def save(self, path: Path | str) -> str:
        """Write the frozen schedule byte-stably; returns its sha256.

        Byte-stably because `Path.write_text` translates LF to CRLF on
        Windows, so the same schedule written on the dev box and on the GPU
        instance would differ in every line (R4 README P2). The serialized
        form is unchanged -- re-serialising a committed Stage A schedule
        reproduces its blob byte-for-byte -- so this fixes the writer without
        touching any historical artifact.
        """
        return write_json_artifact(path, self.to_dict())

    @classmethod
    def load(cls, path: Path | str) -> "Schedule":
        """Read a frozen schedule of any KNOWN format version.

        The version check exists because the redesign added a second format
        (`headline-schedule-v2`, exact-N with a warmup boundary) alongside the
        first session's `loadgen-schedule-v1`. Both are legitimate and both
        must keep parsing under their own contract -- but an *unknown* version
        must fail loudly rather than being read with whatever semantics this
        code happens to implement today. Silent coercion is how a frozen
        workload stops meaning what its provenance says (R4 README R5).
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        version = data.get("provenance", {}).get("schedule_scheme_version")
        if version not in KNOWN_SCHEDULE_SCHEME_VERSIONS:
            raise ValueError(
                f"{path}: unknown schedule_scheme_version {version!r}. Known versions are "
                f"{sorted(KNOWN_SCHEDULE_SCHEME_VERSIONS)}. Refusing to interpret an unknown "
                "format rather than guessing at its semantics."
            )
        entries = [ScheduleEntry(**e) for e in data["entries"]]
        return cls(provenance=data["provenance"], entries=entries)

    def validate_corpus_version(self, corpus: Corpus) -> None:
        """WEEK2_PLAN.md §5: replay's reproducibility contract is "frozen
        schedule artifact + pinned corpus artifact (by version) = identical
        workload" -- a schedule alone is not enough if the corpus it
        references has silently drifted (re-downloaded, re-filtered,
        re-sampled) since the schedule was built. Raises on mismatch rather
        than silently driving a different workload than the one the
        schedule's own provenance claims.
        """
        expected = self.provenance.get("corpus_sha256")
        if expected is None:
            raise ValueError("schedule has no corpus_sha256 in its provenance -- cannot validate corpus version")
        actual = hashlib.sha256(corpus.source_path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(
                f"corpus drift detected: schedule was built against corpus_sha256={expected}, "
                f"but {corpus.source_path} currently hashes to {actual} -- replay would drive a "
                "different workload than the one this schedule's provenance claims. Use the exact "
                "corpus file/version recorded in the schedule's provenance."
            )


def _corpus_provenance(corpus: Corpus) -> dict:
    """Embed enough about the corpus to detect drift on replay (§5: 'the
    schedule records the corpus version it was built against')."""
    digest = hashlib.sha256(corpus.source_path.read_bytes()).hexdigest()
    prov_path = corpus.source_path.with_name(corpus.source_path.stem + ".provenance.json")
    corpus_meta = json.loads(prov_path.read_text(encoding="utf-8")) if prov_path.exists() else None
    return {
        "corpus_path": str(corpus.source_path),
        "corpus_sha256": digest,
        "corpus_size": len(corpus),
        "corpus_build_provenance": corpus_meta,
    }


def _base_provenance(
    master_seed: int, target_rps: float, arrival_process: str, duration_s: float, corpus: Corpus, extra: dict
) -> dict:
    return {
        "master_seed": master_seed,
        "rng_scheme_version": RNG_SCHEME_VERSION,
        "schedule_scheme_version": SCHEDULE_SCHEME_VERSION,
        "target_rps": target_rps,
        "arrival_process": arrival_process,
        "duration_s": duration_s,
        **_corpus_provenance(corpus),
        **extra,
    }


def build_poisson_schedule(
    target_rps: float, duration_s: float, master_seed: int, corpus: Corpus, long_context: bool = False
) -> Schedule:
    """Exponential inter-arrival gaps at lambda=target_rps, cumsum to absolute
    offsets, truncated to duration_s. Prompt assignment happens here (at
    materialization time), not at send time (§3.4)."""
    arrival_rng, corpus_rng = derive_streams(master_seed)

    offsets: list[float] = []
    t = 0.0
    while True:
        gap = arrival_rng.exponential(1.0 / target_rps)
        t += gap
        if t >= duration_s:
            break
        offsets.append(t)

    draw = draw_prompt_id_long_context if long_context else draw_prompt_id
    entries = [ScheduleEntry(scheduled_offset=o, prompt_id=draw(corpus, corpus_rng)) for o in offsets]

    provenance = _base_provenance(
        master_seed, target_rps, "poisson", duration_s, corpus,
        {"long_context": long_context, "n_scheduled": len(entries)},
    )
    return Schedule(provenance=provenance, entries=entries)


def build_steady_schedule(
    target_rps: float, duration_s: float, master_seed: int, corpus: Corpus, long_context: bool = False
) -> Schedule:
    """Constant 1/target_rps gaps -- no arrival RNG (trivially reproducible,
    part of why steady is the legible reference, §2.1). corpus_rng is still
    derived from the same master seed/scheme for prompt draws, so the corpus
    draw sequence follows the same reproducibility contract as Poisson."""
    _arrival_rng, corpus_rng = derive_streams(master_seed)

    gap = 1.0 / target_rps
    n = int(duration_s // gap)
    offsets = [i * gap for i in range(n)]

    draw = draw_prompt_id_long_context if long_context else draw_prompt_id
    entries = [ScheduleEntry(scheduled_offset=o, prompt_id=draw(corpus, corpus_rng)) for o in offsets]

    provenance = _base_provenance(
        master_seed, target_rps, "steady", duration_s, corpus,
        {"long_context": long_context, "n_scheduled": len(entries)},
    )
    return Schedule(provenance=provenance, entries=entries)

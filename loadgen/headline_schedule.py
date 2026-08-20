"""Matched repeat-family schedules with exact-N semantics
(R4 README R5/R6; `WEEK2_PLAN.md` §10.1/§10.2).

## The invariant this module exists to hold

    N is a schedule-generation constraint, enforced offline.
    N is NEVER a runtime stop condition.

Both readings pass a naive test. A build that stops after `N` completions
produces runs of very nearly the right size and looks correct in every
summary — and is closed-loop, because the server's own latency then decides
how much work it is offered. At exactly the load level where the breach
happens, that feedback removes the thing being measured.

So the count is fixed here, in an offline materialization, before any request
is sent. Runtime loads the frozen list and drives all of it. Completions,
TTFT, errors, timeouts, censoring rate and the running p99 may all change
whether a point is *valid*; none of them may change what was *offered*.

`N / λ` is likewise not the duration. It is the expectation of the duration,
and using it would put finite-Poisson count variance straight back into the
quantity `N` was calibrated to hold still.

## Repeat identity

    canonical membership   identical in every repeat and at every λ
    assignment seed        new per repeat -> new prompt order
    arrival seed           new per repeat -> new Poisson realization
    vLLM process           the same one (no restart between repeats)

Within one repeat, every λ point maps the *same* ordered canonical sequence
onto its post-warmup arrivals. That is what makes two λ points comparable:
same prompts, same order, only the arrival timing differs. Across repeats
both seeds change, which is what makes two repeats independent.

Note what is deliberately *not* varied: membership. Re-drawing prompts per
repeat would reintroduce exactly the realized-tail variance the canonical
construction removes.

## Warmup

Time-based, excluded from `N`, drawn i.i.d. from the pinned corpus with its
own derived RNG stream. Warmup arrivals are part of the frozen schedule and
are driven normally; the metrics layer discards them by send timestamp, so
warmup load is statistically identical to measured load.

Warmup prompts may coincide with canonical ones. That would have been a
contamination risk while prefix caching was enabled; it is not one now,
because the controlled headline runs with caching disabled (§10.8).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from loadgen.canonical import CANONICAL_SCHEME_VERSION
from loadgen.corpus import Corpus
from loadgen.schedule import Schedule, ScheduleEntry
from metrics.artifacts import write_json_artifact

# A NEW format version, not an edit to the old one. Legacy Stage A schedules
# stay `loadgen-schedule-v1` and keep parsing under their own contract; the
# reader refuses an unknown version rather than coercing it (README R5).
HEADLINE_SCHEDULE_SCHEME_VERSION = "headline-schedule-v2"

# Seed -> stream derivation for the headline family. Separate from
# `loadgen.rng.RNG_SCHEME_VERSION` because the stream layout is different
# (arrival + warmup-corpus, with assignment handled by hash), and a shared
# version tag would make one scheme's change look like the other's.
HEADLINE_RNG_SCHEME_VERSION = "headline-rng-v1"


class HeadlineScheduleError(RuntimeError):
    """Raised when the exact-N contract cannot be honoured."""


@dataclass(frozen=True)
class RepeatIdentity:
    """Everything that makes one repeat distinct from another."""
    canonical_membership_id: str
    repeat_id: int
    arrival_seed: int
    assignment_seed: int

    def to_dict(self) -> dict:
        return {
            "canonical_prompt_membership_id": self.canonical_membership_id,
            "repeat_id": self.repeat_id,
            "arrival_seed": self.arrival_seed,
            "assignment_seed": self.assignment_seed,
        }


def derive_headline_streams(arrival_seed: int, repeat_id: int
                            ) -> tuple[np.random.Generator, np.random.Generator]:
    """(arrival_rng, warmup_corpus_rng), independent, reproducible.

    Child 0 is always arrival, child 1 is always warmup-corpus — fixed by
    HEADLINE_RNG_SCHEME_VERSION. `repeat_id` is folded into the entropy so two
    repeats with the same nominal seed still differ, and so a repeat's
    identity is visible in its stream rather than only in its filename.
    """
    parent = np.random.SeedSequence([arrival_seed, repeat_id])
    arrival_seq, warmup_seq = parent.spawn(2)
    return np.random.default_rng(arrival_seq), np.random.default_rng(warmup_seq)


def canonical_permutation(membership: list[int], assignment_seed: int) -> list[int]:
    """The repeat's prompt order: a deterministic permutation of the canonical
    membership.

    Hash-keyed for the same reason the membership selection is (see
    `loadgen/canonical.py`): NumPy does not promise `Generator` stream
    stability across releases, and this ordering has to reproduce for as long
    as the schedules built from it are cited.
    """
    def key(prompt_id: int) -> str:
        return hashlib.sha256(f"{assignment_seed}:perm:{prompt_id}".encode("utf-8")).hexdigest()

    return sorted(membership, key=key)


def materialize_exact_n(nominal_lambda_rps: float, warmup_s: float, n: int,
                        arrival_rng: np.random.Generator) -> tuple[list[float], int]:
    """Poisson offsets containing EXACTLY `n` arrivals at or after `warmup_s`.

    Draws exponential gaps until the post-warmup count reaches `n`, then
    stops. The number of warmup arrivals and the total duration are both
    outcomes of the realization, not inputs — which is the point: fixing the
    measured count is what makes λ points comparable, and letting duration
    float is what keeps the arrival process honestly Poisson.

    Returns `(offsets, n_warmup)`.
    """
    if nominal_lambda_rps <= 0:
        raise HeadlineScheduleError(f"nominal lambda must be positive, got {nominal_lambda_rps}")
    if n <= 0:
        raise HeadlineScheduleError(f"N must be positive, got {n}")
    if warmup_s < 0:
        raise HeadlineScheduleError(f"warmup must be non-negative, got {warmup_s}")

    mean_gap = 1.0 / nominal_lambda_rps
    offsets: list[float] = []
    post_warmup = 0
    t = 0.0
    while post_warmup < n:
        t += float(arrival_rng.exponential(mean_gap))
        offsets.append(t)
        if t >= warmup_s:
            post_warmup += 1

    return offsets, len(offsets) - n


def build_headline_schedule(
    *,
    canonical: dict,
    corpus: Corpus,
    identity: RepeatIdentity,
    nominal_lambda_rps: float,
    warmup_s: float,
) -> Schedule:
    """One frozen headline schedule: warmup traffic + exactly N canonical arrivals."""
    if canonical["scheme_version"] != CANONICAL_SCHEME_VERSION:
        raise HeadlineScheduleError(
            f"canonical workload is {canonical['scheme_version']!r}, this generator implements "
            f"{CANONICAL_SCHEME_VERSION!r}")
    if canonical["membership_id"] != identity.canonical_membership_id:
        raise HeadlineScheduleError(
            f"identity references membership {identity.canonical_membership_id[:16]}... but the "
            f"supplied workload is {canonical['membership_id'][:16]}...")

    membership = canonical["membership"]
    n = canonical["locks"]["N"]
    if len(membership) != n:
        raise HeadlineScheduleError(f"workload declares N={n} but carries {len(membership)} prompts")

    arrival_rng, warmup_rng = derive_headline_streams(identity.arrival_seed, identity.repeat_id)
    offsets, n_warmup = materialize_exact_n(nominal_lambda_rps, warmup_s, n, arrival_rng)

    order = canonical_permutation(membership, identity.assignment_seed)

    # Warmup draws are i.i.d. with replacement over the whole pinned corpus --
    # ordinary traffic, not canonical traffic. The canonical membership is
    # untouched by whatever warmup happens to draw.
    warmup_prompt_ids = [
        corpus.prompts[int(warmup_rng.integers(0, len(corpus.prompts)))].prompt_id
        for _ in range(n_warmup)
    ]

    entries = [
        ScheduleEntry(scheduled_offset=offset, prompt_id=prompt_id)
        for offset, prompt_id in zip(offsets[:n_warmup], warmup_prompt_ids)
    ] + [
        ScheduleEntry(scheduled_offset=offset, prompt_id=prompt_id)
        for offset, prompt_id in zip(offsets[n_warmup:], order)
    ]

    post_warmup_count = sum(1 for e in entries if e.scheduled_offset >= warmup_s)
    if post_warmup_count != n:
        raise HeadlineScheduleError(
            f"materialization produced {post_warmup_count} post-warmup arrivals, expected exactly "
            f"{n} -- the exact-N contract is broken")

    duration_s = entries[-1].scheduled_offset
    corpus_digest = hashlib.sha256(corpus.source_path.read_bytes()).hexdigest()
    if corpus_digest != canonical["corpus"]["sha256"]:
        raise HeadlineScheduleError(
            f"corpus drift: workload was built against {canonical['corpus']['sha256']}, this "
            f"corpus hashes to {corpus_digest}")

    provenance = {
        # --- format identity ------------------------------------------------
        "schedule_scheme_version": HEADLINE_SCHEDULE_SCHEME_VERSION,
        "rng_scheme_version": HEADLINE_RNG_SCHEME_VERSION,
        "canonical_scheme_version": canonical["scheme_version"],
        "workload_class": "headline_controlled",
        # --- repeat identity (R5) -------------------------------------------
        **identity.to_dict(),
        # --- workload parameters --------------------------------------------
        "arrival_process": "poisson",
        "nominal_lambda_rps": nominal_lambda_rps,
        "warmup_boundary_s": warmup_s,
        "post_warmup_target_count": n,
        # --- realization outcomes (R6) ---------------------------------------
        "materialized_schedule_count": len(entries),
        "materialized_warmup_count": n_warmup,
        "materialized_post_warmup_count": post_warmup_count,
        "materialized_schedule_duration_s": duration_s,
        "materialized_post_warmup_duration_s": duration_s - warmup_s,
        "materialized_schedule_rps": post_warmup_count / (duration_s - warmup_s)
        if duration_s > warmup_s else 0.0,
        "expected_duration_if_deterministic_s": n / nominal_lambda_rps + warmup_s,
        # --- corpus contract --------------------------------------------------
        "corpus_path": str(corpus.source_path),
        "corpus_sha256": corpus_digest,
        "corpus_size": len(corpus),
        "warmup_prompt_source": "i.i.d. with replacement over the full pinned corpus, "
                                "warmup_corpus_rng (child 1 of the headline seed sequence)",
        # --- the invariant, stated in the artifact itself ---------------------
        "n_is_a_schedule_generation_constraint": True,
        "runtime_stop_condition": "schedule issuance exhausted",
        "note": "duration_s is an OUTCOME of the Poisson realization, not an input. Runtime "
                "must drive every entry and must not stop on completions, samples, errors or "
                "censoring (WEEK2_PLAN.md 10.2).",
        # --- back-compat for readers that predate v2 --------------------------
        # `duration_s` and `target_rps` keep their legacy names so the existing
        # scheduler and point-metrics code read a v2 schedule without special
        # cases. Their MEANING is recorded above; nothing infers it from these.
        "duration_s": duration_s,
        "target_rps": nominal_lambda_rps,
        "n_scheduled": len(entries),
    }

    return Schedule(provenance=provenance, entries=entries)


def schedule_family_tag(repeat_id: int, nominal_lambda_rps: float) -> str:
    """Artifact tag. `rps1.5` must survive discovery -- see metrics.artifacts."""
    rps = f"{nominal_lambda_rps:g}"
    return f"headline_r{repeat_id}_rps{rps}"


def save_headline_schedule(schedule: Schedule, directory: Path | str) -> tuple[Path, str]:
    prov = schedule.provenance
    tag = schedule_family_tag(prov["repeat_id"], prov["nominal_lambda_rps"])
    path = Path(directory) / f"{tag}.schedule.json"
    digest = write_json_artifact(path, schedule.to_dict())
    return path, digest


def load_headline_schedule(path: Path | str) -> Schedule:
    """Load a v2 schedule, refusing anything else.

    A v1 schedule loaded here would be driven with warmup/exact-N semantics it
    was never built under, so this refuses rather than guessing. `Schedule.load`
    remains the reader for legacy artifacts.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    version = data.get("provenance", {}).get("schedule_scheme_version")
    if version != HEADLINE_SCHEDULE_SCHEME_VERSION:
        raise HeadlineScheduleError(
            f"{path}: schedule_scheme_version {version!r}, expected "
            f"{HEADLINE_SCHEDULE_SCHEME_VERSION!r}. Legacy schedules are read with "
            "loadgen.schedule.Schedule.load under their own contract; they are never "
            "reinterpreted under redesigned semantics.")
    return Schedule(provenance=data["provenance"],
                    entries=[ScheduleEntry(**e) for e in data["entries"]])

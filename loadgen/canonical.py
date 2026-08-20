"""The canonical headline prompt multiset (R4 README R4A; `WEEK2_PLAN.md` §10.1).

## What this replaces, and why

The first session fed every RPS point the same *seeded distribution* and assumed
that held the prompt contribution constant. It held the population constant and
let the realized tail move: a fixed 120s window makes request count a function of
λ, so the 1 RPS point drew zero prompts over 10k chars and the 10 RPS point drew
fourteen. Excluding essentially one extreme prompt flipped the 2-RPS breach
verdict.

The fix is to stop sampling the workload per point and start *constructing* it
once: a frozen multiset of exactly `N` unique prompt IDs, drawn proportionally
from `k` length strata, reused unchanged at every RPS point and in every repeat.
The empirical prompt-cost mix is then identical by construction rather than
identical in expectation.

## The locked construction

    k = 6 strata at corpus quantiles 0/50/90/95/99/99.5/100
    L = corpus q99 = 11,471 chars  (the tail-support boundary)
    N = 4,000 unique prompt IDs
    N_max = 5,000                  (structural: the corpus holds 5,000)

Allocation is **proportional to each stratum's natural population share**, by
largest remainder. Proportional, not tail-inflating: the goal is to make the
corpus's natural composition deterministic, not to reshape it. That also honours
the original §3.4 intent ("measuring the corpus's natural mix") more exactly than
a random draw did, because the mix is now exact rather than sampled.

## Why selection is hash-based rather than RNG-based

Which prompts fill a stratum has to be reproducible for as long as the artifact
is cited — across machines, Python versions and NumPy versions. NumPy explicitly
does *not* guarantee that `Generator` method streams stay identical across
releases, so a `rng.choice` selection would silently stop reproducing after an
upgrade, and the failure would look like corruption.

Instead each candidate gets a deterministic sort key `sha256(seed:prompt_id)`
and the lowest keys win. That is stable across every language and runtime, needs
no RNG at all, and can be re-derived by hand from the recorded seed. The arrival
and corpus RNG streams in `loadgen/rng.py` are unaffected — they solve a
different problem (per-run schedule generation), where NumPy's streams are
appropriate because the schedule artifact itself is what gets frozen.

## Selection without replacement

No prompt appears twice in the canonical multiset. Repeating a prompt inside one
run is not neutral on this server: prefix caching is a live, large effect, and a
second serving of the same prompt collapsed from 523.3ms to 103.9ms in the first
session. Repetition would make a request's cost depend on its position in the
run. That constraint is also what makes `N_max` structural — the corpus holds
5,000 prompts, so 5,000 is the ceiling.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from loadgen.corpus import Corpus

# Bump on any change to how membership is derived -- stratum assignment,
# allocation rule, or selection key. Same discipline as RNG_SCHEME_VERSION:
# the version is what lets a reader tell a stale frozen artifact from a
# current one instead of assuming they match.
CANONICAL_SCHEME_VERSION = "canonical-workload-v1"

# --- LOCKED at Hard Stop R3, 2026-08-19 -------------------------------------
# Read off benchmarks/calibration/week2_redesign/R3_EVIDENCE_PACKAGE.md by the
# human. Do not adjust these to make a build succeed; a mismatch is a finding.
K_NAME = "k6_readme_example"
STRATUM_EDGES_PCT: tuple[float, ...] = (0.0, 50.0, 90.0, 95.0, 99.0, 99.5, 100.0)
L_PCT = 99.0
CANONICAL_N = 4000
N_MAX = 5000
CANONICAL_SELECTION_SEED = 20260819

# The char-length boundaries these quantiles resolved to against the pinned
# corpus, recorded so a corpus change is caught as a mismatch rather than
# silently producing a different workload under the same name. Compared with a
# tolerance because they come out of a float percentile computation.
EXPECTED_EDGES_CHARS: tuple[float, ...] = (1.0, 142.0, 2358.1, 4566.2, 11471.37, 13101.0, 44445.0)
EDGE_TOLERANCE_CHARS = 0.5
EXPECTED_L_CHARS = 11471.37

# The corpus this construction was calibrated against. A different corpus is a
# different experiment, so the builder refuses rather than adapting.
EXPECTED_CORPUS_SHA256 = "f7ec37d33bc2f53c4468a39c52b792406dbb383de8a38cfbc207c8cf59af6630"
EXPECTED_CORPUS_SIZE = 5000


class CanonicalWorkloadError(RuntimeError):
    """Raised when the locked construction cannot be honoured exactly."""


@dataclass(frozen=True)
class Stratum:
    index: int
    quantile_range_pct: tuple[float, float]
    char_len_range: tuple[float, float]
    population_fraction: float
    available_prompt_ids: tuple[int, ...]
    selected_prompt_ids: tuple[int, ...]

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "quantile_range_pct": list(self.quantile_range_pct),
            "char_len_range": list(self.char_len_range),
            "population_fraction": self.population_fraction,
            "available_count": len(self.available_prompt_ids),
            "selected_count": len(self.selected_prompt_ids),
            "selected_prompt_ids": list(self.selected_prompt_ids),
        }


def corpus_sha256(corpus: Corpus) -> str:
    return hashlib.sha256(corpus.source_path.read_bytes()).hexdigest()


def selection_key(seed: int, prompt_id: int) -> str:
    """The deterministic sort key. Stable across languages and runtimes, and
    re-derivable by hand from the recorded seed."""
    return hashlib.sha256(f"{seed}:{prompt_id}".encode("utf-8")).hexdigest()


def resolve_edges(corpus: Corpus) -> list[float]:
    lengths = np.array([p.char_len for p in corpus.prompts], dtype=float)
    return [float(np.percentile(lengths, q, method="linear")) for q in STRATUM_EDGES_PCT]


def validate_corpus(corpus: Corpus) -> dict:
    """Refuse any corpus other than the one the construction was calibrated on.

    A changed corpus does not mean "recalibrate silently"; it means the frozen
    workload's identity contract is broken and a human has to decide what that
    implies (README R4A negative controls)."""
    digest = corpus_sha256(corpus)
    problems = []
    if digest != EXPECTED_CORPUS_SHA256:
        problems.append(
            f"corpus sha256 {digest} != locked {EXPECTED_CORPUS_SHA256} -- the canonical "
            "construction was calibrated against a different corpus")
    if len(corpus) != EXPECTED_CORPUS_SIZE:
        problems.append(f"corpus holds {len(corpus)} prompts, locked construction expects "
                        f"{EXPECTED_CORPUS_SIZE}")

    edges = resolve_edges(corpus)
    for i, (got, want) in enumerate(zip(edges, EXPECTED_EDGES_CHARS)):
        if abs(got - want) > EDGE_TOLERANCE_CHARS:
            problems.append(
                f"stratum edge {i} (q{STRATUM_EDGES_PCT[i]:g}) resolves to {got:.2f} chars, "
                f"locked value is {want:.2f}")

    if problems:
        raise CanonicalWorkloadError(
            "canonical workload refuses to build:\n  - " + "\n  - ".join(problems))

    return {"corpus_sha256": digest, "corpus_size": len(corpus), "edges_chars": edges}


def assign_strata(corpus: Corpus, edges: list[float]) -> list[list[int]]:
    """Partition every corpus prompt into exactly one stratum.

    Half-open `[lo, hi)` except the last stratum, which closes on the max --
    the same rule `scripts/analyze_corpus_tail.py` used, so the availability
    counts here and in the R3 evidence are the same numbers.
    """
    buckets: list[list[int]] = [[] for _ in range(len(edges) - 1)]
    last = len(buckets) - 1
    for prompt in corpus.prompts:
        placed = False
        for i in range(len(buckets)):
            lo, hi = edges[i], edges[i + 1]
            if (lo <= prompt.char_len <= hi) if i == last else (lo <= prompt.char_len < hi):
                buckets[i].append(prompt.prompt_id)
                placed = True
                break
        if not placed:
            raise CanonicalWorkloadError(
                f"prompt {prompt.prompt_id} (char_len={prompt.char_len}) fell outside every "
                "stratum -- the edge computation and the corpus disagree")
    return buckets


def allocate(n: int) -> list[int]:
    """Proportional allocation by largest remainder, summing to exactly `n`."""
    fractions = [
        (STRATUM_EDGES_PCT[i + 1] - STRATUM_EDGES_PCT[i]) / 100.0
        for i in range(len(STRATUM_EDGES_PCT) - 1)
    ]
    exact = [n * f for f in fractions]
    floors = [int(x) for x in exact]
    remainder = n - sum(floors)
    # Largest fractional part first; ties broken by stratum index so the result
    # does not depend on sort stability.
    order = sorted(range(len(floors)), key=lambda i: (-(exact[i] - floors[i]), i))
    for j in range(remainder):
        floors[order[j % len(floors)]] += 1
    return floors


def build(corpus: Corpus, n: int = CANONICAL_N, seed: int = CANONICAL_SELECTION_SEED) -> dict:
    """Construct the canonical membership. Pure: no I/O beyond hashing the
    corpus file, and no randomness beyond the recorded seed."""
    if n > N_MAX:
        raise CanonicalWorkloadError(
            f"N={n} exceeds the structural evidence ceiling N_max={N_MAX}. The pinned corpus "
            f"holds {EXPECTED_CORPUS_SIZE} prompts, so a larger N could only be reached by "
            "repeating prompts -- which is not neutral on a prefix-caching server and is "
            "forbidden (WEEK2_PLAN.md 10.3).")

    validated = validate_corpus(corpus)
    edges = validated["edges_chars"]
    buckets = assign_strata(corpus, edges)
    quota = allocate(n)

    by_id = {p.prompt_id: p for p in corpus.prompts}
    strata: list[Stratum] = []
    for i, (available, want) in enumerate(zip(buckets, quota)):
        if want > len(available):
            raise CanonicalWorkloadError(
                f"stratum {i} (q{STRATUM_EDGES_PCT[i]:g}-{STRATUM_EDGES_PCT[i + 1]:g}) needs "
                f"{want} prompts but only {len(available)} exist. Selection is without "
                "replacement by design; this is the structural ceiling biting.")
        chosen = sorted(sorted(available, key=lambda pid: selection_key(seed, pid))[:want])
        strata.append(Stratum(
            index=i,
            quantile_range_pct=(STRATUM_EDGES_PCT[i], STRATUM_EDGES_PCT[i + 1]),
            char_len_range=(edges[i], edges[i + 1]),
            population_fraction=(STRATUM_EDGES_PCT[i + 1] - STRATUM_EDGES_PCT[i]) / 100.0,
            available_prompt_ids=tuple(sorted(available)),
            selected_prompt_ids=tuple(chosen),
        ))

    membership = sorted(pid for s in strata for pid in s.selected_prompt_ids)
    if len(membership) != n:
        raise CanonicalWorkloadError(f"selected {len(membership)} prompts, expected {n}")
    if len(set(membership)) != n:
        raise CanonicalWorkloadError("canonical membership contains duplicate prompt IDs")

    lengths = np.array([by_id[pid].char_len for pid in membership], dtype=float)
    l_chars = edges[STRATUM_EDGES_PCT.index(L_PCT)]
    above_l = [pid for pid in membership if by_id[pid].char_len >= l_chars]

    return {
        "scheme_version": CANONICAL_SCHEME_VERSION,
        "membership_id": membership_id(membership),
        "locks": {
            "k_name": K_NAME,
            "k": len(strata),
            "stratum_edges_pct": list(STRATUM_EDGES_PCT),
            "stratum_edges_chars": edges,
            "L_pct": L_PCT,
            "L_chars": l_chars,
            "N": n,
            "N_max": N_MAX,
            "locked_at": "Hard Stop R3, 2026-08-19",
            "source": "benchmarks/calibration/week2_redesign/R3_EVIDENCE_PACKAGE.md",
        },
        "selection": {
            "algorithm": "per-stratum: sort candidates by sha256(f'{seed}:{prompt_id}'), "
                         "take the lowest `quota` keys, then sort the result by prompt_id",
            "allocation_rule": "proportional to population fraction, largest remainder, "
                               "ties broken by stratum index",
            "replacement": "without replacement; no prompt_id appears twice",
            "seed": seed,
            "why_hash_not_rng": "NumPy does not guarantee Generator stream stability across "
                                "releases; a hash key reproduces on any runtime, forever.",
        },
        "corpus": {
            "path": str(corpus.source_path).replace("\\", "/"),
            "sha256": validated["corpus_sha256"],
            "size": validated["corpus_size"],
        },
        "strata": [s.to_dict() for s in strata],
        "tail_support": {
            "L_chars": l_chars,
            "corpus_prompts_above_L": sum(1 for p in corpus.prompts if p.char_len >= l_chars),
            "canonical_prompts_above_L": len(above_l),
            "prompt_ids_above_L": above_l,
            "fraction_of_N": len(above_l) / n,
        },
        "char_len_profile": {
            "min": float(lengths.min()),
            "max": float(lengths.max()),
            "mean": float(lengths.mean()),
            "quantiles": {
                str(q): float(np.percentile(lengths, q, method="linear"))
                for q in (0, 25, 50, 75, 90, 95, 99, 99.5, 100)
            },
            "total_chars": int(lengths.sum()),
        },
        "membership": membership,
    }


def membership_id(membership: list[int]) -> str:
    """A stable identity for one canonical membership.

    Schedules reference this rather than embedding 4,000 IDs, so a schedule
    built against a different membership is detectable instead of merely
    different."""
    payload = ",".join(str(pid) for pid in sorted(membership))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_frozen(path: Path | str) -> dict:
    """Read a frozen canonical workload and re-verify its internal identity.

    The membership_id is recomputed from the membership rather than trusted,
    so an edited artifact fails here instead of silently defining a different
    workload downstream."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    recomputed = membership_id(data["membership"])
    if recomputed != data["membership_id"]:
        raise CanonicalWorkloadError(
            f"{path}: membership_id {data['membership_id']} does not match the membership it "
            f"contains (recomputed {recomputed}) -- the artifact was edited")
    if len(set(data["membership"])) != len(data["membership"]):
        raise CanonicalWorkloadError(f"{path}: membership contains duplicate prompt IDs")
    if data["scheme_version"] != CANONICAL_SCHEME_VERSION:
        raise CanonicalWorkloadError(
            f"{path}: scheme version {data['scheme_version']!r} but this code implements "
            f"{CANONICAL_SCHEME_VERSION!r} -- refusing to reinterpret an artifact from a "
            "different construction rather than silently coercing it")
    return data

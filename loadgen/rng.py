"""Seed -> independent RNG streams (WEEK2_PLAN.md §3.2).

The Poisson headline's reproducibility depends on arrival timing and corpus
selection never interleaving on a shared RNG -- a shared stream would make
draw order (and therefore the "deterministic" schedule) depend on code
structure/timing, not just the seed. `numpy.random.SeedSequence.spawn()`
gives two independent, reproducible child streams from one master seed.
"""

from __future__ import annotations

import numpy as np

# Bump this if the spawn order or child count below ever changes -- the same
# master seed would then produce a *different* schedule, and any archived
# schedule needs to record which scheme it was built under to stay
# interpretable (WEEK2_PLAN.md §3.2, "Provenance -- the RNG scheme is part of
# the reproducibility contract, not just metadata").
RNG_SCHEME_VERSION = "loadgen-rng-v1"


def derive_streams(master_seed: int) -> tuple[np.random.Generator, np.random.Generator]:
    """Return (arrival_rng, corpus_rng), independently derived from `master_seed`.

    Child 0 is always arrival, child 1 is always corpus -- fixed by
    RNG_SCHEME_VERSION. Do not reorder without bumping the version.
    """
    parent = np.random.SeedSequence(master_seed)
    arrival_seq, corpus_seq = parent.spawn(2)
    return np.random.default_rng(arrival_seq), np.random.default_rng(corpus_seq)

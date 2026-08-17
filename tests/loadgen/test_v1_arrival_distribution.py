"""V1 -- arrival distribution (WEEK2_PLAN.md §4). Offline: the materialized
schedule is a static artifact, so this is checked by inspecting it, no
sending involved.

Pass: Poisson inter-arrival gaps at (RPS, seed) fit Exponential(lambda=RPS)
(K-S goodness-of-fit). Determinism: same seed -> byte-identical
(offset, prompt_id) list; different seed -> different list.

The negative control (steady schedule must FAIL the exponential fit) lives
in test_negative_controls.py, run against the SAME assert_fits_exponential
helper -- see that file for why it must be the same function, not a
lookalike.
"""

from __future__ import annotations

import pytest

from loadgen.corpus import load_corpus
from loadgen.schedule import build_poisson_schedule
from tests.loadgen._assertions import assert_fits_exponential, gaps_from_schedule

pytestmark = pytest.mark.loadgen

RPS = 20.0
DURATION_S = 120.0
SEED = 42


@pytest.fixture(scope="module")
def corpus():
    return load_corpus()


def test_poisson_gaps_fit_exponential(corpus):
    schedule = build_poisson_schedule(RPS, DURATION_S, SEED, corpus)
    gaps = gaps_from_schedule(schedule)
    assert len(gaps) > 500, f"only {len(gaps)} arrivals -- too few for a meaningful K-S test"

    assert_fits_exponential(gaps, rate=RPS, context="V1 poisson: ")


def test_poisson_mean_gap_matches_target_rps(corpus):
    schedule = build_poisson_schedule(RPS, DURATION_S, SEED, corpus)
    gaps = gaps_from_schedule(schedule)
    mean_gap = sum(gaps) / len(gaps)
    target_gap = 1.0 / RPS
    assert abs(mean_gap - target_gap) / target_gap < 0.1, (
        f"mean gap {mean_gap:.4f}s deviates >10% from target 1/RPS={target_gap:.4f}s"
    )


def test_same_seed_byte_identical_schedule(corpus):
    s1 = build_poisson_schedule(RPS, DURATION_S, SEED, corpus)
    s2 = build_poisson_schedule(RPS, DURATION_S, SEED, corpus)
    assert s1.entries == s2.entries, "same seed produced different schedules -- determinism broken"


def test_different_seed_different_schedule(corpus):
    s1 = build_poisson_schedule(RPS, DURATION_S, SEED, corpus)
    s2 = build_poisson_schedule(RPS, DURATION_S, SEED + 1, corpus)
    assert s1.entries != s2.entries, "different seeds produced identical schedules"

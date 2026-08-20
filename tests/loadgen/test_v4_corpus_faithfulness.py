"""V4 -- corpus faithfulness (WEEK2_PLAN.md §4). Offline: inspect the
schedule's prompt assignments.

Pass: draws come only from the pinned corpus file; with-replacement produces
expected i.i.d. draw statistics; every prompt in the pinned file passes the
validity filter.

The negative control (a filter-bypassed corpus letting junk reach
assignment) lives in test_negative_controls.py.
"""

from __future__ import annotations

import pytest

from loadgen.corpus import draw_prompt_id, load_corpus
from loadgen.rng import derive_streams
from tests.loadgen._assertions import assert_all_prompts_valid

pytestmark = pytest.mark.loadgen

SEED = 42
N_DRAWS = 3000


@pytest.fixture(scope="module")
def corpus():
    return load_corpus()


def test_pinned_corpus_prompts_all_valid(corpus):
    assert_all_prompts_valid(corpus)


def test_draws_come_only_from_pinned_corpus(corpus):
    _arrival_rng, corpus_rng = derive_streams(SEED)
    valid_ids = {p.prompt_id for p in corpus.prompts}

    drawn = [draw_prompt_id(corpus, corpus_rng) for _ in range(N_DRAWS)]
    assert all(pid in valid_ids for pid in drawn), "a draw returned a prompt_id outside the pinned corpus"


def test_with_replacement_draws_are_iid_and_diverse(corpus):
    """Sanity check on the draw statistics -- not a rigorous uniformity test,
    but enough to catch a badly broken draw function (e.g. always returning
    the same id, or only ever drawing from a narrow slice)."""
    _arrival_rng, corpus_rng = derive_streams(SEED)
    drawn_ids = [draw_prompt_id(corpus, corpus_rng) for _ in range(N_DRAWS)]

    n_unique = len(set(drawn_ids))
    # With-replacement draws of N_DRAWS=3000 over a 5000-item pool expect
    # ~2255 unique ids (coupon-collector expectation); N_DRAWS/3 is a loose
    # floor that a correct implementation clears with wide margin but a
    # broken one (e.g. drawing from a tiny slice, or a constant) would not.
    assert n_unique > N_DRAWS / 3, f"only {n_unique} unique ids across {N_DRAWS} draws -- draws are not diverse"

    id_to_len = {p.prompt_id: p.char_len for p in corpus.prompts}
    population_mean = sum(p.char_len for p in corpus.prompts) / len(corpus.prompts)
    drawn_mean = sum(id_to_len[pid] for pid in drawn_ids) / len(drawn_ids)
    assert abs(drawn_mean - population_mean) / population_mean < 0.2, (
        f"drawn mean char_len {drawn_mean:.1f} deviates >20% from corpus population mean {population_mean:.1f}"
    )


def test_same_seed_identical_draw_sequence(corpus):
    _arrival_rng_a, corpus_rng_a = derive_streams(SEED)
    _arrival_rng_b, corpus_rng_b = derive_streams(SEED)

    drawn_a = [draw_prompt_id(corpus, corpus_rng_a) for _ in range(200)]
    drawn_b = [draw_prompt_id(corpus, corpus_rng_b) for _ in range(200)]
    assert drawn_a == drawn_b, "same seed produced different corpus draw sequences"


def test_different_seed_different_draw_sequence(corpus):
    _arrival_rng_a, corpus_rng_a = derive_streams(SEED)
    _arrival_rng_b, corpus_rng_b = derive_streams(SEED + 1)

    drawn_a = [draw_prompt_id(corpus, corpus_rng_a) for _ in range(200)]
    drawn_b = [draw_prompt_id(corpus, corpus_rng_b) for _ in range(200)]
    assert drawn_a != drawn_b, "different seeds produced identical corpus draw sequences"

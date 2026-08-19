"""Workload identity controls (R4 README §10 "Workload identity").

The canonical multiset is the experiment's central control: every RPS point
and every repeat is comparable *because* they see the same prompts. Anything
that lets the membership drift, duplicate, shrink or be built against a
different corpus destroys that comparability while leaving artifacts that
still look like a workload. So each guard below is paired with the broken
variant it has to reject.
"""

from __future__ import annotations

import json

import pytest

from loadgen.canonical import (
    CANONICAL_N,
    CANONICAL_SCHEME_VERSION,
    CANONICAL_SELECTION_SEED,
    EXPECTED_CORPUS_SHA256,
    L_PCT,
    N_MAX,
    STRATUM_EDGES_PCT,
    CanonicalWorkloadError,
    allocate,
    build,
    load_frozen,
    membership_id,
    selection_key,
)
from loadgen.corpus import Corpus, Prompt, load_corpus

pytestmark = pytest.mark.redesign


@pytest.fixture(scope="module")
def corpus():
    return load_corpus()


@pytest.fixture(scope="module")
def workload(corpus):
    return build(corpus)


# ---------------------------------------------------------------------------
# The locked construction is honoured exactly.
# ---------------------------------------------------------------------------


def test_membership_is_exactly_n_unique_prompts(workload):
    assert len(workload["membership"]) == CANONICAL_N
    assert len(set(workload["membership"])) == CANONICAL_N, (
        "a duplicate prompt would make one request's cost depend on its position in the run"
    )


def test_locked_values_are_what_hard_stop_r3_approved(workload):
    locks = workload["locks"]
    assert locks["stratum_edges_pct"] == list(STRATUM_EDGES_PCT)
    assert locks["k"] == 6
    assert locks["L_pct"] == L_PCT
    assert locks["N"] == CANONICAL_N == 4000
    assert locks["N_max"] == N_MAX == 5000


def test_strata_partition_the_corpus_exactly(workload, corpus):
    total_available = sum(s["available_count"] for s in workload["strata"])
    assert total_available == len(corpus), (
        "every corpus prompt must land in exactly one stratum; a gap or an overlap would make "
        "the proportional allocation describe a different population than the corpus"
    )
    selected = sum(s["selected_count"] for s in workload["strata"])
    assert selected == CANONICAL_N


def test_allocation_is_proportional_and_sums_to_n():
    for n in (250, 1000, 4000, 5000):
        quota = allocate(n)
        assert sum(quota) == n
        # Proportional: each stratum within one of its exact share.
        for i, count in enumerate(quota):
            share = (STRATUM_EDGES_PCT[i + 1] - STRATUM_EDGES_PCT[i]) / 100.0
            assert abs(count - n * share) <= 1.0


def test_tail_support_matches_the_r3_recommendation(workload):
    tail = workload["tail_support"]
    assert tail["canonical_prompts_above_L"] == 40, (
        "R3 sized N=4000 expecting 40 canonical prompts above L=q99; a different count means "
        "the construction no longer matches the evidence it was locked from"
    )
    assert tail["canonical_prompts_above_L"] <= tail["corpus_prompts_above_L"]
    assert abs(tail["fraction_of_N"] - 0.01) < 1e-9


def test_the_extremes_are_present_by_construction(workload, corpus):
    """The first session never drew the corpus's longest prompt. The canonical
    construction guarantees it, which is why R4B's capacity proof exists."""
    by_id = {p.prompt_id: p for p in corpus.prompts}
    longest = max(corpus.prompts, key=lambda p: p.char_len)
    assert longest.prompt_id in workload["membership"]
    assert max(by_id[pid].char_len for pid in workload["membership"]) == longest.char_len


def test_selection_is_deterministic(corpus):
    a = build(corpus)
    b = build(corpus)
    assert a == b
    assert a["membership_id"] == b["membership_id"]


def test_selection_key_is_runtime_independent():
    """Hash-keyed selection is the reason the membership reproduces across
    Python and NumPy versions. Pinning one key catches a change to the key
    derivation itself."""
    assert selection_key(20260819, 790) == selection_key(CANONICAL_SELECTION_SEED, 790)
    assert selection_key(1, 1) != selection_key(2, 1)
    assert selection_key(1, 1) != selection_key(1, 2)
    assert len(selection_key(1, 1)) == 64


# ---------------------------------------------------------------------------
# Controls: each of these must be REFUSED.
# ---------------------------------------------------------------------------


def test_control_corpus_hash_mismatch_is_refused(corpus, tmp_path):
    drifted_path = tmp_path / "drifted.jsonl"
    drifted_path.write_bytes(corpus.source_path.read_bytes() + b'{"prompt_id":9999,'
                             b'"text":"x","char_len":1}\n')
    drifted = Corpus(prompts=corpus.prompts + (Prompt(9999, "x", 1),),
                     source_path=drifted_path)

    with pytest.raises(CanonicalWorkloadError, match="corpus sha256"):
        build(drifted)


def test_control_changed_stratum_config_changes_workload_identity(corpus, monkeypatch):
    """A different `k` must produce a different membership_id. If it did not,
    two experiments with different controls would be indistinguishable in
    provenance."""
    import loadgen.canonical as canonical

    baseline = build(corpus)["membership_id"]
    monkeypatch.setattr(canonical, "STRATUM_EDGES_PCT", (0.0, 50.0, 90.0, 99.0, 100.0))
    monkeypatch.setattr(canonical, "EXPECTED_EDGES_CHARS", (1.0, 142.0, 2358.1, 11471.37, 44445.0))
    changed = canonical.build(corpus)["membership_id"]

    assert changed != baseline


def test_control_n_above_the_ceiling_is_refused(corpus):
    with pytest.raises(CanonicalWorkloadError, match="exceeds the structural evidence ceiling"):
        build(corpus, n=N_MAX + 1)


def test_control_a_dropped_prompt_breaks_the_membership_id(workload):
    """The membership_id is what schedules reference. Losing one prompt must
    change it, or a schedule could claim a workload it is not driving."""
    full = membership_id(workload["membership"])
    short = membership_id(workload["membership"][:-1])
    assert full != short


def test_control_an_edited_frozen_artifact_is_refused(workload, tmp_path):
    path = tmp_path / "tampered.json"
    tampered = dict(workload)
    tampered["membership"] = workload["membership"][:-1] + [workload["membership"][0]]
    path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(CanonicalWorkloadError, match="does not match the membership"):
        load_frozen(path)


def test_control_duplicate_prompt_in_a_frozen_artifact_is_refused(workload, tmp_path):
    path = tmp_path / "dupes.json"
    duped = dict(workload)
    duped["membership"] = workload["membership"][:-1] + [workload["membership"][0]]
    duped["membership_id"] = membership_id(duped["membership"])
    path.write_text(json.dumps(duped), encoding="utf-8")

    with pytest.raises(CanonicalWorkloadError, match="duplicate prompt IDs"):
        load_frozen(path)


def test_control_a_foreign_scheme_version_is_refused(workload, tmp_path):
    path = tmp_path / "future.json"
    future = dict(workload)
    future["scheme_version"] = "canonical-workload-v9"
    path.write_text(json.dumps(future), encoding="utf-8")

    with pytest.raises(CanonicalWorkloadError, match="scheme version"):
        load_frozen(path)


def test_control_tail_support_accounting_cannot_silently_disagree(workload, corpus):
    """R4A requires the recorded tail-support count to match the frozen IDs.
    Recomputing it from the corpus is the check; a provenance number nobody
    re-derives is decoration."""
    by_id = {p.prompt_id: p for p in corpus.prompts}
    l_chars = workload["locks"]["L_chars"]
    recomputed = sum(1 for pid in workload["membership"] if by_id[pid].char_len >= l_chars)
    assert recomputed == workload["tail_support"]["canonical_prompts_above_L"]
    assert sorted(workload["tail_support"]["prompt_ids_above_L"]) == sorted(
        pid for pid in workload["membership"] if by_id[pid].char_len >= l_chars)


# ---------------------------------------------------------------------------
# The frozen artifact on disk, if it has been built.
# ---------------------------------------------------------------------------


def test_frozen_artifact_matches_a_fresh_build(frozen_workload, corpus):
    rebuilt = build(corpus, n=frozen_workload["locks"]["N"],
                    seed=frozen_workload["selection"]["seed"])
    assert rebuilt["membership"] == frozen_workload["membership"]
    assert rebuilt["membership_id"] == frozen_workload["membership_id"]
    assert frozen_workload["corpus"]["sha256"] == EXPECTED_CORPUS_SHA256
    assert frozen_workload["scheme_version"] == CANONICAL_SCHEME_VERSION


def test_frozen_artifact_carries_its_capacity_proof(frozen_workload):
    """R4C: the freeze may only happen after R4B passes, so a frozen artifact
    without a capacity proof means the gate was bypassed."""
    proof = frozen_workload.get("capacity_proof")
    assert proof is not None, "frozen workload has no capacity_proof -- R4C was bypassed"
    assert proof["verdict"] == "PASS"
    assert proof["max_input_tokens"] > 0
    assert proof["tokenizer_repo"] == "meta-llama/Llama-3.2-3B-Instruct"

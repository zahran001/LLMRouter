"""Replay (WEEK2_PLAN.md §5, WEEK2_EXECUTION.md Block D). Re-driving a
committed frozen schedule artifact must reproduce the exact workload
(arrivals + prompt sequence) independent of generator code -- the
determinism check here is workload identity, NOT latency identity (§5:
"Re-driving the same schedule artifact reproduces byte-identical arrivals
... Latencies differ run-to-run -- that is the system's noise").

Reproducibility contract: frozen schedule artifact + pinned corpus artifact
(by version) = identical workload. A schedule alone is not enough if the
corpus it references has drifted since -- that's what
Schedule.validate_corpus_version tests below.
"""

from __future__ import annotations

import pytest

from loadgen.corpus import Corpus, Prompt, load_corpus
from loadgen.log import RunLogger, read_log
from loadgen.schedule import Schedule, build_poisson_schedule
from loadgen.scheduler import OpenLoopScheduler

pytestmark = pytest.mark.loadgen

RPS = 10.0
DURATION_S = 3.0
SEED = 99


@pytest.fixture(scope="module")
def corpus():
    return load_corpus()


def test_round_trip_through_disk_is_byte_identical(corpus, tmp_path):
    """Save -> load reproduces the exact (offset, prompt_id) list -- proves
    the JSON serialization itself introduces no drift (float precision,
    field ordering, etc.)."""
    original = build_poisson_schedule(RPS, DURATION_S, SEED, corpus)
    path = tmp_path / "frozen.schedule.json"
    original.save(path)

    reloaded = Schedule.load(path)
    assert reloaded.entries == original.entries
    assert reloaded.provenance == original.provenance


async def test_replay_drives_the_identical_prompt_sequence(mock_base_url, corpus, tmp_path):
    """The actual point of replay: driving a FROZEN, previously-saved
    schedule (not a freshly-built one) must issue the exact same prompt_id
    sequence in the exact same order as the schedule's own entries -- this
    is workload identity, checked against what was actually SENT, not just
    what was loaded."""
    schedule = build_poisson_schedule(RPS, DURATION_S, SEED, corpus)
    frozen_path = tmp_path / "frozen.schedule.json"
    schedule.save(frozen_path)

    replayed = Schedule.load(frozen_path)
    replayed.validate_corpus_version(corpus)

    log_path = tmp_path / "replay.raw_log.jsonl"
    scheduler = OpenLoopScheduler(
        schedule=replayed,
        corpus=corpus,
        base_url=mock_base_url,
        logger=RunLogger(log_path),
        concurrency_cap=100,
        query_params={"config": "fast", "num_tokens": 5},
        capture_samples=False,
    )
    result = await scheduler.run()
    scheduler.logger.close()
    assert result.n_shed == 0 and result.n_errored == 0

    rows = sorted(read_log(log_path), key=lambda r: r["request_id"])
    sent_prompt_ids = [r["prompt_id"] for r in rows]
    expected_prompt_ids = [e.prompt_id for e in schedule.entries]
    assert sent_prompt_ids == expected_prompt_ids, "replayed run sent a different prompt sequence than the frozen schedule specifies"


# ---------------------------------------------------------------------------
# Corpus-version validation -- closes the loop against silent corpus drift.
# ---------------------------------------------------------------------------


def test_validate_corpus_version_passes_for_the_matching_corpus(corpus):
    schedule = build_poisson_schedule(RPS, DURATION_S, SEED, corpus)
    schedule.validate_corpus_version(corpus)  # must not raise


def test_validate_corpus_version_raises_for_a_drifted_corpus(corpus, tmp_path):
    """The negative control: a schedule built against the real corpus, but
    replayed against a corpus that has since changed (different prompt text
    at the same file path -- e.g. a re-download or re-filter), must be
    caught, not silently driven as if nothing changed."""
    schedule = build_poisson_schedule(RPS, DURATION_S, SEED, corpus)

    drifted_path = tmp_path / "baseline_prompts.jsonl"
    drifted_path.write_text('{"prompt_id": 0, "text": "a completely different corpus", "char_len": 29}\n')
    drifted_corpus = Corpus(prompts=(Prompt(prompt_id=0, text="a completely different corpus", char_len=29),), source_path=drifted_path)

    with pytest.raises(ValueError, match="corpus drift detected"):
        schedule.validate_corpus_version(drifted_corpus)

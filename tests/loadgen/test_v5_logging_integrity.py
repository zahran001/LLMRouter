"""V5 -- logging/ordering integrity (WEEK2_PLAN.md §4). Every downstream
number reads the raw log.

Pass: every scheduled send appears once with a status in
{sent, shed, errored}; scheduled = sent + shed + errored reconciles;
send_time >= scheduled_offset always (late allowed, early impossible).

The negative control (an injected dropped log-write must trip
reconciliation) lives in test_negative_controls.py.
"""

from __future__ import annotations

import pytest

from loadgen.corpus import load_corpus
from loadgen.log import RunLogger, read_log
from loadgen.schedule import build_steady_schedule
from loadgen.scheduler import OpenLoopScheduler
from tests.loadgen._assertions import assert_log_reconciles

pytestmark = [pytest.mark.loadgen, pytest.mark.integration]

SEED = 11


async def test_log_reconciles_with_mixed_sent_and_shed(mock_base_url, tmp_path):
    """Mix of sent and shed (tight cap) so the reconciliation check exercises
    more than the all-sent happy path."""
    corpus = load_corpus()
    schedule = build_steady_schedule(15.0, 2.0, SEED, corpus)
    log_path = tmp_path / "v5.raw_log.jsonl"

    scheduler = OpenLoopScheduler(
        schedule=schedule,
        corpus=corpus,
        base_url=mock_base_url,
        logger=RunLogger(log_path),
        concurrency_cap=3,
        query_params={"config": "slow", "num_tokens": 5},
    )
    result = await scheduler.run()
    scheduler.logger.close()

    assert result.n_shed > 0, "test setup should produce some shedding to exercise the mixed-status path"

    rows = read_log(log_path)
    assert_log_reconciles(rows, schedule)

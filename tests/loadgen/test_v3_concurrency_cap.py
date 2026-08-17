"""V3 -- concurrency cap (WEEK2_PLAN.md §4). Against the slow mock, drive
in-flight past the cap.

Pass: over-cap sends record `shed` (fail-fast, non-blocking); the scheduler
keeps firing on schedule for non-shed sends (shedding one does not delay the
next). Below the cap, shed count is exactly zero.

The negative control (a broken cap that sheds early even below the nominal
cap) lives in test_negative_controls.py.
"""

from __future__ import annotations

import statistics

import pytest

from loadgen.corpus import load_corpus
from loadgen.log import RunLogger
from loadgen.schedule import build_steady_schedule
from loadgen.scheduler import OpenLoopScheduler

pytestmark = [pytest.mark.loadgen, pytest.mark.integration]

SEED = 7


async def _run(base_url, log_path, rps, duration_s, cap, config="slow"):
    corpus = load_corpus()
    schedule = build_steady_schedule(rps, duration_s, SEED, corpus)
    scheduler = OpenLoopScheduler(
        schedule=schedule,
        corpus=corpus,
        base_url=base_url,
        logger=RunLogger(log_path),
        concurrency_cap=cap,
        query_params={"config": config, "num_tokens": 5},
    )
    result = await scheduler.run()
    scheduler.logger.close()
    return result, schedule


async def test_over_cap_sheds_fail_fast_without_blocking(mock_base_url, tmp_path):
    # slow config (~900ms/response) at 20 RPS with cap=2 guarantees heavy
    # shedding -- in-flight demand (~18 concurrent) vastly exceeds the cap.
    result, schedule = await _run(mock_base_url, tmp_path / "v3_over.raw_log.jsonl", rps=20.0, duration_s=2.0, cap=2)

    assert result.n_shed > 0, "expected shedding under a deliberately tight cap"
    assert result.n_sent + result.n_shed + result.n_errored == result.n_scheduled

    # The load-bearing assertion: if the cap check blocked the scheduler loop
    # instead of failing fast, scheduling lag would blow up under heavy
    # shedding. It doesn't.
    mean_lag = statistics.mean(result.per_send_lag_s)
    assert mean_lag < 0.1, f"mean scheduling lag {mean_lag:.3f}s under heavy shedding -- cap may be blocking the loop"


async def test_below_cap_zero_sheds(mock_base_url, tmp_path):
    # fast config, low RPS, cap comfortably above any plausible in-flight count.
    result, _ = await _run(
        mock_base_url, tmp_path / "v3_under.raw_log.jsonl", rps=2.0, duration_s=2.0, cap=50, config="fast"
    )
    assert result.n_shed == 0, f"expected zero sheds below cap, got {result.n_shed}"

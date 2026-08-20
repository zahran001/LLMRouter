"""V2 -- open-loop fidelity (WEEK2_PLAN.md §4), THE load-bearing check.
Requires driving the mock.

Pass: driven at target RPS against the slow mock (500ms), per-send
scheduling lag (scheduled_offset vs actual send_time) stays within a band;
achieved RPS tracks offered RPS.

The negative control (fast-mock vs slow-mock achieved RPS must be INVARIANT
for the real open-loop scheduler, but DIVERGE for a closed-loop one) lives in
test_negative_controls.py -- it's the single most important validation in
§4 because it's the one thing that can't be tested away downstream (Hard
Stop 1 covers the architecture; this is the runtime proof).
"""

from __future__ import annotations

import statistics

import pytest

from loadgen.corpus import load_corpus
from loadgen.log import RunLogger
from loadgen.schedule import build_poisson_schedule, build_steady_schedule
from loadgen.scheduler import OpenLoopScheduler
from tests.loadgen._assertions import assert_achieved_rps_invariant

pytestmark = [pytest.mark.loadgen, pytest.mark.integration]

RPS = 5.0
DURATION_S = 3.0
SEED = 42
CONCURRENCY_CAP = 100  # comfortably above what this test needs -- cap behavior is V3's job, not V2's


async def _run(base_url: str, log_path, config: str) -> tuple:
    corpus = load_corpus()
    schedule = build_poisson_schedule(RPS, DURATION_S, SEED, corpus)
    scheduler = OpenLoopScheduler(
        schedule=schedule,
        corpus=corpus,
        base_url=base_url,
        logger=RunLogger(log_path),
        concurrency_cap=CONCURRENCY_CAP,
        query_params={"config": config, "num_tokens": 5},
    )
    result = await scheduler.run()
    scheduler.logger.close()
    return result


async def test_scheduling_lag_within_band_against_slow_mock(mock_base_url, tmp_path):
    result = await _run(mock_base_url, tmp_path / "v2.raw_log.jsonl", "slow")

    assert result.n_shed == 0, "cap is high enough here that shedding would indicate a bug, not saturation"
    lag = result.per_send_lag_s
    assert lag, "no sends recorded"

    mean_lag = statistics.mean(lag)
    max_lag = max(lag)
    # Not yet [CALIBRATE]d (that's Block C) -- generous bounds that would
    # still catch a scheduler that's accidentally gated on response time
    # (a closed-loop bug would blow this out by roughly the slow config's
    # ~900ms response time, not fractions of the inter-arrival gap).
    inter_arrival_gap = 1.0 / RPS
    assert mean_lag < 0.5 * inter_arrival_gap, f"mean scheduling lag {mean_lag:.3f}s too large vs gap {inter_arrival_gap:.3f}s"
    assert max_lag < 2.0 * inter_arrival_gap, f"max scheduling lag {max_lag:.3f}s too large vs gap {inter_arrival_gap:.3f}s"


async def test_achieved_rps_tracks_offered(mock_base_url, tmp_path):
    # Steady, not Poisson, and a longer window: this checks whether the
    # DRIVER tracks the schedule it was given (V2's concern), not whether
    # the schedule's own realized arrival count matches its target rate
    # (that's sampling noise, V1's concern, and inherent to any Poisson
    # process over a short window -- at RPS=5/duration=3s the expected
    # arrival count is only ~15, where Poisson's own relative stdev
    # (~1/sqrt(15) ~= 26%) alone can exceed a 20% band with nothing wrong
    # in the driver at all). Steady removes that confound: n_scheduled is
    # deterministic, so any divergence here is genuinely about the driver.
    corpus = load_corpus()
    schedule = build_steady_schedule(RPS, 10.0, SEED, corpus)
    scheduler = OpenLoopScheduler(
        schedule=schedule,
        corpus=corpus,
        base_url=mock_base_url,
        logger=RunLogger(tmp_path / "v2b.raw_log.jsonl"),
        concurrency_cap=CONCURRENCY_CAP,
        query_params={"config": "slow", "num_tokens": 5},
    )
    result = await scheduler.run()
    scheduler.logger.close()

    assert result.n_shed == 0, "cap should not bite here"
    divergence = abs(result.achieved_rps - RPS) / RPS
    assert divergence < 0.1, f"achieved RPS {result.achieved_rps:.2f} diverges >10% from offered {RPS}"


async def test_achieved_rps_invariant_across_fast_and_slow(mock_base_url, tmp_path):
    """V2's load-bearing property, asserted through the shared helper that
    `test_negative_controls.py` feeds a closed-loop driver to under
    `pytest.raises`. Same helper on both sides: the control proves the check
    can fail, this proves the real implementation passes it.

    An open-loop generator's achieved rate is a property of the schedule, not
    of the server, so making the server ~5x slower must not move it.
    """
    fast = await _run(mock_base_url, tmp_path / "v2inv_fast.raw_log.jsonl", "fast")
    slow = await _run(mock_base_url, tmp_path / "v2inv_slow.raw_log.jsonl", "slow")

    print(
        f"\nV2 invariance: fast={fast.achieved_rps:.2f} slow={slow.achieved_rps:.2f} "
        f"divergence={abs(fast.achieved_rps - slow.achieved_rps) / fast.achieved_rps:.1%}"
    )
    assert fast.n_shed == 0 and slow.n_shed == 0, "cap must not bite -- would confound V2 with V3"
    assert_achieved_rps_invariant(fast.achieved_rps, slow.achieved_rps, context="V2 real: ")

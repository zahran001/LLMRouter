"""Negative controls for the Week 2 mock validations (WEEK2_PLAN.md §4).

A validation that cannot fail proves nothing. Each test here deliberately
breaks one thing the corresponding V-check depends on and asserts the SAME
assertion helper the real check uses (tests/loadgen/_assertions.py) goes
RED against it -- mirroring tests/eval/test_negative_controls.py and
tests/router/test_negative_controls.py. A test in this file failing (i.e.
the broken input still passes) means the corresponding V-check has no teeth
and WEEK2_EXECUTION.md Hard Stop 2 cannot be signed off.
"""

from __future__ import annotations

import time

import httpx
import pytest

from loadgen.corpus import Corpus, Prompt, load_corpus
from loadgen.log import RunLogger, read_log
from loadgen.schedule import build_poisson_schedule, build_steady_schedule
from loadgen.scheduler import OpenLoopScheduler
from tests.loadgen._assertions import (
    assert_all_prompts_valid,
    assert_fits_exponential,
    assert_log_reconciles,
    gaps_from_schedule,
)

pytestmark = [pytest.mark.loadgen, pytest.mark.negative_control]

RPS = 20.0
DURATION_S = 120.0
SEED = 42


@pytest.fixture(scope="module")
def corpus():
    return load_corpus()


# ---------------------------------------------------------------------------
# V1 control: the steady schedule must FAIL the exponential fit.
# ---------------------------------------------------------------------------


def test_v1_steady_schedule_fails_exponential_fit(corpus):
    # Sanity: the real (Poisson) pipeline passes first, so this test isn't
    # "passing" because assert_fits_exponential is broken.
    poisson = build_poisson_schedule(RPS, DURATION_S, SEED, corpus)
    assert_fits_exponential(gaps_from_schedule(poisson), rate=RPS, context="sanity/poisson: ")

    steady = build_steady_schedule(RPS, DURATION_S, SEED, corpus)
    gaps = gaps_from_schedule(steady)
    assert len(set(round(g, 9) for g in gaps)) == 1, "steady gaps should be constant by construction"

    with pytest.raises(AssertionError):
        assert_fits_exponential(gaps, rate=RPS, context="V1 control/steady: ")


# ---------------------------------------------------------------------------
# V2 control (THE load-bearing one): fast-vs-slow achieved RPS must be
# INVARIANT for the real open-loop scheduler, but a deliberately closed-loop
# driver's achieved RPS must DIVERGE between fast and slow.
# ---------------------------------------------------------------------------

V2_RPS = 8.0
V2_DURATION_S = 3.0
V2_CAP = 100  # high enough that shedding can't confound this control


async def _closed_loop_achieved_rps(base_url: str, config: str, n: int, num_tokens: int = 5) -> float:
    """Deliberately closed-loop: send, wait for the FULL response, send
    again. No schedule, no target rate to hit -- its achieved rate is
    whatever the server's response time allows, by construction. This is
    the exact failure mode WEEK2_PLAN.md §3.1 says open-loop avoids."""
    url = f"{base_url}/v1/chat/completions"
    t_start = time.monotonic()
    async with httpx.AsyncClient(timeout=30.0) as client:
        for _ in range(n):
            async with client.stream(
                "POST", url, params={"config": config, "num_tokens": num_tokens},
                json={"model": "mock", "messages": [{"role": "user", "content": "hi"}]},
            ) as response:
                async for _ in response.aiter_lines():
                    pass
    elapsed = time.monotonic() - t_start
    return n / elapsed


async def _open_loop_achieved_rps(base_url: str, config: str, corpus: Corpus, log_path) -> float:
    schedule = build_poisson_schedule(V2_RPS, V2_DURATION_S, SEED, corpus)
    scheduler = OpenLoopScheduler(
        schedule=schedule,
        corpus=corpus,
        base_url=base_url,
        logger=RunLogger(log_path),
        concurrency_cap=V2_CAP,
        query_params={"config": config, "num_tokens": 5},
    )
    result = await scheduler.run()
    scheduler.logger.close()
    assert result.n_shed == 0, "cap should not bite here -- would confound this control with V3's concern"
    return result.achieved_rps


async def test_v2_closed_loop_diverges_but_open_loop_is_invariant(mock_base_url, corpus, tmp_path):
    closed_fast = await _closed_loop_achieved_rps(mock_base_url, "fast", n=15)
    closed_slow = await _closed_loop_achieved_rps(mock_base_url, "slow", n=15)
    closed_ratio = closed_fast / closed_slow

    print(f"\nclosed-loop achieved RPS: fast={closed_fast:.2f} slow={closed_slow:.2f} ratio={closed_ratio:.2f}x")
    assert closed_ratio > 2.0, (
        f"closed-loop fast/slow ratio {closed_ratio:.2f}x is not a clear divergence -- "
        "control has no teeth (fast config: ~180ms/response, slow: ~900ms/response, "
        "so closed-loop throughput should differ by close to that ratio)"
    )

    open_fast = await _open_loop_achieved_rps(mock_base_url, "fast", corpus, tmp_path / "v2c_fast.raw_log.jsonl")
    open_slow = await _open_loop_achieved_rps(mock_base_url, "slow", corpus, tmp_path / "v2c_slow.raw_log.jsonl")
    open_divergence = abs(open_fast - open_slow) / open_fast

    print(f"open-loop achieved RPS: fast={open_fast:.2f} slow={open_slow:.2f} divergence={open_divergence:.1%}")
    assert open_divergence < 0.2, (
        f"open-loop fast vs slow achieved RPS diverged {open_divergence:.1%} -- "
        "response time is leaking into send timing (hidden closed-loop dependency)"
    )


# ---------------------------------------------------------------------------
# V3 control: a broken cap (effectively admits fewer than the configured
# value -- the observable signature of an off-by-N enforcement bug) must
# shed under load where the correctly-configured cap sheds exactly zero.
# ---------------------------------------------------------------------------


async def _run_with_cap(base_url, corpus, log_path, rps, duration_s, cap, config="fast"):
    schedule = build_steady_schedule(rps, duration_s, SEED, corpus)
    scheduler = OpenLoopScheduler(
        schedule=schedule, corpus=corpus, base_url=base_url,
        logger=RunLogger(log_path), concurrency_cap=cap,
        query_params={"config": config, "num_tokens": 5},
    )
    result = await scheduler.run()
    scheduler.logger.close()
    return result


async def test_v3_below_cap_zero_sheds_but_broken_cap_sheds_early(mock_base_url, corpus, tmp_path):
    # slow config (~900ms/response) at 20 RPS keeps ~18 streams open at
    # once -- comfortably under nominal_cap=50 (zero sheds expected) but
    # well past broken_effective_cap=5, so the two parameter values are
    # actually distinguished by real concurrent load, not just by the
    # request COUNT (too few in-flight requests would never touch either
    # cap, and the control would prove nothing).
    rps, duration_s, nominal_cap = 20.0, 3.0, 50

    real_result = await _run_with_cap(
        mock_base_url, corpus, tmp_path / "v3c_real.raw_log.jsonl", rps, duration_s, nominal_cap, config="slow"
    )
    assert real_result.n_shed == 0, f"real cap should not shed here, got {real_result.n_shed}"

    # Same load, but an off-by-N enforcement bug means the pool is actually
    # admitting far fewer streams than configured -- exactly what a broken
    # "if open_streams >= cap" comparison (e.g. wrong variable, stale value,
    # wrong sign) looks like from the outside: it sheds well before the load
    # that the configured cap should tolerate.
    broken_effective_cap = 5  # i.e. an enforcement bug pins it at 5, not 50
    broken_result = await _run_with_cap(
        mock_base_url, corpus, tmp_path / "v3c_broken.raw_log.jsonl", rps, duration_s, broken_effective_cap,
        config="slow",
    )
    assert broken_result.n_shed > 0, (
        f"expected the broken (effectively-smaller) cap to shed under load where the real "
        f"cap={nominal_cap} sheds zero, got n_shed={broken_result.n_shed} -- "
        "control has no teeth"
    )


# ---------------------------------------------------------------------------
# V4 control: a filter-bypassed corpus (contains an empty/invalid entry)
# must fail assert_all_prompts_valid, where the real pinned corpus passes.
# ---------------------------------------------------------------------------


def test_v4_filter_bypass_lets_junk_reach_assignment(corpus, tmp_path):
    # Sanity: the real committed corpus passes first.
    assert_all_prompts_valid(corpus)

    bypassed = Corpus(
        prompts=(
            Prompt(prompt_id=0, text="a valid prompt", char_len=14),
            Prompt(prompt_id=1, text="   ", char_len=3),  # whitespace-only -- should never have passed the filter
            Prompt(prompt_id=2, text="", char_len=0),  # empty -- should never have passed the filter
        ),
        source_path=tmp_path / "bypassed_corpus.jsonl",
    )

    with pytest.raises(AssertionError):
        assert_all_prompts_valid(bypassed)


# ---------------------------------------------------------------------------
# V5 control: an injected dropped log-write must trip reconciliation.
# ---------------------------------------------------------------------------


class _DroppingLogger(RunLogger):
    """Deliberately broken: silently discards the write for one specific
    request_id, simulating a lost log line (e.g. a crash mid-write)."""

    def __init__(self, path, drop_request_id: int):
        super().__init__(path)
        self._drop_request_id = drop_request_id

    def write(self, request_id, *args, **kwargs) -> None:
        if request_id == self._drop_request_id:
            return
        super().write(request_id, *args, **kwargs)


async def test_v5_dropped_log_write_trips_reconciliation(mock_base_url, corpus, tmp_path):
    schedule = build_steady_schedule(10.0, 1.0, SEED, corpus)
    log_path = tmp_path / "v5c.raw_log.jsonl"

    scheduler = OpenLoopScheduler(
        schedule=schedule, corpus=corpus, base_url=mock_base_url,
        logger=_DroppingLogger(log_path, drop_request_id=0), concurrency_cap=50,
        query_params={"config": "fast", "num_tokens": 5},
    )
    await scheduler.run()
    scheduler.logger.close()

    rows = read_log(log_path)
    assert len(rows) < len(schedule.entries), "test setup should have dropped exactly one row"

    with pytest.raises(AssertionError):
        assert_log_reconciles(rows, schedule)

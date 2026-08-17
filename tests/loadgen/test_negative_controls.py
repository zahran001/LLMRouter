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
    assert_cap_respected,
    assert_fits_exponential,
    assert_log_reconciles,
    gaps_from_schedule,
    peak_concurrency,
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


async def _open_loop_run(base_url: str, config: str, corpus: Corpus, log_path):
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
    return result


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

    open_fast = await _open_loop_run(mock_base_url, "fast", corpus, tmp_path / "v2c_fast.raw_log.jsonl")
    open_slow = await _open_loop_run(mock_base_url, "slow", corpus, tmp_path / "v2c_slow.raw_log.jsonl")
    open_divergence = abs(open_fast.achieved_rps - open_slow.achieved_rps) / open_fast.achieved_rps

    print(
        f"open-loop achieved RPS: fast={open_fast.achieved_rps:.2f} slow={open_slow.achieved_rps:.2f} "
        f"divergence={open_divergence:.1%}"
    )
    assert open_divergence < 0.2, (
        f"open-loop fast vs slow achieved RPS diverged {open_divergence:.1%} -- "
        "response time is leaking into send timing (hidden closed-loop dependency)"
    )

    # achieved_rps alone is not sufficient here: it divides by the FIXED
    # offered window (schedule.duration_s), so a hypothetical leak that
    # delays every send but still eventually issues all of them would leave
    # achieved_rps looking unchanged ("eventually issued" is all it checks,
    # not "issued on schedule"). Scheduling lag is the metric that actually
    # rules that out -- a leak would blow up max lag for the slow config
    # specifically (by roughly its response time) while leaving fast's lag
    # small, so comparing the two directly closes the gap achieved_rps
    # alone leaves open. This is NOT confounded by response-tail draining
    # time the way switching achieved_rps itself to a wall-clock-drain
    # metric would be (fast/slow inherently differ there even when correct).
    fast_max_lag = max(open_fast.per_send_lag_s)
    slow_max_lag = max(open_slow.per_send_lag_s)
    print(f"open-loop max scheduling lag: fast={fast_max_lag*1000:.1f}ms slow={slow_max_lag*1000:.1f}ms")
    inter_arrival_gap = 1.0 / V2_RPS
    for label, lag in (("fast", fast_max_lag), ("slow", slow_max_lag)):
        assert lag < 0.5 * inter_arrival_gap, (
            f"open-loop {label} max scheduling lag {lag*1000:.1f}ms is a large fraction of the "
            f"{inter_arrival_gap*1000:.1f}ms inter-arrival gap -- sends are not landing on schedule "
            "(closed-loop-style delay, even if achieved_rps looked invariant)"
        )


# ---------------------------------------------------------------------------
# V3 control: a genuinely broken cap-ENFORCEMENT (off-by-one comparison
# operator, not a different cap value) must let peak concurrency exceed the
# cap where the real enforcement respects it -- run at the SAME cap and the
# SAME load, so the only variable is the comparison itself.
# ---------------------------------------------------------------------------


class _OffByOneCapScheduler(OpenLoopScheduler):
    """Deliberately broken: `>` instead of `>=`. This admits a request when
    open_streams == cap (the real check sheds it), so the effective ceiling
    becomes cap+1, not cap -- a realistic single-character bug class (wrong
    comparison operator), not a smaller configured cap. Body is otherwise an
    exact copy of OpenLoopScheduler._handle; the changed line is marked.
    """

    async def _handle(self, request_id, entry, t_start):
        prompt = self.corpus.prompts[entry.prompt_id]

        if self._open_streams > self.concurrency_cap:  # BUG: should be >=
            self._n_shed += 1
            self.logger.write(request_id, None, None, entry.prompt_id, prompt.char_len, "shed")
            return
        self._open_streams += 1

        send_time = time.monotonic()
        self._per_send_lag.append(send_time - (t_start + entry.scheduled_offset))
        url = f"{self.base_url}{self.endpoint_path}"
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt.text}], **self.extra_body}

        try:
            async with self._client.stream("POST", url, params=self.query_params, json=body) as response:
                response.raise_for_status()
                async for _ in response.aiter_lines():
                    pass
            close_time = time.monotonic()
            self._n_sent += 1
            self.logger.write(
                request_id, send_time - t_start, close_time - t_start, entry.prompt_id, prompt.char_len, "sent"
            )
        except Exception:
            close_time = time.monotonic()
            self._n_errored += 1
            self.logger.write(
                request_id, send_time - t_start, close_time - t_start, entry.prompt_id, prompt.char_len, "errored"
            )
        finally:
            self._open_streams -= 1


async def _run_with_scheduler(scheduler_cls, base_url, corpus, log_path, rps, duration_s, cap, config="slow"):
    schedule = build_steady_schedule(rps, duration_s, SEED, corpus)
    scheduler = scheduler_cls(
        schedule=schedule, corpus=corpus, base_url=base_url,
        logger=RunLogger(log_path), concurrency_cap=cap,
        query_params={"config": config, "num_tokens": 5}, capture_samples=False,
    )
    await scheduler.run()
    scheduler.logger.close()
    return read_log(log_path)


async def test_v3_real_cap_respected_but_broken_comparison_admits_over_cap(mock_base_url, corpus, tmp_path):
    # slow config (~900ms/response) at 20 RPS sustains ~18 concurrent demand
    # -- comfortably above cap=10, so demand persistently presses against
    # the cap boundary for most of the run (not just a single fleeting
    # instant), making the off-by-one difference reliably observable rather
    # than dependent on hitting one exact instant. IDENTICAL cap=10 is used
    # for both runs below -- only the comparison operator differs.
    rps, duration_s, cap = 20.0, 3.0, 10

    # Sanity: the real (unmodified) scheduler must respect the cap under
    # this load, before this control is trusted to mean anything (mirrors
    # V1's control asserting the real Poisson schedule passes first).
    real_rows = await _run_with_scheduler(
        OpenLoopScheduler, mock_base_url, corpus, tmp_path / "v3c_real.raw_log.jsonl", rps, duration_s, cap,
    )
    assert_cap_respected(real_rows, cap=cap, context="real scheduler: ")

    # Same cap, same load, only the comparison operator is wrong. If fed to
    # the exact same assertion the real V3 positive test uses
    # (assert_cap_respected -- see test_v3_concurrency_cap.py), this must
    # fail: peak concurrency should reach cap+1=11, one over.
    broken_rows = await _run_with_scheduler(
        _OffByOneCapScheduler, mock_base_url, corpus, tmp_path / "v3c_broken.raw_log.jsonl", rps, duration_s, cap,
    )
    broken_peak = peak_concurrency(broken_rows)
    print(f"\nV3 control: real peak={peak_concurrency(real_rows)} broken peak={broken_peak} (cap={cap})")
    assert broken_peak > cap, (
        f"expected the off-by-one comparison to admit over cap={cap}, but broken peak concurrency was "
        f"only {broken_peak} -- control has no teeth"
    )
    with pytest.raises(AssertionError):
        assert_cap_respected(broken_rows, cap=cap, context="broken scheduler: ")


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

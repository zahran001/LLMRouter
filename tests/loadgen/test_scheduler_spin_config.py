"""Scheduler spin-margin configuration (WEEK2_PLAN.md §8, WEEK2_EXECUTION.md
Block C).

The spin exists to guarantee V5's "send_time >= scheduled_offset -- late
allowed, early impossible" on platforms whose bare `asyncio.sleep` can wake
EARLY. It was tuned on Windows, and §8 forbids shipping that value onto the
Linux vLLM runs unverified; the A/B that resolved it is
`scripts/calibrate_scheduler_spin.py` with evidence in
`benchmarks/calibration/scheduler_spin/`.

These tests pin the *resolution rules* (platform default, env override,
explicit argument) rather than the calibrated numbers themselves -- asserting
the numbers here would just restate the constants. What matters is that a
Linux GPU host cannot silently end up running the Windows value, and that the
override the runbook documents actually takes effect.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from loadgen import scheduler as sched_mod
from loadgen.corpus import load_corpus
from loadgen.log import RunLogger
from loadgen.schedule import build_steady_schedule
from loadgen.scheduler import (
    LINUX_SPIN_MARGIN_S,
    SPIN_MARGIN_ENV,
    WINDOWS_SPIN_MARGIN_S,
    OpenLoopScheduler,
    default_spin_margin_s,
)

pytestmark = pytest.mark.loadgen


def test_platform_default_is_per_platform_not_one_constant(monkeypatch):
    """The whole point of the Block C calibration: Windows and Linux get
    their own values, chosen from measurement."""
    monkeypatch.delenv(SPIN_MARGIN_ENV, raising=False)

    monkeypatch.setattr(sched_mod.sys, "platform", "win32")
    assert default_spin_margin_s() == WINDOWS_SPIN_MARGIN_S

    monkeypatch.setattr(sched_mod.sys, "platform", "linux")
    assert default_spin_margin_s() == LINUX_SPIN_MARGIN_S


def test_windows_keeps_a_nonzero_spin():
    """Windows is the platform whose bare asyncio.sleep actually returns
    early -- the correctness failure the spin prevents. Zeroing it there
    would reintroduce V5 violations."""
    assert WINDOWS_SPIN_MARGIN_S > 0


def test_env_override_wins_over_the_platform_default(monkeypatch):
    """The runbook's escape hatch: a session host can be re-tuned without
    editing tracked source (which `bootstrap` would reject as a dirty tree)."""
    monkeypatch.setattr(sched_mod.sys, "platform", "linux")
    monkeypatch.setenv(SPIN_MARGIN_ENV, "0.012")
    assert default_spin_margin_s() == pytest.approx(0.012)


def test_blank_env_override_falls_back_to_the_platform_default(monkeypatch):
    """An exported-but-empty variable is a common shell accident; it must not
    parse as 0.0 and silently disable the spin on Windows."""
    monkeypatch.setattr(sched_mod.sys, "platform", "win32")
    monkeypatch.setenv(SPIN_MARGIN_ENV, "   ")
    assert default_spin_margin_s() == WINDOWS_SPIN_MARGIN_S


def test_scheduler_records_the_margin_it_will_actually_use(monkeypatch):
    corpus = load_corpus()
    schedule = build_steady_schedule(5.0, 1.0, 1, corpus)

    explicit = OpenLoopScheduler(
        schedule=schedule, corpus=corpus, base_url="http://127.0.0.1:1",
        logger=RunLogger(_tmp()), concurrency_cap=10, capture_samples=False,
        spin_margin_s=0.037,
    )
    assert explicit.spin_margin_s == pytest.approx(0.037)

    monkeypatch.delenv(SPIN_MARGIN_ENV, raising=False)
    defaulted = OpenLoopScheduler(
        schedule=schedule, corpus=corpus, base_url="http://127.0.0.1:1",
        logger=RunLogger(_tmp()), concurrency_cap=10, capture_samples=False,
    )
    assert defaulted.spin_margin_s == default_spin_margin_s()


def test_zero_margin_is_honoured_not_treated_as_unset():
    """0.0 is the Linux arm's actual value -- a `spin_margin_s or default`
    style bug would silently swap it for the platform default and make the
    calibration unrunnable."""
    corpus = load_corpus()
    schedule = build_steady_schedule(5.0, 1.0, 1, corpus)
    s = OpenLoopScheduler(
        schedule=schedule, corpus=corpus, base_url="http://127.0.0.1:1",
        logger=RunLogger(_tmp()), concurrency_cap=10, capture_samples=False,
        spin_margin_s=0.0,
    )
    assert s.spin_margin_s == 0.0


@pytest.mark.parametrize("margin", [0.0, 0.005])
def test_sleep_until_never_returns_early_at_either_margin(margin):
    """V5's contract, exercised directly against both A/B arms: `_sleep_until`
    must return at or after its target, never before. This is the property the
    spin exists to protect, so it is asserted for the spin-disabled arm too --
    if 0ms ever broke it on a platform, that platform must keep a spin."""
    async def run() -> list[float]:
        overshoots = []
        for _ in range(40):
            target = time.monotonic() + 0.01
            await sched_mod._sleep_until(target, margin)
            overshoots.append(time.monotonic() - target)
        return overshoots

    overshoots = asyncio.run(run())
    earliest = min(overshoots)
    assert earliest >= 0.0, (
        f"_sleep_until returned {abs(earliest) * 1000:.3f}ms EARLY at spin_margin_s={margin} -- "
        "violates 'send_time >= scheduled_offset, late allowed, early impossible' (§4 V5)"
    )


def _tmp():
    import tempfile
    from pathlib import Path
    return Path(tempfile.mkdtemp()) / "spin_test.raw_log.jsonl"

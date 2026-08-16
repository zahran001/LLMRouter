"""Precise timing for the mock's simulated ttft/tpot waits.

Bare `await asyncio.sleep(target)` measurably overshoots its target on this
project's dev machine (see BENCHMARKS.md for the measured distribution) --
a systematic bias, not run-to-run noise, that the mock has no business
introducing. Ground truth for the deterministic eval is the mock's
*configured* value; the mock should deliver it precisely, the same way real
GPU token timing is precise rather than sloppy. See
AGENT_TIMING_FIX_BRIEF.md Part 1.
"""

from __future__ import annotations

import asyncio
import time

# [CALIBRATE] Must exceed this machine's asyncio.sleep() overshoot so the
# coarse sleep below lands before the deadline, leaving something to spin
# for -- if the coarse sleep alone overshoots past the deadline, that one
# sample just degrades back to bare-asyncio.sleep behavior (no worse than
# pre-fix, not catastrophic, but the point is to make that rare).
#
# Measured via a clean (no other load), 60-sample-per-duration, no-HTTP
# asyncio.sleep run at the durations this mock actually uses. Overshoot
# (actual - target), median / p95 / max, ms:
#   20ms  -> 11.24 / 12.43 / 15.62
#   50ms  -> 13.12 / 15.50 / 41.74   (one outlier; see note below)
#   100ms -> 9.82  / 11.55 / 28.76
#   300ms -> 10.99 / 14.45 / 14.61
#   500ms -> 13.39 / 15.02 / 15.42
# p95 tops out at ~15.5ms across all durations tested; 20ms clears that
# with headroom without being the "huge margin" the brief warns against
# (spinning burns CPU for the margin's duration on every chunk). The one
# 41.74ms max (50ms target) was a single outlier, not reproduced at any
# other duration -- chasing single outliers would push the margin well
# past "just above observed overshoot," so it's accepted as a rare
# fallback-to-imprecise sample rather than calibrated against.
SPIN_MARGIN_S = 0.020


async def precise_sleep(duration_s: float, spin_margin_s: float | None = None) -> None:
    """Sleep `duration_s` with sub-ms accuracy.

    Coarse `asyncio.sleep` for the bulk of the interval (cheap, but
    imprecise -- may overshoot by the OS's timer granularity), then a tight
    spin against `time.perf_counter()` (monotonic) for the final
    `spin_margin_s`, which is where the actual precision comes from.

    `spin_margin_s` defaults to the module-level `SPIN_MARGIN_S`, read at
    call time (not bound as a function default) so a calibration harness can
    monkeypatch `mock.timing.SPIN_MARGIN_S` before driving requests -- e.g.
    setting it to 0 makes this degenerate to a bare `asyncio.sleep`, which is
    the A/B this module's docstring references (WEEK2_PLAN.md §7 /
    MOCK_TRUST_BOUNDARY.md: is the busy-wait even needed on Linux). Passing
    `spin_margin_s` explicitly still overrides per-call as before.

    The spin loop yields to the event loop every iteration via
    `await asyncio.sleep(0)` -- a bare `while` with no await would starve
    every other concurrent stream this mock is serving. Do not remove that
    yield.
    """
    if duration_s <= 0:
        return
    if spin_margin_s is None:
        spin_margin_s = SPIN_MARGIN_S

    deadline = time.perf_counter() + duration_s
    coarse = duration_s - spin_margin_s
    if coarse > 0:
        await asyncio.sleep(coarse)

    while time.perf_counter() < deadline:
        await asyncio.sleep(0)

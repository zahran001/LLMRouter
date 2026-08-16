"""The three [CALIBRATE] values for the router eval (WEEK1_ROUTER_IMPL.md §7).

Provenance rule carried from the metrics module (tests/tolerances.py): every
constant traces to either the mock's *configured* timing or an
already-measured noise floor. None is a fresh guess, and none is tuned to
whatever the router happened to measure on the day.

The two streaming bounds are deliberately **coarse separation bounds**, not
tight timing checks: per-chunk TCP delivery is below the application
(WEEK1_ROUTER_IMPL.md §1 scope note), so anything tighter would be measuring
hyper, Nagle and the loopback rather than the router.
"""

from __future__ import annotations

from mock.configs import CONFIGS
from tests.tolerances import TOLERANCE_FLOOR_MS, hybrid_band

# --- The config S1/S2 run against -----------------------------------------
# slow (500ms TTFT, 100ms TPOT) with 20 content chunks -- the spec's worked
# example (§4.2): long total duration, many chunks, so streaming and
# buffering are separated by seconds rather than by jitter.
STREAMING_CONFIG = "slow"
STREAMING_NUM_TOKENS = 20

_SLOW = CONFIGS[STREAMING_CONFIG]

# Configured, not measured: the mock waits ttft_ms, then emits N content
# chunks with tpot_ms between consecutive ones, so the content stream itself
# occupies (N-1) x tpot_ms and the whole response ttft + that.
CONFIGURED_CONTENT_STREAM_MS = (STREAMING_NUM_TOKENS - 1) * _SLOW.tpot_ms   # 1900ms
CONFIGURED_TOTAL_MS = _SLOW.ttft_ms + CONFIGURED_CONTENT_STREAM_MS          # 2400ms

# --- S1: first-content-chunk -> last-content-chunk gap ---------------------
# A streaming router reproduces the full 1900ms content stream at the client;
# a buffering one collapses it to ~0ms (every byte is delivered at once, at
# the end). 1000ms sits ~53% of the way to the true value: far enough below
# 1900ms to absorb any plausible coalescing, and ~100x the 10ms measured
# noise floor, so socket jitter cannot reach it from either side.
S1_MIN_FIRST_TO_LAST_GAP_MS = 1000.0

# --- S2: first content chunk arrives near TTFT, not near completion --------
# Bound = configured TTFT + margin. The margin is 5 x hybrid_band(500ms) =
# 5 x 50ms, i.e. five times the band the metrics suite already accepts for a
# 500ms configured value -- generous by construction rather than by taste.
# For scale: 250ms is 25x the 10ms noise floor and ~33x the 7.56ms measured
# structural TTFT offset (tests/tolerances.py), while a buffering router
# arrives at ~2400ms and so misses this bound by ~1.65 SECONDS.
S2_FIRST_CHUNK_MARGIN_MS = 5.0 * hybrid_band(_SLOW.ttft_ms)                 # 250ms
S2_FIRST_CHUNK_BOUND_MS = _SLOW.ttft_ms + S2_FIRST_CHUNK_MARGIN_MS          # 750ms

# --- O1: sequential router overhead ---------------------------------------
# Reused, not re-derived: TOLERANCE_FLOOR_MS is the calibrated noise floor
# from CALIBRATION_TASK.md Part A (200 sequential runs; max |TTFT p50 -
# configured| = 7.56ms, independently corroborated by the ~8-10ms structural
# TTFT offset in tests/mock/test_timing_accuracy.py). The router's extra hop
# must disappear inside the instrument's own noise.
O1_MEDIAN_OVERHEAD_BOUND_MS = TOLERANCE_FLOOR_MS                            # 10ms

# "Roughly constant, not growing with response size" (§4.3): the same bound
# applied to the *difference between* the two response sizes' overheads. A
# per-chunk cost (hidden buffering or parsing) shows up here even if each
# individual delta stayed under the bound. The buffering handler's deltas are
# ~(N-1) x tpot_ms, so they grow by ~400ms between the two arms below.
O1_OVERHEAD_GROWTH_BOUND_MS = TOLERANCE_FLOOR_MS                            # 10ms

# Overhead is measured on the fast config (100ms TTFT / 20ms TPOT) -- the
# cheapest config, so the router's fixed cost is the largest fraction of the
# signal and hardest to hide. Two response sizes, same config: only the chunk
# count differs, so any growth is attributable to per-chunk work.
OVERHEAD_CONFIG = "fast"
OVERHEAD_SMALL_NUM_TOKENS = 5
OVERHEAD_LARGE_NUM_TOKENS = 25

# Sequential samples per arm, plus discarded warmup requests. Warmup exists
# to establish the connection pool (WEEK1_MEASUREMENT_SPEC.md §2) so TTFT is
# steady-state, not TCP-handshake-inclusive. 21 is an odd count, so the
# median is a real sample rather than an average of two.
OVERHEAD_N = 21
OVERHEAD_WARMUP = 3

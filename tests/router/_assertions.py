"""Shared "what does a correct router look like" assertions.

Not a test module (no test_ prefix). Imported by the real eval, which expects
these to PASS, and by tests/router/test_negative_controls.py, which expects
them to RAISE against the two deliberately-wrong routers. One source of truth
keeps the controls honest: they exercise the exact gate the eval uses, not a
lookalike.

Same structure as tests/eval/_assertions.py for the metrics module.
"""

from __future__ import annotations

from metrics.types import RequestSample
from tests.router._client import OverheadArm, first_content_index, parsed_chunks
from tests.router.tolerances import (
    O1_MEDIAN_OVERHEAD_BOUND_MS,
    O1_OVERHEAD_GROWTH_BOUND_MS,
    S1_MIN_FIRST_TO_LAST_GAP_MS,
    S2_FIRST_CHUNK_BOUND_MS,
)


# --- F1: byte-identity ----------------------------------------------------


def assert_byte_identical(direct: bytes, proxied: bytes) -> None:
    """The proxied body is the same *bytes*, not merely the same meaning.

    A transparent forwarder cannot re-serialize, re-order keys or normalize
    whitespace, so nothing weaker than byte equality is being claimed here.
    """
    if direct == proxied:
        return

    detail = f"direct {len(direct)} bytes, proxied {len(proxied)} bytes"
    for i, (a, b) in enumerate(zip(direct, proxied)):
        if a != b:
            window = slice(max(0, i - 40), i + 40)
            detail = (
                f"first difference at byte {i} ({detail})\n"
                f"  direct : {direct[window]!r}\n"
                f"  proxied: {proxied[window]!r}"
            )
            break
    raise AssertionError(f"proxied body is not byte-identical to the direct body: {detail}")


# --- F2: parser no-op -----------------------------------------------------


def assert_parser_agrees(direct: RequestSample, proxied: RequestSample) -> None:
    """The locked metrics parser extracts the same structure from both paths.

    Timing *values* are deliberately not compared -- they are allowed to
    differ by the router hop. What must not differ is what the parser found:
    how many tokens, whether TTFT was gated at all, and how many TPOT gaps
    the stream yielded (which is where chunk coalescing would show up).
    """
    assert direct.error is None and proxied.error is None, (
        f"parser recorded an error: direct={direct.error!r} proxied={proxied.error!r}"
    )
    assert direct.content_chunk_count == proxied.content_chunk_count, (
        f"token count differs: direct {direct.content_chunk_count} vs proxied {proxied.content_chunk_count}"
    )
    assert (direct.ttft_ms is None) == (proxied.ttft_ms is None), (
        f"t_first gating differs: direct ttft={direct.ttft_ms!r} proxied ttft={proxied.ttft_ms!r}"
    )
    assert len(direct.tpot_samples_ms) == len(proxied.tpot_samples_ms), (
        f"TPOT sample count differs: direct {len(direct.tpot_samples_ms)} "
        f"vs proxied {len(proxied.tpot_samples_ms)} -- the router coalesced or split chunks"
    )


def assert_gating_identical(direct_raw: bytes, proxied_raw: bytes) -> None:
    """Clock-free half of F2: the parser classifies the same chunk sequence.

    The role chunk arrives before the TTFT wait and must not count as
    t_first; asserting on the *index* of the first content chunk checks that
    gating decision without any timing involved, so it cannot be rescued by
    a lucky measurement.
    """
    direct_chunks = parsed_chunks(direct_raw)
    proxied_chunks = parsed_chunks(proxied_raw)

    assert len(direct_chunks) == len(proxied_chunks), (
        f"chunk count differs: direct {len(direct_chunks)} vs proxied {len(proxied_chunks)}"
    )
    assert first_content_index(direct_chunks) == first_content_index(proxied_chunks), (
        f"t_first gating differs: first content chunk at index "
        f"{first_content_index(direct_chunks)} direct vs {first_content_index(proxied_chunks)} proxied"
    )


# --- S1/S2: the router streams rather than collects ------------------------


def assert_incremental_delivery(sample: RequestSample) -> None:
    """S1 -- the client received data incrementally.

    The gap between first- and last-content-chunk arrival is the sum of the
    observed TPOT samples. Streaming reproduces the configured content-stream
    duration (~1900ms); buffering collapses it toward zero because every byte
    lands at once, at the end.
    """
    assert sample.ttft_ms is not None, "no content chunk arrived at all"
    gap_ms = sum(sample.tpot_samples_ms)
    assert gap_ms > S1_MIN_FIRST_TO_LAST_GAP_MS, (
        f"first->last content chunk gap was {gap_ms:.1f}ms, not > {S1_MIN_FIRST_TO_LAST_GAP_MS}ms "
        f"-- the client did not receive the body incrementally ({sample.content_chunk_count} content chunks)"
    )


def assert_first_chunk_early(sample: RequestSample) -> None:
    """S2 -- the first chunk arrived near the configured TTFT, not near
    completion. A coarse bound a buffering router misses by ~1.65 seconds."""
    assert sample.ttft_ms is not None, "no content chunk arrived at all"
    assert sample.ttft_ms < S2_FIRST_CHUNK_BOUND_MS, (
        f"first content chunk arrived at {sample.ttft_ms:.1f}ms, not < {S2_FIRST_CHUNK_BOUND_MS}ms "
        "-- first-chunk time has collapsed toward completion time, i.e. the body was collected"
    )


# --- O1: small, constant overhead -----------------------------------------


def assert_overhead_small_and_constant(small: OverheadArm, large: OverheadArm) -> None:
    """O1 -- both claims from §4.3, asserted together because they are one
    property: the router costs a fixed hop, not per-chunk work.

    The bound is one-sided. A proxied path measuring *faster* than direct is
    noise around zero, not a failure of "small overhead".
    """
    for arm in (small, large):
        assert arm.delta_ms < O1_MEDIAN_OVERHEAD_BOUND_MS, (
            f"median TTFT overhead too large -- {arm.describe()}, "
            f"bound {O1_MEDIAN_OVERHEAD_BOUND_MS}ms"
        )

    growth_ms = large.delta_ms - small.delta_ms
    assert abs(growth_ms) < O1_OVERHEAD_GROWTH_BOUND_MS, (
        f"overhead grew with response size by {growth_ms:+.2f}ms "
        f"(bound {O1_OVERHEAD_GROWTH_BOUND_MS}ms) -- that is per-chunk work, i.e. hidden "
        f"buffering or parsing.\n  {small.describe()}\n  {large.describe()}"
    )

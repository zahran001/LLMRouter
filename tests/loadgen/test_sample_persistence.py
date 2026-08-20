"""Per-request TTFT/TPOT persistence and per-point metrics
(WEEK2_PLAN.md §2.4/§2.5/§2.6/§6.3, WEEK2_EXECUTION.md Block E/F).

The gap these cover: the scheduler captured TTFT into an in-memory dict and
the CLI printed a summary without it, so every sample died with the process.
The raw log's six fields cannot substitute -- close_time bounds the whole
stream, and nothing in it is a first-token time. A GPU point run that way
produces no p99 TTFT, which is the entire baseline number.

Three properties, each with a control where a control is meaningful:
1. the sidecar exists, reconciles against the raw log, and carries real TTFT;
2. it is written DURING the run, not at the end (§6.3 durable-on-produce);
3. the point record filters warmup by TIME, gates on achieved samples, and
   resolves breach the way §2.4/§2.5/§2.6 say.
"""

from __future__ import annotations

import asyncio
import math

import pytest

from loadgen.corpus import load_corpus
from loadgen.log import RunLogger, SampleLogger, read_log, read_samples
from loadgen.schedule import build_steady_schedule
from loadgen.scheduler import OpenLoopScheduler
from metrics.point import point_metrics, post_warmup
from tests.loadgen._assertions import assert_log_reconciles, assert_samples_reconcile

pytestmark = [pytest.mark.loadgen, pytest.mark.integration]

SEED = 4242


def _scheduler(schedule, corpus, base_url, tmp_path, cap, sample_logger=None, tag="pt"):
    return OpenLoopScheduler(
        schedule=schedule,
        corpus=corpus,
        base_url=base_url,
        logger=RunLogger(tmp_path / f"{tag}.raw_log.jsonl"),
        sample_logger=sample_logger,
        concurrency_cap=cap,
        query_params={"config": "slow", "num_tokens": 5},
    )


# ---------------------------------------------------------------------------
# 1. The sidecar exists, reconciles, and carries real TTFT
# ---------------------------------------------------------------------------


async def test_samples_persist_and_reconcile_with_raw_log(mock_base_url, tmp_path):
    """A run with a tight cap (so there are sheds) must leave one sidecar row
    per issued request and none for the shed ones."""
    corpus = load_corpus()
    schedule = build_steady_schedule(15.0, 2.0, SEED, corpus)
    samples_path = tmp_path / "pt.samples.jsonl"

    sample_logger = SampleLogger(samples_path)
    scheduler = _scheduler(schedule, corpus, mock_base_url, tmp_path, cap=3, sample_logger=sample_logger)
    result = await scheduler.run()
    scheduler.logger.close()
    sample_logger.close()

    assert result.n_shed > 0, "test setup should shed, so the sidecar's shed-exclusion is exercised"

    raw_rows = read_log(tmp_path / "pt.raw_log.jsonl")
    sample_rows = read_samples(samples_path)

    assert_log_reconciles(raw_rows, schedule)
    assert_samples_reconcile(sample_rows, raw_rows)

    ttfts = [r["ttft_ms"] for r in sample_rows if r["error"] is None]
    assert ttfts, "no clean samples -- TTFT was not actually captured"
    assert all(t is not None and t > 0 for t in ttfts), f"non-positive/absent TTFT in {ttfts[:5]}"
    # The slow config's configured TTFT is ~500ms; this asserts the sidecar
    # holds a real measurement rather than a placeholder, without re-testing
    # the mock's timing fidelity (that is BENCHMARKS.md's job).
    assert max(ttfts) > 50.0, f"all TTFTs implausibly small ({max(ttfts):.2f}ms) -- not a real measurement"


async def test_sidecar_is_not_written_when_capture_is_off(mock_base_url, tmp_path):
    """--no-capture-samples must not silently produce an empty-but-present
    sidecar that later reads as "this point was quiet"."""
    corpus = load_corpus()
    schedule = build_steady_schedule(5.0, 1.0, SEED, corpus)

    with pytest.raises(ValueError, match="capture_samples=False"):
        OpenLoopScheduler(
            schedule=schedule,
            corpus=corpus,
            base_url=mock_base_url,
            logger=RunLogger(tmp_path / "off.raw_log.jsonl"),
            sample_logger=SampleLogger(tmp_path / "off.samples.jsonl"),
            concurrency_cap=50,
            capture_samples=False,
        )


# ---------------------------------------------------------------------------
# 1b. CONTROL -- a dropped sample write must trip reconciliation
# ---------------------------------------------------------------------------


class _DroppingSampleLogger(SampleLogger):
    """Drops exactly one request's sample row (the V5 dropped-log-write
    control, applied to the sidecar). If assert_samples_reconcile does not
    go red on this, it is not actually checking anything."""

    def __init__(self, path, drop_request_id: int):
        super().__init__(path)
        self.drop_request_id = drop_request_id

    def write(self, request_id, send_time, sample):
        if request_id == self.drop_request_id:
            return
        super().write(request_id, send_time, sample)


async def test_control_dropped_sample_write_trips_reconciliation(mock_base_url, tmp_path):
    corpus = load_corpus()
    schedule = build_steady_schedule(5.0, 1.0, SEED, corpus)
    samples_path = tmp_path / "drop.samples.jsonl"

    sample_logger = _DroppingSampleLogger(samples_path, drop_request_id=0)
    scheduler = _scheduler(schedule, corpus, mock_base_url, tmp_path, cap=50,
                           sample_logger=sample_logger, tag="drop")
    await scheduler.run()
    scheduler.logger.close()
    sample_logger.close()

    raw_rows = read_log(tmp_path / "drop.raw_log.jsonl")
    sample_rows = read_samples(samples_path)

    with pytest.raises(AssertionError, match="missing="):
        assert_samples_reconcile(sample_rows, raw_rows)


# ---------------------------------------------------------------------------
# 2. Durable-on-produce: rows are on disk mid-run, not at the end (§6.3)
# ---------------------------------------------------------------------------


async def test_samples_land_on_disk_during_the_run(mock_base_url, tmp_path):
    """§6.3: "a crash at point 5 must not lose points 1-4" -- applied within
    a point. Reads the sidecar while the run is still in flight and requires
    completed samples to already be there.

    A buffered implementation that flushed at close() would pass every other
    test in this file and fail this one, which is the only reason it exists.
    """
    corpus = load_corpus()
    schedule = build_steady_schedule(10.0, 3.0, SEED, corpus)
    samples_path = tmp_path / "live.samples.jsonl"

    sample_logger = SampleLogger(samples_path)
    scheduler = _scheduler(schedule, corpus, mock_base_url, tmp_path, cap=50,
                           sample_logger=sample_logger, tag="live")

    mid_run_rows: list[int] = []

    async def peek() -> None:
        # Late enough that the slow config's ~500ms TTFT + content stream has
        # let several requests complete; well before the 3s schedule ends.
        await asyncio.sleep(2.0)
        mid_run_rows.append(len(read_samples(samples_path)))

    _, _ = await asyncio.gather(scheduler.run(), peek())
    scheduler.logger.close()
    sample_logger.close()

    final = len(read_samples(samples_path))
    assert mid_run_rows[0] > 0, (
        "sidecar was still empty 2s into a 3s run -- samples are being buffered in memory, "
        "which is exactly the failure §6.3's durable-on-produce rule forbids"
    )
    assert mid_run_rows[0] < final, (
        f"the run had already finished at the mid-run peek ({mid_run_rows[0]} of {final} rows) -- "
        "this test did not actually observe an in-flight run; adjust the timing"
    )


# ---------------------------------------------------------------------------
# 3. The point record -- pure, synthetic inputs (Tier 1 style)
# ---------------------------------------------------------------------------

pytestmark_unit = pytest.mark.loadgen


def _rows(n: int, *, start_t: float, step: float, ttft_ms: float, status: str = "sent"):
    """n issued requests at `step`-second spacing from `start_t`, all with the
    same TTFT -- returns (raw_rows, sample_rows) sharing request_ids."""
    raw, samples = [], []
    for i in range(n):
        t = start_t + i * step
        raw.append({"request_id": i, "send_time": t, "close_time": t + 0.1,
                    "prompt_id": i, "prompt_len": 100, "status": status})
        samples.append({"request_id": i, "send_time": t, "ttft_ms": ttft_ms,
                        "tpot_samples_ms": [10.0, 10.0], "content_chunk_count": 3, "error": None})
    return raw, samples


def _offset(raw, samples, by: int):
    for r in raw:
        r["request_id"] += by
    for s in samples:
        s["request_id"] += by
    return raw, samples


def test_warmup_filter_is_time_based_not_count_based():
    """§2.4: discard the first N *seconds*, not the first N requests. The
    control is built in -- the pre-warmup samples carry a 9000ms TTFT that
    would dominate every percentile if the filter did not exclude them."""
    warm_raw, warm_samples = _rows(50, start_t=0.0, step=0.1, ttft_ms=9000.0)
    meas_raw, meas_samples = _offset(*_rows(200, start_t=10.0, step=0.5, ttft_ms=100.0), by=50)

    record = point_metrics(
        raw_rows=warm_raw + meas_raw,
        sample_rows=warm_samples + meas_samples,
        offered_rps=2.0,
        duration_s=120.0,
        warmup_n_s=10.0,
    )

    assert record["n_samples_window"] == 200, "warmup filter kept or dropped the wrong rows"
    assert record["ttft_p99_ms"] == pytest.approx(100.0), (
        f"p99 is {record['ttft_p99_ms']} -- the 9000ms warmup transient leaked into the window"
    )
    # And the filter itself, directly.
    assert len(post_warmup(warm_samples, 10.0)) == 0
    assert len(post_warmup(warm_samples + meas_samples, 10.0)) == 200


def test_control_count_based_warmup_would_leak_the_transient():
    """The same data with NO warmup discarded: p99 must be dragged up by the
    9000ms transient. This is what a broken (or absent) filter looks like --
    it proves the assertion above is load-bearing."""
    warm_raw, warm_samples = _rows(50, start_t=0.0, step=0.1, ttft_ms=9000.0)
    meas_raw, meas_samples = _offset(*_rows(200, start_t=10.0, step=0.5, ttft_ms=100.0), by=50)

    record = point_metrics(
        raw_rows=warm_raw + meas_raw,
        sample_rows=warm_samples + meas_samples,
        offered_rps=2.0,
        duration_s=120.0,
        warmup_n_s=0.0,
    )
    assert record["ttft_p99_ms"] > 1000.0, (
        "with warmup=0 the 9000ms transient should dominate p99 -- if it does not, the "
        "time-based-filter test above is not proving anything"
    )


def test_tail_invalid_below_the_100_sample_floor():
    """§2.4: a point whose achieved post-warmup sample count is under the
    floor is flagged and its tail NOT reported -- and breach is None, not
    False. "We did not measure a breach" is not "we measured no breach"."""
    raw, samples = _rows(40, start_t=10.0, step=1.0, ttft_ms=800.0)

    record = point_metrics(raw_rows=raw, sample_rows=samples, offered_rps=0.3,
                           duration_s=60.0, warmup_n_s=10.0)

    assert record["tail_valid"] is False
    assert record["ttft_p99_ms"] is None, "p99 must be null, not a number, below the sample floor"
    assert record["breach_500ms"] is None, (
        "a tail-invalid point must not claim a breach verdict either way -- its p99 is not a "
        "tail estimate"
    )
    assert record["ttft_p50_ms"] == pytest.approx(800.0), "p50/mean stay populated for visibility"


def test_breach_and_severe_thresholds():
    raw, samples = _rows(200, start_t=10.0, step=0.5, ttft_ms=640.0)
    under = point_metrics(raw_rows=raw, sample_rows=samples, offered_rps=2.0,
                          duration_s=110.0, warmup_n_s=10.0)
    assert under["tail_valid"] and under["breach_500ms"] is True and under["severe_2s"] is False

    raw, samples = _rows(200, start_t=10.0, step=0.5, ttft_ms=120.0)
    clean = point_metrics(raw_rows=raw, sample_rows=samples, offered_rps=2.0,
                          duration_s=110.0, warmup_n_s=10.0)
    assert clean["breach_500ms"] is False and clean["severe_2s"] is False

    raw, samples = _rows(200, start_t=10.0, step=0.5, ttft_ms=3500.0)
    severe = point_metrics(raw_rows=raw, sample_rows=samples, offered_rps=2.0,
                           duration_s=110.0, warmup_n_s=10.0)
    assert severe["breach_500ms"] is True and severe["severe_2s"] is True


def test_achieved_rps_counts_window_sends_and_option_y_flags_divergence():
    """§2.5: achieved RPS is sends within the measurement window / window;
    beyond the band the point is kept and plotted at achieved (Option Y)."""
    # 200 sends over a 100s window = 2 RPS achieved against 5 offered: a
    # client that could not keep up, i.e. exactly the client-saturation case
    # the gate exists to surface.
    raw, samples = _rows(200, start_t=10.0, step=0.5, ttft_ms=100.0)
    record = point_metrics(raw_rows=raw, sample_rows=samples, offered_rps=5.0,
                           duration_s=110.0, warmup_n_s=10.0)

    assert record["window_s"] == pytest.approx(100.0)
    assert record["achieved_rps"] == pytest.approx(2.0)
    assert record["divergence_pct"] == pytest.approx(-60.0)
    assert record["flagged"] is True
    assert record["plot_rps"] == pytest.approx(2.0), "flagged points plot at achieved, not offered"
    assert record["plot_rps_basis"] == "achieved"

    clean = point_metrics(raw_rows=raw, sample_rows=samples, offered_rps=2.0,
                          duration_s=110.0, warmup_n_s=10.0)
    assert clean["flagged"] is False and clean["plot_rps"] == pytest.approx(2.0)
    assert clean["plot_rps_basis"] == "offered"


def test_shed_rows_are_excluded_from_achieved_but_counted():
    """A shed request never left the client, so it cannot count toward
    achieved RPS -- but it must still be visible in the record, since a
    shedding point is a client-capability finding (§2.5)."""
    raw, samples = _rows(200, start_t=10.0, step=0.5, ttft_ms=100.0)
    raw += [{"request_id": 1000 + i, "send_time": None, "close_time": None,
             "prompt_id": 0, "prompt_len": 10, "status": "shed"} for i in range(37)]

    record = point_metrics(raw_rows=raw, sample_rows=samples, offered_rps=2.0,
                           duration_s=110.0, warmup_n_s=10.0)

    assert record["achieved_rps"] == pytest.approx(2.0), "shed requests inflated achieved RPS"
    assert record["n_shed_total"] == 37, "shed count must survive into the point record"


def test_all_requests_errored_is_not_a_clean_under_500ms_point():
    """Enough post-warmup requests to clear the sample floor, but not one
    content chunk between them. `tail_valid` is true (the count is there)
    while p99 is null -- and breach must stay None. A point where the
    upstream returned nothing must never read as "measured, no breach"."""
    raw, samples = _rows(200, start_t=10.0, step=0.5, ttft_ms=100.0)
    for s in samples:
        s.update(ttft_ms=None, tpot_samples_ms=[], content_chunk_count=0, error="no_content_chunks")

    record = point_metrics(raw_rows=raw, sample_rows=samples, offered_rps=2.0,
                           duration_s=110.0, warmup_n_s=10.0)

    assert record["tail_valid"] is True, "the requests were there; it is the content that was not"
    assert record["n_ttft_samples"] == 0
    assert record["ttft_p99_ms"] is None
    assert record["breach_500ms"] is None, "a point with no TTFT at all cannot report 'under 500ms'"


def test_warmup_longer_than_the_schedule_raises():
    """The one case scripts/generate_stage_a_schedules.py flags as needing
    regeneration: a real N so large the schedule cannot absorb it."""
    raw, samples = _rows(10, start_t=0.0, step=0.1, ttft_ms=100.0)
    with pytest.raises(ValueError, match="no measurement window"):
        point_metrics(raw_rows=raw, sample_rows=samples, offered_rps=2.0,
                      duration_s=130.0, warmup_n_s=130.0)


def test_record_is_json_serializable_with_no_nans():
    """The point record is written to disk verbatim; a NaN would make it
    invalid JSON that json.load rejects on the offline recompute."""
    import json

    raw, samples = _rows(5, start_t=10.0, step=1.0, ttft_ms=100.0)
    record = point_metrics(raw_rows=raw, sample_rows=samples, offered_rps=1.0,
                           duration_s=60.0, warmup_n_s=10.0)
    round_tripped = json.loads(json.dumps(record))
    assert round_tripped["ttft_p99_ms"] is None
    for key, value in round_tripped.items():
        assert not (isinstance(value, float) and math.isnan(value)), f"{key} is NaN"

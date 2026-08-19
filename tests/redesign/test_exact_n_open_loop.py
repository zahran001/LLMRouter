"""Exact-N schedule generation and the open-loop runtime contract
(R4 README R6 and §10 "Evidence-count / open-loop stop semantics";
`WEEK2_PLAN.md` §10.2).

This is the most important file in the redesign suite. The invariant it
guards passes a naive test while being wrong:

    N is fixed OFFLINE, in the frozen schedule.
    N is NEVER a runtime stop condition.

A runtime that stops after `N` completions produces runs of very nearly the
right size, writes artifacts that look correct, and is closed-loop — the
server's own latency decides how much work it is offered. At the load level
where the breach happens, that feedback removes the effect being measured.

So the control here is not "does the real implementation issue N requests".
It is: **a deliberately response-dependent variant must fail, and the real
one must pass, against the same schedule.** The two are run side by side.

The runtime half drives the mock at two very different response speeds. If
the schedule issued depends on how fast the server answers, the two runs
diverge; if it does not, they are identical. That is the same fast-vs-slow
invariance V2 established for the legacy scheduler, re-established for the
frozen exact-N family.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from loadgen.canonical import CANONICAL_SCHEME_VERSION, membership_id
from loadgen.corpus import load_corpus
from loadgen.headline_schedule import (
    HEADLINE_SCHEDULE_SCHEME_VERSION,
    HeadlineScheduleError,
    RepeatIdentity,
    build_headline_schedule,
    canonical_permutation,
    derive_headline_streams,
    load_headline_schedule,
    materialize_exact_n,
    save_headline_schedule,
)
from loadgen.log import RunLogger
from loadgen.scheduler import OpenLoopScheduler

pytestmark = pytest.mark.redesign

WARMUP_S = 5.0
SMALL_N = 40  # keeps the driven tests quick; the contract is size-independent


@pytest.fixture(scope="module")
def corpus():
    return load_corpus()


@pytest.fixture(scope="module")
def small_workload(corpus):
    """A miniature canonical workload with the same SHAPE as the real one.

    Deliberately not the frozen 4,000-prompt artifact: driving that against a
    mock would take an hour and prove nothing extra. The exact-N contract does
    not depend on the value of N, so the test uses a value that can be driven.
    """
    membership = [p.prompt_id for p in corpus.prompts[:SMALL_N]]
    return {
        "scheme_version": CANONICAL_SCHEME_VERSION,
        "membership_id": membership_id(membership),
        "membership": membership,
        "locks": {"N": SMALL_N, "L_pct": 99.0, "L_chars": 11471.37, "k": 6, "N_max": 5000},
        "corpus": {"sha256": __import__("hashlib").sha256(
            corpus.source_path.read_bytes()).hexdigest(), "size": len(corpus)},
    }


def _identity(workload, repeat_id=1, arrival_seed=101, assignment_seed=201):
    return RepeatIdentity(workload["membership_id"], repeat_id, arrival_seed, assignment_seed)


def _post_warmup(schedule, warmup_s=WARMUP_S):
    return [e for e in schedule.entries if e.scheduled_offset >= warmup_s]


# ---------------------------------------------------------------------------
# Offline: the schedule contains exactly N post-warmup arrivals.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("nominal_lambda", [1.5, 2.0, 4.0, 20.0])
def test_materialization_produces_exactly_n_post_warmup_arrivals(small_workload, corpus,
                                                                 nominal_lambda):
    schedule = build_headline_schedule(
        canonical=small_workload, corpus=corpus, identity=_identity(small_workload),
        nominal_lambda_rps=nominal_lambda, warmup_s=WARMUP_S)

    post = _post_warmup(schedule)
    assert len(post) == SMALL_N
    assert schedule.provenance["materialized_post_warmup_count"] == SMALL_N
    assert schedule.provenance["post_warmup_target_count"] == SMALL_N
    # And the last entry IS the Nth post-warmup arrival: materialization stops
    # there rather than running to a duration.
    assert schedule.entries[-1].scheduled_offset >= WARMUP_S
    assert schedule.entries[-1] == post[-1]


def test_duration_is_an_outcome_not_n_over_lambda(small_workload, corpus):
    """`N / λ` is the EXPECTATION of the duration. Using it as the duration
    would put finite-Poisson count variance straight back into the quantity N
    exists to hold still."""
    durations = []
    for arrival_seed in range(300, 310):
        schedule = build_headline_schedule(
            canonical=small_workload, corpus=corpus,
            identity=_identity(small_workload, arrival_seed=arrival_seed),
            nominal_lambda_rps=2.0, warmup_s=WARMUP_S)
        durations.append(schedule.provenance["materialized_schedule_duration_s"])
        assert schedule.provenance["materialized_post_warmup_count"] == SMALL_N

    assert len(set(durations)) > 1, (
        "every realization produced the same duration -- the arrivals are not stochastic, or "
        "the materializer is running to a fixed duration rather than to a fixed count")
    expected = SMALL_N / 2.0 + WARMUP_S
    assert not all(abs(d - expected) < 1e-9 for d in durations)


def test_materialize_exact_n_is_the_primitive():
    rng = np.random.default_rng(7)
    offsets, n_warmup = materialize_exact_n(2.0, warmup_s=10.0, n=25, arrival_rng=rng)
    assert sum(1 for o in offsets if o >= 10.0) == 25
    assert n_warmup == sum(1 for o in offsets if o < 10.0)
    assert offsets == sorted(offsets), "arrival offsets must be non-decreasing"
    assert offsets[-1] >= 10.0


def test_control_a_fixed_duration_materializer_does_not_hold_n(corpus):
    """The old design, shown failing the new contract.

    A fixed 120s window is exactly what made request count a function of λ,
    and therefore what let each point realize a different prompt tail. Running
    it here demonstrates the property the exact-N materializer removes.
    """
    from loadgen.schedule import build_poisson_schedule

    counts = {
        lam: len(build_poisson_schedule(lam, 120.0, 42, corpus).entries)
        for lam in (1.0, 2.0, 5.0, 10.0)
    }
    assert len(set(counts.values())) == len(counts), (
        "fixed-duration schedules produced the same count at every lambda -- then the confound "
        "this control describes would not exist and the exact-N redesign would be unmotivated")
    assert counts[10.0] > 5 * counts[1.0]


# ---------------------------------------------------------------------------
# Repeat identity.
# ---------------------------------------------------------------------------


def test_same_seeds_give_a_byte_identical_schedule(small_workload, corpus, tmp_path):
    kwargs = dict(canonical=small_workload, corpus=corpus,
                  identity=_identity(small_workload), nominal_lambda_rps=2.0, warmup_s=WARMUP_S)
    a = build_headline_schedule(**kwargs)
    b = build_headline_schedule(**kwargs)

    _, digest_a = save_headline_schedule(a, tmp_path / "a")
    _, digest_b = save_headline_schedule(b, tmp_path / "b")
    assert digest_a == digest_b
    assert a.entries == b.entries


def test_different_arrival_seed_changes_timing_but_not_membership(small_workload, corpus):
    base = build_headline_schedule(
        canonical=small_workload, corpus=corpus, identity=_identity(small_workload),
        nominal_lambda_rps=2.0, warmup_s=WARMUP_S)
    other = build_headline_schedule(
        canonical=small_workload, corpus=corpus,
        identity=_identity(small_workload, repeat_id=2, arrival_seed=999, assignment_seed=201),
        nominal_lambda_rps=2.0, warmup_s=WARMUP_S)

    assert [e.scheduled_offset for e in base.entries] != [e.scheduled_offset for e in other.entries]
    assert sorted(e.prompt_id for e in _post_warmup(base)) == \
           sorted(e.prompt_id for e in _post_warmup(other))


def test_different_assignment_seed_changes_order_but_not_membership(small_workload, corpus):
    base = build_headline_schedule(
        canonical=small_workload, corpus=corpus, identity=_identity(small_workload),
        nominal_lambda_rps=2.0, warmup_s=WARMUP_S)
    other = build_headline_schedule(
        canonical=small_workload, corpus=corpus,
        identity=_identity(small_workload, repeat_id=2, arrival_seed=101, assignment_seed=888),
        nominal_lambda_rps=2.0, warmup_s=WARMUP_S)

    base_order = [e.prompt_id for e in _post_warmup(base)]
    other_order = [e.prompt_id for e in _post_warmup(other)]
    assert base_order != other_order, "a new assignment seed must reorder the prompts"
    assert sorted(base_order) == sorted(other_order), "membership must be identical"


def test_permutation_is_a_permutation(small_workload):
    order = canonical_permutation(small_workload["membership"], 4242)
    assert sorted(order) == sorted(small_workload["membership"])
    assert order != sorted(small_workload["membership"]), "hash order should not be sorted order"


def test_rng_streams_are_independent(small_workload):
    arrival_a, warmup_a = derive_headline_streams(101, 1)
    arrival_b, warmup_b = derive_headline_streams(101, 2)
    assert arrival_a.random() != arrival_b.random(), "repeat_id must change the arrival stream"
    assert warmup_a.random() != warmup_b.random()


# ---------------------------------------------------------------------------
# Matched RPS points within one repeat.
# ---------------------------------------------------------------------------


def test_within_a_repeat_every_lambda_sees_the_same_prompt_order(small_workload, corpus):
    identity = _identity(small_workload)
    orders = {}
    for nominal_lambda in (1.5, 2.0, 4.0, 20.0):
        schedule = build_headline_schedule(
            canonical=small_workload, corpus=corpus, identity=identity,
            nominal_lambda_rps=nominal_lambda, warmup_s=WARMUP_S)
        orders[nominal_lambda] = [e.prompt_id for e in _post_warmup(schedule)]

    reference = orders[1.5]
    for nominal_lambda, order in orders.items():
        assert order == reference, (
            f"lambda {nominal_lambda} sees a different prompt order; RPS points would not be "
            "matched and p99 movement could not be attributed to load")


def test_only_arrival_timing_changes_across_lambdas(small_workload, corpus):
    identity = _identity(small_workload)
    a = build_headline_schedule(canonical=small_workload, corpus=corpus, identity=identity,
                                nominal_lambda_rps=2.0, warmup_s=WARMUP_S)
    b = build_headline_schedule(canonical=small_workload, corpus=corpus, identity=identity,
                                nominal_lambda_rps=4.0, warmup_s=WARMUP_S)

    assert a.provenance["materialized_schedule_duration_s"] > \
           b.provenance["materialized_schedule_duration_s"]
    assert [e.prompt_id for e in _post_warmup(a)] == [e.prompt_id for e in _post_warmup(b)]


# ---------------------------------------------------------------------------
# Provenance and format versioning.
# ---------------------------------------------------------------------------


def test_schedule_records_everything_r6_requires(small_workload, corpus):
    schedule = build_headline_schedule(
        canonical=small_workload, corpus=corpus, identity=_identity(small_workload),
        nominal_lambda_rps=2.0, warmup_s=WARMUP_S)
    prov = schedule.provenance

    for field in ("nominal_lambda_rps", "warmup_boundary_s", "materialized_schedule_count",
                  "materialized_post_warmup_count", "materialized_schedule_duration_s",
                  "post_warmup_target_count", "canonical_prompt_membership_id",
                  "repeat_id", "arrival_seed", "assignment_seed", "corpus_sha256"):
        assert field in prov, f"schedule provenance is missing {field}"

    assert prov["schedule_scheme_version"] == HEADLINE_SCHEDULE_SCHEME_VERSION
    assert prov["n_is_a_schedule_generation_constraint"] is True
    assert prov["runtime_stop_condition"] == "schedule issuance exhausted"


def test_control_a_mismatched_membership_id_is_refused(small_workload, corpus):
    wrong = RepeatIdentity("0" * 64, repeat_id=1, arrival_seed=1, assignment_seed=1)
    with pytest.raises(HeadlineScheduleError, match="identity references membership"):
        build_headline_schedule(canonical=small_workload, corpus=corpus, identity=wrong,
                                nominal_lambda_rps=2.0, warmup_s=WARMUP_S)


def test_control_a_legacy_schedule_is_not_read_as_a_headline_schedule(tmp_path, corpus):
    """A v1 schedule loaded through the v2 reader would be driven with
    warmup/exact-N semantics it was never built under."""
    from loadgen.schedule import build_poisson_schedule

    legacy = build_poisson_schedule(2.0, 30.0, 42, corpus)
    path = tmp_path / "legacy.schedule.json"
    legacy.save(path)

    with pytest.raises(HeadlineScheduleError, match="schedule_scheme_version"):
        load_headline_schedule(path)


# ---------------------------------------------------------------------------
# Runtime: the frozen schedule is driven to exhaustion, whatever the server does.
# ---------------------------------------------------------------------------


class StopAfterNCompletionsScheduler(OpenLoopScheduler):
    """The forbidden implementation, built deliberately so the control has
    something real to reject.

    This is what `while completed < N` looks like in practice: it reads
    correct, it produces roughly the right number of requests, and it makes
    the offered workload a function of server latency.
    """

    def __init__(self, *args, stop_after_completions: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.stop_after_completions = stop_after_completions

    async def run(self):
        import time

        import httpx

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            self._client = client
            t_start = time.monotonic()
            tasks = []
            for request_id, entry in enumerate(self.schedule.entries):
                # THE BUG: a response-dependent stop condition.
                if self._n_sent >= self.stop_after_completions:
                    break
                target = t_start + entry.scheduled_offset
                while time.monotonic() < target:
                    await asyncio.sleep(0.001)
                tasks.append(asyncio.create_task(self._handle(request_id, entry, t_start)))
            await asyncio.gather(*tasks)

        from loadgen.scheduler import RunResult
        return RunResult(
            n_scheduled=len(self.schedule.entries), n_sent=self._n_sent, n_shed=self._n_shed,
            n_errored=self._n_errored, achieved_rps=0.0,
            window_s=self.schedule.provenance["duration_s"],
            wall_clock_drain_s=0.0, per_send_lag_s=self._per_send_lag, samples=self._samples)


async def _drive(schedule, corpus, base_url, log_path, config, scheduler_cls=OpenLoopScheduler,
                 **extra):
    scheduler = scheduler_cls(
        schedule=schedule, corpus=corpus, base_url=base_url,
        logger=RunLogger(log_path), concurrency_cap=200,
        query_params={"config": config, "num_tokens": 3}, **extra)
    result = await scheduler.run()
    scheduler.logger.close()
    return result


@pytest.fixture(scope="module")
def drivable_schedule(small_workload, corpus):
    """A schedule short enough to drive repeatedly, long enough that responses
    complete WHILE it is still issuing.

    That second property is what makes the closed-loop control meaningful. At
    a high enough rate the whole schedule is issued before anything finishes,
    and a completion-gated stop never fires — so a fast schedule would let the
    forbidden implementation pass, which is precisely the false negative this
    file exists to prevent.
    """
    return build_headline_schedule(
        canonical=small_workload, corpus=corpus, identity=_identity(small_workload),
        nominal_lambda_rps=10.0, warmup_s=0.2)


@pytest.mark.integration
async def test_runtime_issues_the_whole_frozen_schedule_at_any_server_speed(
        drivable_schedule, corpus, mock_base_url, tmp_path):
    """Fast and slow servers must issue the identical frozen schedule."""
    fast = await _drive(drivable_schedule, corpus, mock_base_url, tmp_path / "fast.jsonl", "fast")
    slow = await _drive(drivable_schedule, corpus, mock_base_url, tmp_path / "slow.jsonl", "slow")

    scheduled = len(drivable_schedule.entries)
    assert fast.n_sent + fast.n_errored + fast.n_shed == scheduled
    assert slow.n_sent + slow.n_errored + slow.n_shed == scheduled
    assert fast.n_scheduled == slow.n_scheduled == scheduled, (
        "the issued schedule changed with server speed -- response behaviour is leaking into "
        "the offered workload")


@pytest.mark.integration
async def test_control_a_completion_gated_runtime_fails_the_same_check(
        drivable_schedule, corpus, mock_base_url, tmp_path):
    """The forbidden variant, shown failing the check the real one passes.

    Two things are asserted, and the second is the real signature:

      1. it stops short of the frozen schedule;
      2. it stops at a DIFFERENT point depending on how fast the server
         answers -- a fast server completes requests sooner, so the counter
         reaches its limit sooner and less work is offered.

    (2) is what "closed-loop" means operationally: the server's latency
    decided the workload. A build that only failed (1) might merely be
    truncating; a build that fails (2) is feeding responses back into
    issuance.
    """
    scheduled = len(drivable_schedule.entries)
    stop_after = 8

    fast = await _drive(
        drivable_schedule, corpus, mock_base_url, tmp_path / "broken_fast.jsonl", "fast",
        scheduler_cls=StopAfterNCompletionsScheduler, stop_after_completions=stop_after)
    slow = await _drive(
        drivable_schedule, corpus, mock_base_url, tmp_path / "broken_slow.jsonl", "slow",
        scheduler_cls=StopAfterNCompletionsScheduler, stop_after_completions=stop_after)

    issued_fast = fast.n_sent + fast.n_errored + fast.n_shed
    issued_slow = slow.n_sent + slow.n_errored + slow.n_shed

    assert issued_fast < scheduled, (
        "the deliberately completion-gated scheduler issued the whole schedule anyway -- then "
        "this control cannot detect a closed-loop stop condition and R6 has no teeth")
    assert issued_fast < issued_slow, (
        f"the completion-gated scheduler issued {issued_fast} against a fast server and "
        f"{issued_slow} against a slow one; they should differ, with the fast server producing "
        "LESS offered work. If they match, the stop condition is not actually reading "
        "completions and the control proves nothing.")

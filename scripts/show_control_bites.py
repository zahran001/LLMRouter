#!/usr/bin/env python
"""Show each redesign control going RED before it goes GREEN.

`WEEK2_EXECUTION.md` Hard Stop 2 states the rule this script exists to
serve: "Do not accept 'all five pass' as a summary -- the reds are the
proof." A green test that never went red proves nothing, and "make the test
pass" and "make the test meaningfully pass" look identical in a checkmark.

The test suite already encodes both halves, but it reports them as passing
control tests, which shows the reds only by implication. This runs the
broken variant and the real one side by side and PRINTS what each does, so
the failure is legible rather than inferred.

Covers R0-R3 (evidence preservation, artifact naming, legacy interpretation)
and R4-R11 (canonical workload identity, exact-N semantics, the percentile
lock, censoring suppression, RPS fidelity, prefix-cache policy, the repeat
drain, and the evidence ceiling).

The one control that needs a live server -- fast-vs-slow schedule invariance
against a completion-gated scheduler -- lives in
`tests/redesign/test_exact_n_open_loop.py`, because it needs the mock
fixture. It is listed at the end of this run with a pointer.

Exit code is non-zero if any control fails to bite, i.e. if a broken input
was accepted.

Usage:
    .venv/Scripts/python.exe scripts/show_control_bites.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from loadgen.corpus import Corpus, Prompt, load_corpus  # noqa: E402
from loadgen.log import read_log, read_samples  # noqa: E402
from loadgen.schedule import Schedule  # noqa: E402
from metrics.artifacts import RAW_LOG_SUFFIX, SAMPLES_SUFFIX, discover_tags  # noqa: E402
from metrics.point import point_metrics  # noqa: E402

EVIDENCE = REPO_ROOT / "benchmarks" / "evidence" / "week2" / "first_session"
STAGE_A = EVIDENCE / "stage_a"

results: list[tuple[str, bool, str]] = []


def report(name: str, red_ok: bool, green_ok: bool, red_detail: str, green_detail: str) -> None:
    ok = red_ok and green_ok
    print(f"\n--- {name} ---")
    print(f"  RED   (broken input must be rejected): {'BITES' if red_ok else 'DID NOT BITE'}")
    print(f"        {red_detail}")
    print(f"  GREEN (real input must be accepted):   {'PASSES' if green_ok else 'FAILED'}")
    print(f"        {green_detail}")
    results.append((name, ok, "" if ok else "control did not bite or real input failed"))


def control_fractional_discovery() -> None:
    """R0 / README 6 'Fractional RPS'."""
    names = [p.name for p in STAGE_A.glob(f"*{RAW_LOG_SUFFIX}")]

    old_tags = sorted({n.split(".")[0] for n in names})
    old_missing = [t for t in old_tags if not (STAGE_A / f"{t}{SAMPLES_SUFFIX}").exists()]

    new_tags = discover_tags(STAGE_A)
    new_missing = [t for t in new_tags if not (STAGE_A / f"{t}{SAMPLES_SUFFIX}").exists()]

    report(
        "fractional-RPS artifact discovery",
        red_ok=bool(old_missing),
        green_ok=not new_missing,
        red_detail=f"old rule name.split('.')[0] invents {len(old_missing)} phantom point(s) "
                   f"with no sidecar: {old_missing}",
        green_detail=f"suffix-stripping finds {len(new_tags)} point(s), 0 falsely incomplete; "
                     f"'poisson_rps1.5' present = {'poisson_rps1.5' in new_tags}",
    )


def control_promotion_refuses_overwrite() -> None:
    """R0.4 'Do not rewrite raw first-session artifacts'."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_promote_probe", REPO_ROOT / "scripts" / "promote_first_session_evidence.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src, dest = tmp / "runs", tmp / "evidence"
        (src / "stage_a").mkdir(parents=True)
        artifact = src / "stage_a" / "poisson_rps1.5.raw_log.jsonl"
        artifact.write_text('{"request_id": 1, "status": "sent"}\n', encoding="utf-8")

        mod.SRC_ROOT, mod.DEST_ROOT, mod.SUBDIRS = src, dest, {"stage_a": "stage_a"}
        first = mod.promote(verify_only=False)
        promoted = dest / "stage_a" / "poisson_rps1.5.raw_log.jsonl"
        original = promoted.read_bytes()

        artifact.write_text('{"request_id": 1, "status": "errored"}\n', encoding="utf-8")
        second = mod.promote(verify_only=False)
        preserved = promoted.read_bytes() == original

        report(
            "promotion refuses to overwrite differing bytes",
            red_ok=(second != 0 and preserved),
            green_ok=(first == 0),
            red_detail=f"re-promotion of changed bytes exited {second} and left the promoted "
                       f"copy intact = {preserved}",
            green_detail="first promotion of unseen bytes exited 0",
        )


def control_hash_manifest_detects_edit() -> None:
    """R0.5 'Record hashes when promoting'."""
    manifest = json.loads((EVIDENCE / "MANIFEST.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["files"] if e["path"].endswith("poisson_rps2.metrics.json"))
    original = (REPO_ROOT / entry["path"]).read_bytes()

    with tempfile.TemporaryDirectory() as td:
        tampered = Path(td) / "tampered.json"
        tampered.write_bytes(original.replace(b"524.5720889199937", b"524.5720889199938", 1))
        tampered_sha = hashlib.sha256(tampered.read_bytes()).hexdigest()

    actual_sha = hashlib.sha256(original).hexdigest()
    report(
        "hash manifest detects a one-digit edit",
        red_ok=(tampered_sha != entry["sha256"]),
        green_ok=(actual_sha == entry["sha256"]),
        red_detail=f"changing the last digit of one p99 moves sha256 to {tampered_sha[:16]}...",
        green_detail=f"untouched artifact still hashes to {actual_sha[:16]}... as recorded",
    )


def control_interpretation_pin_detects_reader_change() -> None:
    """R0.6 / README 3.1: legacy bytes must keep their historical reading."""
    fixtures = json.loads((EVIDENCE / "LEGACY_FIXTURES.json").read_text(encoding="utf-8"))
    point = next(p for p in fixtures["points"] if p["tag"] == "poisson_rps2")
    arts = point["artifacts"]
    committed = json.loads((REPO_ROOT / arts["metrics"]["path"]).read_text(encoding="utf-8"))
    pinned = point["historical_read"]["exact"]

    def read_at(warmup: float) -> dict:
        return point_metrics(
            raw_rows=read_log(REPO_ROOT / arts["raw_log"]["path"]),
            sample_rows=read_samples(REPO_ROOT / arts["samples"]["path"]),
            offered_rps=committed["offered_rps"],
            duration_s=committed["duration_s"],
            warmup_n_s=warmup,
        )

    shifted = read_at(point["historical_read"]["warmup_n_s"] + 2.0)
    faithful = read_at(point["historical_read"]["warmup_n_s"])

    report(
        "interpretation pin detects a changed warmup basis",
        red_ok=(shifted["ttft_p99_ms"] != pinned["ttft_p99_ms"]),
        green_ok=all(faithful[k] == v for k, v in pinned.items()),
        red_detail=f"a 2s warmup shift moves p99 {pinned['ttft_p99_ms']:.1f}ms -> "
                   f"{shifted['ttft_p99_ms']:.1f}ms and n {pinned['n_ttft_samples']} -> "
                   f"{shifted['n_ttft_samples']}",
        green_detail=f"at the historical warmup all {len(pinned)} pinned fields still match "
                     "bit-for-bit",
    )


def control_corpus_drift_refusal() -> None:
    """README 3.1: legacy schedules stay replayable under frozen schedule + pinned corpus."""
    schedule = Schedule.load(REPO_ROOT / "benchmarks/schedules/stage_a/poisson_rps2.schedule.json")
    corpus = load_corpus()

    with tempfile.TemporaryDirectory() as td:
        drifted_path = Path(td) / "drifted.jsonl"
        shutil.copyfile(corpus.source_path, drifted_path)
        with drifted_path.open("ab") as f:
            f.write(b'{"prompt_id": 9999, "text": "x", "char_len": 1}\n')
        drifted = Corpus(prompts=(Prompt(0, "x", 1),), source_path=drifted_path)

        try:
            schedule.validate_corpus_version(drifted)
            red_ok, red_detail = False, "a mutated corpus was ACCEPTED for replay"
        except ValueError as exc:
            red_ok = True
            red_detail = f"refused: {str(exc).split(' -- ')[0][:88]}..."

    try:
        schedule.validate_corpus_version(corpus)
        green_ok, green_detail = True, f"pinned corpus validates against {schedule.provenance['corpus_sha256'][:16]}..."
    except ValueError as exc:
        green_ok, green_detail = False, str(exc)

    report("corpus-drift refusal (the guard that stopped Stage A)", red_ok, green_ok,
           red_detail, green_detail)


def control_bootstrap_reproducibility() -> None:
    """R2 requires explicit seeds and a persisted configuration."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_p99_probe", REPO_ROOT / "scripts" / "calibrate_p99_sample_size.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    src = mod.load_source("poisson_rps2")["ttft"]
    a = mod.bootstrap_p99(src, 500, 200, seed=7, methods=("linear",))["linear"]
    b = mod.bootstrap_p99(src, 500, 200, seed=7, methods=("linear",))["linear"]
    c = mod.bootstrap_p99(src, 500, 200, seed=8, methods=("linear",))["linear"]

    report(
        "bootstrap is seeded, not merely random",
        red_ok=not np.array_equal(a, c),
        green_ok=np.array_equal(a, b),
        red_detail=f"a different seed gives a different resample stream: "
                   f"{int((a != c).sum())}/{len(a)} resample p99s differ "
                   f"(2.5th pct {np.percentile(a, 2.5):.1f}ms vs {np.percentile(c, 2.5):.1f}ms)",
        green_detail="the same seed reproduces the resample stream exactly",
    )


def control_canonical_membership_identity() -> None:
    """R4A: a changed corpus or stratum config must change workload identity."""
    from loadgen.canonical import CanonicalWorkloadError, N_MAX, build
    from loadgen.corpus import Corpus, Prompt, load_corpus

    corpus = load_corpus()
    baseline = build(corpus)

    with tempfile.TemporaryDirectory() as td:
        drifted_path = Path(td) / "drifted.jsonl"
        drifted_path.write_bytes(corpus.source_path.read_bytes()
                                 + b'{"prompt_id":9999,"text":"x","char_len":1}\n')
        drifted = Corpus(prompts=corpus.prompts + (Prompt(9999, "x", 1),),
                         source_path=drifted_path)
        try:
            build(drifted)
            red_ok, red_detail = False, "a drifted corpus was ACCEPTED for workload construction"
        except CanonicalWorkloadError as exc:
            red_ok = True
            red_detail = f"refused: {str(exc).splitlines()[1].strip()[:88]}..."

    try:
        build(corpus, n=N_MAX + 1)
        ceiling_ok = False
    except CanonicalWorkloadError:
        ceiling_ok = True

    report(
        "canonical workload refuses a drifted corpus and an N over the ceiling",
        red_ok=red_ok and ceiling_ok,
        green_ok=(len(baseline["membership"]) == 4000
                  and len(set(baseline["membership"])) == 4000),
        red_detail=red_detail + f"; N={N_MAX + 1} also refused = {ceiling_ok}",
        green_detail=f"pinned corpus builds {len(baseline['membership'])} unique prompts, "
                     f"{baseline['tail_support']['canonical_prompts_above_L']} above L",
    )


def control_exact_n_materialization() -> None:
    """R6: the schedule holds exactly N post-warmup arrivals, and duration is
    an outcome rather than N/lambda."""
    import hashlib

    from loadgen.canonical import CANONICAL_SCHEME_VERSION, membership_id
    from loadgen.corpus import load_corpus
    from loadgen.headline_schedule import RepeatIdentity, build_headline_schedule
    from loadgen.schedule import build_poisson_schedule

    corpus = load_corpus()
    n = 40
    membership = [p.prompt_id for p in corpus.prompts[:n]]
    workload = {
        "scheme_version": CANONICAL_SCHEME_VERSION,
        "membership_id": membership_id(membership),
        "membership": membership,
        "locks": {"N": n},
        "corpus": {"sha256": hashlib.sha256(corpus.source_path.read_bytes()).hexdigest()},
    }
    identity = RepeatIdentity(workload["membership_id"], 1, 101, 201)

    # RED: the OLD fixed-duration materializer -- count varies with lambda,
    # which is the prompt-tail confound at its source.
    old_counts = {lam: len(build_poisson_schedule(lam, 120.0, 42, corpus).entries)
                  for lam in (1.0, 2.0, 5.0, 10.0)}

    # GREEN: the exact-N materializer -- count is identical at every lambda.
    new = {}
    for lam in (1.5, 2.0, 4.0, 20.0):
        schedule = build_headline_schedule(canonical=workload, corpus=corpus,
                                           identity=identity, nominal_lambda_rps=lam,
                                           warmup_s=5.0)
        new[lam] = (schedule.provenance["materialized_post_warmup_count"],
                    schedule.provenance["materialized_schedule_duration_s"])

    counts = {v[0] for v in new.values()}
    durations = {round(v[1], 3) for v in new.values()}

    report(
        "exact-N materialization vs the fixed-duration design",
        red_ok=len(set(old_counts.values())) == len(old_counts),
        green_ok=(counts == {n} and len(durations) == len(new)),
        red_detail=f"fixed 120s window yields {old_counts} -- request count is a function of "
                   "lambda, so each point realizes a different prompt tail",
        green_detail=f"exact-N yields {n} post-warmup arrivals at every lambda, with duration "
                     f"an outcome ({', '.join(f'{d:.0f}s' for d in sorted(durations))})",
    )


def control_percentile_lock() -> None:
    """L5: conventions disagree across the SLO; the redesigned path is pinned."""
    from metrics.percentile import percentile_nearest_rank

    rows = [json.loads(line) for line in
            (STAGE_A / "poisson_rps2.samples.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    ttft = [r["ttft_ms"] for r in rows if r["send_time"] >= 10.0 and r.get("ttft_ms") is not None]

    by_method = {m: float(np.percentile(np.array(ttft), 99, method=m))
                 for m in ("linear", "lower", "higher", "nearest", "midpoint")}
    verdicts = {m: "OVER" if v >= 500 else "UNDER" for m, v in by_method.items()}
    split = len(set(verdicts.values())) == 2

    locked = percentile_nearest_rank(ttft, 99)
    report(
        "percentile convention lock",
        red_ok=split,
        green_ok=(locked in ttft and abs(locked - by_method["nearest"]) < 1e-9),
        red_detail="unlocked, the same 225 samples give " + ", ".join(
            f"{m}={v:.1f}({verdicts[m]})" for m, v in by_method.items()),
        green_detail=f"nearest-rank returns {locked:.1f}ms, an actually observed latency",
    )


def control_censoring_suppression() -> None:
    """R8: survivor-only p99 is refused above the 5% gate."""
    from metrics.headline_point import OVER_CENSORED, headline_point_metrics
    from metrics.point import MIN_TAIL_SAMPLES

    n, censored = 200, 66  # 33%, the first session's 10-RPS rate
    raw, samples = [], []
    for i in range(n):
        is_censored = i < censored
        raw.append({"request_id": i, "send_time": i * 0.01, "close_time": 1.0,
                    "prompt_id": i, "prompt_len": 100,
                    "status": "errored" if is_censored else "sent"})
        samples.append({"request_id": i, "send_time": i * 0.01,
                        "ttft_ms": None if is_censored else 120.0,
                        "tpot_samples_ms": [], "content_chunk_count": 0 if is_censored else 5,
                        "error": "ReadTimeout: timed out" if is_censored else None})

    prov = {"nominal_lambda_rps": 10.0, "warmup_boundary_s": 0.0,
            "materialized_schedule_count": n, "materialized_post_warmup_count": n,
            "post_warmup_target_count": n, "materialized_schedule_duration_s": 20.0}
    record = headline_point_metrics(raw, samples, prov, warmup_n_s=0.0,
                                    scheduled_offsets=[i * 0.01 for i in range(n)])
    survivors = n - censored

    report(
        "censoring suppresses a survivor-only p99",
        red_ok=(survivors >= MIN_TAIL_SAMPLES),
        green_ok=(record["point_state"] == OVER_CENSORED and record["ttft_p99_ms"] is None),
        red_detail=f"{survivors} surviving samples clear the old n>={MIN_TAIL_SAMPLES} gate, so "
                   "the old rule would publish a p99 of 120ms for a point that lost 33% of "
                   "its requests",
        green_detail=f"the new gate returns {record['point_state']} at "
                     f"{record['ttft_censoring_rate']:.0%} censoring and suppresses the p99",
    )


def control_driver_fidelity_denominator() -> None:
    """R7: finite-Poisson noise must not fail the driver; dropped sends must."""
    from metrics.headline_point import headline_point_metrics

    def record(n_sent, materialized, duration, nominal):
        prov = {"nominal_lambda_rps": nominal, "warmup_boundary_s": 0.0,
                "materialized_schedule_count": materialized,
                "materialized_post_warmup_count": materialized,
                "post_warmup_target_count": materialized,
                "materialized_schedule_duration_s": duration}
        step = duration / materialized
        raw = [{"request_id": i, "send_time": i * step, "close_time": i * step + 0.1,
                "prompt_id": i, "prompt_len": 100, "status": "sent"} for i in range(n_sent)]
        samples = [{"request_id": i, "send_time": i * step, "ttft_ms": 120.0,
                    "tpot_samples_ms": [], "content_chunk_count": 3, "error": None}
                   for i in range(n_sent)]
        return headline_point_metrics(
            raw, samples, prov, warmup_n_s=0.0,
            scheduled_offsets=[i * step for i in range(materialized)])

    dropped = record(200, 248, 130.0, 2.0)      # driver lost 48 sends
    realization = record(248, 248, 130.0, 2.0)  # the first session's 2-RPS point

    report(
        "driver fidelity measures the materialized schedule, not nominal lambda",
        red_ok=(dropped["schedule_delivery_ok"] is False),
        green_ok=(realization["schedule_delivery_ok"] is True
                  and realization["nominal_realization_delta_pct"] < 0),
        red_detail=f"dropping 48 of 248 scheduled sends gives "
                   f"{dropped['schedule_delivery_divergence_pct']:+.1f}% and FAILS the gate",
        green_detail=f"the 2-RPS point delivered 248/248 -> gate passes, while its finite-Poisson "
                     f"realization of {realization['nominal_realization_delta_pct']:+.2f}% vs "
                     "nominal is recorded as metadata (it was a -6.25% 'divergence' before)",
    )


def control_prefix_cache_gate() -> None:
    """L6: a cache-hit-shaped replay must be refused."""
    from loadgen.prefix_cache import DISABLED, ENABLED, ProbeResult, evaluate

    warm = evaluate([ProbeResult(458, 14960, 523.3, 103.9)])
    cold = evaluate([ProbeResult(458, 14960, 523.3, 519.0)])

    report(
        "prefix-cache preflight gate",
        red_ok=(warm["verdict"] == ENABLED and not warm["safe_for_controlled_headline"]),
        green_ok=(cold["verdict"] == DISABLED and cold["safe_for_controlled_headline"]),
        red_detail=f"the measured first-session replay (523.3ms -> 103.9ms, "
                   f"{warm['min_ratio']:.2f}x) is refused as {warm['verdict']}",
        green_detail=f"a cold replay ({cold['min_ratio']:.2f}x) is allowed as {cold['verdict']}",
    )


def control_repeat_drain_and_ceiling() -> None:
    """R9/R10: overlapping repeats are refused; the ceiling reports an interval."""
    from loadgen.repeat_runner import RepeatOverlapError, RepeatPlan, RepeatRunner
    from metrics.classification import RepeatPolicy, resolve_breach

    clock = {"t": 0.0}

    def tick():
        clock["t"] += 1.0
        return clock["t"]

    plans = [RepeatPlan(1, 101, 201, [2.0]), RepeatPlan(2, 102, 202, [2.0])]
    try:
        RepeatRunner(run_point=lambda p, l: {}, inflight_probe=lambda: 7,
                     sleep=lambda _s: None, clock=tick).run(plans)
        overlap_refused = False
    except RepeatOverlapError:
        overlap_refused = True

    drained = RepeatRunner(run_point=lambda p, l: {"repeat_id": p.repeat_id},
                           inflight_probe=lambda: 0, sleep=lambda _s: None,
                           clock=tick).run(plans)

    from metrics.classification import HeadlineEvidenceSpec

    membership = "m" * 64
    policy = RepeatPolicy(min_valid_repeats=3, n_per_run=4000, n_max=5000,
                          max_repeats_authorized=3,
                          headline=HeadlineEvidenceSpec(membership_id=membership,
                                                        percentile_population_n=4000))

    def rep(i, lam, state, p99):
        return {"record_version": "headline-point-v1",
                "evidence_class": "headline_evidence",
                "may_define_headline_breach": True,
                "schedule_scheme_version": "headline-schedule-v2",
                "process_epoch": "vllm-start-1000",
                "percentile_population_n": 4000,
                "repeat_id": i, "canonical_prompt_membership_id": membership,
                "arrival_seed": 1000 + i, "assignment_seed": 2000 + i,
                "nominal_lambda_rps": lam, "point_state": state, "ttft_p99_ms": p99,
                "n_ttft_observed": 4000, "ttft_censoring_rate": 0.0,
                "tail_censoring_warning": False, "schedule_delivery_ok": True,
                "exact_n_honoured": True}

    sweep = {
        1.5: [rep(i, 1.5, "UNDER", 300.0) for i in (1, 2, 3)],
        2.0: [rep(1, 2.0, "UNDER", 480.0), rep(2, 2.0, "OVER", 520.0),
              rep(3, 2.0, "UNDER", 495.0)],
        2.5: [rep(i, 2.5, "OVER", 600.0) for i in (1, 2, 3)],
    }
    resolved = resolve_breach(sweep, policy, n_used=5000, repeats_used=3)

    report(
        "repeat drain gate and the evidence ceiling",
        red_ok=overlap_refused,
        green_ok=(len(drained.points) == 2
                  and resolved["resolution"] == "INTERVAL_AT_EVIDENCE_CEILING"),
        red_detail="starting repeat 2 with 7 requests in flight was REFUSED",
        green_detail=f"a drained family runs both repeats; an unresolved point at the ceiling "
                     f"reports {resolved['breach_interval']['notation']} instead of escalating",
    )


def main() -> None:
    if not STAGE_A.exists():
        raise SystemExit(
            "first-session evidence not promoted -- run "
            "scripts/promote_first_session_evidence.py first (README R0)")

    print("Red-then-green evidence for the redesign controls.")
    print("Each control is run against a deliberately-broken input FIRST.")

    control_fractional_discovery()
    control_promotion_refuses_overwrite()
    control_hash_manifest_detects_edit()
    control_interpretation_pin_detects_reader_change()
    control_corpus_drift_refusal()
    control_bootstrap_reproducibility()
    control_canonical_membership_identity()
    control_exact_n_materialization()
    control_percentile_lock()
    control_censoring_suppression()
    control_driver_fidelity_denominator()
    control_prefix_cache_gate()
    control_repeat_drain_and_ceiling()

    print("\n" + "=" * 72)
    failed = [name for name, ok, _ in results if not ok]
    for name, ok, _ in results:
        print(f"  {'BITES + PASSES' if ok else 'FAILED':<16} {name}")
    print("=" * 72)
    if failed:
        print(f"\n{len(failed)} control(s) did not bite. Hard Stop R3 cannot be signed off.")
        raise SystemExit(1)
    print(f"\nAll {len(results)} controls went red on the broken input and green on the real one.")
    print("One further control needs a live server and runs in pytest instead:")
    print("  tests/redesign/test_exact_n_open_loop.py -- fast-vs-slow schedule invariance,")
    print("  with a deliberately completion-gated scheduler proving the check bites.")


if __name__ == "__main__":
    main()

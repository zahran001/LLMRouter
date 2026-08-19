#!/usr/bin/env python
"""Recompute per-point metrics offline from the durable session artifacts
(WEEK2_EXECUTION.md Block F; WEEK2_PLAN.md §2.4, §2.6, §6.3).

This is the post-teardown half of the pair: `loadgen/_cli.py` writes each
point's metrics live during the session using the [CALIBRATE] warmup-N
placeholder, and this re-derives every point at the real N once Block F
reads it off the transient plot. Both call the same
`metrics.point.point_metrics`, so "recomputed offline" and "printed on the
meter" cannot silently disagree.

Nothing here touches the GPU or needs the schedules re-driven -- the warmup
filter is metrics-side and time-based (§2.4), so a new N is a new filter
over the same committed sidecars, not a new run.

Usage:
    # recompute every point in a run dir at the resolved warmup N
    .venv/Scripts/python.exe scripts/compute_point_metrics.py \
        --run-dir benchmarks/runs/stage_a --warmup-n 18.5

    # dry-run at the placeholder N, writing nothing (just the table)
    .venv/Scripts/python.exe scripts/compute_point_metrics.py \
        --run-dir benchmarks/runs/stage_a --warmup-n 10 --no-write
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loadgen.log import read_log, read_samples
from loadgen.schedule import Schedule
from metrics.artifacts import SAMPLES_SUFFIX, discover_tags
from metrics.point import DEFAULT_BAND_PCT, MIN_TAIL_SAMPLES, point_metrics


def _resolve_provenance(tag: str, run_dir: Path, schedule_dir: Path | None) -> tuple[float, float, dict]:
    """Offered RPS + schedule duration for a point, from whichever artifact
    still has them. Prefers the point's own metrics.json (written during the
    session, so it is the record of what was actually driven); falls back to
    a schedule artifact for a point whose run died before its metrics were
    written -- exactly the case §6.3's durable-on-produce rule exists for."""
    metrics_path = run_dir / f"{tag}.metrics.json"
    if metrics_path.exists():
        prev = json.loads(metrics_path.read_text(encoding="utf-8"))
        sched_prov = prev.get("provenance", {}).get("schedule_provenance", {})
        return prev["offered_rps"], prev["duration_s"], sched_prov

    if schedule_dir is not None:
        for candidate in schedule_dir.glob(f"{tag}*.schedule.json"):
            prov = Schedule.load(candidate).provenance
            return float(prov["target_rps"]), float(prov["duration_s"]), prov

    raise SystemExit(
        f"{tag}: no {metrics_path.name} and no matching schedule in "
        f"{schedule_dir or '<--schedule-dir not given>'} -- cannot recover this point's "
        "offered RPS / duration. Pass --schedule-dir pointing at the committed schedules."
    )


def _fmt(x: float | None, width: int = 8) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-".rjust(width)
    return f"{x:.1f}".rjust(width)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", required=True, type=Path,
                        help="directory holding <tag>.raw_log.jsonl / <tag>.samples.jsonl per point")
    parser.add_argument("--warmup-n", required=True, type=float, dest="warmup_n_s",
                        help="warmup seconds to discard by send timestamp (§2.4) -- the value Block F "
                             "reads off the TTFT-vs-wall-clock transient plot")
    parser.add_argument("--schedule-dir", type=Path, default=None,
                        help="fallback source of offered RPS / duration for a point with no metrics.json")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="where to write recomputed <tag>.metrics.json (default: --run-dir, overwriting)")
    parser.add_argument("--min-samples", type=int, default=MIN_TAIL_SAMPLES)
    parser.add_argument("--band-pct", type=float, default=DEFAULT_BAND_PCT)
    parser.add_argument("--no-write", action="store_true", help="print the table, write nothing")
    args = parser.parse_args()

    run_dir: Path = args.run_dir
    out_dir: Path = args.out_dir or run_dir
    tags = discover_tags(run_dir, SAMPLES_SUFFIX)
    if not tags:
        raise SystemExit(f"no *.samples.jsonl under {run_dir} -- nothing to recompute")

    records = []
    for tag in tags:
        offered_rps, duration_s, sched_prov = _resolve_provenance(tag, run_dir, args.schedule_dir)
        record = point_metrics(
            raw_rows=read_log(run_dir / f"{tag}.raw_log.jsonl"),
            sample_rows=read_samples(run_dir / f"{tag}.samples.jsonl"),
            offered_rps=offered_rps,
            duration_s=duration_s,
            warmup_n_s=args.warmup_n_s,
            min_samples=args.min_samples,
            band_pct=args.band_pct,
            provenance={
                "tag": tag,
                "arrival_process": sched_prov.get("arrival_process"),
                "schedule_provenance": sched_prov,
                "recomputed_offline": True,
                "warmup_n_is_placeholder": False,
            },
        )
        records.append((tag, record))
        if not args.no_write:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{tag}.metrics.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

    records.sort(key=lambda tr: tr[1]["plot_rps"])

    print(f"\nwarmup N = {args.warmup_n_s}s, band = +/-{args.band_pct}%, tail floor = {args.min_samples} samples\n")
    print(f"{'offered':>8} {'achieved':>9} {'plot':>8} {'div%':>7} {'n':>6} "
          f"{'p50':>8} {'p95':>8} {'p99':>8}  {'breach':<8} flags")
    print("-" * 90)
    for tag, r in records:
        flags = []
        if r["flagged"]:
            flags.append("FLAGGED(plot@achieved)")
        if not r["tail_valid"]:
            flags.append(f"TAIL-INVALID(n<{r['min_samples']})")
        if r["n_shed_total"]:
            flags.append(f"shed={r['n_shed_total']}")
        if r["n_errored_total"]:
            flags.append(f"errored={r['n_errored_total']}")
        if r["severe_2s"]:
            flags.append("SEVERE>2s")
        breach = "-" if r["breach_500ms"] is None else ("BREACH" if r["breach_500ms"] else "under")
        print(
            f"{r['offered_rps']:>8.6g} {r['achieved_rps']:>9.2f} {r['plot_rps']:>8.2f} "
            f"{r['divergence_pct']:>+7.1f} {r['n_samples_window']:>6d} "
            f"{_fmt(r['ttft_p50_ms'])} {_fmt(r['ttft_p95_ms'])} {_fmt(r['ttft_p99_ms'])}  "
            f"{breach:<8} {' '.join(flags)}"
        )

    # §2.6: breach RPS = the LOWEST swept RPS whose full-window p99 TTFT
    # >= 500ms. Tail-invalid points are not eligible -- their p99 is not a
    # tail estimate (§2.4), so they can neither establish nor rule out a
    # breach.
    breached = [r for _, r in records if r["tail_valid"] and r["breach_500ms"]]
    clean_under = [r for _, r in records if r["tail_valid"] and r["breach_500ms"] is False]
    print()
    if breached:
        lowest = min(breached, key=lambda r: r["plot_rps"])
        print(f"breach RPS (lowest swept point with p99 TTFT >= 500ms): {lowest['plot_rps']:.2f} "
              f"(p99 {lowest['ttft_p99_ms']:.1f}ms, plotted at {lowest['plot_rps_basis']})")
        if clean_under:
            highest_under = max(clean_under, key=lambda r: r["plot_rps"])
            print(f"bracketed by: {highest_under['plot_rps']:.2f} RPS under "
                  f"(p99 {highest_under['ttft_p99_ms']:.1f}ms)")
        else:
            print("NOT bracketed: no valid point stayed under 500ms -- the sweep needs lower points")
    else:
        print("no valid point breached 500ms -- the sweep needs to extend upward (§6.2 step 3)")

    if not args.no_write:
        print(f"\n{len(records)} point records written to {out_dir}")


if __name__ == "__main__":
    main()

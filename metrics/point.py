"""Per-RPS-point metrics for the Week 2 baseline sweep (WEEK2_PLAN.md §2.4,
§2.5, §2.6; WEEK2_EXECUTION.md Block E/F).

Pure: takes already-read log rows and returns a dict. No I/O, no clock
reads -- so the number the GPU session prints live at Hard Stop 5 and the
number Block F recomputes offline come out of the *same* function, given
the same two files. The only thing that legitimately changes between those
two calls is `warmup_n_s`, which is still [CALIBRATE] during the session
and resolved from the transient plot afterwards.

Inputs are the two durable artifacts a point produces:
- the raw 6-field log (loadgen/log.py: RunLogger) -- sends, sheds, errors;
- the per-request TTFT/TPOT sidecar (SampleLogger) -- the breach metric.

Both carry `send_time` relative to the run's t_start, which is what makes
the warmup filter time-based rather than count-based (§2.4).
"""

from __future__ import annotations

import math

from metrics.compute import aggregate
from metrics.types import RequestSample

# §2.6: the breach line, and the secondary severe-degradation reference.
# 500ms is the same SLO the router defends in Weeks 4-8 -- one number across
# the project, deliberately (§2.6 "no future seam").
BREACH_TTFT_MS = 500.0
SEVERE_TTFT_MS = 2000.0

# §2.4: a point's tail percentile is only reportable once the *achieved*
# post-warmup sample count clears this floor.
MIN_TAIL_SAMPLES = 100

# §2.5: offered-vs-achieved divergence band. RESOLVED 2026-08-18 at 5.0 --
# no longer [CALIBRATE]. Block C's low-load tracking measured 0.0/0.0/0.0/-0.67%
# divergence at 0.5/1/2/5 RPS, i.e. the driver tracks essentially perfectly
# where any divergence would be a bug rather than saturation. Deliberately NOT
# tightened to that measured 0.67% max: the band's job is to catch material
# under-delivery, and a band with no headroom would flag healthy points near
# the breach -- the worst place to lose data (Option Y below exists for the
# same reason). Full provenance in WEEK2_PLAN.md §2.5/§8.
DEFAULT_BAND_PCT = 5.0

ISSUED_STATUSES = ("sent", "errored")


def _clean(x: float) -> float | None:
    """NaN -> None, so the point record is valid JSON."""
    return None if isinstance(x, float) and math.isnan(x) else x


def post_warmup(rows: list[dict], warmup_n_s: float) -> list[dict]:
    """Discard the first `warmup_n_s` seconds by send timestamp (§2.4).

    Time-based, not count-based: a sustained-RPS run's transient (queue
    filling, KV cache + CUDA graph warming, connection pool establishment)
    is a wall-clock phenomenon. This supersedes Week 1's count-based
    "discard first 10", which was correct for single-shot mock requests and
    is wrong here.

    Rows with no send_time (a `shed` request was never sent) are dropped --
    they have no position on the wall-clock axis to filter by.
    """
    return [r for r in rows if r.get("send_time") is not None and r["send_time"] >= warmup_n_s]


def point_metrics(
    raw_rows: list[dict],
    sample_rows: list[dict],
    offered_rps: float,
    duration_s: float,
    warmup_n_s: float,
    min_samples: int = MIN_TAIL_SAMPLES,
    band_pct: float = DEFAULT_BAND_PCT,
    provenance: dict | None = None,
) -> dict:
    """One RPS point's complete record: percentiles, validity gates, breach.

    `duration_s` is the schedule's full offered duration (warmup + window),
    so the measurement window is `duration_s - warmup_n_s` == Y (§2.4).
    """
    window_s = duration_s - warmup_n_s
    if window_s <= 0:
        raise ValueError(
            f"warmup_n_s={warmup_n_s} leaves no measurement window in a {duration_s}s schedule "
            "-- the point cannot be measured (regenerate with a longer duration_s, per "
            "scripts/generate_stage_a_schedules.py's note on a larger-than-expected N)"
        )

    issued = [r for r in raw_rows if r["status"] in ISSUED_STATUSES]
    issued_window = post_warmup(issued, warmup_n_s)
    shed_window = [r for r in raw_rows if r["status"] == "shed"]

    # §2.5: achieved RPS is counted from *sends* within the measurement
    # window (both `sent` and `errored` were actually issued; only `shed`
    # never left the client), divided by that window -- not completions, and
    # not the full schedule duration, which would fold the warmup transient's
    # own rate into the number the validity gate reads.
    achieved_rps = len(issued_window) / window_s
    divergence_pct = 100.0 * (achieved_rps - offered_rps) / offered_rps if offered_rps else 0.0
    flagged = abs(divergence_pct) > band_pct
    # Option Y (§2.5): a flagged point is KEPT and plotted at the rate the
    # server actually saw. Dropping flagged points would systematically
    # remove data near the breach -- the worst place to lose it.
    plot_rps = achieved_rps if flagged else offered_rps

    measured_rows = sorted(post_warmup(sample_rows, warmup_n_s), key=lambda r: r["request_id"])
    samples = [RequestSample.from_dict(r) for r in measured_rows]

    # warmup=0 is not "no warmup" -- the time-based filter above already did
    # the discarding. Passing a non-zero count here would discard a second
    # time, by request count, on top of it.
    run_metrics = aggregate(samples, warmup=0, min_samples=min_samples, config={})
    m = run_metrics.to_dict()

    ttft_p99 = _clean(run_metrics.ttft_p99)
    tail_valid = run_metrics.valid

    return {
        "offered_rps": offered_rps,
        "achieved_rps": achieved_rps,
        "divergence_pct": divergence_pct,
        "band_pct": band_pct,
        "flagged": flagged,
        "plot_rps": plot_rps,
        "plot_rps_basis": "achieved" if flagged else "offered",
        "warmup_n_s": warmup_n_s,
        "window_s": window_s,
        "duration_s": duration_s,
        "n_scheduled": len(raw_rows),
        "n_issued_total": len(issued),
        "n_issued_window": len(issued_window),
        "n_shed_total": len(shed_window),
        "n_errored_total": sum(1 for r in raw_rows if r["status"] == "errored"),
        "n_samples_window": len(samples),
        "n_ttft_samples": m["n_ttft_samples"],
        "n_tpot_samples": m["n_tpot_samples"],
        "min_samples": min_samples,
        # §2.4: tail percentiles are NaN -> null and MUST NOT be read as real
        # tail estimates when this is false.
        "tail_valid": tail_valid,
        "ttft_p50_ms": m["ttft_p50"],
        "ttft_p95_ms": m["ttft_p95"],
        "ttft_p99_ms": m["ttft_p99"],
        "ttft_mean_ms": m["ttft_mean"],
        "tpot_p50_ms": m["tpot_p50"],
        "tpot_p95_ms": m["tpot_p95"],
        "tpot_p99_ms": m["tpot_p99"],
        "tpot_mean_ms": m["tpot_mean"],
        # §2.6. Both are None (not False) when the tail isn't valid: "we did
        # not measure a breach" and "we measured no breach" are different
        # claims, and only the second one is evidence.
        "breach_500ms": (ttft_p99 >= BREACH_TTFT_MS) if (tail_valid and ttft_p99 is not None) else None,
        "severe_2s": (ttft_p99 >= SEVERE_TTFT_MS) if (tail_valid and ttft_p99 is not None) else None,
        "breach_threshold_ms": BREACH_TTFT_MS,
        "severe_threshold_ms": SEVERE_TTFT_MS,
        # Raw TTFT/TPOT populations are deliberately NOT embedded here: the
        # sidecar already holds them durably and per-request, and a 120s
        # window at high RPS makes raw_tpot_ms enormous. This record is a
        # summary; the sidecar is the source.
        "provenance": dict(provenance or {}),
    }

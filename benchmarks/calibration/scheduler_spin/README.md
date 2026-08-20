# Loadgen scheduler spin-margin calibration (Linux)

Closes `WEEK2_PLAN.md` §8's last non-deferred `[CALIBRATE]` row and
`WEEK2_EXECUTION.md` Block C's carried-forward item: `loadgen/scheduler.py`'s
5ms spin margin was Windows-tuned, and §8 forbade shipping it onto the Linux
vLLM runs unverified.

Harness: `scripts/calibrate_scheduler_spin.py`. Decision write-up:
`BENCHMARKS.md`.

## Run conditions

Dedicated CPU-only **`e2-standard-4`, `us-central1-a`**, Ubuntu 22.04,
kernel 6.8.0-1066-gcp, Python 3.10.12, httpx 0.28.1. Created and destroyed for
this measurement; deletion verified. Not CI — a shared runner would measure the
neighbour's contention, and the question is platform-specific
(`WEEK2_EXECUTION.md` Block 0 makes the same point for the mock's spin).

One variable: `spin_margin_s ∈ {0.0, 0.005}`. Everything else held identical —
same machine, seed (20260818), Poisson schedule construction, corpus, client,
concurrency cap (3000), mock config (`slow`), 5 repeats × 30s per cell.

## Files

| File | What it is |
|---|---|
| `scheduler_spin_linux_ab.json` | **The calibration.** Mock in a **separate process** over loopback, `ulimit -n 65535`. |
| `scheduler_spin_linux_ab_inprocess_mock.json` | First pass, kept as history. Mock in a **thread of the driver process** and `ulimit -n` left at the default 1024. Superseded — see below. |
| `rps_knee_diagnostic.txt` | 20/40/60/80 RPS sweep with client + mock CPU sampling and reconstructed peak concurrency. Explains the 80-RPS numbers. |

> **Reading `scheduler_spin_linux_ab.json`'s `method.mock_spin_margin_s: 0.02`:**
> that field records the **driver process's** `mock.timing.SPIN_MARGIN_S`, which
> is meaningless in the external-process topology — the mock ran in its own
> process with its spin set to 0. The field is left as the harness emitted it
> rather than hand-edited; this note is the correction.

## Two methodology traps, both real, both fixed between passes

1. **In-process mock ⇒ shared GIL.** With the mock in a thread of the driver,
   its request handling and the scheduler's send loop compete for one
   interpreter. At 80 RPS that dominated everything. Fixed by running the mock
   as a separate process over loopback — which is also the real topology, since
   the GPU session drives vLLM in its own process and venv.
2. **`ulimit -n` applies to the calibration too.** The first 80-RPS attempt hit
   `OSError: [Errno 24] Too many open files` — §3.3's documented precondition,
   from the same default soft limit of 1024, in a harness that had not raised
   it. `remote_loadgen.sh` enforces the raise for the GPU run; the calibration
   runner now does the same. Any harness driving at Stage A rates needs it.

## Result

| RPS | spin | lag p50 | p95 | p99 | max | offered | achieved | divergence | early sends |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 | **0ms** | 0.910 | 2.016 | 2.667 | 5.741 | 20 | 20.97 | +4.83% | **0** |
| 20 | 5ms | 0.081 | 0.548 | 1.384 | 36.559 | 20 | 20.97 | +4.83% | **0** |
| 80 | **0ms** | 745.884 | 4448.784 | 5030.837 | 6293.291 | 80 | 79.87 | −0.17% | **0** |
| 80 | 5ms | 733.896 | 4398.058 | 5174.818 | 6082.602 | 80 | 79.87 | −0.17% | **0** |

*(lag in ms, averaged over 5 runs per cell; `max` is the worst single
observation across all 5.)*

**The 80-RPS row measures the mock, not the scheduler.** `rps_knee_diagnostic.txt`
shows the mock holding a flat 0.911s response with concurrency scaling linearly
through 60 RPS, then collapsing at 80 — response time 12×, peak concurrency 78 →
1323 — while client CPU never exceeds ~25% of one core. The lag is downstream of
1323 concurrent open streams, and `MOCK_TRUST_BOUNDARY.md` explicitly does not
trust the mock for saturation behaviour or latency under concurrency. Both arms
are affected identically, so the A/B comparison survives; the absolute 80-RPS
numbers do not transfer to real vLLM.

## Decision: `LINUX_SPIN_MARGIN_S = 0.0`, `WINDOWS_SPIN_MARGIN_S = 0.005`

- **The spin's only justification does not apply on Linux.** It exists to stop a
  send firing *before* its scheduled offset (§4 V5: "late allowed, early
  impossible"). **Zero early sends were observed at 0ms in every cell of every
  pass** — including the saturated ones. On Windows early wakeup does occur, so
  Windows keeps its 5ms.
- **Where the measurement is clean it buys nothing that matters.** At 20 RPS the
  5ms arm lands closer to target in the body (p50 0.08ms vs 0.91ms), but both are
  negligible against a 50ms inter-arrival gap, and the 5ms arm's *worst* case is
  6× worse (36.6ms vs 5.7ms). At 80 RPS the arms are indistinguishable.
- **It has a real cost in this project's topology.** Week 2 drives the loadgen
  **on the GPU instance** (`WEEK2_GPU_SESSION_2_PLAN.md`), so a 5ms busy-wait
  per send burns ~40% of a core at 80 RPS *on the same box as vLLM* — spending
  CPU that the thing being measured needs, for no measured benefit.
- Consistent with Block 0's independent finding that the mock's busy-wait is a
  Windows-only fix (`MOCK_TRUST_BOUNDARY.md`).

Override per host without editing tracked source (which `bootstrap`'s dirty-tree
guard would reject): `--spin-margin-s`, or `LOADGEN_SPIN_MARGIN_S`. Every point
record carries `provenance.spin_margin_s` and `provenance.platform`.

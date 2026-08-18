# Mock Trust Boundary + Loadgen Request-Pattern Logging (LOCKED)

Scope: what the mock is and isn't trusted for under concurrency, and the
minimal generator-side logging needed so Week 2 can validate load-generator
**request patterns** without trusting the mock's response timing. Does not
touch the router, percentile logic, or the mock's timing fix.

---

## 1. The trust boundary (Option 0)

**Trusted — sequential fidelity.** One stream at a time, the mock's delivered
timing matches configured timing. Everything Week 1 asks of it (deterministic
measurement tests, router build, sequential overhead comparison) lives here
and is safe.

**Not trusted — latency under concurrent load.** The busy-wait spin contends
for the single event loop, so once streams overlap, delivered timing drifts —
and drifts worse as load rises. Any latency number the mock produces under
concurrency is suspect.

**Consequence for Week 2.** When the (concurrent) load generators run against
the mock during development, trust the mock to validate **request patterns**
(what the generator *sends*), not **latency** (how fast responses come back).
All reported latency numbers in this project come from real vLLM on GPU, not
the mock. This boundary doesn't shrink the mock below its planned role — the
plan already sends every reported latency number to the GPU.

**Open question, deferred to Week 2 (not part of this lock):** whether the
busy-wait is even needed on Linux. The spin exists only to correct Windows
`asyncio.sleep()` overshoot; on the Linux/GCP target the problem may not
arise. Re-run the sequential noise calibration on Linux without the busy-wait
as an early Week-2 check.

**Status update (2026-08-15) — STILL OPEN, and one specific run will be
tempting to mistake for having closed it.** The router eval's first CI run on
`ubuntu-latest` delivered configured timing far more accurately than the
Windows dev machine (direct TTFT p50 ~102.9ms against a configured 100ms,
versus ~113-115ms here; BENCHMARKS.md, "CI run (ubuntu-latest)"). Early
evidence, therefore: the busy-wait is **probably not** needed on Linux.

That is not the check, and the number must not be quoted as if it were:

- **The spin was ENABLED for that run.** ~3ms measures how well the mock
  delivers its configured timing on Linux *with* `precise_sleep` working — not
  how `asyncio.sleep` behaves unaided, which is the actual question. No
  spin-enabled run, however clean, can answer it.
- Because the spin corrected overshoot on both platforms, the ~3ms vs ~13-15ms
  gap is mostly **structural** latency (transport, event-loop scheduling), a
  different quantity from the ~10-30ms bare-`asyncio.sleep()` overshoot the
  busy-wait was built to correct.

**The disabling test is still required.** It closes only on an A/B on Linux:
the sequential noise calibration run with the spin disabled
(`precise_sleep(d, spin_margin_s=0)` degenerates to a bare `asyncio.sleep(d)`)
and again with it enabled, both compared against the *configured* values. Until
that A/B exists, the busy-wait stays and this question stays open.

**Status update (2026-08-16) — CLOSED. The A/B ran; the spin is not needed on
Linux.** Dedicated `e2-standard-2` GCP VM (`us-central1-a`), same
`calibrate_noise_floor.py` harness, 200 runs each, `fast` config, spin
toggled via `mock.timing.SPIN_MARGIN_S` (see `mock/timing.py`,
`--spin-margin-s` flag) so both runs share everything except the one
variable:

| | spin disabled (bare `asyncio.sleep`) | spin enabled (default 20ms margin) |
|---|---|---|
| TTFT bias vs configured | +5.97ms | +5.26ms |
| TTFT max abs deviation | 6.76ms | 5.75ms |
| TPOT bias vs configured | +0.59ms | +0.23ms |
| TPOT max abs deviation | 0.66ms | 0.28ms |

Full results: `benchmarks/calibration/noise_floor/noise_floor_fast_linux_nospin.json`,
`benchmarks/calibration/noise_floor/noise_floor_fast_linux_spin.json`.

**Reading it:** the spin buys under 1ms on Linux (5.97ms -> 5.26ms TTFT bias),
nothing like the ~10-30ms bare-`asyncio.sleep()` overshoot it corrects on
Windows (`mock/timing.py`'s own calibration comment). The ~5-6ms that
*remains* even with the spin enabled is the same structural
transport/event-loop latency the CI ~3ms number reflected (§ above) — a
different quantity from sleep overshoot, and one the spin was never meant to
fix. **Conclusion: the busy-wait is a Windows-only fix.** It stays in the
code (harmless on Linux, required on Windows, and this project's dev/CI
matrix includes both), but Linux GPU-session numbers do not depend on it —
Week 2's real-vLLM measurements would be trustworthy on Linux even if the
spin were removed entirely.

---

## 2. What "request patterns" means

Three generator-side properties, all measurable from what the generator
*sends* — independent of the mock's response timing:

- **Arrival distribution** — *when* requests are fired (send timestamps).
  Steady / Poisson / adversarial are validated from the gaps between sends.
- **Concurrency level** — *how many* requests are in flight at once.
  Validated by counting overlapping open-intervals.
- **Corpus sampling** — *which* prompts are sent (content/length distribution
  drawn from ShareGPT). Validated from the prompt draws themselves.

The test all three share: they depend only on what the generator emits, never
on how fast the mock responds. That's why the mock's concurrency bug can't
corrupt them.

---

## 3. Current state (from codebase trace)

None of the three properties is reconstructable from what's logged today.
The metrics path records only pooled TTFT/TPOT arrays + counts + config per
**run**; `t0` is computed and discarded, no per-request start/end times, no
prompt data, and — critically — **no per-request identity**. Nothing collides
under concurrency today only because nothing is logged per in-flight request
at all, which also means concurrent runs leave no artifact to validate.

---

## 4. The lock — five fields in a separate loadgen log

A new per-request raw log, emitted by the Week 2 loadgen (`loadgen/`), **one
row per request**, kept fully separate from `metrics/` (`RequestSample` /
`RunMetrics` stay focused on TTFT/TPOT). All three distributions are computed
offline from these raw columns — never pre-aggregated.

| Field | Meaning | Captured |
|---|---|---|
| `request_id` | Per-run unique id (int or UUID), assigned before send. **Prerequisite** — without it, concurrent requests' records can't be told apart. | At fire decision, generator-side. |
| `send_time` | Generator's clock read immediately before `.send()`. Serves both arrival distribution and one endpoint of the concurrency interval. | Where `t0` is already captured — retained instead of discarded. |
| `close_time` | Generator-side timestamp taken **immediately after the `async with client.stream(...)` block exits**. Used **only** to count overlapping requests. **Not a latency number** — never trust it as response-completion timing. | At stream-block exit, generator-side. |
| `prompt_id` | Index/key of the ShareGPT prompt drawn. | At prompt selection, before building the body. |
| `prompt_len` | **Char count** for now (cheap, generator-pure). **Token count is a Week-3 revisit** — needed for KV-cache math, requires a tokenizer; do not build yet. | At prompt selection. |

### Why this is faithful to the boundary
- **Generator-side only:** every field is a fact about what the generator
  sent or how it scheduled — none require the mock's timing to be accurate.
- **Separate artifact:** keeps generator-sent data physically apart from
  mock-response-timing data, enforcing the trust boundary in the code layout.
- **Raw, not pre-computed:** arrival / concurrency / corpus distributions are
  derived offline from these columns, consistent with the existing
  "log raw samples, compute stats separately" stance.

---

## 5. The three things locked

1. **Five fields, separate loadgen log** — `request_id`, `send_time`,
   `close_time`, `prompt_id`, `prompt_len`; never on the metrics path.
2. **`close_time` pinned** — generator-side timestamp after the stream block
   exits, for overlap counting only, never a latency.
3. **`prompt_len` = char count now**, token count flagged as a Week-3 revisit.

Nothing here blocks the router. This is a Week-2 logging plan; the artifact is
built when `loadgen/` is implemented.

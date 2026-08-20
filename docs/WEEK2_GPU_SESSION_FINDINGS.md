# Week 2 — GPU session #1 findings (2026-08-18)

> **STATUS: EVIDENCE — DOES NOT GOVERN EXECUTION**
>
> Role: the permanent interpretation of GPU session #1.
>
> This document records *why* something is believed. It does not govern
> execution, and any command text below is a record of what was run at the
> time, not an instruction to run it now.
> Current execution instructions: `WEEK2_GPU_SESSION_2_PLAN.md`.
> Index: `WEEK2_DOC_INDEX.md`.

The permanent record of the first real Week 2 GPU session: what it set out to
measure, what it falsified, which of its conclusions are trusted, and which must
never be published.

**Headline outcome, stated once and unambiguously:**

> **The session produced no final breach RPS.** It ran the experiment
> `WEEK2_PLAN.md` specified and, in doing so, falsified three of that
> experiment's statistical assumptions. The result is a redesign, not a number.

This is not a failure report in the sense of wasted money. The session cost
~$1.85 and ~1h50m, and it bought the one thing an offline analysis could never
have produced: the discovery that the design could not support the claim it was
built to make. Everything in §3 below is a finding that only real GPU data could
surface.

- **Session artifacts** (diagnostic, hashed, never rewritten):
  `benchmarks/evidence/week2/first_session/`
- **Calibration built from them:**
  `benchmarks/calibration/week2_redesign/R3_EVIDENCE_PACKAGE.md`
- **What the findings changed in the plan:** `WEEK2_PLAN.md` §10

---

## 1. Setup

| Setting | Value |
|---|---|
| Instance | 1× L4 Spot, `g2-standard-8`, `us-central1-a` |
| Server | vLLM 0.27.1, `meta-llama/Llama-3.2-3B-Instruct` |
| `max_model_len` | 20000 |
| `enforce_eager` | 0 (non-eager) |
| **`enable_prefix_caching`** | **True** (vLLM default — never a decision; see §3.6) |
| **`enable_chunked_prefill`** | **True** (vLLM default) |
| Output policy | `max_tokens=512` |
| Client timeout | 60s |
| Concurrency cap | 3000 |
| Network path | loopback, loadgen on-instance |
| Corpus | `corpus/baseline_prompts.jsonl`, 5000 prompts, `sha256=f7ec37d3…` |
| Arrival process | seeded Poisson, one master seed (20260817) for every point |
| Warmup / window | 10s placeholder / 120s |

Driven: Stage A at 2, 5, 10, 20, 30, 40 RPS; then an unloaded floor at
concurrency 1; then 1.0 and 1.5 RPS, added mid-session because the sweep had no
clearly-under-SLO anchor. 60 and 80 RPS were never driven — by then the
timeout-censoring finding (§3.4) had made higher points pointless.

Teardown was run and independently verified; 22 artifacts were SHA-256 compared
against their local copies before the instance was deleted (0 missing, 0
mismatched).

---

## 2. Trusted findings

These survive the redesign and may be cited.

1. **The corpus-drift guard worked, and caught a real portability defect.**
   Stage A initially refused with `corpus drift detected`. Cause: Windows had
   `core.autocrlf=true` and the repo lacked `.gitattributes` protection for the
   corpus JSONL, so the committed blob was LF while the working tree that
   generated the frozen schedules was CRLF. The prompt *values* were identical —
   verified three ways (5000 = 5000 parsed rows, byte-identical regenerated
   `entries`, only the stored `corpus_sha256` differed). The guard correctly
   refused a frozen workload that was not portable. Fixed by `.gitattributes`.
2. **vLLM ran as intended in the target environment**, config-only swap held, no
   code change was needed.
3. **Open-loop low-load driving worked**: 0 shed and 0 errors at 1.5, 2 and 5
   RPS, with the driver tracking its materialized schedules.
4. **Prompt length dominates intrinsic TTFT.** At concurrency 1, prompt length
   alone explains **91%** of TTFT variance (`r = 0.953`, n = 248):
   `TTFT ≈ 76.8ms + 25.7ms per 1000 chars`.
5. **Concurrent load materially moves the TTFT tail.** Joining the 2-RPS point
   against the concurrency-1 floor on `prompt_id`, long prompts cost a median
   **1.18×** more under 2 RPS of load than unloaded.
6. **The instrument survived contact with reality.** Durable-on-produce writing,
   the raw-log/sidecar split, the schedule-provenance header and the artifact
   pull-and-verify step all did their jobs. The redesign changes the experiment,
   not the plumbing.

---

## 3. What the session falsified

### 3.1 Prompt-tail confound — a fixed duration makes the realized tail a function of λ

The plan's causal story was that feeding every RPS point the *same seeded
distribution* holds the prompt contribution constant while λ moves. It holds the
**population** constant. It does not hold the **realized empirical tail**
constant, and a small-sample p99 reads only the latter.

A fixed 120s window means request count scales with λ, so higher-λ points draw
more prompts and therefore more chances at the rare long ones:

| Schedule | Requests | prompt p50 | prompt p99 | max prompt | prompts >10k chars |
|---|---:|---:|---:|---:|---:|
| 1.0 RPS | ~116 | 129 | 6,890 | 8,049 | **0** |
| 1.5 RPS | ~182 | 129 | 8,049 | 14,960 | 1 |
| 2 RPS | ~248 | 129 | 11,327 | 16,781 | 4 |
| 5 RPS | ~643 | 130 | 10,034 | 16,781 | 7 |
| 10 RPS | ~1316 | 142 | 10,034 | 39,801 | **14** |

The consequence is a verdict that turns on a single draw. Restricting the 2-RPS
sample to a shared prompt-length ceiling — excluding essentially **one** extreme
prompt — moved p99 from ~552.9ms to ~434.8ms, **flipping the breach
classification**.

*Correct interpretation:* the 2-RPS classification is highly sensitive to the
realized long-prompt tail. The ~118ms delta is **not** a measurement of "prompt-
caused latency".

### 3.2 `n >= 100` is not a p99 reliability rule

The existing gate required ≥100 achieved post-warmup samples. That makes a p99
computable, not reliable. A nonparametric bootstrap over the session's own 2-RPS
TTFT array (n=225) measured the classification-flip rate against 500ms:

| candidate N | p99 median | 95% interval | flip rate |
|---:|---:|---|---:|
| 250 | 495.0ms | [366.0, 656.8] | **51.8%** |
| 1,000 | 552.9ms | [421.7, 574.8] | 22.1% |
| 2,500 | 552.9ms | [434.8, 574.8] | 8.0% |
| 4,000 | 552.9ms | [436.0, 574.8] | 3.0% |
| 7,500 | 552.9ms | [552.9, 574.8] | 0.6% |

At roughly the sample size it actually had, the near-boundary point flipped its
own verdict in **about half** of resamples.

*Caveat carried forward:* the bootstrap is a run-sizing diagnostic. It cannot
invent tail mass the source never observed, and concurrent latencies are not
iid — so it is a **lower bound** on real run-to-run variability, not an estimate
of it.

### 3.3 Percentile convention alone can flip the verdict

The same 225 post-warmup 2-RPS samples:

| method | p99 | verdict |
|---|---:|---|
| nearest-rank | 552.9ms | OVER |
| linear (numpy default) | 524.6ms | OVER |
| midpoint | 493.9ms | **UNDER** |
| lower | 434.8ms | **UNDER** |

Two conventions are already mixed inside the session's own artifacts: every
Stage A point record is linear (`metrics.compute.percentile`), while the unloaded
floor's committed record is a nearest-rank value, because the floor was produced
by a one-off on-instance script that is not in the repo. The percentile
definition was never a decision; it was inherited from whichever code ran.

### 3.4 A 60s client timeout censors every saturated point

| RPS | Rows | TTFT samples | Errors | Censoring |
|---:|---:|---:|---:|---:|
| 5 | 643 | 643 | 0 | 0% |
| 10 | 1316 | 876 | 440 | ~33% |
| 20 | 2597 | 772 | 1825 | ~70% |
| 30 | 3847 | 714 | 3133 | ~81% |

Reported p99 values clustered near 60s. That is not a latency plateau: slow
requests timed out and **left the sample**, so the percentile was computed over
survivors. The validity gate blessed these points anyway, because enough
*surviving* samples remained to clear `n ≥ 100` — `tail_valid` meant "enough
survivors", which is exactly the wrong question.

*These points remain valid evidence of severe saturation, and nothing else.*

### 3.5 Offered-vs-achieved conflated two different quantities

At 2 RPS: target λ = 2.0, achieved 1.875, reported divergence −6.25%, point
`flagged`. But the materialized finite-Poisson schedule itself contained 248
arrivals over 130s — fewer than `λ × duration`, as a finite Poisson realization
should. The driver delivered its schedule faithfully; the gate compared it
against the nominal rate instead. Both low-RPS points were flagged for a
stochastic property of their own frozen schedules.

Three quantities need separating: nominal λ, the materialized schedule, and
actual sends.

### 3.6 Prefix caching made run order an experimental variable

*Discovered offline during R2, not during the session.*

vLLM ran with `enable_prefix_caching=True`. Every Stage A schedule used one
master seed, so each shorter schedule is a strict **prefix** of the longer ones —
every point replays the prompts of every shorter point. Run order therefore
became a hidden variable.

Joining each loaded point against the concurrency-1 floor on `prompt_id`:

| point | prompts ≥ q95 in common | median loaded/unloaded TTFT | reading |
|---|---:|---:|---|
| 2 RPS | 12 | **1.18×** | consistent — load costs something |
| 1.5 RPS | 7 | **0.46×** | impossible — load cannot speed up prefill |

The worked case:

```text
prompt 458 (14,960 chars)
  concurrency 1, no load     523.3ms
  under 1.5 RPS of load      103.9ms   (0.20x)
```

The 1.5-RPS point was driven **last**, after the sweep and after the floor had
just re-loaded those exact prompts; vLLM's reported prefix-cache hit rate climbs
from 17.4% to 27.4% across that single 2.5-minute run.

**Consequences:**

- The 1.5-RPS point is **cache-confounded diagnostic evidence** and is *not* a
  clean under-SLO anchor. Its 113.6ms p99 is an artifact of run order.
- The old 1.5 / 2 / 5 RPS sequence is **not an authoritative bracket** for the
  redesigned experiment.
- The 2-RPS array remains the conservative driver of run sizing — it ran early
  and its loaded/unloaded ratio points the right way.

### 3.7 The unloaded floor is cache-influenced

The ~402.3ms floor was measured at concurrency 1 over the 2-RPS prompt set —
**after** the Stage A sweep had already served those prompts, with caching
enabled. Audited in
`benchmarks/calibration/week2_redesign/unloaded_floor_cache_audit.json`:

- **Verdict: `CACHE_INFLUENCED_DIAGNOSTIC`.** Prior exposure is documented, so a
  cold cache cannot be *proven*.
- Supporting evidence that it nonetheless *behaves* cold: 12 prompts were served
  twice within the floor run itself, and the one discriminating pair shows a
  first serving paying full cold prefill (197.7ms for 4,992 chars, 0.96× the
  cold-prefill prediction) and its immediate replay collapsing to 83.9ms. So the
  sweep's earlier exposure had been evicted, while the cache was live for
  immediate replays.
- None of the top 10 TTFT samples — the ones that set the floor's p99 — is a
  repeat serving.

**402.3ms may no longer be cited as *the* unloaded floor.** A cache-influenced
floor is biased **low**, so the true cold floor is at or above it and may sit
closer to the SLO. The thesis-level conclusion — that 500ms is achievable for
this corpus/model without contention — is **weakened, not overturned**. A new
clean floor is collected next session with caching disabled.

### 3.8 Fractional-RPS artifact names broke the completeness checker

`pull_artifacts.sh` recovered a point tag with `name.split(".")[0]`, reading
`poisson_rps1.5.raw_log.jsonl` as the point `poisson_rps1` — whose sidecar and
metrics did not exist, because that point did not exist. It reported a healthy
fractional point as unusable, on the meter, while the instance was still up. The
1.5-RPS artifacts were intact (182/182 requests, 0 errors). Fixed in
`metrics/artifacts.py`; Stage B is entirely fractional, so this was a
precondition of the next session.

---

## 4. Do not publish

Never claim, from this session:

- `breach RPS = 2` — or any breach RPS at all;
- that 1.5 RPS is a clean under-SLO point;
- `p99 at 10/20/30 RPS ≈ 60s` as ordinary measured latency;
- the capped-prompt diagnostic as a corrected baseline;
- the ~118ms cap-diagnostic delta as "prompt-caused latency";
- 402.3ms as the definitive unloaded floor;
- that ≥100 samples suffices for a p99;
- any fine breach location.

---

## 5. What the findings changed

Recorded in full in `WEEK2_PLAN.md` §10, with the explicit list of locks that did
**not** change in §10.9. In brief:

| Finding | Change |
|---|---|
| §3.1 prompt-tail confound | Headline uses a frozen stratified canonical multiset (`k`=6, `L`=q99, `N`=4,000); natural-random becomes the secondary workload |
| §3.1 fixed window | Headline basis is exactly `N` post-warmup **scheduled** arrivals; duration is the Poisson realization's outcome |
| §3.2 `n >= 100` | Replaced by the R3 evidence policy and repeat-level classification; `N_max` = 5,000 with interval-valued fallback |
| §3.3 percentile ambiguity | Nearest-rank locked, one shared implementation, version in provenance |
| §3.4 timeout censoring | Four point states; >5% censoring ⇒ `CENSORED` with ordinary p99 suppressed |
| §3.5 offered-vs-achieved | Nominal λ / materialized schedule / actual sends recorded separately; fidelity measured against the materialized schedule |
| §3.6 prefix caching | Disabled for the controlled headline, effective state verified and preflight-enforced |
| §3.7 floor | Reclassified as cache-influenced; a new clean floor is collected next session |
| §3.8 fractional RPS | Suffix-stripping tag recovery, with a control that bites |

---

## 6. Why this record exists

The artifacts are hashed and preserved, but bytes do not carry interpretation. A
future reader — including a future agent — finding
`poisson_rps2.metrics.json` with `breach_500ms: true` and `tail_valid: true`
would have every reason to treat it as the answer. It is not, and the reasons are
not visible from inside the file. This document is what stands between that
record and a published claim built on it.

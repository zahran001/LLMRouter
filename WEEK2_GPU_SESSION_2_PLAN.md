# Week 2 — GPU session #2 runbook

> **STATUS: EXECUTABLE — GPU SESSION #2**
>
> Role: **the** GPU session #2 runbook. This is the one file to keep open while
> the meter is running.
>
> Current document authority:
> - experiment semantics: `WEEK2_PLAN.md`
> - execution / gating: `WEEK2_EXECUTION.md`
> - GPU commands: **this document**
> - machine-readable policy: `benchmarks/workloads/week2_headline/repeat_policy.json`
>
> If these appear to conflict: **HALT and surface the conflict. Do not reconcile
> silently.** Index: `WEEK2_DOC_INDEX.md`.
>
> **No instance may be created until Hard Stop R-DOC and Hard Stop R-PREGPU have
> both been passed by a human.** This document being executable describes what it
> is *for*, not that it is *authorized to run right now*.

The first session spent its money discovering that its own experimental design
was unsound. This one executes an experiment that is already fully specified.
Everything discoverable offline has been discovered; the meter is for
collecting raw artifacts, not for deciding anything.

Rationale lives elsewhere and this document links out to it, but **nothing
below requires you to go read it mid-session**:

- Locks and semantics: `WEEK2_PLAN.md` §10 (supersessions), §11 (the six locks)
- Why the redesign exists: `docs/WEEK2_GPU_SESSION_FINDINGS.md`
- Calibration: `benchmarks/calibration/week2_redesign/R3_EVIDENCE_PACKAGE.md`
- Environment gotchas: `GPU_SESSION_NOTES.md`

---

## 0. Identity — what is being run

Record these in the session log. Any mismatch is a STOP.

### Benchmark identity

| Field | Value |
|---|---|
| Benchmark commit SHA | *(filled in at R-PREGPU; the session is pinned to it)* |
| Canonical workload | `benchmarks/workloads/week2_headline/canonical_v1.json` |
| Workload scheme version | `canonical-workload-v1` |
| **Membership id** | `a49ecdd8071920303f240fcf0b8da42dbbc66da593ae88e3c07aa246c4b5aa7b` |
| Corpus SHA-256 | `f7ec37d33bc2f53c4468a39c52b792406dbb383de8a38cfbc207c8cf59af6630` (5,000 prompts) |
| Schedule scheme version | `headline-schedule-v2` |
| RNG scheme version | `headline-rng-v1` |
| Repeat policy | `repeat_policy.json`, `"status": "LOCKED"`, `policy_version` 3 (bumped 2026-08-22: `OVER_CENSORED` state + `sustained_scout` block, D-ATTEMPT2-1) |
| Percentile method | **nearest-rank**, one shared implementation (`metrics/percentile.py`) |
| Scout workload | `benchmarks/workloads/week2_scout/canonical_v1.json`, membership id `e9470f8f…` — **separately namespaced so it can never be mistaken for headline evidence** |

The canonical multiset holds the corpus's natural shape exactly, including the
44,445-char prompt (`prompt_id 790`) that the first session never drew.

### Server configuration

| Field | Value |
|---|---|
| Model | `meta-llama/Llama-3.2-3B-Instruct` |
| vLLM | 0.27.1 lineage, installed by `setup_and_launch_vllm.sh` |
| `--max-model-len` | **20000** — backed by exact tokenizer evidence: 10,482 max input + 512 output + 1,099 margin = 12,093 ≤ 20,000 **PASS** |
| Output `max_tokens` | **512** (locked policy) |
| Prefix caching | **DISABLED** — `DISABLE_PREFIX_CACHING=1` → `--no-enable-prefix-caching` |
| `--enforce-eager` | `ENFORCE_EAGER` knob. Week 1's proven config is eager; session #1's runbook (removed 2026-08-20; in git history at 39ed3f1) said "try non-eager first"; that is **not** binding on this session. Whichever mode the server comes up in, **every point in the session must run the same mode** — the launch script echoes the resolved mode; record it |
| Sampler | `VLLM_USE_FLASHINFER_SAMPLER=0`, flashinfer uninstalled (three real crashes, `GPU_SESSION_NOTES.md`) |
| Network topology | **on-instance loopback**, `http://127.0.0.1:8000`. Never the SSH tunnel — it folds WAN RTT into every TTFT and multiplexes 3000 streams down one TCP connection |

### Client configuration

| Field | Value |
|---|---|
| Load generator | on-instance, from the pinned repo clone |
| Concurrency cap | **3000** |
| Linux scheduler spin | **0 ms** (calibrated, `benchmarks/calibration/scheduler_spin/`) |
| fd limit | `ulimit -n 65535` (asserted by `remote_loadgen.sh env-check`) |
| Client timeout | 60 s — censoring, not an error; see §5 |
| Warmup boundary | **60 s, frozen into every schedule** |
| `EXTRA_BODY` | Unset unless the session decides otherwise. It is merged into every request body and is **not** recorded in the schedule, so if it is set at all it must be set identically for the floor, scout, headline, steady and adversarial commands — otherwise the floor stops being the headline curve's floor. Every point record logs the value it ran with |
| `LOADGEN_MODEL` | Unset; defaults to the pinned model above. Same rule: identical across every stage or the stages are not comparable |

---

## 1. Preflight (before the meter starts)

Standing Hard Stop 4 checklist plus the redesign items. Full evidence:
`WEEK2_GPU_SESSION_2_PREFLIGHT.md`.

| Item | Evidence |
|---|---|
| R-DOC passed | Human verdict recorded |
| R-PREGPU passed | Human verdict recorded |
| Working tree clean, HEAD pushed | `run_on_instance.sh bootstrap` refuses otherwise |
| Canonical workload frozen | `canonical_v1.json`, membership `a49ecdd8…` |
| Capacity proven | `tokenizer_capacity_report.json` — PASS |
| Schedules committed | `benchmarks/schedules/week2_redesign/` — **32**: 15 headline + 6 scout + 5 natural-random + 5 steady + 1 adversarial |
| Every scenario frozen | Nothing is generated on the meter (lock 6A; `SECONDARY_SCENARIOS_MANIFEST.json`) |
| Unloaded floor executable | `run_on_instance.sh floor` |
| Repeat policy signed off | `repeat_policy.json` — **`LOCKED`** |
| All controls bite | `scripts/show_control_bites.py`, `scripts/show_doc_control_bites.py`, `tests/redesign/` |
| Regression suites green | see `WEEK2_GPU_SESSION_2_PREFLIGHT.md` |
| Quota / budget ladder | $10 canary / $75 / $135 / $150 hard line |
| Teardown dry-run | `DRY_RUN=1 bash scripts/gpu_session/teardown_week2.sh` |

---

## 2. On-instance sequence

```
 1. stand up 1x L4 spot, launch vLLM                        ~15 min
 2. verify_prefix_cache_disabled.py            GATE          ~3 min
 3. Tier A: clean unloaded floor over the canonical set     ~10 min
 4. Tier A: scout sweep                                     ~20 min
      -- HARD STOP GPU-1: HUMAN READ --
 5. Tier B: confirmation sweep, repeat-major            2.8-5.4 h
 6. Secondary: natural-random (~50 min), then steady (~23 min)
 7. Adversarial scenario (LAST)                            ~10 min
 8. pull artifacts, verify, teardown                        ~15 min
```

### Commands

```bash
# local, once
bash scripts/gpu_session/create_instance.sh

# step 1b -- launch vLLM. `setup_and_launch_vllm.sh` runs `vllm serve` in the
# FOREGROUND, so it must not be run through a plain ssh --command: the server
# would die with the connection. Copy it up and run it under nohup, then wait
# for /health.
gcloud compute scp scripts/gpu_session/setup_and_launch_vllm.sh \
    llmrouter-vllm-l4-week2:~/ --zone=us-central1-a
gcloud compute ssh llmrouter-vllm-l4-week2 --zone=us-central1-a \
    --command="nohup bash ~/setup_and_launch_vllm.sh > ~/vllm.log 2>&1 &"
# watch it come up (first launch downloads the model; several minutes)
gcloud compute ssh llmrouter-vllm-l4-week2 --zone=us-central1-a \
    --command="tail -f ~/vllm.log"

bash scripts/gpu_session/run_on_instance.sh bootstrap     # pins the instance to THIS commit
bash scripts/gpu_session/run_on_instance.sh check         # deps, fd limit, GPU, vLLM health

# step 2 -- the gate. No point of any kind may run before this passes.
bash scripts/gpu_session/run_on_instance.sh verify-cache

# step 3 -- the unloaded floor: every canonical prompt once, concurrency 1,
# sequential. Not an RPS point; the floor is defined by the absence of queueing.
SESSION_TAG=floor bash scripts/gpu_session/run_on_instance.sh floor

# step 4 -- scout (Tier A), one schedule at a time
SESSION_TAG=scout bash scripts/gpu_session/run_on_instance.sh scout \
    benchmarks/schedules/week2_redesign/scout/headline_r1_rps1.schedule.json

# step 5 -- Tier B, repeat-major, drain-gated, three lambdas
SESSION_TAG=headline REPEAT_IDS='1 2 3' \
    bash scripts/gpu_session/run_on_instance.sh headline 1.5 2 2.5

# step 6 -- secondary: natural-random, then steady. One schedule at a time.
SESSION_TAG=secondary bash scripts/gpu_session/run_on_instance.sh secondary \
    benchmarks/schedules/week2_redesign/secondary_natural/secondary_rps2.schedule.json
SESSION_TAG=steady bash scripts/gpu_session/run_on_instance.sh steady \
    benchmarks/schedules/week2_redesign/secondary_steady/secondary_steady_rps2.schedule.json

# step 7 -- adversarial, LAST
SESSION_TAG=adversarial bash scripts/gpu_session/run_on_instance.sh adversarial \
    benchmarks/schedules/week2_redesign/adversarial/adversarial_rps2.schedule.json

# pull after EVERY repeat, not only at the end. `pull_artifacts.sh` pulls ONE
# tag, so each stage needs its own invocation -- and SESSION_TAG has no useful
# default here (it falls back to session #1's `stage_a`).
for tag in floor scout headline secondary steady adversarial; do
    SESSION_TAG=$tag bash scripts/gpu_session/pull_artifacts.sh
done

# the prefix-cache verdict lives outside the artifact root; §11 requires it
gcloud compute scp \
    llmrouter-vllm-l4-week2:~/LLMRouter/benchmarks/runs/preflight/prefix_cache_verdict.json \
    benchmarks/runs/preflight/ --zone=us-central1-a
# and the launch log
gcloud compute scp llmrouter-vllm-l4-week2:~/vllm.log benchmarks/runs/ \
    --zone=us-central1-a

# teardown -- the Week 2 wrapper, never bare teardown.sh
bash scripts/gpu_session/teardown_week2.sh
```

> ### The commands above show ONE point per stage; several stages have more
>
> | Stage | Points to drive | Where the list is |
> |---|---|---|
> | scout | 4 — λ 1, 2, 4, 8 (0.5 / 16 only if lock 5A fires) | §3 |
> | headline | 3 λ × 3 repeats, one `headline` invocation per repeat | §5 |
> | secondary | 5 — `secondary_rps{1.5,2,2.5,3,4}.schedule.json` | §8 |
> | steady | 5 — `secondary_steady_rps{1.5,2,2.5,3,4}.schedule.json` | §8 |
> | adversarial | 1 | §8 |
>
> **Tier B is one blocking invocation per repeat, not one for all three.**
> `REPEAT_IDS='1 2 3'` runs all three inside a single `ssh --command` that
> blocks for up to 5.4 h, which makes "pull after every repeat" impossible.
> Drive them separately:
>
> ```bash
> for r in 1 2 3; do
>     SESSION_TAG=headline REPEAT_IDS="$r" \
>         bash scripts/gpu_session/run_on_instance.sh headline 1.5 2 2.5
>     SESSION_TAG=headline bash scripts/gpu_session/pull_artifacts.sh
> done
> ```
>
> Each repeat still drains between λ points, and the drain gate still refuses
> to start a repeat while the server has work in flight.

> ### Every scenario is validated against the artifact, not its directory
>
> `scout`, `steady`, `secondary` and `adversarial` each check the schedule's own
> provenance before driving it (`scripts/gpu_session/scenario_contract.py`) and
> refuse a schedule generated for a different scenario. This matters most for
> the pair nothing else separates: `headline/headline_r1_rps2.schedule.json` and
> `scout/headline_r1_rps2.schedule.json` have the same filename, the same
> `headline-schedule-v2` scheme and the same `workload_class` — because a scout
> point genuinely is a controlled Poisson draw. Only the canonical membership
> differs, and that is what the check reads.

> `run_on_instance.sh stage-a` drives the **superseded** session #1 fixed-duration
> sweep. It prompts for a typed confirmation. Never use it in this session.

> ### `scout` and `run` are different commands on purpose
>
> `scout` drives a frozen session #2 schedule through the **same** measurement
> path Tier B uses — the warmup boundary, expected N, delivery-fidelity
> denominator, censoring gate and membership all come off the schedule's own
> provenance, so a Tier A bracket is expressed in the units Tier B confirms in.
> The only difference is authority: the record is stamped
> `evidence_class: scout_diagnostic`, and `metrics/classification.py` refuses
> to aggregate it.
>
> `run` drives the **legacy v1** format — the secondary natural-random points
> in `secondary_natural/`. It refuses a session #2 schedule rather than reading
> it with the legacy 10s warmup placeholder, which is what it did until
> 2026-08-21.

### Step 2 — the gate that has no equivalent in session #1

`scripts/gpu_session/verify_prefix_cache_disabled.py` sends the three longest
canonical prompts twice each and compares TTFT. A replay at ≤0.75× its first
serving means the cache is live and the script **exits non-zero**. The CLI flag
is not accepted as evidence: it can be renamed between vLLM releases or applied
to a different server than the one being driven.

**If this gate fails, no headline point may be driven.** Relaunch and re-verify.
The headline driver enforces this independently — it refuses to start unless a
prefix-cache verdict artifact exists and says DISABLED.

### Step 3 — a real unloaded floor, over the real workload

Concurrency 1, all 4,000 canonical prompts, prefix caching off, stop at first
content token. ~4,000 × ~100 ms ≈ 7 min.

This replaces the first session's floor, which is classified
`CACHE_INFLUENCED_DIAGNOSTIC` and can no longer be cited. It is better than its
predecessor in kind, not just in cleanliness: the old floor sampled 248 prompts
from one schedule's realized draw, while this measures the **exact multiset the
headline curve uses**, so the intrinsic p99 it produces is the floor that curve
actually starts from rather than an estimate of it.

Projected (from the first session's fit — an order of magnitude, not a
prediction): unloaded p99 ≈ 370 ms, leaving ~130 ms of headroom to the SLO.

---

## 3. Tier A — diagnostic scouting

> **Diagnostic only. Scout points may locate the region. They may not produce
> an UNDER/OVER headline claim, and they never enter the classification.**

| Parameter | Value | Why |
|---|---|---|
| λ points | **1.0, 2.0, 4.0, 8.0** | Wide, cheap, brackets a crossing that has moved by an unknown amount |
| N per point | **500** | ~34% per-run flip rate — useless for a verdict, ample for locating a knee |
| Repeats | 1 | Scouting, not evidence |
| Warmup boundary | 60 s | Same as Tier B, so the transient read transfers |
| Drive time | 500/1 + 500/2 + 500/4 + 500/8 + 4×60 ≈ **20 min** | |

**The old bracket is not authoritative.** The first session's 1.5 RPS point is
prefix-cache confounded, so "1.5 under, 5 over" is not a bracket this experiment
inherits. Two things also moved the crossing since: prefix caching is now off
(every request pays full prefill where the first session got a 12–16% engine-wide
hit rate), and the workload composition changed. Both push the crossing **down**,
and neither is quantified — which is exactly why scouting is cheap and confirming
is expensive.

### Pre-authorized scout fallback (lock 5A)

```
if λ=1 is already OVER   →  add λ=0.5
if λ=8 is still UNDER    →  add λ=16
```

If the authorized fallback still fails to establish a useful bracket:

```
STOP. Return to human review.
```

**Do not invent additional λ values on the meter.** 0.5 and 16 are the only
pre-authorized additions — not 0.25, not 32.

> ### ✅ Closed: the fallback schedules are committed
>
> **Both fallback schedules exist and are frozen.** The committed scout family
> is λ ∈ {0.5, 1, 2, 4, 8, 16} — six schedules, one repeat each, N = 500
> post-warmup arrivals, 60s frozen boundary, all against the scout workload
> `e9470f8f…`. If the 5A fallback fires, drive the schedule; do not generate
> one.
>
> | λ | schedule | total / warmup / post | duration |
> |---|---|---|---|
> | 0.5 | `scout/headline_r1_rps0.5.schedule.json` | 530 / 30 / 500 | 1090.2s |
> | 16 | `scout/headline_r1_rps16.schedule.json` | 1458 / 958 / 500 | 88.9s |
>
> They are **staged, not spent**: neither runs unless Tier A's bracket fails at
> the end it covers — the same argument that justifies the 15-schedule headline
> family of which only 9 are driven. Cost if one does fire: 18 minutes of drive
> time at λ=0.5, 1.5 minutes at λ=16.
>
> This closes the gap recorded at the pre-GPU documentation cleanup, where the
> lock authorized a response the frozen artifacts could not deliver. **Building
> a new schedule while the meter runs stays forbidden**: `run_on_instance.sh
> bootstrap` refuses a dirty or unpushed tree, so it would cost a commit, a push
> and a **new benchmark SHA**. That rule has not changed — it is simply no
> longer reachable through the 5A fallback.

### What the human reads off Tier A

1. **The crossing region** — which λ are clearly under, which clearly over.
2. **The warmup transient** — TTFT vs wall-clock, to confirm the frozen 60 s
   boundary is sufficient.
3. **Sanity gates** — 0 shed, censoring 0%, `exact_n_honoured` true,
   `schedule_delivery_ok` true at every scout point.

---

## 4. ── HARD STOP GPU-1 — mid-session, human verdict ──

The only sanctioned mid-session judgment. It must answer exactly two questions:

```
1. Is the crossing neighbourhood bracketed?
2. Is the 60s warmup boundary sufficient?
```

**On (2) — the constraint that makes this a stop rather than a note.** The
resolved warmup must be **≤ 60 s**, the boundary the Tier B schedules were
frozen with. Exactly N arrivals were materialized at or after that boundary, so
filtering later would discard canonical arrivals and leave fewer than N measured
samples — `metrics/headline_point.py` refuses it rather than letting the count
quietly drop.

If the transient runs past 60 s:

```
STOP
pull artifacts
regenerate the Tier B schedules at a larger frozen boundary
re-run the required GPU-free checks
return to pre-GPU approval
```

That is a few seconds of offline work, not a session restart. **Do not resolve a
larger warmup afterward by re-filtering headline sidecars** — that was valid
under the superseded fixed-duration experiment and is invalid here (lock 4A).

---

## 5. Tier B — headline confirmation

| Parameter | Value |
|---|---|
| λ points | **3**, chosen from the Tier A bracket: the highest clearly-under, the lowest clearly-over, and one between |
| N per point | **4,000** (locked) |
| Repeats | **3** (`min_valid_repeats`) |
| Order | **repeat-major** |
| Separation | drain to in-flight = 0, then each repeat's own warmup. **No vLLM restart.** |

### Repeat-major ordering is a deliberate choice

```
r1: λ_low → λ_mid → λ_high      (drain between each)
r2: λ_low → λ_mid → λ_high
r3: λ_low → λ_mid → λ_high
```

Not λ-major. This is a spot-preemption hedge: a preemption at hour 4 leaves
**two complete sweeps** rather than three complete λ points and nothing at the
others. Two complete repeats is a reportable (if UNCERTAIN) result; a partial
λ-major sweep is not.

The drain probe reads the **server** (`vllm:num_requests_running` /
`num_requests_waiting`), not the client — a client-side in-flight count is
always zero by the time a point returns, so gating on it would be green forever.

### Drive time

| λ set | per repeat | × 3 repeats |
|---|---:|---:|
| 1.5 / 2.0 / 2.5 | 1.79 h | **5.37 h** |
| 2.0 / 2.5 / 3.0 | 1.28 h | 3.83 h |
| 2.5 / 3.0 / 4.0 | 1.00 h | 3.00 h |

The committed 15-schedule family covers λ ∈ {1.5, 2, 2.5, 3, 4} × 3 repeats;
only the three chosen λ are driven. The rest are staged, not spent.

**Every row above uses only λ that exist.** A previous row read `3.0 / 4.0 /
5.0`; there is no `headline_r*_rps5.schedule.json` and there never was. The
frozen family is the whole menu.

### Choosing the three λ — the rule, not a judgement

```
the three driven λ MUST come from {1.5, 2, 2.5, 3, 4}
    λ_low   the highest frozen λ that Tier A found clearly UNDER
    λ_high  the lowest  frozen λ that Tier A found clearly OVER
    λ_mid   the frozen λ between them
```

The scout ladder is λ ∈ {0.5, 1, 2, 4, 8, 16} and the headline family is
λ ∈ {1.5, 2, 2.5, 3, 4}. **These do not span the same range**, so a scout
bracket can land where no headline schedule exists — `(0.5, 1]`, `(4, 8]` and
`(8, 16]` have no headline point at either end, and `(1, 2]` has none at its
lower end. §3 argues the crossing has moved *down*, which makes the low-end
miss the likely one.

If the Tier A bracket does not contain at least two frozen headline λ:

```
STOP.
Pull the scout artifacts. Regenerate the headline family offline at
lambdas that bracket the observed crossing, re-run the GPU-free checks,
take a NEW benchmark SHA, and return to pre-GPU approval.
```

Do **not** pick the nearest frozen λ and drive it anyway: that measures a
different point from the one Tier A located, and the resulting bracket would
be an artifact of what happened to be committed. Generating a schedule
mid-session is forbidden for the reason §2 gives — `bootstrap` refuses a dirty
or unpushed tree, so it costs a commit, a push and a new benchmark SHA with
the meter running.

---

## 6. Point and repeat validity

Applied **offline, after teardown**, from `repeat_policy.json`.

```
min_valid_repeats      3
require_unanimous      true
majority_vote          false
n_per_run              4000
n_max                  5000
max_repeats_authorized 3
```

### Repeat states

```
UNDER      p99 TTFT < 500ms, all gates clean
OVER       p99 TTFT >= 500ms, all gates clean
CENSORED   >5% censoring -- ordinary p99 SUPPRESSED, never reported as latency
UNCERTAIN  cannot finalize
```

- A repeat that is `CENSORED`, missed exact-N, or failed delivery fidelity is
  **excluded, never pooled**.
- A boundary-determining point with **sub-5% censoring** and no completed
  tail-sensitivity review **cannot finalize** — it stays `UNCERTAIN`.

### Point classification (lock 1A)

```
UNDER + UNDER + UNDER  →  UNDER
OVER  + OVER  + OVER   →  OVER
any 2-1 split          →  UNCERTAIN
```

**No majority voting.** Near the SLO the split *is* the finding — the point is
unstable. Taking the majority would convert an honest UNCERTAIN into a verdict,
which is the failure the first session already made once.

### The stop condition, stated before the money is spent (lock 2B)

If the crossing is unresolved once `N = 4000` × 3 repeats is spent:

```
breach interval = (highest defensible UNDER λ, lowest defensible OVER λ]
```

and the session **stops**.

**`N = 5000` is NOT AUTHORIZED.** There is no escalation of any kind in this
session — `repeat_policy.json` records `escalation.authorized: false` and
`escalation.n5000.authorized: false`. An interval is a legitimate final answer,
not a failure: a ≤1% per-run flip rate would need N ≈ 7,500, which is above
`N_max = 5,000` and therefore unreachable with this corpus at all.

**Do not increase N on the meter.**

---

## 7. Spot preemption — the process-epoch rule (lock 3A)

D4 forbids restarting vLLM between repeats, so the repeatability estimate
measures arrival/queue variability rather than cold-process variance. A spot
preemption **forces** a restart. This was an open question in the proposed plan;
it is now closed.

**Headline repeats from different vLLM process epochs must not be combined into
one final classification family.**

```
epoch A:  repeat 1
          repeat 2
          PREEMPTED
                          →  epoch A becomes preserved DIAGNOSTIC evidence

epoch B:  repeat 1
          repeat 2
          repeat 3
                          →  the final classification family
```

A new process may **not** contribute only `repeat 3` to epoch A's family. If the
session dies after two complete repeats, the third is not addable — the fresh
process re-drives all three. The schedules are frozen, so this is exactly
reproducible; only meter time is lost.

Preempted **mid-repeat**: discard the partial repeat. Its artifacts stay as
diagnostics.

---

## 8. Secondary scenarios (lock 6A)

Week 2 is **not closed** until all four are accounted for. They are in scope,
not dropped:

| # | Scenario | Frozen input | Role |
|---|---|---|---|
| 1 | Controlled Poisson headline | `headline/` — 15 schedules, N=4000 | **Defines the breach.** Tier B above |
| 2 | Natural-random secondary | `secondary_natural/` — 5 schedules, 600s each | Does the knee survive unconstrained traffic? (~30–50 min) |
| 3 | Steady-arrival reference | `secondary_steady/` — 5 schedules, N=500, 60s boundary | Lower-variance legible reference (~23 min) |
| 4 | Adversarial long-context | `adversarial/` — 1 schedule, λ=2, 600s | Separate scenario — **runs LAST** (~10 min) |

**All four drive from committed artifacts.** Nothing is generated on the meter:
`bootstrap` refuses a dirty or unpushed tree, so live generation would cost a
commit, a push and a new benchmark SHA mid-session.

**The steady and adversarial operating points were human decisions, taken
2026-08-21**, because §2.1 constrains the shape of both scenarios and names a λ
for neither. Steady uses the headline λ set (1.5 / 2 / 2.5 / 3 / 4) under
session #2 exact-N mechanics, so the only thing differing from the headline
curve is Poisson vs fixed intervals — an arrival-process comparison rather than
a second experiment. Adversarial is one point at λ=2 rather than a saturating
λ=5: the q90 long-context selection already supplies the adversarial pressure,
and λ=2 sits in the expected headline neighbourhood where the result is
informative rather than a trivial censoring collapse.

The controlled Poisson workload alone defines the headline breach. The others
may support interpretation but **may never redefine it**. Secondary points never
enter the headline classification, structurally rather than by convention —
though by two different mechanisms, which is worth knowing when reading the
records:

- **steady** is a v2 exact-N point, so its record is stamped
  `evidence_class: secondary_diagnostic` and is refused on that field;
- **natural-random and adversarial** are v1 artifacts read by the frozen
  legacy reader, which writes no `evidence_class` at all. They are refused
  because the gate is *fail-closed on absence*: no `evidence_class`, no
  `record_version` and no `process_epoch` each independently disqualify them.

Either way `metrics/classification.py` accepts only `headline_evidence`.

Adversarial is last deliberately: it drives the replica toward saturation, and
the headline and steady curves are already durably written by then.

If session wall-clock forces a cut, cut from the **bottom** of that table and
record what was deferred — do not cut the headline to make room.

---

## 9. The no-improvisation matrix

The complete set of authorized responses. **No other mid-session policy change
is authorized.**

| Condition | Authorized response |
|---|---|
| λ=1 already OVER | Add λ=0.5 scout |
| λ=8 still UNDER | Add λ=16 scout |
| Authorized scout still fails to bracket | **STOP** |
| Tier A bracket contains fewer than two frozen headline λ | **STOP** — pull artifacts, regenerate the headline family offline at bracketing λ, new benchmark SHA, back to pre-GPU approval (§5). Never substitute the nearest committed λ |
| Transient not stable by 60 s | **STOP** + regenerate schedules at a larger boundary |
| Prefix-cache verification fails | **STOP** — relaunch, re-verify. No headline points until it passes |
| Shed > 0 | Point invalid / investigate. The cap is shaping results — an instrument finding, not a server one |
| Driver fails materialized-schedule fidelity | Point invalid / investigate |
| Censoring > 5% | `CENSORED`; **no ordinary p99** |
| Censoring 0–5% near boundary | Tail-sensitivity review required; cannot finalize without it |
| 2–1 repeat split | `UNCERTAIN` |
| N=4000 unresolved | Report **interval**; stop |
| Desire to increase N to 5000 | **NOT AUTHORIZED** |
| Spot preemption during Tier B | Do not combine process epochs (§7) |
| Code change required | **STOP** — new benchmark SHA + preflight |
| Historical README conflicts with this plan | **STOP** — surface the conflict |

---

## 10. Cost and risk

| | Estimate |
|---|---|
| Total session | **4.3 – 7.2 h** (Tier B dominates) |
| Instance | `g2-standard-8` + 1× L4, Spot, `us-central1-a` |
| Rate | ~$0.40–0.50 / h |
| **Cost** | **~$1.70 – $3.60** |
| Budget ladder | $10 canary may fire; $150 hard line is not in reach |

**The binding constraint is wall-clock and spot preemption, not money.**

---

## 11. Artifact gate — what must exist before teardown

Teardown is irreversible and the instance is spot. Nothing may be torn down
until all of this is on the laptop and verified:

- [ ] Every driven point has its **three** artifacts: `.raw_log.jsonl`,
      `.samples.jsonl`, `.metrics.json`
- [ ] `pull_artifacts.sh` completeness check passes (fractional names like
      `headline_r1_rps1.5.*` survive it — that fix is a precondition of this
      session, since every headline tag is fractional or repeat-tagged)
- [ ] Prefix-cache verdict artifact present and says **DISABLED**
- [ ] vLLM launch log captured, with the **resolved** eager / prefix-cache modes
- [ ] Unloaded-floor run captured — `floor.metrics.json` with
      `membership_complete: true` and `floor_complete: true`. A floor that did
      not cover the canonical membership says so in the record
- [ ] Scout points captured
- [ ] Secondary points captured: natural-random, steady, adversarial
- [ ] Session log records the benchmark SHA and the process epoch of every repeat

Every driven point's record now carries its own `process_epoch`, and the family
report computes `vllm_restarted_between_repeats` from those values rather than
asserting it. If a spot preemption forces a vLLM restart mid-family, the
classifier refuses to combine the epochs offline (lock 3A) — so the check
cannot be lost by nobody noticing at the time.

**Pull incrementally, after each repeat, not only at session end.** The first
session pulled once at the end and it worked; it worked because nothing went
wrong. Over a 5-hour spot session that is a bet, and `pull_artifacts.sh` is
cheap to run repeatedly.

---

## 12. Teardown

```bash
SESSION_TAG=headline bash scripts/gpu_session/pull_artifacts.sh   # one last time
bash scripts/gpu_session/teardown_week2.sh                        # NOT bare teardown.sh
```

`teardown_week2.sh` owns Week 2's instance name and **verifies the deletion
afterwards** rather than trusting the exit code. Bare `scripts/teardown.sh`
defaults to Week 1's instance name and would leave the Week 2 meter running.

**Verify deletion in the console as well.** The script tells you if the instance
still exists; believe the console over any exit code.

Afterwards, promote accepted points into `benchmarks/evidence/week2/session_2/`
with a hash manifest, the same way session #1's were.

---

## 13. Classification happens offline

After teardown, from the pulled artifacts, via `metrics/classification.py`.
No percentile is ever computed on the meter, and no verdict is rendered during
the session. The session collects bytes; the analysis reads them afterwards for
free.

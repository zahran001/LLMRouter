# Week 2 — GPU session #2 runbook (attempt 2)

> **STATUS: EXECUTABLE — GPU SESSION #2, ATTEMPT 2**
>
> Role: **the** GPU session #2 runbook. This is the one file to keep open while
> the meter is running.
>
> Current document authority:
> - experiment semantics: `WEEK2_PLAN.md`
> - execution / gating: `WEEK2_EXECUTION.md`
> - GPU commands: **this document**
> - machine-readable policy: `benchmarks/workloads/week2_headline/repeat_policy.json`
> - attempt-2 design record: `WEEK2_GPU_SESSION_2_ATTEMPT_2_PLAN.md` (§14 locked
>   2026-08-22; the decisions it locked are merged into this document, so
>   nothing below requires reading it mid-session either)
>
> If these appear to conflict: **HALT and surface the conflict. Do not reconcile
> silently.** Index: `WEEK2_DOC_INDEX.md`.
>
> **No instance may be created until Hard Stop R-DOC and Hard Stop R-PREGPU have
> both been passed by a human.** This document being executable describes what it
> is *for*, not that it is *authorized to run right now*.

Attempt 1 (2026-08-22) ran the unloaded floor and Tier A scout cleanly, then
stopped after Tier B repeat 1: all three driven points (λ ∈ {1.5, 2, 2.5})
came back `CENSORED` — 27–37% of requests timed out waiting for a first
token — even though Tier A's N=500 scout (5–6 minute points) had read λ=1 as
a clean `UNDER` and λ=2 as barely `OVER` at 0% censoring. Full account:
`WEEK2_GPU_SESSION_2_REPORT.md`.

**The finding, not a bug in attempt 1's mechanics, is what changed this
document.** A short scouting window cannot see a queue that is only slowly
diverging — the exact failure mode the whole Week 2 redesign exists to catch,
recurring one level up. Attempt 2 (design locked 2026-08-22,
`WEEK2_GPU_SESSION_2_ATTEMPT_2_PLAN.md` §14) replaces:

- the N=500 scout with a **sustained-scout** tier that freezes each schedule
  on whichever binds last of a minimum **45-minute** duration and a minimum
  **2,000**-request count, so a slowly diverging queue has time to reveal
  itself before the point is read;
- the flat N=4000 headline confirmation, at this lower λ range, with the same
  duration+count rule (N=4000 was measured to be impractical below λ=1.5 —
  over two hours per repeat at λ=0.5);
- the 5%-censoring `CENSORED` state with `OVER_CENSORED`: the exact
  order-statistics form of "censoring alone proves the breach," which turns
  out to fire at a **lower** bar than 5% for any realistic N, so it decides
  the state and 5% survives only as informational metadata.

Server/client configuration, corpus, percentile convention, repeat/epoch
rules and teardown are **unchanged** from attempt 1 — only the λ range, the
schedule-freezing rule, and the censoring-to-verdict logic moved.

Rationale lives elsewhere and this document links out to it, but **nothing
below requires you to go read it mid-session**:

- Locks and semantics: `WEEK2_PLAN.md` §10 (supersessions), §11 (the six
  locks), §11.7 (attempt-2 secondary-scenario decisions)
- Why the redesign exists: `docs/WEEK2_GPU_SESSION_FINDINGS.md`
- Why attempt 2 exists: `WEEK2_GPU_SESSION_2_REPORT.md`, `WEEK2_GPU_SESSION_2_ATTEMPT_2_PLAN.md`
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
| Repeat policy | `repeat_policy.json`, `"status": "LOCKED"`, `policy_version` 4 (bumped 2026-08-22: `OVER_CENSORED` state + `sustained_scout` block, D-ATTEMPT2-1; bumped again 2026-08-23: `headline_threshold` block + floor-based population check for the real headline family at λ≤1.25, D-ATTEMPT2-2) |
| Percentile method | **nearest-rank**, one shared implementation (`metrics/percentile.py`) |
| Scout workload | `benchmarks/workloads/week2_scout/canonical_v1.json`, membership id `e9470f8f…` — **separately namespaced so it can never be mistaken for headline evidence.** Superseded as the Tier A tool by sustained-scout (§3); its schedules and code path are unchanged and still exist, just not driven this session |
| Sustained-scout workload | Same as the headline canonical workload above (`a49ecdd8…`) — the 500-prompt scout pool is too small for the ≥2000-request count floor. `workload_class: sustained_scout_controlled` is what keeps it from being confused with a real headline schedule (`scripts/gpu_session/scenario_contract.py`) |
| Sustained-scout / low-λ headline thresholds | **≥45 min post-warmup elapsed AND ≥2,000 post-warmup requests**, frozen at whichever binds last (`loadgen/headline_schedule.py`'s `materialize_min_duration_and_count`) |

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
| Schedules committed | `benchmarks/schedules/week2_redesign/` — **56**: 27 headline (15 exact-N λ∈{1.5,2,2.5,3,4} + 12 threshold λ∈{0.5,0.75,1.0,1.25}) + 6 scout (unused this attempt) + 4 sustained-scout + 9 natural-random + 9 steady + 1 adversarial |
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
 4. Tier A: sustained-scout sweep, all 4 committed points   ~3.5 h
      -- HARD STOP GPU-1: HUMAN READ --
 5. Tier B: confirmation sweep, repeat-major, threshold N    ~4.6-7.9 h
 6. Secondary: operating points chosen AFTER the headline    TBD
    boundary closes (§8) — natural-random, then steady
 7. Adversarial scenario (LAST)                            ~10 min
 8. pull artifacts, verify, teardown                        ~15 min
```

**Step 4 is the biggest wall-clock change from attempt 1.** The old N=500
scout took ~20 minutes total; sustained-scout takes ~3.5 hours because that
duration is the entire point — it is what attempt 1's scout didn't have and
needed.

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

# step 4 -- sustained-scout (Tier A), one schedule at a time. All FOUR
# committed points are driven -- there is no cheap subset, since the whole
# point is sustained duration.
SESSION_TAG=sustained_scout bash scripts/gpu_session/run_on_instance.sh sustained-scout \
    benchmarks/schedules/week2_redesign/sustained_scout/headline_r1_rps0.5.schedule.json
# ...repeat for rps0.75, rps1, rps1.25

# step 5 -- Tier B, repeat-major, drain-gated. The lambdas below are an
# EXAMPLE -- the real invocation uses whichever 2-3 lambdas Hard Stop GPU-1
# selects from {0.5, 0.75, 1.0, 1.25} (see §5). Drive one repeat at a time,
# exactly as attempt 1 did (a single REPEAT_IDS='1 2 3' invocation blocks for
# the whole family and makes "pull after every repeat" impossible):
for r in 1 2 3; do
    SESSION_TAG=headline REPEAT_IDS="$r" \
        bash scripts/gpu_session/run_on_instance.sh headline 1.0 1.25
    SESSION_TAG=headline bash scripts/gpu_session/pull_artifacts.sh
done

# step 6 -- secondary: natural-random, then steady. The example below uses
# rps1 for command SHAPE only -- the real lambda is chosen from the 9
# committed points AFTER the headline boundary closes (§8), not decided yet.
SESSION_TAG=secondary bash scripts/gpu_session/run_on_instance.sh secondary \
    benchmarks/schedules/week2_redesign/secondary_natural/secondary_rps1.schedule.json
SESSION_TAG=steady bash scripts/gpu_session/run_on_instance.sh steady \
    benchmarks/schedules/week2_redesign/secondary_steady/secondary_steady_rps1.schedule.json

# step 7 -- adversarial, LAST
SESSION_TAG=adversarial bash scripts/gpu_session/run_on_instance.sh adversarial \
    benchmarks/schedules/week2_redesign/adversarial/adversarial_rps2.schedule.json

# pull after EVERY repeat, not only at the end. `pull_artifacts.sh` pulls ONE
# tag, so each stage needs its own invocation -- and SESSION_TAG has no useful
# default here (it falls back to session #1's `stage_a`).
for tag in floor sustained_scout headline secondary steady adversarial; do
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
> | sustained-scout | **all 4** — λ 0.5, 0.75, 1.0, 1.25 (no fallback ladder; see §3) | §3 |
> | headline | **2 or 3** λ (whichever Hard Stop GPU-1 selects) × 3 repeats, one `headline` invocation per repeat | §5 |
> | secondary | 1, chosen after §5 closes (from the 9 committed `secondary_rps{0.5,0.75,1.0,1.25,1.5,2,2.5,3,4}.schedule.json`) | §8 |
> | steady | 1, same chosen point (from the 9 committed `secondary_steady_rps{...}.schedule.json`) | §8 |
> | adversarial | 1 | §8 |
>
> **Tier B is one blocking invocation per repeat, not one for all three.**
> A single `REPEAT_IDS='1 2 3'` invocation blocks for the whole family (up to
> ~7.9 h in the worst case), which makes "pull after every repeat"
> impossible. Drive them separately, exactly as shown in the commands block
> above. Each repeat still drains between λ points, and the drain gate still
> refuses to start a repeat while the server has work in flight.

> ### Every scenario is validated against the artifact, not its directory
>
> `scout`, `sustained-scout`, `steady`, `secondary` and `adversarial` each
> check the schedule's own provenance before driving it
> (`scripts/gpu_session/scenario_contract.py`) and refuse a schedule generated
> for a different scenario. This matters most for the pairs nothing else
> separates: `headline/headline_r1_rps2.schedule.json` and
> `scout/headline_r1_rps2.schedule.json` have the same filename, the same
> `headline-schedule-v2` scheme and the same `workload_class` — only the
> canonical membership differs. `sustained-scout` is the newer version of the
> same trap: it shares scheme **and** membership with the real headline
> family (both draw from the 4000-prompt canonical set), so
> `workload_class: sustained_scout_controlled` is the *only* thing left to
> keep a sustained-scout schedule from being driven as headline evidence.

> `run_on_instance.sh stage-a` drives the **superseded** session #1 fixed-duration
> sweep. It prompts for a typed confirmation. Never use it in this session.

> ### `scout`, `sustained-scout` and `run` are different commands on purpose
>
> `scout` and `sustained-scout` both drive a frozen session #2 schedule
> through the **same** measurement path Tier B uses — the warmup boundary,
> expected N, delivery-fidelity denominator, censoring gate and membership all
> come off the schedule's own provenance, so a Tier A bracket is expressed in
> the units Tier B confirms in. **`scout` (N=500) is not driven this
> session** — attempt 1's finding (`WEEK2_GPU_SESSION_2_REPORT.md`) is that its
> short window cannot see sustained queue instability, so `sustained-scout` is
> this attempt's Tier A tool; `scout`'s command and schedules remain available
> for reference but are not part of this runbook's sequence. The only
> difference either scout variant has from `headline` is authority: the record
> is stamped `evidence_class: scout_diagnostic`, and `metrics/classification.py`
> refuses to aggregate it.
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

## 3. Tier A — sustained scouting

> **Diagnostic only. Sustained-scout points may locate the region. They may
> not produce an UNDER/OVER headline claim, and they never enter the
> classification.** `evidence_class: scout_diagnostic`, same as the superseded
> N=500 scout.

| Parameter | Value | Why |
|---|---|---|
| λ points | **0.5, 0.75, 1.0, 1.25** — all four, no fallback ladder | Attempt 1's own data: Tier B repeat 1 found λ=1.5 already 36% censored, so the crossing is somewhere at or below this range |
| Freezing rule | **≥45 min post-warmup elapsed AND ≥2,000 post-warmup requests**, whichever binds last | A fixed N alone makes low-λ points long and high-λ points short; a fixed duration alone can starve the p99 tail at low λ. This is the property attempt 1's scout didn't have |
| Repeats | 1 | Scouting, not evidence |
| Warmup boundary | 60 s | Same as Tier B, so the transient read transfers |
| Drive time (actual, committed schedules) | 0.5: 4178.8s · 0.75: 2780.4s · 1.0: 2760.9s · 1.25: 2760.5s ≈ **3.47 h** | |

**The crossing is somewhere in this range, or below it.** Attempt 1's Tier B
proved λ ∈ {1.5, 2, 2.5} are all badly censored under sustained load. Nothing
in this range has been driven under sustained load yet — that is exactly what
this tier is for.

### No fallback ladder this attempt

Unlike attempt 1's lock 5A (scout 1/2/4/8, fallback 0.5/16), there is no
pre-authorized extension of the sustained-scout λ range. The committed family
is the whole menu:

```
No sustained UNDER anywhere in {0.5, 0.75, 1.0, 1.25}  →  STOP (extending downward on the meter is NOT AUTHORIZED)
All four are sustained UNDER                            →  STOP (extending upward on the meter is NOT AUTHORIZED)
```

Both extensions are offline-only work (generate new sustained-scout schedules
at the indicated end, re-run the GPU-free checks, take a new benchmark SHA,
return to pre-GPU approval) — never a meter decision. Inventing additional λ
values on the meter must not happen under any condition this section names.

### What the human reads off Tier A

1. **The crossing region** — which λ are clearly sustained `UNDER`, which are
   `OVER` or `OVER_CENSORED`.
2. **The warmup transient** — TTFT vs wall-clock, to confirm the frozen 60 s
   boundary is still sufficient (unchanged check from attempt 1).
3. **Sanity gates** — 0 shed, `exact_n_honoured` true, `schedule_delivery_ok`
   true at every sustained-scout point. Censoring is not a sanity gate here —
   `OVER_CENSORED` is a legitimate, informative outcome, not a fault.

---

## 4. ── HARD STOP GPU-1 — mid-session, human verdict ──

The only sanctioned mid-session judgment. It must answer exactly two questions:

```
1. Is the crossing neighbourhood bracketed?
2. Is the 60s warmup boundary sufficient?
```

**On (1).** Bracketed means: at least one sustained-scout point reads
`UNDER`, and at least one reads `OVER` or `OVER_CENSORED` (§6 treats both as
breach-confirmed). Read the λ_low/λ_mid/λ_high selection rule in §5 before
answering — with a 0.25-spaced grid, a 2-step bracket (e.g. 0.5 `UNDER`, 1.0
`OVER`) has a committed intermediate to confirm at (0.75); a 1-step bracket
(e.g. 0.75 `UNDER`, 1.0 `OVER`) does not, and Tier B confirms at just those
two points.

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
| λ points | **2 or 3**, chosen from the Tier A bracket (see below) |
| Freezing rule | Same as sustained-scout (§3): **≥45 min AND ≥2,000 requests**, whichever binds last. Replaces attempt 1's flat N=4000, which was measured to take >2h per repeat at λ=0.5 |
| Repeats | **3** (`min_valid_repeats`) |
| Order | **repeat-major** |
| Separation | drain to in-flight = 0, then each repeat's own warmup. **No vLLM restart.** |

### Repeat-major ordering is a deliberate choice

```
r1: λ_low → [λ_mid →] λ_high      (drain between each)
r2: λ_low → [λ_mid →] λ_high
r3: λ_low → [λ_mid →] λ_high
```

Not λ-major. This is a spot-preemption hedge: a preemption partway through
leaves **complete repeats** rather than complete λ points and nothing at the
others. A complete repeat is a reportable (if UNCERTAIN) result; a partial
λ-major sweep is not.

The drain probe reads the **server** (`vllm:num_requests_running` /
`num_requests_waiting`), not the client — a client-side in-flight count is
always zero by the time a point returns, so gating on it would be green forever.

### Drive time

Per-repeat times below are the actual committed schedules' realized durations
(averaged across their 3 repeats — the threshold rule makes these vary
slightly by realization, unlike attempt 1's exact-N family where every repeat
at a λ was close to identical):

| λ | per repeat | × 3 repeats |
|---:|---:|---:|
| 0.5 | 1.10 h | 3.30 h |
| 0.75 | 0.77 h | 2.30 h |
| 1.0 | 0.77 h | 2.30 h |
| 1.25 | 0.77 h | 2.30 h |

| Example 2-point bracket | × 3 repeats | Example 3-point bracket | × 3 repeats |
|---|---:|---|---:|
| 0.75 / 1.0 | 4.60 h | 0.5 / 0.75 / 1.0 | 7.90 h |
| 1.0 / 1.25 | 4.60 h | 0.75 / 1.0 / 1.25 | 6.90 h |

The committed 27-schedule `headline/` family covers λ ∈ {0.5, 0.75, 1.0, 1.25,
1.5, 2, 2.5, 3, 4} × 3 repeats; only the chosen 2-3 λ are driven. The rest
are staged, not spent. **λ ∈ {1.5, 2, 2.5, 3, 4} are not expected to be
chosen** — attempt 1 already proved 1.5, 2 and 2.5 badly censored under
sustained load, and 3/4 are certain to be worse — but they stay committed as
historical, already-driven-once evidence.

### Choosing the λ — the rule, not a judgement

```
the driven λ MUST come from {0.5, 0.75, 1.0, 1.25}
    λ_low   the highest frozen λ that Tier A found sustained UNDER
    λ_high  the lowest  frozen λ that Tier A found OVER or OVER_CENSORED
    λ_mid   the frozen λ between them, driven ONLY IF ONE IS COMMITTED
```

The grid is spaced 0.25 apart. A 1-step bracket (e.g. 0.75 `UNDER`, 1.0
`OVER`) has no committed intermediate — drive exactly those two. A 2-step
bracket (e.g. 0.5 `UNDER`, 1.0 `OVER`) has one (0.75) — drive all three.
**Do not drive a third point when the bracket is 1-step**, and do not skip
the intermediate when the bracket is 2-step: either way changes what the
family reports without changing what was authorized.

If the Tier A bracket does not contain at least one frozen headline λ at
each end:

```
STOP.
Pull the sustained-scout artifacts. Regenerate the headline family offline
at lambdas that bracket the observed crossing, re-run the GPU-free checks,
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

Applied **offline, after teardown**, from `repeat_policy.json`
(`policy_version` 4).

```
min_valid_repeats      3
require_unanimous      true
majority_vote          false
n_max                  5000
max_repeats_authorized 3
sustained_scout.min_duration_s   2700
sustained_scout.min_count        2000
headline_threshold.min_duration_s   2700
headline_threshold.min_count        2000
```

`headline_threshold` (D-ATTEMPT2-2, added 2026-08-23) governs the REAL headline
evidence family at λ∈{0.5, 0.75, 1.0, 1.25} — same numbers as
`sustained_scout` above, but a separate policy block, since `sustained_scout`
stays diagnostic-only. `metrics/classification.py` checks a threshold
lambda's `percentile_population_n` against this floor rather than requiring
exact equality to `n_per_run` (4000), because each repeat is an
independently-seeded draw and legitimately realizes a different exact count
(observed 2065–2078 across three repeats at λ=0.75 in GPU session #2 attempt
2). `n_per_run` = 4000 still governs λ≥1.5, whose schedules remain fixed-N.

`n_per_run: 4000` no longer applies to whichever λ Tier B drives this
attempt — the threshold rule makes N a realization outcome (§5), not a fixed
input. It still governs the untouched λ ∈ {1.5, 2, 2.5, 3, 4} exact-N
schedules, which is why the field is not removed from the policy file.

### Repeat states

```
UNDER          p99 TTFT < 500ms, all gates clean
OVER           p99 TTFT >= 500ms, all gates clean
OVER_CENSORED  censoring alone proves p99 > 500ms (exact nearest-rank proof,
               ~>=1% at this N) -- breach confirmed, no numeric p99 published
UNCERTAIN      cannot finalize
```

`OVER_CENSORED` (added 2026-08-22, `repeat_policy.json` `D-ATTEMPT2-1`)
**replaces** the flat 5% `CENSORED` gate for records this session produces:
the exact rank-based condition fires at a lower bar than 5% for any realistic
N, so it decides the state first. It agrees with `OVER` for repeat-family
unanimity — both mean breach confirmed, one via a computed percentile and one
via the censoring proof. Legacy `CENSORED` records (attempt 1 and earlier)
remain readable and still excluded, never pooled — that behavior is
unchanged.

- A repeat that missed exact-N or failed delivery fidelity is **excluded,
  never pooled**. (`OVER_CENSORED` is not excluded — it is a proven, valid
  repeat.)
- A boundary-determining point with **sub-threshold censoring** (i.e. some
  censoring, but not enough to prove `OVER_CENSORED`) and no completed
  tail-sensitivity review **cannot finalize** — it stays `UNCERTAIN`.

### Point classification (lock 1A, extended for `OVER_CENSORED`)

```
UNDER + UNDER + UNDER                        →  UNDER
{OVER, OVER_CENSORED} x 3, any mix           →  OVER
UNDER mixed with {OVER, OVER_CENSORED}       →  UNCERTAIN
```

**No majority voting.** Near the SLO the split *is* the finding — the point is
unstable. Taking the majority would convert an honest UNCERTAIN into a verdict,
which is the failure the first session already made once. The `OVER`/
`OVER_CENSORED` equivalence is not a relaxation of this rule — both states
mean the same thing (breach confirmed); only `UNDER` disagreeing with either
is a real split.

### The stop condition, stated before the money is spent (lock 2B)

If the crossing is unresolved once the authorized repeats are spent:

```
breach interval = (highest defensible UNDER λ, lowest defensible OVER λ]
```

and the session **stops**.

**No escalation of any kind is authorized.** Neither the old `N = 5000`
fixed-count escalation nor a larger sustained-scout/headline threshold to
force a resolution — `repeat_policy.json` records `escalation.authorized:
false`. An interval is a legitimate final answer, not a failure.

**Do not increase the thresholds on the meter.**

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
| 1 | Controlled Poisson headline | `headline/` — 27 schedules (12 threshold λ∈{0.5,0.75,1.0,1.25} + 15 exact-N λ∈{1.5,2,2.5,3,4}) | **Defines the breach.** Tier B above |
| 2 | Natural-random secondary | `secondary_natural/` — 9 schedules, 600s each | Does the knee survive unconstrained traffic? Point chosen after headline closes |
| 3 | Steady-arrival reference | `secondary_steady/` — 9 schedules, N=500, 60s boundary | Lower-variance legible reference. Point chosen after headline closes |
| 4 | Adversarial long-context | `adversarial/` — 1 schedule, λ=2, 600s | Separate scenario — **runs LAST** (~10 min) |

**All four drive from committed artifacts.** Nothing is generated on the meter:
`bootstrap` refuses a dirty or unpushed tree, so live generation would cost a
commit, a push and a new benchmark SHA mid-session.

**Adversarial's operating point was a human decision, taken 2026-08-21**, and
is unaffected by the attempt-2 redesign: one point at λ=2 rather than a
saturating λ=5, because the q90 long-context selection already supplies the
adversarial pressure and λ=2 sits in the expected headline neighbourhood
where the result is informative rather than a trivial censoring collapse.

**Natural-random and steady's operating points are deliberately deferred**
(`WEEK2_GPU_SESSION_2_ATTEMPT_2_PLAN.md` §10, locked 2026-08-22) — the
2026-08-21 decision to use the old headline λ set (1.5–4) no longer makes
sense now that the whole range is known over-SLO under sustained load. Both
scenarios are committed at all nine λ ∈ {0.5, 0.75, 1.0, 1.25, 1.5, 2, 2.5,
3, 4} precisely so the choice can be made **after** Tier B closes, "around
the confirmed boundary," without generating anything mid-session. **Do not
drive natural-random or steady before Tier B closes** — there is no boundary
yet to center them on.

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
| No sustained UNDER anywhere in {0.5, 0.75, 1.0, 1.25} | **STOP** — pull artifacts, extend the sustained-scout family downward offline, new benchmark SHA, back to pre-GPU approval |
| All four sustained-scout points are UNDER | **STOP** — pull artifacts, extend the sustained-scout family upward offline, new benchmark SHA, back to pre-GPU approval |
| Tier A bracket missing a committed headline λ at either end | **STOP** — pull artifacts, regenerate the headline family offline at bracketing λ, new benchmark SHA, back to pre-GPU approval (§5). Never substitute the nearest committed λ |
| Transient not stable by 60 s | **STOP** + regenerate schedules at a larger boundary |
| Prefix-cache verification fails | **STOP** — relaunch, re-verify. No headline points until it passes |
| Shed > 0 | Point invalid / investigate. The cap is shaping results — an instrument finding, not a server one |
| Driver fails materialized-schedule fidelity | Point invalid / investigate |
| Censoring proves the exact-rank `OVER_CENSORED` condition (§6) | `OVER_CENSORED`; **no ordinary p99**, agrees with `OVER` for unanimity |
| Sub-threshold censoring near boundary | Tail-sensitivity review required; cannot finalize without it |
| UNDER disagreeing with OVER/OVER_CENSORED | `UNCERTAIN` |
| Authorized repeats spent, crossing unresolved | Report **interval**; stop |
| Desire to increase N, min_duration_s or min_count beyond the locked values | **NOT AUTHORIZED** |
| Desire to drive natural-random/steady before Tier B closes | **NOT AUTHORIZED** — their operating point isn't chosen yet (§8) |
| Spot preemption during Tier B | Do not combine process epochs (§7) |
| Code change required | **STOP** — new benchmark SHA + preflight |
| Historical README conflicts with this plan | **STOP** — surface the conflict |

---

## 10. Cost and risk

| | Estimate |
|---|---|
| Total session | **~9.5 – 13.5 h** (up from attempt 1's 4.3–7.2h: sustained-scout alone is ~3.5h where the old scout was ~20min, and threshold-based Tier B runs longer per point at these lower λ) |
| Instance | `g2-standard-8` + 1× L4, Spot, `us-central1-a` |
| Rate | ~$0.40–0.50 / h (attempt 1's actual observed rate) |
| **Cost** | **~$3.80 – $6.80** |
| Budget ladder | $10 canary may fire; $150 hard line is not in reach |

**The binding constraint is wall-clock and spot preemption, not money** — more
so than attempt 1, given the longer session. A spot preemption during the
~3.5h sustained-scout sweep loses more progress than one during the old
20-minute scout would have; nothing here changes the response (§7), but it is
worth budgeting session time with that in mind.

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
- [ ] Sustained-scout points captured (all 4)
- [ ] Secondary points captured: natural-random, steady, adversarial
- [ ] Session log records the benchmark SHA and the process epoch of every repeat

Every driven point's record now carries its own `process_epoch`, and the family
report computes `vllm_restarted_between_repeats` from those values rather than
asserting it. If a spot preemption forces a vLLM restart mid-family, the
classifier refuses to combine the epochs offline (lock 3A) — so the check
cannot be lost by nobody noticing at the time.

**Pull incrementally, after each repeat, not only at session end.** The first
session pulled once at the end and it worked; it worked because nothing went
wrong. Over a session this long (§10: ~9.5–13.5h) that is a bigger bet than it
was for attempt 1, and `pull_artifacts.sh` is cheap to run repeatedly.

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

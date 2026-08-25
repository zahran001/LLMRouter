# Week 2 — GPU session #2, second attempt: report and outcome

> **STATUS: EVIDENCE — DOES NOT GOVERN EXECUTION**
>
> Record of what actually happened on 2026-08-23. Decides no experiment
> semantics; not a runbook. Current GPU commands live in
> `WEEK2_GPU_SESSION_2_PLAN.md`. Not yet wired into `WEEK2_DOC_INDEX.md`.

## 1. Executive summary

Attempt 2 ran in two parts. A **first instance** (benchmark SHA `5c53d1e`)
completed setup and the unloaded floor cleanly, then failed immediately on
the first sustained-scout point with an argparse error — `drive_scenario_point.py`
had never been updated to accept `--scenario sustained-scout`, despite every
other part of the redesign (dispatch scripts, `scenario_contract.py`, tests)
already supporting it. No request was sent; the instance was torn down at
negligible cost, the bug fixed, tested, and pushed as `398b929`.

A **second instance** (SHA `398b929`) ran the full runbook end to end: floor,
all four sustained-scout points, Hard Stop GPU-1 (human-cleared), three Tier
B headline repeats at λ∈{0.5, 0.75}, secondary/steady/adversarial, and a
clean teardown. **Result: λ=0.75 classifies OVER (unanimous); λ=0.5
classifies UNCERTAIN (2 OVER, 1 UNDER — a genuine split at the boundary).**
Offline resolution is `NO_UNDER_ANCHOR`: no λ in the swept range is a
confirmed UNDER, so the crossing sits at or below λ=0.5, unresolved within
this session's authorized evidence. No escalation is authorized — this
stands as the session's final answer.

A **second real defect** was found offline, after teardown, while running
the classification: `metrics/classification.py` could not classify *any*
threshold-based headline family (λ≤1.25), because `repeat_policy.json` was
updated for the diagnostic sustained-scout tier's threshold parameters but
never for the fact that the real headline family at these same λ also
switched from fixed N=4000 to the same threshold rule. Fixed and tested
(530 tests, both control-bites suites green) but **left uncommitted at the
user's request, pending their review**.

## 2. Session identity

| Field | First instance (aborted) | Second instance (full run) |
|---|---|---|
| Benchmark SHA | `5c53d1e28c...` | `398b9298ed05adc2424278f1a71b8c03f364b3f7` |
| Instance | `llmrouter-vllm-l4-week2`, `g2-standard-8` + 1× L4, SPOT, `us-central1-a` | same |
| Model | `meta-llama/Llama-3.2-3B-Instruct` | same |
| Resolved server config | `enforce_eager=1`, `disable_prefix_caching=1`, `max_model_len=20000` | same |
| vLLM process epoch | `vllm-start-1787467507` | `vllm-start-1787469907` (single epoch, no preemption) |
| Prefix-cache verdict | `PREFIX_CACHING_DISABLED` (min ratio 0.94) | `PREFIX_CACHING_DISABLED` (min ratio 0.95) |
| Floor | 4000/4000, p99=408.4ms, 92ms headroom | 4000/4000, p99=397.6ms, 102ms headroom |
| Outcome | Teardown after sustained-scout argparse failure | Full runbook completed, teardown verified |

Canonical headline membership (both instances): `a49ecdd8071920303f240fcf0b8da42dbbc66da593ae88e3c07aa246c4b5aa7b` (4,000 prompts).

## 3. Defect #1 — `drive_scenario_point.py` rejected `sustained-scout`

```
drive_scenario_point.py: error: argument --scenario: invalid choice: 'sustained-scout'
  (choose from 'scout', 'steady')
```

`scenario_contract.py` already had a full contract entry for `sustained-scout`
(`workload_class: sustained_scout_controlled`, `evidence_class: scout_diagnostic`),
and both `run_on_instance.sh` and `remote_loadgen.sh` already dispatched to it
correctly. Only this one script's hardcoded `choices=["scout", "steady"]`
was never updated. `check_scenario.py`'s tests never caught it because that
script derives its choices from `sorted(CONTRACTS)` — a different script.

**Fix**: widened the choices list to `["scout", "sustained-scout", "steady"]`;
updated the module docstring. **Regression test**: `tests/redesign/test_sustained_scout.py::test_drive_scenario_point_actually_accepts_sustained_scout_on_its_cli` —
drives the real committed schedule through the real CLI entrypoint (network
stubbed), reproduces the exact live `SystemExit(2)` against the pre-fix code.

**Committed and pushed**: `398b929` — "week2: fix drive_scenario_point.py to accept --scenario sustained-scout".

## 4. Tier A — sustained-scout (N≥2000, ≥45min, DIAGNOSTIC only)

| λ | state | p99 TTFT | censoring | issued (target N) | gates |
|---|---|---:|---:|---|---|
| 0.5 | UNDER | 484.5ms | 0.0% | 2039 (2000) | clean |
| 0.75 | OVER | 583.7ms | 0.0% | 2032 (2000) | clean |
| 1.0 | OVER | 644.8ms | 0.0% | 2711 (2640) | clean |
| 1.25 | OVER_CENSORED | — | 24.2% | 3473 (3389), 819 errored | clean |

All `exact_n_honoured` / `schedule_delivery_ok` true, 0 shed, at every point.

### Hard Stop GPU-1

- **Bracket**: λ_low=0.5 (UNDER), λ_high=0.75 (OVER) — adjacent on the 0.25
  grid, a 1-step bracket. Tier B drove exactly {0.5, 0.75}, no intermediate.
- **Warmup transient**: λ=0.5 (most exposed) showed two short bursts of
  1.0–3.4s TTFT between t=30.1–43.5s, including small prompts (31–463 chars,
  ruling out prompt-length as the cause) — read as continuous-batching
  contention (at λ=0.5, mean ~14s decode time per request means ~7 requests
  are concurrently in-flight in steady state). Fully resolved by t≈44s,
  ~16s of margin before the frozen 60s boundary (vs ~30s margin in attempt
  1). Confirmed non-recurring across the full ~70-minute run (one further
  isolated 1.0s sample at t=1310s, not a burst).
- **Human verdict**: cleared to proceed on both questions.

## 5. Tier B — headline confirmation (`headline_evidence`)

| repeat | λ=0.5 | λ=0.75 |
|---|---|---|
| 1 | OVER, p99=500.3ms | OVER, p99=589.2ms |
| 2 | OVER, p99=504.5ms | OVER, p99=559.0ms |
| 3 | UNDER, p99=494.4ms | OVER_CENSORED, 2.5% censoring |

All 6 points: `exact_n_honoured`/`schedule_delivery_ok` true, 0 shed.
Population per repeat varies naturally (2000 exactly at λ=0.5 on all three;
2069/2078/2065 at λ=0.75) — each repeat is an independently-seeded
threshold-freeze draw, not a driver bug (see §7).

**Classification** (no majority voting, OVER_CENSORED counts as OVER for
unanimity): λ=0.5 → **UNCERTAIN**. λ=0.75 → **OVER**.

## 6. Secondary scope (λ=0.75, chosen after Tier B closed)

| Scenario | Result |
|---|---|
| Natural-random (secondary) | UNDER, p99=371.6ms, n=471. Achieved rate 0.80rps vs offered 0.75rps (+6.4%, outside ±5% band) — flagged, plots at achieved rate per policy, diagnostic only |
| Steady reference | UNDER, p99=434.8ms, N=500, issued 544/544, 0% censoring |
| Adversarial (λ=2, long-context, run last) | p99≈60,005ms (client timeout ceiling) — saturated as designed. 577/1212 sent, 635 errored (timeouts), 0 shed (real saturation, not a concurrency-cap artifact) |

## 7. Defect #2 — classification couldn't handle threshold-family variance

`metrics/classification.py`'s `HeadlineEvidenceSpec` required every repeat's
`percentile_population_n` to match one fixed value (`n_per_run=4000`,
read from `repeat_policy.json`). That was correct while every headline
schedule used fixed N=4000. Attempt 2 switched λ≤1.25 headline schedules to
the same min(45min, 2000-count) threshold rule sustained-scout uses — each
repeat is an independently-seeded draw, so its realized count legitimately
differs (2069/2078/2065 here, frozen into the *committed schedule files
themselves*, not a runtime artifact). `repeat_policy.json` was updated for
sustained-scout's threshold parameters (D-ATTEMPT2-1, 2026-08-22) but never
for the fact that the real headline family also needed them. Result: any
threshold-lambda headline family was unclassifiable —

```
NotHeadlineEvidence: repeat_id=2 is not session #2 headline evidence:
  - percentile_population_n=2078, expected 2069
```

**Fix** (D-ATTEMPT2-2, uncommitted):
- `repeat_policy.json`: `policy_version` 3→4; new `headline_threshold` block
  (`lambdas: [0.5, 0.75, 1.0, 1.25]`, `min_count: 2000`, `min_duration_s: 2700`)
  — a separate block from `sustained_scout`, deliberately, since conflating
  a diagnostic tier's policy with the breach-defining one would recreate the
  exact workload-identity ambiguity `scenario_contract.py` exists to prevent.
- `metrics/classification.py`: `HeadlineEvidenceSpec` gained
  `threshold_lambdas`/`threshold_min_count`; the population check is now
  **exact-match** for legacy λ (≥1.5, unchanged behavior) and **floor**
  (`population >= min_count`) for threshold λ (≤1.25).
- `WEEK2_GPU_SESSION_2_PLAN.md`: §0 and §6 updated for `policy_version` 4 and
  the new `headline_threshold` numbers.
- `tests/redesign/test_repeat_and_classification.py`: 6 new tests, including
  one that classifies this session's *actual* pulled λ=0.75 records
  end-to-end and fails against the pre-fix code.

**Verification**: 530 tests pass (380 `tests/redesign` + 150 general), both
`show_control_bites.py` (13/13) and `show_doc_control_bites.py` (6/6) green.
Confirmed the new tests fail-to-collect against the pre-fix code
(`TypeError: unexpected keyword argument 'threshold_lambdas'`).

**Not committed** — user chose to review the diff first. Files touched:
`benchmarks/workloads/week2_headline/repeat_policy.json`,
`metrics/classification.py`, `WEEK2_GPU_SESSION_2_PLAN.md`,
`tests/redesign/test_repeat_and_classification.py`.

## 8. Final offline classification

```python
resolve_breach({0.5: [...], 0.75: [...]}, RepeatPolicy.from_frozen(), ...)
```

```
under_lambdas:      []
over_lambdas:       [0.75]
unresolved_lambdas: [0.5]
resolution:         NO_UNDER_ANCHOR
breach_interval:    null
message: "no λ was classified UNDER. The crossing is at or below the lowest
          swept point. Offline conclusion only: extending the range means
          regenerated schedules and a new session, never a live decision."
```

**This is the session's final answer.** No escalation is authorized
(`repeat_policy.json`: `escalation.authorized: false`); a next session would
need new sustained-scout/headline schedules at λ<0.5, generated offline,
GPU-free-checked, and re-approved through R-DOC/R-PREGPU — not a live
decision on this data.

## 9. Operational note — repeated background-monitor kills (no data impact)

During Tier B repeats 2 and 3, the local process tracking the remote SSH
driver was killed externally 7 times in a row (gaps shrinking from ~7min to
under 1min between kills), cause undetermined — user confirmed no
intentional action on their end. **Zero impact on the actual run**: every
check of the remote instance during this period showed vLLM healthy and
`drive_headline_family.py` steadily accumulating CPU time under the same PID
across every kill. Recovered each time by polling the remote PID directly
rather than relying on the original blocking driver call. Worth
investigating (session-length limit? machine sleep?) before the next
long GPU session, but did not affect this session's evidence.

## 10. Artifacts on disk

All pulled, hash/completeness-checked, left in place under `benchmarks/runs/`:

| Path | Contents |
|---|---|
| `floor/` | Unloaded floor (second instance's run; 397.6ms p99) |
| `sustained_scout/` | 4 Tier A points, `scout_diagnostic` |
| `headline/` | 9 points: 3 repeats × {0.5, 0.75} (this session) + 3 legacy λ∈{1.5,2,2.5} repeat-1 points (attempt 1, `CENSORED`, still present from before) |
| `secondary/` | Natural-random λ=0.75 |
| `steady/` | Steady reference λ=0.75 |
| `adversarial/` | λ=2 long-context flood |
| `preflight/prefix_cache_verdict.json` | Second instance's gate verdict |
| `vllm.log` | Second instance's full launch log |

Not yet done: promotion into `benchmarks/evidence/week2/session_2/` with a
hash manifest (runbook §12) — held pending the Defect #2 fix review, since
promoting evidence classified by code the user hasn't yet accepted would tie
the two together.

## 11. Approximate cost and duration

First instance: setup + floor + immediate scout failure, on the order of
20–30 minutes (~$0.15–0.25). Second instance: vLLM up ~2026-08-23T07:25 UTC,
teardown after adversarial completed, roughly **~13 hours** total (floor
~5min, sustained-scout ~3.5h, Hard Stop GPU-1 human review, Tier B repeats
running ~2.1–2.2h each — somewhat longer than the runbook's 1.87h/repeat
estimate — secondary+steady+adversarial ~1h). At the plan's stated spot rate
(~$0.40–0.50/h), combined session cost is approximately **$5.35–$6.75** —
within the plan's own worst-case estimate (~$6.80) and well under the $10
canary.

## 12. What's next

1. Review and decide on the Defect #2 fix (§7) — commit if accepted.
2. Promote this session's accepted points into `benchmarks/evidence/week2/session_2/` with a hash manifest.
3. If a lower-λ bracket is wanted: generate new sustained-scout/headline schedules below λ=0.5 offline, re-run GPU-free checks, new benchmark SHA, fresh R-DOC/R-PREGPU — not reachable from this session's data.

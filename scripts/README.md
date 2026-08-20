# scripts

Operational scripts for benchmark infrastructure.

- `teardown.sh` — **generic** deletion primitive (parameterized via `INSTANCE_NAME` /
  `ZONE`). Not a Week 2 entry point: use `gpu_session/teardown_week2.sh`, which
  owns Week 2's instance name and verifies the deletion afterwards.
- `reproduce.sh`, `router_eval.sh` — Week 1 reproduction + router eval gate.
- `build_baseline_corpus.py` — build the pinned ShareGPT corpus artifact.
- `calibrate_noise_floor.py` — Block 0 Linux spin-disabled noise calibration
  (the **mock's** `precise_sleep` spin).
- `calibrate_scheduler_spin.py` — the **loadgen scheduler's** spin-margin A/B
  (0ms vs 5ms), the Block C calibration that let `loadgen/scheduler.py` ship a
  Linux default instead of the Windows-tuned one. CPU-only, run on a dedicated
  `e2`. Pass `--mock-spin-margin-s 0`: the mock runs in a thread of the same
  process, so its own busy-wait competes for the GIL and inflates measured
  scheduling lag for both arms.
- `calibrate_block_c.py` — Block C data generation (shed onset, natural
  concurrency, low-load tracking).
- `generate_schedules.py` — the **fixed-duration** schedule generator, for any
  RPS points. `--rps 32 34 36 38` (explicit) or `--rps-start 30 --rps-stop 40
  --rps-step 2` (inclusive range). **Session #1 only:** it produced Stage B's
  fine bracket mid-session. Session #2's headline uses exact-N schedules from
  `generate_headline_schedules.py` instead — a fixed window makes request count
  a function of λ, which is the confound that cost the first session its breach
  number (`WEEK2_PLAN.md` §10.2).
- `generate_stage_a_schedules.py` — the committed **session #1** Stage A coarse
  schedules. A thin wrapper over `generate_schedules.py`; its only
  distinguishing content is the RPS list, so Stage A and Stage B cannot drift
  apart. Kept so session #1's workload stays replayable, not because it is how
  session #2 is run.
- `compute_point_metrics.py` — recompute per-point metrics offline from the
  committed raw log + samples sidecar. Its `--warmup-n` re-filter applies to
  **session #1's** fixed-duration artifacts; it must not be used to resolve the
  redesigned headline's warmup after the fact (`WEEK2_PLAN.md` §11.4).

## Week 2 redesign — offline calibration (GPU-free)

Blocks R0–R3 of the redesign README. Run in this order; each writes a
machine-readable JSON beside the last, and the last one assembles them into the
package the human reads at Hard Stop R3.

## Week 2 documentation governance (Hard Stop R-DOC)

- `show_doc_control_bites.py` — run the four documentation-governance controls
  (C-DOC-1..4) and PRINT each one going red on a broken document before it goes
  green on the real one. Mutates a tracked file, runs the real check, restores
  the original bytes, and hash-verifies the restore. Companion to
  `tests/redesign/test_week2_doc_state.py`, whose passing checkmarks show the
  reds only by implication. `docs/WEEK2_DOC_INDEX.md` is what both hold the
  repository to.

- `promote_first_session_evidence.py` — **R0.** Copy the first GPU session's
  artifacts out of gitignored `benchmarks/runs/` into tracked
  `benchmarks/evidence/week2/first_session/`, byte-for-byte, with a SHA-256
  manifest. Refuses to overwrite a promoted artifact whose bytes differ;
  `--verify` re-checks a promotion made months ago.
- `capture_legacy_fixtures.py` — **R0.6.** Pin the two R2 source points as
  immutable fixtures: the bytes *and* what today's readers derive from them, so
  a reader change that silently reinterprets first-session evidence fails a test
  instead of rewriting history.
- `analyze_corpus_tail.py` — **R1.** Corpus length quantiles, histogram, eCDF,
  candidate `k`/`L` constructions and their tail support per candidate `N`.
- `analyze_prompt_cost.py` — **R1 support.** The measured TTFT-vs-prompt-length
  relation from the unloaded floor, which is what makes a tail boundary `L`
  mean something in latency rather than only in quantiles.
- `analyze_run_order_effects.py` — the prefix-cache finding: joins each loaded
  point against the unloaded floor on `prompt_id` to show whether a point read a
  warm cache. Unplanned, and it bears on whether D2+D4 are jointly workable.
- `calibrate_p99_sample_size.py` — **R2.** Bootstrap p99 stability vs candidate
  `N`, independently over the 1.5-RPS and 2-RPS arrays, never averaged.
- `report_kln_candidates.py` — **R3.** Joins the above into
  `benchmarks/calibration/week2_redesign/R3_EVIDENCE_PACKAGE.md`.
- `audit_floor_cache_state.py` — **P1.** Classifies the first session's
  unloaded floor for cache-state trustworthiness. Verdict:
  `CACHE_INFLUENCED_DIAGNOSTIC`, so 402.3ms is no longer citable as *the*
  unloaded floor.
- `show_control_bites.py` — runs every redesign control against a deliberately
  broken input first and prints the red, then the green. Hard Stop 2's rule is
  that the reds are the proof; this makes them legible instead of implied.

## Week 2 redesign — canonical workload and schedules (GPU-free)

Blocks R4–R11. The order below is enforced in code, not just documented: the
freeze refuses until the capacity proof exists, covers the same membership, and
says PASS (R4C).

`fetch_tokenizer.py` and `check_tokenizer_capacity.py` need
`requirements-preflight.txt`, which is deliberately **not** part of
`requirements.txt`: the GPU instance installs the latter, and these two run only
on the dev box before the session.

- `fetch_tokenizer.py` — fetch the pinned model's tokenizer and **prove** it is
  the pinned model's. `meta-llama/Llama-3.2-3B-Instruct` is gated, but the
  public metadata API reports the git blob id of every file in it, so an
  ungated mirror's copy can be hash-verified against the gated repo without
  needing access to it. `--verify-only` re-checks the cache.
- `build_canonical_workload.py --emit-candidate` — **R4A.** Select the
  canonical membership: k6 strata, proportional allocation, without
  replacement, hash-keyed selection (stable across NumPy versions in a way
  `Generator` streams are not). `--scout` builds the smaller Tier A workload
  into its own namespace.
- `check_tokenizer_capacity.py` — **R4B.** Renders every canonical prompt
  through the model's own chat template and counts real tokens. Replaces the
  old char-estimate sizing, which was only safe because the extremes were
  unlikely to be drawn — the canonical construction guarantees them.
- `build_canonical_workload.py --freeze` / `--verify` — **R4C.** Freeze after
  the capacity proof passes; `--verify` re-derives the membership from the
  recorded seed and compares byte-for-byte.
- `generate_headline_schedules.py` — **R5/R6/R11.** The repeat family (exactly
  `N` post-warmup arrivals per schedule, duration an outcome), the
  natural-random secondary family (`--secondary`), and the Tier A scout family
  (`--scout`).
- `gpu_session/verify_prefix_cache_disabled.py` — **L6.** Runs on the instance
  and refuses the session if a replayed long prompt comes back faster than its
  first serving. The CLI flag is not accepted as evidence.

## `hooks/` — repo hooks

`pre-commit` blocks staged changes that would publish GCP billing-account or
project identifiers. This repo is public and the pre-flight docs are written
by pasting real `gcloud` transcripts into them, so shipping an account ID
alongside the proof is a routine mistake, not an exotic one.

```bash
git config core.hooksPath scripts/hooks
```

It scans added lines only, so pre-existing text elsewhere in a file never
blocks an unrelated edit. Thresholds are tuned against this repo's real
content: the 12-digit project-number rule clears the 11-digit CI run IDs in
`BENCHMARKS.md` and the 10-digit unix timestamps in the fixtures. Bypass a
deliberate false positive with `git commit --no-verify`.

## `gpu_session/` — the metered session (human-run only)

In session order:

1. `create_instance.sh` — stand up the L4.
2. `setup_and_launch_vllm.sh` — **remote**; installs vLLM and serves, with the
   three flashinfer workarounds from `docs/GPU_SESSION_NOTES.md`. Eager mode
   is the `ENFORCE_EAGER` env knob (default `1` = `--enforce-eager`, Week 1's
   proven config); `ENFORCE_EAGER=0` is the non-eager first attempt
   `WEEK2_GPU_IMPLEMENTATION_README.md` §3.2 calls for.
3. `run_on_instance.sh bootstrap` — clone the repo on the instance pinned to
   this commit, install the driver's deps.
4. `run_on_instance.sh check` — deps, fd limit, GPU, vLLM health.
5. `run_on_instance.sh stage-a` — drive the Stage A sweep.
6. `pull_artifacts.sh` — copy the artifacts back and verify them **before**
   teardown.
7. `teardown_week2.sh` — delete the L4 and **verify** it is gone.

> **Always `gpu_session/teardown_week2.sh`, never bare `../teardown.sh`.**
> `teardown.sh` is the generic deletion primitive and still defaults to Week 1's
> `llmrouter-vllm-l4`; run bare against a Week 2 session it describes an instance
> that does not exist, prints "nothing to tear down" and exits 0 while the L4 keeps
> billing. The wrapper owns Week 2's `llmrouter-vllm-l4-week2`, prints the resolved
> instance/zone before deleting, and polls afterwards to confirm the instance is
> actually gone (`WEEK2_PLAN.md` §6.4 — do not trust the delete's exit code).
> `DRY_RUN=1` resolves the target and reports without deleting anything.

`remote_loadgen.sh` runs *on* the instance (from the clone) and does the real
work; the local wrapper only issues simple one-command ssh calls, per
`docs/GPU_SESSION_NOTES.md`. `tunnel.sh` is no longer the measurement path —
the loadgen drives on-instance over loopback so WAN latency and SSH
multiplexing stay out of TTFT (`docs/WEEK2_GPU_PREFLIGHT.md` §9).

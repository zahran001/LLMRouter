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
- `generate_schedules.py` — **the** schedule generator, for any RPS points.
  `--rps 32 34 36 38` (explicit) or `--rps-start 30 --rps-stop 40 --rps-step 2`
  (inclusive range). This is what produces Stage B's fine bracket mid-session,
  so no tracked source has to be edited on the meter — which matters because
  `run_on_instance.sh bootstrap` refuses a dirty tree.
- `generate_stage_a_schedules.py` — the committed Stage A coarse schedules. A
  thin wrapper over `generate_schedules.py`; its only distinguishing content is
  the RPS list, so Stage A and Stage B cannot drift apart.
- `compute_point_metrics.py` — recompute per-point metrics offline from the
  committed raw log + samples sidecar, at the warmup N Block F resolves.

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
   three flashinfer workarounds from `docs/GPU_SESSION_NOTES.md`.
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

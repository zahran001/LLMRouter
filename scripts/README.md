# scripts

Operational scripts for benchmark infrastructure.

- `teardown.sh` — delete the GPU instance (parameterized via `INSTANCE_NAME` /
  `ZONE`; verify deletion in the console, not just the exit code).
- `reproduce.sh`, `router_eval.sh` — Week 1 reproduction + router eval gate.
- `build_baseline_corpus.py` — build the pinned ShareGPT corpus artifact.
- `calibrate_noise_floor.py` — Block 0 Linux spin-disabled noise calibration.
- `calibrate_block_c.py` — Block C data generation (shed onset, natural
  concurrency, low-load tracking).
- `generate_stage_a_schedules.py` — pre-generate + commit the Stage A coarse
  schedules.
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
7. `../teardown.sh`.

`remote_loadgen.sh` runs *on* the instance (from the clone) and does the real
work; the local wrapper only issues simple one-command ssh calls, per
`docs/GPU_SESSION_NOTES.md`. `tunnel.sh` is no longer the measurement path —
the loadgen drives on-instance over loopback so WAN latency and SSH
multiplexing stay out of TTFT (`docs/WEEK2_GPU_PREFLIGHT.md` §9).

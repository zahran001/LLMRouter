# GPU Session Notes — GCP + vLLM Setup

Operational knowledge from standing up a real vLLM instance on GCP for the
Week 1 faithfulness check (`docs/archive/week1/WEEK1_CLOSEOUT.md`). Every
item here was a real failure hit during that session, not a hypothetical —
kept here because Week 2 also needs real vLLM on GPU for `BASELINE.md`, and
none of this is visible from reading the code.

Environment this was run from: Windows, `gcloud` using **PuTTY** (`plink`/
`pscp`) as its SSH/SCP backend (not OpenSSH), Windows PowerShell 5.1.

---

## GCP account/quota setup

- **`GPUS_ALL_REGIONS` is a separate project-wide quota** from the
  per-region `NVIDIA_L4_GPUS` / `PREEMPTIBLE_NVIDIA_L4_GPUS` quotas. A new
  project can show the per-region quota as already approved while
  `GPUS_ALL_REGIONS` sits at 0 and blocks every GPU instance creation
  regardless of region. Check both. `GPUS_ALL_REGIONS` increases can't be
  requested via `gcloud` — use Console → IAM & Admin → Quotas, filter for
  "GPUs (all regions)". With active billing history, a request for 1 GPU
  was approved in minutes.
- `gcloud config` had `project` set to the **numeric project number**, not
  the project ID. Most commands accept either, but some (e.g.
  `gcloud compute regions describe`) reject the numeric form outright.
  `gcloud config set project <project-id>` fixes it for the whole session.

## Windows-specific `gcloud`/PuTTY quirks

- **`gcloud compute ssh INSTANCE -- -L 8000:localhost:8000 -N`** (the
  documented `--` passthrough for raw ssh args) does not reliably work on
  Windows — the batch wrapper doesn't pass `--` through, so `-L`/`-N` get
  parsed as gcloud's own (unrecognized) flags. Use `--ssh-flag` instead:
  ```
  gcloud compute ssh INSTANCE --zone=ZONE --ssh-flag="-L 8000:localhost:8000" --ssh-flag="-N"
  ```
- **First contact with a new instance fails with `Server refused our key` /
  `No supported authentication methods available`,** and `pscp` additionally
  stops on an interactive `Store key in cache? (y/n)` host-key prompt that a
  non-interactive shell can never answer. The key hasn't been generated and
  propagated to the instance yet. Fix: pass **`--quiet`**, which accepts the
  host key and lets gcloud provision the key non-interactively —
  ```
  gcloud compute ssh INSTANCE --zone=ZONE --quiet --command="echo ok"
  gcloud compute scp --quiet LOCAL "INSTANCE:/home/<user>/dest" --zone=ZONE
  ```
  Run the `ssh` form once first; `scp` alone does not always trigger the key
  provisioning. Hit for real on 2026-08-18 standing up the scheduler-spin
  calibration VM.
- **`gcloud compute scp SOURCE INSTANCE:~/dest`** — PuTTY's `pscp` doesn't
  reliably expand `~` in the **remote** destination path and fails with
  `pscp: unable to open ~/dest: no such file or directory`. Use an absolute
  remote path instead (`INSTANCE:/home/<user>/dest`).
- **`Out-File -Encoding utf8`** in Windows PowerShell 5.1 always writes a
  UTF-8 **BOM**, even though PowerShell 7's `utf8` doesn't. A script written
  this way and run on Linux via `bash script.sh` fails on line 1 with
  `line 1: <BOM>#!/bin/bash: No such file or directory` (bash doesn't
  recognize the BOM as part of a comment, tries to run it as a command).
  The rest of the script still runs — bash just moves to line 2 — so this
  is often silently non-fatal but noisy. Fix: use `-Encoding ascii` for
  plain-ASCII shell scripts (no BOM), not `utf8`.
- **Chained one-off `gcloud compute ssh --command="a; b; c"` with mixed
  quoting** (nested single/double quotes, `&&`, `;`) intermittently failed
  with exit code 128 and **zero output** — not a normal ssh/plink exit
  code, and inconsistent enough to suggest a quoting-translation issue
  across the bash → `gcloud.cmd` → `plink.exe` chain on Windows, not a
  remote-side failure. Workaround: keep each `--command` to one simple
  command (no chaining, no nested quotes); for anything more complex,
  write a script file locally and `scp` + `ssh --command="bash file.sh"`
  instead of building a complex inline command.
- A secret (e.g. an API token) that must go into a remote command is safer
  written into a local script file and `scp`'d up than interpolated into a
  `--command="..."` string — it sidesteps quoting corruption entirely
  (this project also hit a curly-quote clipboard-paste corruption issue
  typing a long `--command` by hand).

## Image and package choice

- The `deeplearning-platform-release` project's **`common-cu*` image
  family** (e.g. `common-cu129-ubuntu-2204-nvidia-580`) ships NVIDIA
  drivers pre-installed and working (`nvidia-smi` confirms) but has **no
  Docker and no pip** — don't assume "common" DLVM images are
  Docker-ready. Confirmed working recipe on this image:
  ```
  sudo apt-get install -y python3-pip python3-venv
  python3 -m venv ~/vllm-env
  ~/vllm-env/bin/pip install vllm
  ```
- **`gN-standard-*` machine types** (e.g. `g2-standard-8`) bundle the L4
  GPU into the machine type itself — no separate `--accelerator` flag
  needed.
- Reaching the served port (`8000`) via an **SSH tunnel**
  (`--ssh-flag="-L 8000:localhost:8000" --ssh-flag="-N"`) avoids ever
  opening a firewall rule — nothing to remember to clean up alongside
  instance teardown, and it's dead the moment the tunnel process exits.

## vLLM 0.27.1 + this environment: three real crashes, in the order hit

1. **`flashinfer-python` is broken on this Python 3.10.12 build** —
   `TypeError: 'type' object is not subscriptable` on
   `def _fd_ancillary(fd: int) -> tuple[tuple[int, int, array.array[int]]]:`
   inside `flashinfer/comm/fd_exchange.py`. Triggered first via vLLM's
   `torch.compile` backend (an all-reduce-fusion pass, irrelevant at
   `tensor_parallel_size=1`) — worked around with `--enforce-eager`
   (skips `torch.compile`/CUDA graph capture entirely; also the right
   setting for a single-request faithfulness check, not a perf run).
2. Even with `--enforce-eager`, a **second unconditional import** of the
   same broken package (`kernel_warmup` → MiniMax-M3 warmup routine) still
   crashed. Fixed by uninstalling the package outright:
   `pip uninstall -y flashinfer flashinfer-python` — this converts the
   failure mode from `TypeError` (uncaught) to `ModuleNotFoundError`
   (which vLLM's `except ImportError` guards *do* catch in that code path).
3. With the package gone, a **third path** — the sampler's own probe,
   `flashinfer_sampler_supported()` in
   `vllm/v1/sample/ops/topk_topp_sampler.py` — imports
   `vllm.v1.attention.backends.flashinfer`, which does an unconditional
   `from flashinfer import (...)` **not wrapped in try/except** at all.
   Fixed with the documented env var: `VLLM_USE_FLASHINFER_SAMPLER=0`
   (defaults to `True` in `vllm/envs.py`).

   All three were needed together; each one alone still crashed on a
   different code path. Working launch invocation for a single-GPU,
   small-model smoke test on this vLLM version:
   ```
   VLLM_USE_FLASHINFER_SAMPLER=0 vllm serve <model> --port 8000 --enforce-eager --max-model-len <small>
   ```

4. **KV cache sizing**: vLLM sizes KV-cache VRAM for the model's full
   `max_model_len` by default. Llama-3.2-3B-Instruct defaults to 131072,
   which needs ~14.0 GiB of KV cache — doesn't fit an L4's 24GB alongside
   model weights at default `gpu_memory_utilization`, even though the
   model itself is tiny. Not a bug — just an oversized default for a short
   test. Fixed with `--max-model-len 8192` (plenty for a smoke-test prompt,
   leaves large headroom).

## What this means for Week 2

`BASELINE.md` and every load-generator run against real vLLM will hit the
GPU for real, sustained traffic (not a single request) — the
`--max-model-len` cap will need to be sized to whatever the actual test
prompts require, not just "small enough to boot." The flashinfer
workarounds above are almost certainly still needed unless a
`flashinfer-python` release fixes the Python 3.10 incompatibility, or a
different base image ships a different Python version — worth a quick
check before repeating the same three-crash sequence.

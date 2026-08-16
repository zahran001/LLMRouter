# LLMRouter — Week 1 Close-Out & GPU Session Runbook

Paste/attach into a fresh chat to continue. Week 1 is built and verified;
**one paid GPU session** is all that remains to close it.

---

## Status: one step left

Everything except the GPU faithfulness session is done:

- **Measurement pipeline** — mock (4 configs), metrics module, 3-tier suite.
  Both `[CALIBRATE]` values locked with provenance (tolerance floor 10ms /
  ~8ms structural; high-variance p99 multiplier 2.5×). 42/42, 5× determinism.
- **Transparent router** (merged to `main`) — axum + tokio single-replica
  pass-through. Streams via `Body::from_stream(bytes_stream())`, never collects
  the response body. Config-only upstream. 25 eval tests + 2 negative controls.
  **CI green**, controls red where they should be, control-count pinned at 5.
- **Mock trust boundary + loadgen logging plan** — locked
  (`MOCK_TRUST_BOUNDARY.md`).
- **Verification checks done** — `?seed=` RNG-independence confirmed;
  `?echo_headers=` confirmed inert-unless-invoked; request-body asymmetry note
  added to the impl doc.

**The single open item:** "mock→vLLM swap is config-only" is confirmed at the
**code** level (no host/URL/port outside `config.rs`, which has no default),
but stays **unproven until the GPU session** behaviorally confirms it. That
session is below.

---

## The GPU session — purpose, in one line

This session tests exactly ONE thing: **was the mock a faithful stand-in for
real vLLM?** Everything to date proves the router streams correctly *against
the mock*; this proves the mock matched *real vLLM*, so the swap is a no-op.
It is a **faithfulness check, not a benchmark**. No performance runs, no extra
configs, no "while I'm here." Capture, diff, tear down.

---

## Pre-flight (do BEFORE starting any instance — all free)

1. **Confirm GPU quota is live.** Verify L4 quota is actually approved in your
   target region (`us-central1`, fallback `us-east4`). No point standing up
   against a region that rejects. (Memory says quota resolved — confirm it
   still holds on the account.)
2. **Confirm billing.** Pay-as-you-go active (credits expired; this is real
   money against the $150 cap). Budget alerts at $50/$100/$150 set.
3. **Have BOTH commands staged before the meter starts:** the fixture-capture
   `curl` and `teardown.sh`. The instance should live only for stand-up +
   capture; the diff runs locally *after* teardown.
4. **Dry-run `teardown.sh` logic** — know it targets the right instance
   name/zone. A teardown that silently no-ops is how a 2×L4 gets left running
   (~$70/weekend, ~half the budget).

---

## Session steps (minimize paid wall-clock)

### A. Stand up (paid clock starts)
- One **L4 spot** instance, `us-central1` (fallback `us-east4`).
- vLLM serving **Llama-3.2-3B-Instruct**, OpenAI-compatible endpoint on :8000.
- Wait for model load + healthy `/health`.

### B. The config-only swap
- Point the router at the vLLM instance by changing **`UPSTREAM_BASE_URL`
  only** — no code change, no recompile beyond the env value.
- **If any code change is required, STOP and record it** — that falsifies the
  config-only claim and is itself the finding.

### C. Capture the golden fixture (~30s of GPU time)
```
curl -N http://<vllm-host>:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"meta-llama/Llama-3.2-3B-Instruct","messages":[{"role":"user","content":"count to five"}],"stream":true}' \
  > tests/fixtures/vllm_real_stream.txt
```
- Prepend the version+date line: `# captured from vLLM <version> on <date>`.
- Optionally capture one streamed request THROUGH the router too, to eyeball
  that `Content-Length` is absent and `Transfer-Encoding: chunked` is present
  on the real path (the streaming signature holds against real vLLM).

### D. TEAR DOWN NOW (paid clock stops)
- Run `teardown.sh`. **Verify the instance is actually deleted** in the console
  — don't trust the script's exit code alone.
- Everything below is local/free.

### E. Faithfulness diff (local, free, after teardown)
- **Layer 2 — schema assertion** against `vllm_real_stream.txt`: every chunk
  has `id`, `object == "chat.completion.chunk"`, `created`, `model`,
  `choices`; `choices[0]` has `index == 0` and a `delta`; role chunk first;
  first content chunk non-empty; final `finish_reason == "stop"`; stream ends
  with `[DONE]`.
- **Layer 3 — key-set diff** (mock chunk vs real chunk, recursive into
  `choices[0]` and `delta`). Any key vLLM sends that the mock omits = a gap.
- **The real proof:** run the existing parser over the real fixture. It must
  need **zero changes**. If the key-set diff is empty for parser-read fields
  and the parser is a no-op, faithfulness is confirmed.

### F. Commit
- Commit the version-tagged fixture + any diff test. If a gap surfaced, note it
  explicitly (it's a real finding, not a failure — it means re-capture
  deliberately or add the field).

---

## Week 1 DoD — final boxes
- [ ] GPU quota confirmed live; teardown pre-verified (pre-flight)
- [ ] vLLM (Llama-3.2-3B) up; router swap was `UPSTREAM_BASE_URL`-only
- [ ] Golden fixture captured, version+date tagged, committed
- [ ] Instance torn down and delete **verified in console**
- [ ] Schema assertion + key-set diff clean for parser-read fields
- [ ] Parser is a no-op on real stream → **swap confirmed faithful**

When these are ticked, **Week 1 is fully closed.**

---

## Carry-forward into Week 2 (NOT Week 1 work — don't lose them)

- **Linux busy-wait check — now with a first data point.** The CI run on
  `ubuntu-latest` showed the mock's structural TTFT offset at **~3ms**
  (direct p50 ~103ms vs configured 100ms), against ~13–15ms on Windows, with
  S1/S2 nearer their configured values. This points toward "the busy-wait is
  probably NOT needed on Linux" — BUT two caveats travel with that number and
  must stay attached: **(a)** it's a single CI run, one config, no repetition —
  not the calibration; **(b)** `precise_sleep`'s spin was **still enabled**, so
  this does *not* yet test the actual question ("does timing hold on Linux
  *without* the busy-wait?"). Treat as: prior raised, experiment still required.
  The Week-2 check stands — sequential noise calibration on Linux, **spin
  disabled**, repeated at scale. Do NOT read "~3ms" as settling it.
- **Machine-drift signal** — fast/slow/bursty mock timing overshoots the 10ms
  band on the Windows box (fails identically on main; can't reach the router
  verdict). Reinforces that the noise floor is machine-specific; re-measure on
  Linux. Don't fix now.
- **`prompt_len` units** — char count for now; revisit as token count in Week 3
  for KV-cache math.
- **Loadgen raw log** — 5 fields (`request_id`, `send_time`, `close_time`,
  `prompt_id`, `prompt_len`) in a separate `loadgen/` log, never on the metrics
  path. Built when `loadgen/` is implemented.

---

## Then: Week 2 proper
Load generators (`steady.py`, `poisson.py`, `adversarial.py`), ShareGPT prompt
corpus (don't invent prompts), trace capture + deterministic replay, and
`BASELINE.md` ("at X RPS, p99 TTFT crosses 2s on one replica") — the problem
statement everything after is measured against. All reported latency numbers
come from real vLLM on GPU, not the mock. **First action of Week 2:** the
Linux spin-disabled calibration check above.

---

## Immediate next action
Run the pre-flight (quota + billing + staged teardown), then the GPU session:
stand up → swap via env → capture fixture → **tear down and verify** → diff
locally → commit. That closes Week 1.

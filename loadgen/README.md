# loadgen

Open-loop load generators (steady, poisson, adversarial) used to drive
traffic against the router/vLLM during Week 2 benchmarks. Spec:
`WEEK2_PLAN.md` §3; build order: `WEEK2_EXECUTION.md` Block A.

- `rng.py` -- seed -> independent `arrival_rng`/`corpus_rng` streams.
- `corpus.py` -- load the pinned `corpus/baseline_prompts.jsonl`, draw
  prompts (with replacement; `draw_prompt_id_long_context` for adversarial).
- `schedule.py` -- pre-materialize `(scheduled_offset, prompt_id)` schedules
  (Poisson/steady) with an embedded provenance header, before any sending.
- `log.py` -- streamed 6-field raw per-request log
  (`request_id, send_time, close_time, prompt_id, prompt_len, status`).
- `scheduler.py` -- the open-loop scheduler itself: absolute-time,
  fire-and-forget send, concurrency-capped open streams (shed over-cap).
- `steady.py` / `poisson.py` / `adversarial.py` -- CLI entry points
  (`python -m loadgen.poisson --help`).

Committed frozen schedules live under `benchmarks/schedules/`; per-run raw
logs under `benchmarks/runs/` (both gitignored except artifacts explicitly
committed for replay/regression, per WEEK2_PLAN.md §5).

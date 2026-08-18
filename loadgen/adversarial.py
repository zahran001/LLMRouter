#!/usr/bin/env python
"""Open-loop long-context flood generator (WEEK2_PLAN.md §2.1) -- a separate
Week 2 scenario, NOT part of the baseline breach number. Its breach is driven
by per-request cost (long prompts), not arrival rate, so it draws only from
the corpus's long-context tail rather than the natural-spread baseline
sampling.

**The tail cut is a fixed Week 2 constant, not a knob.** It is the 90th
char_len percentile, set in `loadgen.corpus.draw_prompt_id_long_context` and
applied by `loadgen.schedule`, which never passes an override. There is
deliberately no `--long-context-percentile` flag: §2.1 defines adversarial as
one scenario, and a sweepable cut would make it a length sweep -- which §2.2
puts out of scope for Week 2 (it belongs to Week 3, where prompt length
becomes the independent variable). Changing the cut means changing the
constant and re-freezing the schedules, which is the point.

Run LAST in the GPU session runbook (§6.2) -- it deliberately drives the
replica toward saturation and may leave KV cache / scheduler degraded.

Usage:
    python -m loadgen.adversarial --rps 5 --duration 130 --seed 42 \
        --concurrency-cap 50 --mock-config slow --num-tokens 20
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loadgen._cli import add_common_args, build_or_load_schedule, run_and_report, save_schedule

ARRIVAL_PROCESS = "adversarial"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    parser.add_argument("--arrival-shape", choices=["poisson", "steady"], default="poisson",
                         help="arrival process used to schedule the flood (the long-context selection is the adversarial part, not the arrival shape)")
    args = parser.parse_args()

    schedule, corpus = build_or_load_schedule(args, args.arrival_shape, long_context=True)
    if not args.schedule_in:
        save_schedule(schedule, args, ARRIVAL_PROCESS)

    asyncio.run(run_and_report(schedule, corpus, args, ARRIVAL_PROCESS))


if __name__ == "__main__":
    main()

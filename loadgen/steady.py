#!/usr/bin/env python
"""Open-loop steady (fixed-interval) arrival generator (WEEK2_PLAN.md §2.1,
§3). Legible, lower-variance reference curve, captured in the same sweep as
Poisson.

Usage:
    python -m loadgen.steady --rps 20 --duration 130 --seed 42 \
        --concurrency-cap 200 --mock-config slow --num-tokens 20
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loadgen._cli import main_for

if __name__ == "__main__":
    main_for("steady")

"""Verify the ?seed= identity RNG is independent of the mock's timing RNG.

mock/app.py's `_identity_for` builds its own `random.Random(seed)` so that
making seeded responses byte-reproducible (for the router's F1 test) does not
consume the timing RNG and shift which chunks get heavy-tail delays. That
claim is load-bearing: the mock is the project's ground-truth instrument, and
a perturbed draw sequence would silently change what every seeded timing test
measures.

This script proves it by observation rather than by reading the code. It
drives the mock's ASGI app in-process with `precise_sleep` stubbed out (so it
compares which delays were DRAWN, not how accurately they were delivered) and
records the exact sequence `_draw_delay_ms` returns, for several seeds, on
the high-variance config -- the only config whose draws depend on the RNG.

Usage: run it against this checkout and against a pre-change one, then diff
the two JSON outputs. The `draws` maps must be identical.

    git worktree add ../pre-change <commit-before-the-seed-change>
    python scripts/verify_seed_rng_independence.py ../pre-change > old.json
    python scripts/verify_seed_rng_independence.py .            > new.json
    # compare old["draws"] with new["draws"] -- must match exactly

Result on 2026-08-15 (5 seeds x 30 draws, against the pre-change mock):
identical in every position, including the indices where the 4x tail spike
landed. The `bodies` maps differ, which is the intended change.
"""

import asyncio
import json
import sys

WORKTREE = sys.argv[1]
sys.path.insert(0, WORKTREE)

import mock.app as app  # noqa: E402
import httpx  # noqa: E402

import os  # noqa: E402

_want = os.path.normcase(os.path.abspath(os.path.join(WORKTREE, "mock", "app.py")))
_got = os.path.normcase(os.path.abspath(app.__file__))
assert _got == _want, f"imported the wrong mock: {_got} != {_want}"

# Stub the sleep: we are comparing which delays were DRAWN, not delivered.
async def _no_sleep(seconds):
    return


app.precise_sleep = _no_sleep

drawn: list[float] = []
_orig_draw = app._draw_delay_ms


def _recording_draw(base_ms, cfg, rng):
    value = _orig_draw(base_ms, cfg, rng)
    drawn.append(value)
    return value


app._draw_delay_ms = _recording_draw

SEEDS = [1, 42, 999, 20260813, 20260815]
CONFIG = "high-variance"  # the only config whose draws depend on the RNG
NUM_TOKENS = 30


async def one(seed: int, params_extra: dict | None = None) -> tuple[list[float], bytes]:
    drawn.clear()
    transport = httpx.ASGITransport(app=app.app)
    params = {"config": CONFIG, "num_tokens": NUM_TOKENS, "seed": seed}
    params.update(params_extra or {})
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as client:
        response = await client.post(
            "/v1/chat/completions", params=params, json={"model": "mock", "messages": []}
        )
    return list(drawn), response.content


async def main():
    result = {"mock_file": app.__file__, "draws": {}, "bodies": {}}
    for seed in SEEDS:
        draws, body = await one(seed)
        result["draws"][str(seed)] = draws
        result["bodies"][str(seed)] = body.decode("utf-8")

        # Same seed twice: the draw sequence must repeat (this is what the
        # existing seeded timing tests rely on).
        draws_again, body_again = await one(seed)
        result["draws"][f"{seed}-repeat"] = draws_again
        result["bodies"][f"{seed}-repeat"] = body_again.decode("utf-8")

    print(json.dumps(result))


asyncio.run(main())

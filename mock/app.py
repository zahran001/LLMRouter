"""Minimal faithful mock replica of vLLM's OpenAI-compatible streaming API.

Implements the streaming contract locked in WEEK1_MEASUREMENT_SPEC.md §1:
role chunk -> wait ttft_ms -> N content chunks (tpot_ms gaps) -> final chunk
-> [DONE]. Built only to give the metrics module's integration tests real
HTTP streaming to consume (mock is not itself part of the metrics module;
see AGENT_METRICS_BRIEF.md §7 for what's out of scope). Not a general-purpose
vLLM stand-in -- routing, admission control, batching, etc. are not modeled.

Run standalone: `uvicorn mock.app:app --port 9001`
"""

from __future__ import annotations

import asyncio
import json
import random
import time
import uuid

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from mock.configs import CONFIGS, TAIL_MULTIPLIER, TAIL_PROBABILITY, MockConfig

DEFAULT_MODEL = "meta-llama/Llama-3.2-3B-Instruct"
DEFAULT_NUM_TOKENS = 20


def _draw_delay_ms(base_ms: float, cfg: MockConfig, rng: random.Random) -> float:
    """One delay draw for either the ttft wait or one tpot gap.

    Stable configs return base_ms exactly (any run-to-run spread observed in
    practice is real scheduler/OS jitter, not injected -- that's the noise
    the calibration task measures). heavy_tailed configs additionally inject
    a large right-tail delay on a minority of draws (spec §5).
    """
    if cfg.heavy_tailed and rng.random() < TAIL_PROBABILITY:
        return base_ms * TAIL_MULTIPLIER
    return base_ms


def _make_chunk(chat_id: str, created: int, model: str, delta: dict, finish_reason: str | None) -> dict:
    return {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def _sse(chunk_dict: dict) -> str:
    return f"data: {json.dumps(chunk_dict)}\n\n"


async def chat_completions(request: Request) -> StreamingResponse:
    body = await request.json() if request.headers.get("content-length") not in (None, "0") else {}
    model = body.get("model", DEFAULT_MODEL)

    config_name = request.query_params.get("config", "fast")
    cfg = CONFIGS.get(config_name)
    if cfg is None:
        return JSONResponse(
            {"error": f"unknown config {config_name!r}, expected one of {sorted(CONFIGS)}"},
            status_code=400,
        )

    num_tokens = int(request.query_params.get("num_tokens", DEFAULT_NUM_TOKENS))
    seed_param = request.query_params.get("seed")
    rng = random.Random(int(seed_param)) if seed_param is not None else random.Random()

    async def event_stream():
        chat_id = f"chatcmpl-{uuid.uuid4()}"
        created = int(time.time())

        # 1. role chunk, emitted immediately, BEFORE the ttft_ms wait.
        yield _sse(_make_chunk(chat_id, created, model, {"role": "assistant"}, None))

        # 2. wait ttft_ms
        await asyncio.sleep(_draw_delay_ms(cfg.ttft_ms, cfg, rng) / 1000.0)

        # 3. N content chunks, tpot_ms gap between consecutive ones
        for i in range(num_tokens):
            if i > 0:
                await asyncio.sleep(_draw_delay_ms(cfg.tpot_ms, cfg, rng) / 1000.0)
            yield _sse(_make_chunk(chat_id, created, model, {"content": f"tok{i} "}, None))

        # 4. final chunk
        yield _sse(_make_chunk(chat_id, created, model, {}, "stop"))

        # 5. terminator
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "configs": sorted(CONFIGS)})


app = Starlette(
    routes=[
        Route("/v1/chat/completions", chat_completions, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ]
)

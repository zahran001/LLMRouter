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

import json
import random
import time
import uuid

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from mock.configs import CONFIGS, TAIL_MULTIPLIER, TAIL_PROBABILITY, MockConfig
from mock.timing import precise_sleep

DEFAULT_MODEL = "meta-llama/Llama-3.2-3B-Instruct"
DEFAULT_NUM_TOKENS = 20

# Fixed `created` value used only when a request carries ?seed=. See
# _identity_for below.
SEEDED_CREATED = 1_700_000_000

# Real vLLM appends a `system_fingerprint` to the finish_reason chunk (the
# captured fixture shows "vllm-0.27.1-nohash"). The mock declares itself as a
# mock rather than impersonating a vLLM build string -- the faithfulness
# check compares key SETS, not values, and a reader tailing the mock's stream
# should never mistake it for the real server. Constant, not generated: the
# router's F1 byte-identity test needs seeded responses to be reproducible.
SYSTEM_FINGERPRINT = "mock-replica-nohash"


def _draw_delay_ms(base_ms: float, cfg: MockConfig, rng: random.Random) -> float:
    """One delay draw for either the ttft wait or one tpot gap, in ms --
    the caller converts to seconds and passes it to precise_sleep (which
    delivers it precisely; this function only decides its magnitude).

    Stable configs return base_ms exactly: ground truth is the configured
    value, delivered with sub-ms accuracy by precise_sleep (mock/timing.py),
    not an empirical baseline. heavy_tailed configs additionally inject a
    large right-tail delay on a minority of draws (spec §5) -- the tail
    spike is just a larger duration handed to the same precise_sleep, so
    it's delivered precisely too, not a return to raw/imprecise sleep.
    """
    if cfg.heavy_tailed and rng.random() < TAIL_PROBABILITY:
        return base_ms * TAIL_MULTIPLIER
    return base_ms


def _identity_for(seed: int | None) -> tuple[str, int]:
    """Return (chat_id, created) for one response.

    Unseeded requests get a fresh uuid4 and the current epoch second, exactly
    as vLLM would. A **seeded** request instead gets an id/created derived
    from the seed, so the same (config, num_tokens, seed) request produces a
    byte-identical response every time.

    That determinism is what gives the router's byte-identity test (F1,
    WEEK1_ROUTER_IMPL.md §4.1) an oracle: "client->mock directly" and
    "client->router->mock" are necessarily two separate requests, so without
    it the uuid and timestamp alone would make identical bytes impossible and
    F1 would have to weaken to semantic equivalence -- the exact weakening
    F1 exists to rule out.

    The id is drawn from its own Random instance so the timing RNG's draw
    sequence (and therefore every existing seeded timing test) is unaffected.
    """
    if seed is None:
        return f"chatcmpl-{uuid.uuid4()}", int(time.time())

    id_rng = random.Random(seed)
    return f"chatcmpl-{uuid.UUID(int=id_rng.getrandbits(128), version=4)}", SEEDED_CREATED


# Faithfulness Layer 3 (WEEK1_MEASUREMENT_SPEC.md §6): the key SET of every
# chunk the mock emits must cover the key set real vLLM emits, checked
# recursively against the captured fixture by
# tests/faithfulness/test_real_fixture.py::test_real_stream_key_set_matches_mock.
#
# The three chunk kinds below carry DIFFERENT key sets in real vLLM 0.27.1 --
# they are not one shape with varying values -- so they are built separately
# rather than emitting the union on every chunk. Emitting the union would pass
# the test while being *less* faithful (real vLLM never puts prompt_token_ids
# on a content chunk), and the point of Layer 3 is shape fidelity, not a green
# check. Every value below is null/empty because the mock has no tokenizer, no
# logprobs and no real prompt echo; the contract being mirrored is the shape
# and type, not the content.
#
# Verified against tests/fixtures/vllm_real_stream.txt (vLLM 0.27.1,
# meta-llama/Llama-3.2-3B-Instruct, captured 2026-08-16).


def _make_chunk(chat_id: str, created: int, model: str, delta: dict, finish_reason: str | None,
                *, choice_extra: dict | None = None, top_extra: dict | None = None) -> dict:
    chunk = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{
            "index": 0,
            "delta": delta,
            # Real vLLM sends logprobs on every chunk kind (null when not
            # requested). Present-and-null, not absent.
            "logprobs": None,
            "finish_reason": finish_reason,
            **(choice_extra or {}),
        }],
    }
    chunk.update(top_extra or {})
    return chunk


def _role_chunk(chat_id: str, created: int, model: str) -> dict:
    """Real vLLM's role chunk carries `content: ""` alongside the role, and
    echoes prompt_token_ids/prompt_text (null unless explicitly requested) at
    the top level -- only on this first chunk.

    The empty-string content is deliberate and load-bearing: metrics/parse.py
    classifies a chunk as content iff delta.content is a NON-EMPTY string, so
    this chunk stays a non-content chunk and TTFT is still measured to the
    first real token. Emitting `""` here matches vLLM without touching that
    contract."""
    return _make_chunk(
        chat_id, created, model, {"role": "assistant", "content": ""}, None,
        top_extra={"prompt_token_ids": None, "prompt_text": None},
    )


def _content_chunk(chat_id: str, created: int, model: str, text: str) -> dict:
    """Content chunks add per-choice `token_ids` and, unlike the role chunk,
    carry no top-level prompt echo."""
    return _make_chunk(
        chat_id, created, model, {"content": text}, None,
        choice_extra={"token_ids": None},
    )


def _final_chunk(chat_id: str, created: int, model: str) -> dict:
    """The finish_reason chunk. Real vLLM sends `delta: {"content": ""}` (not
    an empty delta), adds `stop_reason`, and appends a top-level
    `system_fingerprint`."""
    return _make_chunk(
        chat_id, created, model, {"content": ""}, "stop",
        choice_extra={"stop_reason": None, "token_ids": None},
        top_extra={"system_fingerprint": SYSTEM_FINGERPRINT},
    )


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
    seed = int(seed_param) if seed_param is not None else None
    rng = random.Random(seed) if seed is not None else random.Random()

    # Debug affordance for the router's H1 test (WEEK1_ROUTER_IMPL.md §4.4:
    # "have the mock echo received headers on a debug route"). It hangs off
    # the chat path rather than a separate route because the Week 1 router
    # only proxies /v1/chat/completions -- a debug route on any other path
    # would be unreachable through the router, which is the only place the
    # question "what headers actually arrived?" can be asked.
    if request.query_params.get("echo_headers") is not None:
        return JSONResponse({"headers": {k.lower(): v for k, v in request.headers.items()}})

    async def event_stream():
        chat_id, created = _identity_for(seed)

        # 1. role chunk, emitted immediately, BEFORE the ttft_ms wait.
        yield _sse(_role_chunk(chat_id, created, model))

        # 2. wait ttft_ms
        await precise_sleep(_draw_delay_ms(cfg.ttft_ms, cfg, rng) / 1000.0)

        # 3. N content chunks, tpot_ms gap between consecutive ones
        for i in range(num_tokens):
            if i > 0:
                await precise_sleep(_draw_delay_ms(cfg.tpot_ms, cfg, rng) / 1000.0)
            yield _sse(_content_chunk(chat_id, created, model, f"tok{i} "))

        # 4. final chunk
        yield _sse(_final_chunk(chat_id, created, model))

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

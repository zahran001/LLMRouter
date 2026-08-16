"""Client-side drivers for the router eval.

Everything here is **strictly sequential** -- one request in flight at a time,
always. The Week 1 router suite issues no concurrent load at all: the mock's
delivered timing is only trusted sequentially (MOCK_TRUST_BOUNDARY.md §1), so
a concurrent measurement here would mix router overhead with the mock's known
concurrency artifact and produce an uninterpretable number.

Timing capture reuses the locked metrics module (metrics.consume_stream) as
its oracle rather than re-deriving TTFT/TPOT here.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

import httpx

from metrics import parse
from metrics.consume import consume_stream
from metrics.types import RequestSample

CHAT_PATH = "/v1/chat/completions"
WRONG_BUFFERS_PATH = "/__wrong__/buffers/v1/chat/completions"
WRONG_REEMIT_PATH = "/__wrong__/reemit/v1/chat/completions"

REQUEST_BODY = {"model": "mock", "messages": [{"role": "user", "content": "count to five"}]}
TIMEOUT_S = 60.0


@dataclass
class RawCapture:
    status: int
    headers: httpx.Headers
    body: bytes


def request_params(config: str, num_tokens: int, seed: int | None = None) -> dict:
    params: dict[str, object] = {"config": config, "num_tokens": num_tokens}
    if seed is not None:
        params["seed"] = seed
    return params


async def capture_raw(base_url: str, params: dict, path: str = CHAT_PATH, headers: dict | None = None) -> RawCapture:
    """Read one response body as raw bytes, undecoded and unparsed."""
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        async with client.stream(
            "POST", f"{base_url}{path}", params=params, json=REQUEST_BODY, headers=headers
        ) as response:
            body = b"".join([chunk async for chunk in response.aiter_raw()])
            return RawCapture(status=response.status_code, headers=response.headers, body=body)


async def sample_one(base_url: str, params: dict, path: str = CHAT_PATH) -> RequestSample:
    """One request, measured through the locked metrics consumer."""
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        return await _sample_with(client, base_url, params, path)


async def _sample_with(client: httpx.AsyncClient, base_url: str, params: dict, path: str) -> RequestSample:
    # t0 immediately before the send is awaited, per the consume_stream
    # contract (WEEK1_MEASUREMENT_SPEC.md §2).
    t0 = time.perf_counter()
    async with client.stream("POST", f"{base_url}{path}", params=params, json=REQUEST_BODY) as response:
        return await consume_stream(response, t0)


def parsed_chunks(raw: bytes) -> list[dict]:
    """Every non-terminator SSE chunk in a captured body, via the locked parser."""
    chunks = []
    for line in raw.decode("utf-8").split("\n"):
        parsed = parse.parse_sse_line(line)
        if parsed is None or parsed == parse.DONE:
            continue
        chunks.append(parsed)
    return chunks


def first_content_index(chunks: list[dict]) -> int | None:
    """Position of the first content-bearing chunk -- the parser's t_first
    gating decision, expressed without reference to any clock."""
    for i, chunk in enumerate(chunks):
        if parse.is_content_chunk(chunk):
            return i
    return None


@dataclass
class OverheadArm:
    """Direct vs proxied TTFT for one response size."""

    label: str
    num_tokens: int
    direct_ttft_ms: list[float]
    proxied_ttft_ms: list[float]

    @property
    def direct_median_ms(self) -> float:
        return statistics.median(self.direct_ttft_ms)

    @property
    def proxied_median_ms(self) -> float:
        return statistics.median(self.proxied_ttft_ms)

    @property
    def delta_ms(self) -> float:
        return self.proxied_median_ms - self.direct_median_ms

    def describe(self) -> str:
        return (
            f"{self.label} (num_tokens={self.num_tokens}, n={len(self.direct_ttft_ms)}): "
            f"direct p50 {self.direct_median_ms:.2f}ms, proxied p50 {self.proxied_median_ms:.2f}ms, "
            f"delta {self.delta_ms:+.2f}ms"
        )


async def measure_overhead_arm(
    label: str,
    mock_base_url: str,
    proxied_base_url: str,
    config: str,
    num_tokens: int,
    n: int,
    warmup: int,
    proxied_path: str = CHAT_PATH,
) -> OverheadArm:
    """N sequential request pairs, direct and proxied, interleaved.

    Interleaved rather than block-by-block so any slow drift in machine state
    lands on both arms equally instead of on whichever ran second. Still one
    request in flight at a time -- the pair is sequential too. Each arm keeps
    its own client open across the loop so the connection pool stays warm
    (WEEK1_MEASUREMENT_SPEC.md §2) and TTFT is steady-state.
    """
    params = request_params(config, num_tokens)
    direct: list[float] = []
    proxied: list[float] = []

    async with httpx.AsyncClient(timeout=TIMEOUT_S) as direct_client:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as proxied_client:
            for i in range(warmup + n):
                d = await _sample_with(direct_client, mock_base_url, params, CHAT_PATH)
                p = await _sample_with(proxied_client, proxied_base_url, params, proxied_path)
                if i < warmup:
                    continue
                assert d.ttft_ms is not None and p.ttft_ms is not None, "request produced no content chunk"
                direct.append(d.ttft_ms)
                proxied.append(p.ttft_ms)

    return OverheadArm(label=label, num_tokens=num_tokens, direct_ttft_ms=direct, proxied_ttft_ms=proxied)

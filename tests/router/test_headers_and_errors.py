"""H1, H2, E1, E2 (WEEK1_ROUTER_IMPL.md §4.4).

Behaviour only. Week 1 errors are deliberately minimal -- connect failure is
a 502 and a dead upstream truncates the stream honestly. Retries, fallback
and graceful shutdown are Week 6 and are not exercised (or hinted at) here.
"""

from __future__ import annotations

import time

import httpx
import pytest

from tests.router._client import CHAT_PATH, REQUEST_BODY, TIMEOUT_S, capture_raw, request_params
from tests.router.conftest import TRUNCATED_PREFIX

pytestmark = [pytest.mark.integration, pytest.mark.router]


async def test_h1_request_headers_forwarded_and_hop_by_hop_dropped(router_base_url, mock_base_url):
    """H1 -- the allowlist arrives, the connection-level headers do not."""
    sent = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Authorization": "Bearer test-token",
        # Should not reach the upstream: hop-by-hop, plus one ordinary header
        # that simply is not on the allowlist. "close" rather than
        # "keep-alive" so the assertion below discriminates -- hyper may
        # legitimately set its own Connection header on the hop it makes, but
        # it would never choose the value the client happened to send here.
        "Connection": "close",
        "X-Client-Only": "should-not-be-forwarded",
    }

    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        response = await client.post(
            f"{router_base_url}{CHAT_PATH}",
            params={"config": "fast", "echo_headers": "1"},
            json=REQUEST_BODY,
            headers=sent,
        )
    assert response.status_code == 200
    received = response.json()["headers"]

    assert received["content-type"] == "application/json"
    assert received["accept"] == "text/event-stream"
    assert received["authorization"] == "Bearer test-token"

    assert "x-client-only" not in received
    assert received.get("connection", "").lower() != "close"
    # Host must describe the hop the router actually made, not the router's
    # own address as the client addressed it.
    assert received["host"] == mock_base_url.removeprefix("http://")
    # The router sends a body of known length, so no chunked request framing
    # should be forwarded or invented.
    assert "transfer-encoding" not in received
    assert received["content-length"] == str(len(response.request.content))


async def test_h2_response_content_type_preserved(router_base_url):
    """H2 -- the client sees text/event-stream on the proxied response."""
    proxied = await capture_raw(router_base_url, request_params("fast", 3))

    assert proxied.status == 200
    assert proxied.headers["content-type"] == "text/event-stream; charset=utf-8"
    # Framing belongs to axum/hyper: a hand-copied Content-Length would show
    # up here and would contradict a streamed body.
    assert "content-length" not in proxied.headers


async def test_e1_upstream_down_returns_502(router_dead_upstream_base_url):
    """E1 -- nothing listening upstream is a 502, not a hang and not a 500."""
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        response = await client.post(
            f"{router_dead_upstream_base_url}{CHAT_PATH}",
            params=request_params("fast", 3),
            json=REQUEST_BODY,
        )

    assert response.status_code == 502, f"expected 502, got {response.status_code}: {response.text[:200]}"


async def test_e1_router_itself_stays_healthy_after_upstream_failure(router_dead_upstream_base_url):
    """A failed upstream must not take the router down with it."""
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        await client.post(
            f"{router_dead_upstream_base_url}{CHAT_PATH}",
            params=request_params("fast", 3),
            json=REQUEST_BODY,
        )
        health = await client.get(f"{router_dead_upstream_base_url}/health")

    assert health.status_code == 200


async def test_e2_mid_stream_drop_truncates_cleanly(router_over_truncating_upstream):
    """E2 -- an upstream that dies mid-stream ends the client's stream.

    Either outcome is acceptable and both are honest: the client may see the
    stream simply end, or see a protocol error for the unterminated chunked
    body. What is not acceptable is a hang, a panic, or bytes the upstream
    never sent. Resilience (retry, resume) is Week 6.
    """
    base_url, router_proc = router_over_truncating_upstream

    received = b""
    protocol_error = None
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            async with client.stream(
                "POST", f"{base_url}{CHAT_PATH}", params=request_params("fast", 3), json=REQUEST_BODY
            ) as response:
                assert response.status_code == 200
                async for chunk in response.aiter_raw():
                    received += chunk
        except (httpx.RemoteProtocolError, httpx.ReadError) as exc:
            protocol_error = exc
    elapsed_s = time.perf_counter() - t0

    assert elapsed_s < 10.0, f"stream did not end promptly ({elapsed_s:.1f}s) -- the router hung"
    assert TRUNCATED_PREFIX.startswith(received), "client received bytes the upstream never sent"
    assert router_proc.is_alive(), "router process died on a mid-stream upstream drop"

    async with httpx.AsyncClient(timeout=5.0) as client:
        assert (await client.get(f"{base_url}/health")).status_code == 200

    print(f"\nE2: {len(received)}/{len(TRUNCATED_PREFIX)} bytes before truncation, "
          f"protocol_error={type(protocol_error).__name__ if protocol_error else None}")

"""Shared fixtures: a live mock server for Tier 2/3 tests.

Tier 1 (pure unit) tests do not use this fixture at all -- they import
metrics.compute / metrics.parse directly with synthetic inputs.
"""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import uvicorn

from mock.app import app as mock_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _UvicornThread:
    """Runs the mock Starlette app in a background OS thread with its own
    event loop, independent of pytest-asyncio's per-test loop."""

    def __init__(self, app, port: int):
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self, timeout: float = 5.0) -> None:
        self.thread.start()
        deadline = time.monotonic() + timeout
        while not self.server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("mock server did not start within timeout")
            time.sleep(0.01)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5.0)


@pytest.fixture(scope="session")
def mock_base_url():
    port = _free_port()
    runner = _UvicornThread(mock_app, port)
    runner.start()
    base_url = f"http://127.0.0.1:{port}"

    # Confirm liveness before handing off to tests.
    with httpx.Client(timeout=5.0) as c:
        deadline = time.monotonic() + 5.0
        while True:
            try:
                r = c.get(f"{base_url}/health")
                if r.status_code == 200:
                    break
            except httpx.TransportError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("mock server did not become healthy in time")
            time.sleep(0.02)

    yield base_url
    runner.stop()

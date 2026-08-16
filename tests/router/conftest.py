"""Fixtures for the Week 1 router eval.

Builds the Rust router once per session and runs it as a real process against
real upstreams -- the eval's claims are about client-observed bytes and
client-observed arrival times, so an in-process harness would test something
weaker than what ships.

Three upstream shapes are needed: the live mock (the normal case), an address
with nothing listening (E1), and a server that starts a response then drops
the connection mid-stream (E2). The mock fixture itself comes from
tests/conftest.py.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTER_MANIFEST = REPO_ROOT / "router" / "Cargo.toml"

# Release, not debug: O1 asserts the router's overhead disappears inside a
# 10ms noise floor, and that claim should be made about the binary that would
# actually be deployed.
CARGO_PROFILE = "release"

# The negative controls are compiled in for the whole eval (they mount on
# their own paths and leave the real route untouched), so one router process
# serves all three arms with no startup skew between them.
CARGO_FEATURES = "wrong-routers"

STARTUP_TIMEOUT_S = 20.0


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class RouterProcess:
    """One `llmrouter` process, pointed at a fixed upstream."""

    def __init__(self, binary: Path, upstream_base_url: str, log_path: Path):
        self.binary = binary
        self.upstream_base_url = upstream_base_url
        self.port = free_port()
        self.log_path = log_path
        self.proc: subprocess.Popen | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        env = dict(os.environ, UPSTREAM_BASE_URL=self.upstream_base_url, ROUTER_PORT=str(self.port))
        # Logs go to a file rather than a pipe nobody drains: a full pipe
        # buffer would block the router mid-eval and look like a hang.
        self.log = self.log_path.open("wb")
        self.proc = subprocess.Popen([str(self.binary)], env=env, stdout=self.log, stderr=self.log)

        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        with httpx.Client(timeout=2.0) as c:
            while True:
                if self.proc.poll() is not None:
                    raise RuntimeError(
                        f"router exited during startup (code {self.proc.returncode}); "
                        f"log: {self.log_path.read_text(errors='replace')}"
                    )
                try:
                    if c.get(f"{self.base_url}/health").status_code == 200:
                        return
                except httpx.TransportError:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError(f"router did not become healthy within {STARTUP_TIMEOUT_S}s")
                time.sleep(0.02)

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.log.close()


@pytest.fixture(scope="session")
def router_binary() -> Path:
    build = subprocess.run(
        [
            "cargo", "build",
            f"--{CARGO_PROFILE}",
            "--features", CARGO_FEATURES,
            "--manifest-path", str(ROUTER_MANIFEST),
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if build.returncode != 0:
        pytest.fail(f"cargo build failed:\n{build.stdout}\n{build.stderr}")

    exe = "llmrouter.exe" if os.name == "nt" else "llmrouter"
    binary = ROUTER_MANIFEST.parent / "target" / CARGO_PROFILE / exe
    if not binary.exists():
        pytest.fail(f"router binary not found at {binary}")
    return binary


@pytest.fixture(scope="session")
def router_log_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("router-logs")


@pytest.fixture(scope="session")
def router(router_binary, mock_base_url, router_log_dir) -> RouterProcess:
    """The router under test, proxying to the live mock."""
    proc = RouterProcess(router_binary, mock_base_url, router_log_dir / "router.log")
    proc.start()
    yield proc
    proc.stop()


@pytest.fixture(scope="session")
def router_base_url(router) -> str:
    return router.base_url


@pytest.fixture(scope="session")
def router_dead_upstream_base_url(router_binary, router_log_dir) -> str:
    """A router pointed at an address with nothing listening on it (E1)."""
    dead_port = free_port()  # bound and released, so nothing is listening
    proc = RouterProcess(
        router_binary, f"http://127.0.0.1:{dead_port}", router_log_dir / "router-dead-upstream.log"
    )
    proc.start()
    yield proc.base_url
    proc.stop()


# --- E2: an upstream that drops the connection mid-stream ------------------

TRUNCATED_PREFIX = (
    b'data: {"id": "chatcmpl-truncated", "object": "chat.completion.chunk", '
    b'"created": 1700000000, "model": "mock", "choices": [{"index": 0, '
    b'"delta": {"role": "assistant"}, "finish_reason": null}]}\n\n'
    b'data: {"id": "chatcmpl-truncated", "object": "chat.completion.chunk", '
    b'"created": 1700000000, "model": "mock", "choices": [{"index": 0, '
    b'"delta": {"content": "tok0 "}, "finish_reason": null}]}\n\n'
)


class TruncatingUpstream:
    """Raw HTTP/1.1 server that opens a chunked SSE response, sends two real
    events, then closes the socket **without** the terminating chunk.

    Hand-rolled rather than added to the mock: the mock is the faithful vLLM
    stand-in and has no business learning how to be broken. This is the
    "mock config that closes early" option in WEEK1_ROUTER_IMPL.md §4.4 E2,
    kept outside the faithful path.
    """

    def __init__(self):
        self.port = free_port()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop_event: asyncio.Event | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, ConnectionError):
            writer.close()
            return

        # Drain the request body so the peer never sees a reset while writing.
        length = 0
        for line in head.decode("latin-1").split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        if length:
            await reader.readexactly(length)

        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream; charset=utf-8\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"Cache-Control: no-cache\r\n\r\n"
        )
        writer.write(f"{len(TRUNCATED_PREFIX):x}\r\n".encode() + TRUNCATED_PREFIX + b"\r\n")
        await writer.drain()

        # No terminating "0\r\n\r\n": FIN arrives mid-message, which is
        # exactly what an upstream dying mid-generation looks like.
        await asyncio.sleep(0.05)
        writer.close()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()

        async def serve():
            server = await asyncio.start_server(self._handle, "127.0.0.1", self.port)
            self._ready.set()
            async with server:
                # Shut down by resolving the wait, not by stopping the loop
                # out from under it -- the latter leaves the server socket
                # half-closed and pytest reports it as an unraisable
                # exception in teardown.
                await self._stop_event.wait()

        self._loop.run_until_complete(serve())
        self._loop.close()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            raise RuntimeError("truncating upstream did not start")

    def stop(self) -> None:
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread is not None:
            self._thread.join(timeout=5.0)


@pytest.fixture(scope="session")
def router_over_truncating_upstream(router_binary, router_log_dir):
    """(router_base_url, RouterProcess) for a router whose upstream dies
    mid-stream (E2). The process handle comes back so the test can assert the
    router survived."""
    upstream = TruncatingUpstream()
    upstream.start()
    proc = RouterProcess(
        router_binary, upstream.base_url, router_log_dir / "router-truncating-upstream.log"
    )
    proc.start()
    yield proc.base_url, proc
    proc.stop()
    upstream.stop()

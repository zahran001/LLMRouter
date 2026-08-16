"""Open-loop scheduler (WEEK2_PLAN.md §3.1/§3.3).

Request completion never gates the next send. A closed-loop generator
(send -> wait -> send) lets server latency feed back into arrival timing, so
it backs off exactly at the breach and therefore can't observe it. This is
the one piece Hard Stop 1 (WEEK2_EXECUTION.md) exists to eyeball: the send
loop below must never `await` a send's *issue* -- only the scheduling sleep.

Mechanism (all LOCKED, see WEEK2_PLAN.md §3.3):
- Absolute-time scheduling: each send targets `t_start + scheduled_offset`,
  independently -- a late send does not push later sends late.
- Fire-and-forget async task spawn: the loop sleeps-until the target, spawns
  a task, and immediately continues. It never awaits the send.
- Per-send scheduling lag (`scheduled_offset` vs actual `send_time`) is
  logged -- the ground-truth instrument for open-loop fidelity.
- In-flight *streaming responses* (not sends-in-flight) are bounded by a
  concurrency cap; over-cap spawns fail fast as `shed`, never block.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import httpx

from loadgen.corpus import Corpus
from loadgen.log import RunLogger
from loadgen.schedule import Schedule
from metrics.consume import consume_stream
from metrics.types import RequestSample


@dataclass
class RunResult:
    n_scheduled: int
    n_sent: int
    n_shed: int
    n_errored: int
    achieved_rps: float
    window_s: float
    per_send_lag_s: list[float] = field(default_factory=list)
    samples: dict[int, RequestSample] = field(default_factory=dict)  # request_id -> sample, sent only


class OpenLoopScheduler:
    def __init__(
        self,
        schedule: Schedule,
        corpus: Corpus,
        base_url: str,
        logger: RunLogger,
        concurrency_cap: int,
        endpoint_path: str = "/v1/chat/completions",
        query_params: dict | None = None,
        extra_body: dict | None = None,
        model: str = "mock",
        timeout_s: float = 60.0,
        capture_samples: bool = True,
    ):
        self.schedule = schedule
        self.corpus = corpus
        self.base_url = base_url.rstrip("/")
        self.endpoint_path = endpoint_path
        self.query_params = query_params or {}
        self.extra_body = {"stream": True, **(extra_body or {})}
        self.model = model
        self.logger = logger
        self.concurrency_cap = concurrency_cap
        self.timeout_s = timeout_s
        self.capture_samples = capture_samples

        # Plain int, no lock: check-then-increment below has no `await`
        # between the two statements, so it's atomic under asyncio's
        # cooperative (single-threaded, non-preemptive) scheduling -- a lock
        # would add nothing here and asyncio.Lock.acquire() is itself a
        # coroutine, which would just be extra ceremony around the same
        # guarantee.
        self._open_streams = 0
        self._per_send_lag: list[float] = []
        self._n_sent = 0
        self._n_shed = 0
        self._n_errored = 0
        self._samples: dict[int, RequestSample] = {}

    async def run(self) -> RunResult:
        limits = httpx.Limits(
            max_connections=self.concurrency_cap + 10,
            max_keepalive_connections=self.concurrency_cap + 10,
        )
        async with httpx.AsyncClient(timeout=self.timeout_s, limits=limits) as client:
            self._client = client
            t_start = time.monotonic()
            tasks: list[asyncio.Task] = []

            for request_id, entry in enumerate(self.schedule.entries):
                target = t_start + entry.scheduled_offset
                delay = target - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)

                # Fire-and-forget: create the task and move straight to the
                # next scheduled send. Never `await task` here.
                task = asyncio.create_task(self._handle(request_id, entry, t_start))
                tasks.append(task)

            # After every send has been *issued*, wait for in-flight streams
            # to drain so the run only returns once every response is
            # accounted for. This await is outside the scheduling loop, so it
            # cannot delay any send.
            await asyncio.gather(*tasks)
            window_s = time.monotonic() - t_start

        n_scheduled = len(self.schedule.entries)
        achieved_rps = self._n_sent / window_s if window_s > 0 else 0.0
        return RunResult(
            n_scheduled=n_scheduled,
            n_sent=self._n_sent,
            n_shed=self._n_shed,
            n_errored=self._n_errored,
            achieved_rps=achieved_rps,
            window_s=window_s,
            per_send_lag_s=self._per_send_lag,
            samples=self._samples,
        )

    async def _handle(self, request_id: int, entry, t_start: float) -> None:
        prompt = self.corpus.prompts[entry.prompt_id]

        if self._open_streams >= self.concurrency_cap:
            self._n_shed += 1
            self.logger.write(request_id, None, None, entry.prompt_id, prompt.char_len, "shed")
            return
        self._open_streams += 1

        send_time = time.monotonic()
        self._per_send_lag.append(send_time - (t_start + entry.scheduled_offset))
        url = f"{self.base_url}{self.endpoint_path}"
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt.text}], **self.extra_body}

        try:
            async with self._client.stream("POST", url, params=self.query_params, json=body) as response:
                response.raise_for_status()
                if self.capture_samples:
                    sample = await consume_stream(response, send_time, clock=time.monotonic)
                    self._samples[request_id] = sample
                else:
                    async for _ in response.aiter_lines():
                        pass
            close_time = time.monotonic()
            self._n_sent += 1
            self.logger.write(
                request_id, send_time - t_start, close_time - t_start, entry.prompt_id, prompt.char_len, "sent"
            )
        except Exception:
            close_time = time.monotonic()
            self._n_errored += 1
            self.logger.write(
                request_id, send_time - t_start, close_time - t_start, entry.prompt_id, prompt.char_len, "errored"
            )
        finally:
            self._open_streams -= 1

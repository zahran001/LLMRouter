"""Per-request on-disk logs, streamed as each row is produced -- never
buffered in memory until the run ends, so a crash mid-run doesn't lose
everything before it (same discipline as the GPU session's
durable-on-produce recording, §6.3).

Two files per run, both keyed by `request_id`:

- `RunLogger` -> `<tag>.raw_log.jsonl`, the **locked** raw log
  (WEEK2_PLAN.md §3.1): 5 fields + status -- request_id, send_time,
  close_time, prompt_id, prompt_len, status in {sent, shed, errored}.
  This schema is locked; do not add fields to it.
- `SampleLogger` -> `<tag>.samples.jsonl`, the per-request TTFT/TPOT
  sidecar (§6.3). Deliberately a *separate* file rather than extra columns
  on the raw log, precisely so §3.1's locked schema stays untouched: §6.3
  requires per-request TTFT-vs-wall-clock transient data and per-point
  percentiles, which §3.1's six fields cannot carry (close_time bounds the
  whole stream; there is no first-token time in it). Joined back to the raw
  log on request_id offline (metrics/point.py).

Both are written and flushed per row. The sidecar carries `send_time` in
the same t_start-relative basis as the raw log, which is what makes the
time-based warmup filter (§2.4) and the warmup-N transient plot possible
without a join.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Literal

from metrics.types import RequestSample

Status = Literal["sent", "shed", "errored"]


class _JsonlWriter:
    """One JSONL row per call, written and flushed immediately.

    Thread-safety note: the scheduler fires async tasks that all write
    through this single logger; `asyncio` tasks in one thread don't need a
    lock for correctness (no true parallelism), but a lock is cheap insurance
    if a caller ever drives this from multiple threads/processes.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w", encoding="utf-8")
        self._lock = threading.Lock()

    def _write_row(self, row: dict) -> None:
        line = json.dumps(row)
        with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class RunLogger(_JsonlWriter):
    """The locked 5-fields-plus-status raw log (§3.1)."""

    def write(
        self,
        request_id: int,
        send_time: float | None,
        close_time: float | None,
        prompt_id: int,
        prompt_len: int,
        status: Status,
    ) -> None:
        self._write_row(
            {
                "request_id": request_id,
                "send_time": send_time,
                "close_time": close_time,
                "prompt_id": prompt_id,
                "prompt_len": prompt_len,
                "status": status,
            }
        )


class SampleLogger(_JsonlWriter):
    """The per-request TTFT/TPOT sidecar (§6.3).

    One row per *issued* request (`sent` or `errored`) -- a `shed` request
    never opened a stream, so it has no sample and gets no row. That makes
    the sidecar's own reconciliation `len(rows) == n_sent + n_errored`,
    which is the sidecar analog of V5's `scheduled = sent + shed + errored`.

    Written the moment the sample exists, not at run end: this is the file
    the whole baseline number is computed from, so it follows §6.3's
    durable-on-produce rule strictly. A run killed at request 900 of 1000
    still yields 899 usable samples.
    """

    def write(self, request_id: int, send_time: float, sample: RequestSample) -> None:
        self._write_row({"request_id": request_id, "send_time": send_time, **sample.to_dict()})

    def write_error(self, request_id: int, send_time: float, error: str) -> None:
        """A request that failed before/while producing a sample. Recorded
        rather than dropped so the sidecar still reconciles against the raw
        log's `errored` rows -- a silently missing row and a genuinely
        sample-less request would otherwise look identical."""
        self.write(
            request_id,
            send_time,
            RequestSample(ttft_ms=None, tpot_samples_ms=[], content_chunk_count=0, error=error),
        )


def _read_jsonl(path: Path | str) -> list[dict]:
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def read_log(path: Path | str) -> list[dict]:
    return _read_jsonl(path)


def read_samples(path: Path | str) -> list[dict]:
    return _read_jsonl(path)

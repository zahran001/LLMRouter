"""Raw per-request log (WEEK2_PLAN.md §3.1): 5 fields + status, streamed to
disk as each row is produced -- never buffered in memory until the run ends,
so a crash mid-run doesn't lose everything before it (same discipline as the
GPU session's durable-on-produce recording, §6.3).

Fields: request_id, send_time, close_time, prompt_id, prompt_len,
status in {sent, shed, errored}.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Literal

Status = Literal["sent", "shed", "errored"]


class RunLogger:
    """One JSONL row per request, written and flushed immediately.

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

    def write(
        self,
        request_id: int,
        send_time: float | None,
        close_time: float | None,
        prompt_id: int,
        prompt_len: int,
        status: Status,
    ) -> None:
        row = {
            "request_id": request_id,
            "send_time": send_time,
            "close_time": close_time,
            "prompt_id": prompt_id,
            "prompt_len": prompt_len,
            "status": status,
        }
        line = json.dumps(row)
        with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            self._fh.close()

    def __enter__(self) -> "RunLogger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def read_log(path: Path | str) -> list[dict]:
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

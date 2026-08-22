#!/usr/bin/env python
"""Drive the unloaded intrinsic floor over the canonical workload
(`WEEK2_GPU_SESSION_2_PLAN.md` §2 step 3).

Runs **on the L4**, against vLLM on loopback, from the pinned repo clone.

## Sequential by construction, not by a low arrival rate

Every canonical prompt is served once, alone: send, read to the first content
token, close, next. There is no schedule and no arrival process, because the
floor is defined by the absence of queueing. Driving it as a Poisson point at
some small λ would be easier and wrong — Poisson arrivals collide, so even a
low mean rate produces moments with two requests in flight, and those moments
land in the tail, which is the only part of the distribution anybody reads.

The concurrency-1 guarantee here is structural: one request is in flight
because the loop awaits it before starting the next. There is no cap to
enforce and nothing to shed.

## Stopping at the first content token

The floor is a *first-token* measurement, so the stream is closed as soon as a
content chunk arrives. Draining 512 tokens 4,000 times would add hours to a
metered session and change nothing about the number.

## What it refuses

- to run without a prefix-cache verdict that says DISABLED (L6): a warm cache
  makes the floor a measurement of the cache, and session #1's floor is
  classified `CACHE_INFLUENCED_DIAGNOSTIC` for exactly that reason;
- to report a floor that did not cover the whole canonical membership.

Usage (on the instance):
    python scripts/gpu_session/drive_unloaded_floor.py \
        --out-dir ~/llmrouter-artifacts/floor
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402

from loadgen.canonical import load_frozen  # noqa: E402
from loadgen.corpus import load_corpus  # noqa: E402
from loadgen.prefix_cache import (  # noqa: E402
    require_prefix_cache_disabled,
    server_process_epoch,
)
from metrics.artifacts import write_json_artifact  # noqa: E402
from metrics.floor_point import floor_point_metrics  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scenario_contract import CONTRACTS  # noqa: E402

DEFAULT_WORKLOAD = (REPO_ROOT / "benchmarks" / "workloads" / "week2_headline"
                    / "canonical_v1.json")
FLOOR_CONCURRENCY = 1


def benchmark_sha() -> str | None:
    """The commit the instance was pinned to, read rather than passed.

    A floor that cannot say which code produced it is a floor BASELINE.md
    cannot cite.
    """
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or None
    except Exception:
        return None


def measure_ttft(client: httpx.Client, base_url: str, model: str, prompt: str,
                 max_tokens: int, extra_body: dict) -> tuple[float, int]:
    """TTFT in ms for one streamed request, stopping at the first content chunk.

    Returns `(ttft_ms, content_chunk_count)`. Raises if the stream produced no
    content at all -- a request that returned nothing is censored, not fast,
    and the caller records it as such rather than letting it vanish.
    """
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "max_tokens": max_tokens,
        **extra_body,
    }
    start = time.monotonic()
    with client.stream("POST", f"{base_url}/v1/chat/completions", json=body) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            payload = line[len("data: "):]
            if payload.strip() == "[DONE]":
                break
            chunk = json.loads(payload)
            delta = (chunk.get("choices") or [{}])[0].get("delta", {})
            if delta.get("content"):
                return (time.monotonic() - start) * 1000.0, 1
    raise RuntimeError("stream produced no content chunk")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--workload", type=Path, default=DEFAULT_WORKLOAD)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--model", default="meta-llama/Llama-3.2-3B-Instruct")
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--max-tokens", type=int, default=8,
                        help="output cap; only first-token time is used, and the stream is "
                             "closed at the first content chunk regardless")
    parser.add_argument("--extra-body", default=None)
    parser.add_argument("--tag", default="floor")
    parser.add_argument("--process-epoch", default=None,
                        help="identifier for the vLLM process this ran against; a floor from a "
                             "different epoch than the headline family is not its floor")
    parser.add_argument("--prefix-cache-verdict", type=Path,
                        default=REPO_ROOT / "benchmarks" / "runs" / "preflight"
                        / "prefix_cache_verdict.json")
    parser.add_argument("--limit", type=int, default=None,
                        help="DIAGNOSTIC ONLY: stop after N prompts. A floor driven with this "
                             "does not cover the canonical membership and is recorded as "
                             "incomplete.")
    args = parser.parse_args()

    verdict = require_prefix_cache_disabled(args.prefix_cache_verdict)
    print(f"prefix cache: {verdict['verdict']} (min replay ratio {verdict['min_ratio']:.2f})")

    args.process_epoch = server_process_epoch(args.base_url, args.process_epoch)
    print(f"process epoch: {args.process_epoch}")

    workload = load_frozen(args.workload)

    # The floor is defined as the headline curve's starting point, so it must
    # measure the headline curve's workload. `--workload` exists for testing,
    # not for choosing: pointing it at the 500-prompt scout workload would
    # finish in 50s instead of 7 minutes and produce a record that passes
    # every §11 checkbox -- `membership_complete: true`, `floor_complete:
    # true` -- while being a floor over a different multiset. That is exactly
    # the defect (a floor over some other draw) that §2 step 3 exists to
    # replace.
    expected_membership = CONTRACTS["floor"].expected_membership()
    if workload["membership_id"] != expected_membership:
        raise SystemExit(
            f"REFUSED: {args.workload} carries membership "
            f"{workload['membership_id'][:16]}..., but the unloaded floor is defined over the "
            f"canonical HEADLINE membership {expected_membership[:16]}.... A floor over any "
            "other multiset is not the floor the headline curve starts from.")

    corpus = load_corpus()

    # Measured, not copied out of `workload["corpus"]["sha256"]`.
    corpus_digest = hashlib.sha256(corpus.source_path.read_bytes()).hexdigest()
    if corpus_digest != workload["corpus"]["sha256"]:
        raise SystemExit(
            f"REFUSED: corpus drift. The canonical workload was built against "
            f"{workload['corpus']['sha256'][:16]}..., this corpus hashes to "
            f"{corpus_digest[:16]}.... The floor would be over different prompt text.")

    by_id = {p.prompt_id: p for p in corpus.prompts}
    # The canonical membership is the population, always. `--limit` changes
    # only what gets DRIVEN, so a truncated run reports itself as an
    # incomplete floor rather than as a complete floor over a smaller
    # workload -- which is the shape the record would take if the population
    # were truncated too, and it would be indistinguishable from the real
    # thing.
    membership = list(workload["membership"])
    to_drive = membership[: args.limit] if args.limit is not None else membership

    extra_body = json.loads(args.extra_body) if args.extra_body else {}

    print(f"unloaded floor  (DIAGNOSTIC -- never headline evidence)")
    print(f"  membership   {workload['membership_id'][:16]}...")
    print(f"  population   {len(membership)} canonical prompts")
    if args.limit is not None:
        print(f"  DRIVING      {len(to_drive)} only (--limit) -- this will NOT be a complete floor")
    print(f"  concurrency  {FLOOR_CONCURRENCY} (sequential; no arrival process)")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"{args.tag}.raw_log.jsonl"
    samples_path = out_dir / f"{args.tag}.samples.jsonl"
    metrics_path = out_dir / f"{args.tag}.metrics.json"

    raw_rows: list[dict] = []
    sample_rows: list[dict] = []
    started = time.time()

    # Written per row, flushed per row: a floor that dies at prompt 3,900 must
    # leave 3,900 usable observations behind, not an empty file.
    with raw_path.open("w", encoding="utf-8") as raw_fh, \
            samples_path.open("w", encoding="utf-8") as samples_fh, \
            httpx.Client(timeout=args.timeout_s) as client:

        def emit(fh, row, sink):
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            sink.append(row)

        for request_id, prompt_id in enumerate(to_drive):
            prompt = by_id[prompt_id]
            send_time = time.time() - started
            try:
                ttft_ms, chunks = measure_ttft(client, args.base_url, args.model,
                                               prompt.text, args.max_tokens, extra_body)
                status, error = "sent", None
            except Exception as exc:  # noqa: BLE001 -- recorded, never swallowed
                ttft_ms, chunks = None, 0
                status, error = "errored", f"{type(exc).__name__}: {exc}"

            close_time = time.time() - started
            emit(raw_fh, {"request_id": request_id, "send_time": send_time,
                          "close_time": close_time, "prompt_id": prompt_id,
                          "prompt_len": prompt.char_len, "status": status}, raw_rows)
            emit(samples_fh, {"request_id": request_id, "send_time": send_time,
                              "prompt_id": prompt_id, "ttft_ms": ttft_ms,
                              "tpot_samples_ms": [], "content_chunk_count": chunks,
                              "error": error}, sample_rows)

            if (request_id + 1) % 250 == 0:
                done = [r["ttft_ms"] for r in sample_rows if r["ttft_ms"] is not None]
                print(f"    {request_id + 1}/{len(to_drive)}"
                      + (f"  mean {sum(done) / len(done):.0f}ms" if done else ""))

    record = floor_point_metrics(
        raw_rows=raw_rows,
        sample_rows=sample_rows,
        membership=membership,
        membership_id=workload["membership_id"],
        corpus_sha256=corpus_digest,
        concurrency=FLOOR_CONCURRENCY,
        provenance={
            "tag": args.tag,
            "benchmark_sha": benchmark_sha(),
            "workload_path": str(args.workload),
            "raw_log_path": str(raw_path),
            "samples_path": str(samples_path),
            "base_url": args.base_url,
            "model": args.model,
            "timeout_s": args.timeout_s,
            "max_tokens": args.max_tokens,
            "extra_body": extra_body,
            "prefix_cache_verdict": verdict["verdict"],
            "prefix_cache_verdict_path": str(args.prefix_cache_verdict),
            "process_epoch": args.process_epoch,
            "limit_applied": args.limit,
            "wall_clock_s": time.time() - started,
            "driven_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    write_json_artifact(metrics_path, record)

    p99 = record["ttft_p99_ms"]
    print(f"\n  prompts served   {record['reconciled_measurement_n']}/"
          f"{record['expected_measurement_n']}")
    print(f"  censoring        {record['ttft_censoring_rate']:.1%}")
    print(f"  p50 / p95 / p99  {record['ttft_p50_ms']} / {record['ttft_p95_ms']} / {p99} ms")
    if record["slo_headroom_ms"] is not None:
        print(f"  SLO headroom     {record['slo_headroom_ms']:.0f}ms of "
              f"{record['breach_threshold_ms']:.0f}ms")
    if not record["membership_complete"]:
        print(f"  WARNING: {record['n_missing_prompts']} canonical prompt(s) were never "
              "served -- this is not a floor over the canonical workload.")
    print(f"\n  floor_complete   {record['floor_complete']}")
    print(f"  record: {metrics_path}")


if __name__ == "__main__":
    main()

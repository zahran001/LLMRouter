#!/usr/bin/env python
"""Preflight gate: refuse a controlled headline run if prefix caching is live
(R4 README L6; `WEEK2_PLAN.md` §10.8).

Runs **on the instance**, against the live vLLM server, after launch and
before any headline point is driven. Exits non-zero if caching is enabled or
if the evidence is ambiguous — the headline experiment's central control is
exact prompt replay, and a cache that recognizes those replays invalidates it.

What it does:

  1. picks the longest prompts from the frozen canonical workload (prefill has
     to dominate TTFT for the probe to discriminate at all);
  2. sends each one twice, sequentially, at concurrency 1, measuring TTFT;
  3. scrapes `/metrics` for prefix-cache counters as supporting evidence;
  4. writes a verdict artifact that the session provenance references.

The behavioural probe is the verdict. The CLI flag and the counters are
recorded, but neither decides: a flag can be renamed between vLLM releases
and a counter can be absent from a build, while a replay that skips prefill
cannot hide.

Usage (on the instance, vLLM already healthy):
    python scripts/gpu_session/verify_prefix_cache_disabled.py
    python scripts/gpu_session/verify_prefix_cache_disabled.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402

from loadgen.canonical import load_frozen  # noqa: E402
from loadgen.corpus import load_corpus  # noqa: E402
from loadgen.prefix_cache import DISABLED, ProbeResult, evaluate  # noqa: E402
from metrics.artifacts import write_json_artifact  # noqa: E402

DEFAULT_WORKLOAD = REPO_ROOT / "benchmarks" / "workloads" / "week2_headline" / "canonical_v1.json"
DEFAULT_OUT = REPO_ROOT / "benchmarks" / "runs" / "preflight" / "prefix_cache_verdict.json"

# Counter names differ across vLLM versions; match loosely and record whatever
# was found rather than asserting a schema this script cannot control.
HITS_RE = re.compile(r"^vllm:(?:gpu_)?prefix_cache_hits(?:_total)?\{[^}]*\}\s+([\d.eE+-]+)", re.M)
QUERIES_RE = re.compile(r"^vllm:(?:gpu_)?prefix_cache_queries(?:_total)?\{[^}]*\}\s+([\d.eE+-]+)", re.M)


def measure_ttft(client: httpx.Client, base_url: str, model: str, prompt: str,
                 max_tokens: int) -> float:
    """TTFT in ms for one streamed request, stopping at the first content chunk.

    Stops early deliberately: the probe only needs first-token time, and
    draining a 512-token completion twice per prompt would make the preflight
    slower than it needs to be on a metered instance.
    """
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "max_tokens": max_tokens,
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
                return (time.monotonic() - start) * 1000.0
    raise RuntimeError("probe request produced no content chunk -- cannot measure TTFT")


def scrape_metrics(client: httpx.Client, base_url: str) -> tuple[int | None, int | None]:
    try:
        text = client.get(f"{base_url}/metrics", timeout=10.0).text
    except Exception:
        return None, None
    hits = HITS_RE.search(text)
    queries = QUERIES_RE.search(text)
    return (int(float(hits.group(1))) if hits else None,
            int(float(queries.group(1))) if queries else None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--model", default="meta-llama/Llama-3.2-3B-Instruct")
    parser.add_argument("--workload", type=Path, default=DEFAULT_WORKLOAD)
    parser.add_argument("--probes", type=int, default=3,
                        help="how many distinct long prompts to probe")
    parser.add_argument("--max-tokens", type=int, default=8,
                        help="output cap for probe requests; only first-token time is used")
    parser.add_argument("--settle-s", type=float, default=2.0,
                        help="pause between a prompt's first serving and its replay")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    workload = load_frozen(args.workload)
    corpus = load_corpus()
    by_id = {p.prompt_id: p for p in corpus.prompts}

    # Longest canonical prompts: prefill has to dominate TTFT or the ratio
    # cannot tell a hit from a miss.
    longest = sorted(workload["membership"], key=lambda pid: -by_id[pid].char_len)[:args.probes]

    print(f"probing {len(longest)} prompt(s) against {args.base_url}")
    probes = []
    with httpx.Client(timeout=120.0) as client:
        for prompt_id in longest:
            prompt = by_id[prompt_id]
            first = measure_ttft(client, args.base_url, args.model, prompt.text, args.max_tokens)
            time.sleep(args.settle_s)
            replay = measure_ttft(client, args.base_url, args.model, prompt.text, args.max_tokens)
            probe = ProbeResult(prompt_id=prompt_id, char_len=prompt.char_len,
                                first_ttft_ms=first, replay_ttft_ms=replay)
            probes.append(probe)
            print(f"  prompt {prompt_id:>5} ({prompt.char_len:>6,} chars): "
                  f"first {first:>8.1f}ms  replay {replay:>8.1f}ms  ratio {probe.ratio:.2f}")

        hits, queries = scrape_metrics(client, args.base_url)

    verdict = evaluate(probes, metrics_hits=hits, metrics_queries=queries)
    verdict.update({
        "what": "Effective prefix-cache state of the live server (R4 README L6).",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "model": args.model,
        "canonical_membership_id": workload["membership_id"],
    })

    write_json_artifact(args.out, verdict)

    print(f"\nverdict: {verdict['verdict']}")
    for reason in verdict["reasons"]:
        print(f"  - {reason}")
    print(f"\nwritten: {args.out}")

    if verdict["verdict"] != DISABLED:
        print("\nPREFLIGHT FAILED. Do not drive controlled headline points against this server.\n"
              "Exact prompt replay is the experiment's central control; a live prefix cache "
              "changes the cost being controlled as a function of run order (WEEK2_PLAN.md "
              "10.8). Relaunch with DISABLE_PREFIX_CACHING=1 and re-verify.")
        raise SystemExit(2)

    print("\nSafe to drive controlled headline points.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""Exact token-capacity proof for the canonical workload (R4 README R4B).

The old `--max-model-len=20000` rested on a conservative char-to-token
estimate and on luck: the corpus's longest prompt (44,445 chars,
`prompt_id` 790) was **never drawn** in the first session, and the 2-RPS
schedule topped out at 16,781 chars. Random draws made the extremes unlikely.

The redesign removes that luck deliberately. The canonical multiset has a
fixed top stratum, so the corpus's longest prompts are present **at every RPS
point of every repeat, by construction**. A context limit that was adequate in
expectation is now a hard precondition, and it has to be proven with the real
tokenizer instead of estimated.

## What is measured

Not the bare prompt. The loadgen posts a chat completion --
`{"messages": [{"role": "user", "content": prompt}]}` (`loadgen/scheduler.py`)
-- so vLLM applies the model's chat template before anything reaches the
model. The template adds a BOS token, a default system block and the
generation prompt: 35 tokens for an empty message. This script therefore
renders each prompt through the pinned model's own chat template and counts
the tokens of the rendered string, which is what the server will actually see.

The tokenizer and template come from
`scripts/fetch_tokenizer.py`, which proves byte-identity with the gated
`meta-llama/Llama-3.2-3B-Instruct` repository rather than trusting a mirror.

## What it decides

    required_context = max_input_tokens + output_token_budget + safety_margin

If the intended `--max-model-len` cannot cover that, this **halts**. The
correct response is a larger context or a human decision to change the locked
construction -- never dropping the long prompts to make the server boot, which
would quietly delete the tail the experiment exists to control.

Usage:
    .venv/Scripts/python.exe scripts/check_tokenizer_capacity.py
    .venv/Scripts/python.exe scripts/check_tokenizer_capacity.py --max-model-len 24576
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from cost_model.tokenizer import build_renderer, load_tokenizer  # noqa: E402
from loadgen.canonical import load_frozen  # noqa: E402
from loadgen.corpus import load_corpus  # noqa: E402
from metrics.artifacts import write_json_artifact  # noqa: E402

TOKENIZER_CACHE = REPO_ROOT / ".tokenizer_cache" / "meta-llama__Llama-3.2-3B-Instruct"
WORKLOAD_DIR = REPO_ROOT / "benchmarks" / "workloads" / "week2_headline"
DEFAULT_CANDIDATE = WORKLOAD_DIR / "canonical_v1.candidate.json"
DEFAULT_OUT = WORKLOAD_DIR / "tokenizer_capacity_report.json"

# The output-token policy the first session ran and the redesign keeps.
DEFAULT_OUTPUT_TOKENS = 512

# What the first session launched with. Kept as the default so the report
# answers "does the existing configuration still work" before proposing a
# change.
FIRST_SESSION_MAX_MODEL_LEN = 20000

# Safety margin over (max input + max output). Covers the chat template's
# date string changing length, any future template revision, and vLLM's own
# per-request bookkeeping. Expressed as both a fraction and a floor so a small
# workload cannot end up with a token-sized margin.
MARGIN_FRACTION = 0.10
MARGIN_FLOOR_TOKENS = 512


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def quantiles(values: np.ndarray) -> dict:
    return {
        str(q): float(np.percentile(values, q, method="linear"))
        for q in (0, 50, 90, 95, 99, 99.5, 100)
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workload", type=Path, default=DEFAULT_CANDIDATE,
                        help="canonical workload candidate (or frozen artifact) to size for")
    parser.add_argument("--max-model-len", type=int, default=None,
                        help=f"context limit to test (default: the first session's "
                             f"{FIRST_SESSION_MAX_MODEL_LEN}, then propose)")
    parser.add_argument("--output-tokens", type=int, default=DEFAULT_OUTPUT_TOKENS,
                        help="locked output-token budget per request")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    # Resolve so a relative path typed on the command line still reports a
    # repo-relative provenance path rather than crashing.
    args.workload = args.workload.resolve()
    args.out = args.out.resolve()

    if not args.workload.exists():
        raise SystemExit(f"{args.workload} not found -- run scripts/build_canonical_workload.py "
                         "--emit-candidate first")

    workload = load_frozen(args.workload)
    corpus = load_corpus()
    by_id = {p.prompt_id: p for p in corpus.prompts}

    tokenizer, tok_config, tok_provenance = load_tokenizer(TOKENIZER_CACHE)
    render, template_src = build_renderer(tok_config)

    membership = workload["membership"]
    rendered = [render(by_id[pid].text) for pid in membership]
    encodings = tokenizer.encode_batch(rendered, add_special_tokens=False)
    token_counts = np.array([len(e.ids) for e in encodings], dtype=int)

    # Template overhead, measured rather than assumed.
    empty_tokens = len(tokenizer.encode(render(""), add_special_tokens=False).ids)

    max_idx = int(np.argmax(token_counts))
    max_tokens = int(token_counts[max_idx])
    max_prompt_id = membership[max_idx]

    per_stratum = []
    for stratum in workload["strata"]:
        ids = stratum["selected_prompt_ids"]
        index = {pid: i for i, pid in enumerate(membership)}
        counts = np.array([token_counts[index[pid]] for pid in ids], dtype=int)
        per_stratum.append({
            "index": stratum["index"],
            "quantile_range_pct": stratum["quantile_range_pct"],
            "char_len_range": stratum["char_len_range"],
            "selected_count": len(ids),
            "input_tokens": {
                "min": int(counts.min()), "max": int(counts.max()),
                "mean": float(counts.mean()), "quantiles": quantiles(counts),
            },
        })

    margin = max(MARGIN_FLOOR_TOKENS, int(round(MARGIN_FRACTION * (max_tokens + args.output_tokens))))
    required = max_tokens + args.output_tokens + margin
    tested = args.max_model_len or FIRST_SESSION_MAX_MODEL_LEN
    fits = required <= tested

    # Propose the next power-of-two-ish step that clears `required`, so the
    # recommendation is a round, defensible number rather than the exact
    # requirement with no headroom for a template change.
    proposal = tested if fits else next(
        c for c in (20000, 24576, 32768, 40960, 49152, 65536) if c >= required)

    chars = np.array([by_id[pid].char_len for pid in membership], dtype=float)
    # Prompt-only counts, so the chars/token figure is comparable with the old
    # ~4-chars-per-token estimate. Dividing by the RENDERED count would mix in
    # the 35-token template overhead and make every short prompt look
    # pathological.
    prompt_only = np.array(
        [len(e.ids) for e in tokenizer.encode_batch(
            [by_id[pid].text for pid in membership], add_special_tokens=False)],
        dtype=float)
    ratio = chars / np.maximum(prompt_only, 1)

    report = {
        "what": "Exact tokenizer capacity proof for the canonical headline workload "
                "(R4 README R4B).",
        "verdict": "PASS" if fits else "INSUFFICIENT_CONTEXT",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workload": {
            "path": _rel(args.workload),
            "membership_id": workload["membership_id"],
            "scheme_version": workload["scheme_version"],
            "N": len(membership),
        },
        "tokenizer": {
            "gated_repo": tok_provenance["gated_repo"],
            "gated_repo_commit": tok_provenance["gated_repo_commit"],
            "verification": tok_provenance["verification"],
            "files": [
                {k: f[k] for k in ("filename", "git_blob_sha1", "sha256", "bytes")}
                for f in tok_provenance["files"]
            ],
            "vocab_size": tokenizer.get_vocab_size(),
            "chat_template_applied": True,
            "chat_template_sha256": __import__("hashlib").sha256(
                template_src.encode("utf-8")).hexdigest(),
            "empty_message_overhead_tokens": empty_tokens,
            "note": "Counts are of the RENDERED chat request, which is what vLLM tokenizes -- "
                    "not of the bare prompt text.",
        },
        "input_tokens": {
            "max": max_tokens,
            "max_prompt_id": max_prompt_id,
            "max_prompt_char_len": int(by_id[max_prompt_id].char_len),
            "mean": float(token_counts.mean()),
            "total": int(token_counts.sum()),
            "quantiles": quantiles(token_counts),
        },
        "chars_per_token": {
            "basis": "prompt text only, excluding the chat-template overhead",
            "min": float(ratio.min()), "mean": float(ratio.mean()), "max": float(ratio.max()),
            "at_longest_prompt": float(chars[max_idx] / max(prompt_only[max_idx], 1)),
            "note": "The old sizing assumed ~4 chars/token uniformly. The ratio varies by more "
                    "than 4x across this workload, so the estimate was only safe because the "
                    "extremes were unlikely to be drawn -- which the canonical construction "
                    "deliberately changes.",
        },
        "per_stratum": per_stratum,
        "capacity": {
            "output_token_budget": args.output_tokens,
            "safety_margin_tokens": margin,
            "margin_rule": f"max({MARGIN_FLOOR_TOKENS}, {MARGIN_FRACTION:.0%} of input+output)",
            "required_context_tokens": required,
            "tested_max_model_len": tested,
            "fits": fits,
            "first_session_max_model_len": FIRST_SESSION_MAX_MODEL_LEN,
            "proposed_max_model_len": proposal,
        },
        "caveats": [
            "The chat template embeds today's date via strftime_now; its token count is "
            "stable across plausible dates, and the safety margin covers any drift.",
            "vLLM may add a small number of internal tokens beyond the rendered template. The "
            "margin is sized to absorb that; it is not measured here.",
            "This does not change the Week 2 raw-log `prompt_len` contract, which stays char "
            "count (token count is the Week 3 revisit, WEEK2_PLAN.md 3.4).",
        ],
    }

    sha = write_json_artifact(args.out, report)

    print(f"\ntokenizer: {tok_provenance['gated_repo']} @ "
          f"{tok_provenance['gated_repo_commit'][:12]}...  (blob-verified)")
    print(f"workload:  {workload['membership_id'][:16]}...  N={len(membership)}")
    print(f"\nchat template overhead for an empty message: {empty_tokens} tokens")
    print(f"\ninput tokens over the canonical {len(membership)}:")
    q = report["input_tokens"]["quantiles"]
    print(f"  p50={q['50']:.0f}  p90={q['90']:.0f}  p99={q['99']:.0f}  "
          f"p99.5={q['99.5']:.0f}  max={max_tokens}")
    print(f"  longest: prompt_id {max_prompt_id} "
          f"({report['input_tokens']['max_prompt_char_len']:,} chars -> {max_tokens:,} tokens)")
    cpt = report["chars_per_token"]
    print(f"  chars/token (prompt only): min={cpt['min']:.2f} mean={cpt['mean']:.2f} "
          f"max={cpt['max']:.2f}; at the longest prompt {cpt['at_longest_prompt']:.2f}")

    print(f"\nper stratum (input tokens):")
    print(f"  {'i':>2} {'q-range':>14} {'n':>5} {'p50':>7} {'p99':>8} {'max':>8}")
    for s in per_stratum:
        t = s["input_tokens"]
        print(f"  {s['index']:>2} {str(s['quantile_range_pct']):>14} {s['selected_count']:>5} "
              f"{t['quantiles']['50']:>7.0f} {t['quantiles']['99']:>8.0f} {t['max']:>8}")

    c = report["capacity"]
    print(f"\ncapacity: {max_tokens:,} input + {c['output_token_budget']:,} output + "
          f"{c['safety_margin_tokens']:,} margin = {c['required_context_tokens']:,} required")
    print(f"  tested --max-model-len {tested:,}: {'FITS' if fits else 'TOO SMALL'}")
    print(f"  proposed --max-model-len: {proposal:,}")
    print(f"\nverdict: {report['verdict']}")
    print(f"written: {_rel(args.out)}  sha256={sha[:16]}...")

    if not fits:
        print("\nHALT: the locked canonical workload does not fit the tested context limit. "
              "Raise --max-model-len (or have a human change the locked construction). Do NOT "
              "drop long prompts to make it fit -- that deletes the tail the experiment "
              "controls.")
        raise SystemExit(2)


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""Build the pinned ShareGPT subset committed as corpus/baseline_prompts.jsonl
(WEEK2_PLAN.md §3.4). Run once, offline, to produce the committed artifact --
not part of any loadgen run. Runs draw from the committed file, never live
ShareGPT.

Source: anon8231489123/ShareGPT_Vicuna_unfiltered on Hugging Face,
ShareGPT_V3_unfiltered_cleaned_split.json -- the same corpus vLLM's own
benchmark_serving.py uses for serving benchmarks, so it's a well-precedented
choice for this exact kind of measurement, not an arbitrary pick.

Usage:
    python scripts/build_baseline_corpus.py --raw <path to downloaded json>

The raw ~640MB source file is NOT committed to the repo -- only the sampled
subset (corpus/baseline_prompts.jsonl) and its provenance header
(corpus/baseline_prompts.provenance.json) are.
"""

from __future__ import annotations

import argparse
import datetime
import json
import random
from pathlib import Path

SOURCE_DATASET = "anon8231489123/ShareGPT_Vicuna_unfiltered"
SOURCE_FILE = "ShareGPT_V3_unfiltered_cleaned_split.json"
SOURCE_URL = (
    "https://huggingface.co/datasets/anon8231489123/ShareGPT_Vicuna_unfiltered/"
    "resolve/main/ShareGPT_V3_unfiltered_cleaned_split.json"
)
# HF `X-Repo-Commit` observed at download time -- pins the exact dataset
# revision this subset was drawn from, independent of the mirror's mutable
# `main` ref (WEEK2_PLAN.md §3.4: "a re-download or version change must not
# silently alter the corpus").
SOURCE_COMMIT = "192ab2185289094fc556ec8ce5ce1e8e587154ca"

FILTER_DEFINITION = (
    "keep an entry iff conversations[0]['from'] in {'human','user'} and "
    "conversations[0]['value'], after str.strip(), is a non-empty string -- "
    "a validity predicate only. No exclusion by length or content (WEEK2_PLAN.md "
    "§3.4: 'may NOT remove valid prompts to shape the spread')."
)

DEFAULT_SUBSET_SIZE = 5000
# Fixed selection seed for the one-time corpus-build sample (which entries end
# up in the pinned file). Distinct from the runtime `corpus_rng` used later to
# draw *with replacement* from this pinned file when materializing a schedule
# (WEEK2_PLAN.md §3.2/§3.4) -- this seed only controls which prompts are
# eligible to be drawn at all.
SELECTION_SEED = 20260816


def _is_valid(entry: dict) -> str | None:
    """Return the prompt text if `entry` passes the validity filter, else None."""
    convs = entry.get("conversations")
    if not convs or not isinstance(convs, list):
        return None
    first = convs[0]
    if not isinstance(first, dict):
        return None
    if first.get("from") not in ("human", "user"):
        return None
    text = first.get("value")
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text:
        return None
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", required=True, help="path to the downloaded ShareGPT_V3_unfiltered_cleaned_split.json")
    parser.add_argument("--subset-size", type=int, default=DEFAULT_SUBSET_SIZE)
    parser.add_argument("--seed", type=int, default=SELECTION_SEED)
    parser.add_argument("--out-dir", default=None, help="default: <repo>/corpus")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    out_dir = Path(args.out_dir) if args.out_dir else repo_root / "corpus"
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = json.loads(Path(args.raw).read_text(encoding="utf-8"))
    print(f"loaded {len(raw)} raw conversations")

    valid: list[str] = []
    for entry in raw:
        text = _is_valid(entry)
        if text is not None:
            valid.append(text)
    print(f"{len(valid)} pass the validity filter (of {len(raw)} total)")

    rng = random.Random(args.seed)
    if args.subset_size > len(valid):
        raise SystemExit(f"subset_size {args.subset_size} > {len(valid)} valid entries")
    selected = rng.sample(valid, args.subset_size)

    jsonl_path = out_dir / "baseline_prompts.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for prompt_id, text in enumerate(selected):
            f.write(json.dumps({"prompt_id": prompt_id, "text": text, "char_len": len(text)}) + "\n")

    lengths = [len(t) for t in selected]
    provenance = {
        "source_dataset": SOURCE_DATASET,
        "source_file": SOURCE_FILE,
        "source_url": SOURCE_URL,
        "source_commit": SOURCE_COMMIT,
        "download_date": datetime.date.today().isoformat(),
        "filter_definition": FILTER_DEFINITION,
        "total_raw_entries": len(raw),
        "total_valid_after_filter": len(valid),
        "selection_seed": args.seed,
        "subset_size": len(selected),
        "prompt_len_definition": "char count of conversations[0]['value'] after strip(); token count is a Week 3 revisit (WEEK2_PLAN.md §3.4)",
        "char_len_stats": {
            "min": min(lengths),
            "max": max(lengths),
            "mean": sum(lengths) / len(lengths),
        },
        "artifact": "corpus/baseline_prompts.jsonl",
        "note": "with-replacement i.i.d. draws happen at schedule-materialization time via a separate corpus_rng (WEEK2_PLAN.md §3.2/§3.4); this seed only controls which prompts made it into the pinned subset, not which are drawn from it at runtime.",
    }
    prov_path = out_dir / "baseline_prompts.provenance.json"
    prov_path.write_text(json.dumps(provenance, indent=2))

    print(f"wrote {jsonl_path} ({len(selected)} prompts)")
    print(f"wrote {prov_path}")
    print(f"char_len: min={min(lengths)} max={max(lengths)} mean={sum(lengths)/len(lengths):.1f}")


if __name__ == "__main__":
    main()

"""Load the pinned ShareGPT corpus and draw prompts from it (WEEK2_PLAN.md §3.4).

Runs draw only from the committed `corpus/baseline_prompts.jsonl` artifact
(built once, offline, by scripts/build_baseline_corpus.py) -- never live
ShareGPT. Draws are with-replacement and i.i.d. via the caller-supplied
`corpus_rng` (loadgen/rng.py), which decouples subset size from run length
and matches the independent-arrivals model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DEFAULT_CORPUS_PATH = Path(__file__).resolve().parent.parent / "corpus" / "baseline_prompts.jsonl"


@dataclass(frozen=True)
class Prompt:
    prompt_id: int
    text: str
    char_len: int


@dataclass(frozen=True)
class Corpus:
    prompts: tuple[Prompt, ...]
    source_path: Path

    def __len__(self) -> int:
        return len(self.prompts)


def load_corpus(path: Path | str = DEFAULT_CORPUS_PATH) -> Corpus:
    path = Path(path)
    prompts = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            prompts.append(Prompt(prompt_id=row["prompt_id"], text=row["text"], char_len=row["char_len"]))
    if not prompts:
        raise ValueError(f"corpus at {path} is empty")
    return Corpus(prompts=tuple(prompts), source_path=path)


def draw_prompt_id(corpus: Corpus, corpus_rng: np.random.Generator) -> int:
    """One with-replacement i.i.d. draw, returning a `prompt_id` (index into
    `corpus.prompts`, since the pinned file's prompt_ids are dense 0..N-1)."""
    idx = int(corpus_rng.integers(0, len(corpus.prompts)))
    return corpus.prompts[idx].prompt_id


def draw_prompt_id_long_context(
    corpus: Corpus, corpus_rng: np.random.Generator, percentile: float = 90.0
) -> int:
    """Adversarial-scenario draw: with-replacement i.i.d. over only the
    prompts at or above `percentile` char_len (WEEK2_PLAN.md §2.1: the
    long-context flood is a separate scenario, not part of the baseline's
    natural-spread sampling -- so this length filter is deliberate here,
    unlike the validity-only filter that governs the baseline corpus in
    scripts/build_baseline_corpus.py)."""
    lengths = np.array([p.char_len for p in corpus.prompts])
    threshold = np.percentile(lengths, percentile)
    pool = [p.prompt_id for p in corpus.prompts if p.char_len >= threshold]
    if not pool:
        raise ValueError(f"no prompts at or above the {percentile}th percentile")
    idx = int(corpus_rng.integers(0, len(pool)))
    return pool[idx]

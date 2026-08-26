"""Shared pinned-tokenizer acquisition and chat-template rendering.

Extracted from `scripts/check_tokenizer_capacity.py` (Week 2 R4B) so the
Week 2 tokenizer-capacity path and the Week 3 request-cost reference path
share one implementation and can never silently drift apart on tokenizer
or chat-template semantics. `scripts/check_tokenizer_capacity.py` imports
`load_tokenizer`/`build_renderer` from here rather than defining its own.

Both functions refuse to run against anything not proven byte-identical to
the pinned gated repo (`scripts/fetch_tokenizer.py`'s `PROVENANCE.json`) --
replacing an approximate estimate with exact evidence is the entire point
of this path, so there is no silent fallback.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOKENIZER_CACHE = REPO_ROOT / ".tokenizer_cache" / "meta-llama__Llama-3.2-3B-Instruct"


def load_tokenizer(cache_dir: Path = DEFAULT_TOKENIZER_CACHE):
    """Load the pinned tokenizer, its chat-template config, and its provenance.

    Returns (Tokenizer, tokenizer_config: dict, provenance: dict).
    """
    try:
        from tokenizers import Tokenizer
    except ImportError:
        raise SystemExit(
            "the `tokenizers` package is required (.venv/Scripts/pip install -r "
            "requirements-preflight.txt). This must not fall back to a char-based "
            "estimate -- replacing the estimate is its entire purpose.")

    tok_path = cache_dir / "tokenizer.json"
    cfg_path = cache_dir / "tokenizer_config.json"
    if not tok_path.exists() or not cfg_path.exists():
        raise SystemExit(
            f"tokenizer not cached under {cache_dir} -- run "
            "scripts/fetch_tokenizer.py first (it proves the files are byte-identical to the "
            "gated meta-llama repo).")

    provenance_path = cache_dir / "PROVENANCE.json"
    if not provenance_path.exists():
        raise SystemExit(f"{cache_dir} has no PROVENANCE.json -- refusing to use a "
                         "tokenizer whose identity was never proven")

    return (Tokenizer.from_file(str(tok_path)),
            json.loads(cfg_path.read_text(encoding="utf-8")),
            json.loads(provenance_path.read_text(encoding="utf-8")))


def build_renderer(tokenizer_config: dict) -> tuple[Callable[[str], str], str]:
    """Render prompts exactly as vLLM will, using the model's own chat template.

    Returns (render_fn, raw_template_source_string).
    """
    import jinja2

    template_src = tokenizer_config.get("chat_template")
    if isinstance(template_src, list):  # newer multi-template format
        template_src = next(t["template"] for t in template_src if t.get("name") in (None, "default"))
    if not template_src:
        raise SystemExit("tokenizer_config.json carries no chat_template -- cannot reproduce "
                         "what the server sees")

    env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
    env.globals["raise_exception"] = lambda msg: (_ for _ in ()).throw(RuntimeError(msg))
    env.globals["strftime_now"] = lambda fmt: datetime.now(timezone.utc).strftime(fmt)
    template = env.from_string(template_src)

    bos = tokenizer_config.get("bos_token") or "<|begin_of_text|>"
    if isinstance(bos, dict):
        bos = bos.get("content", "<|begin_of_text|>")

    def render(prompt_text: str) -> str:
        return template.render(
            messages=[{"role": "user", "content": prompt_text}],
            add_generation_prompt=True,
            bos_token=bos,
        )

    return render, template_src

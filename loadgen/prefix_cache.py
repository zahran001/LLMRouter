"""Is prefix caching actually off? (R4 README L6; `WEEK2_PLAN.md` §10.8.)

L6 requires verifying the **effective runtime configuration, not only the CLI
string**, and that distinction is the whole point. A flag can be misspelled,
silently renamed between vLLM releases, overridden by an environment
variable, or applied to a server other than the one being driven. Every one
of those failures produces a launch command that looks right and a server
that caches — which is exactly the state the first session was in, except
there nobody had even asked.

So the check is **behavioural**: send the same long prompt twice, back to
back, at concurrency 1, and compare time-to-first-token.

    caching ON   the second serving skips prefill and collapses.
                 Measured on first-session data: 0.20x and 0.42x.
    caching OFF  the second serving pays full prefill again, so the ratio
                 sits near 1.0 (bounded by ordinary run-to-run jitter).

That is a property of the running server, not of the arguments it was
started with. Two supporting signals are recorded alongside it — the
Prometheus prefix-cache counters and the engine's own config line — but the
verdict rests on the probe, because those two can be absent or stale while
the behaviour cannot.

The decision logic lives here, separate from the I/O, so it can be tested
against injected measurements without a GPU. `tests/redesign/` drives it with
both a cache-hit-shaped ratio and a cold-shaped one.
"""

from __future__ import annotations

from dataclasses import dataclass

# A replay this much faster than its first serving is a cache hit. Sits well
# above the measured hit ratios (0.20, 0.42) and well below the jitter band a
# genuinely cold replay produces, so neither case lands near the line.
CACHE_HIT_RATIO_CEILING = 0.75

# A cold replay should land near 1.0. Below this and above the hit ceiling is
# the ambiguous middle: not obviously cached, not obviously not.
COLD_RATIO_FLOOR = 0.85

# The probe prompt must be long enough that prefill dominates TTFT; on a short
# prompt a hit and a miss both land near the ~82ms floor and the ratio is
# noise. Corpus q95.
MIN_PROBE_PROMPT_CHARS = 4566

DISABLED = "PREFIX_CACHING_DISABLED"
ENABLED = "PREFIX_CACHING_ENABLED"
AMBIGUOUS = "AMBIGUOUS"


def require_prefix_cache_disabled(verdict_path) -> dict:
    """L6, enforced by the drivers rather than by memory.

    Lives here rather than in one driver so Tier A and Tier B cannot diverge
    on what counts as evidence. A second copy could drift into accepting a
    verdict the other rejects, and the whole point of the gate is that it
    cannot be satisfied by remembering to run something.

    `AMBIGUOUS` is refused alongside `ENABLED`: "not obviously cached" is not
    evidence of "not cached".
    """
    import json
    from pathlib import Path

    verdict_path = Path(verdict_path)
    if not verdict_path.exists():
        raise SystemExit(
            f"REFUSED: no prefix-cache verdict at {verdict_path}.\n"
            "Run scripts/gpu_session/verify_prefix_cache_disabled.py first. Exact prompt "
            "replay is this experiment's central control; a live cache changes the cost it "
            "controls as a function of run order (WEEK2_PLAN.md 10.8).")
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    if verdict.get("verdict") != DISABLED:
        raise SystemExit(
            f"REFUSED: prefix-cache verdict is {verdict.get('verdict')!r}, not {DISABLED}.\n"
            "Relaunch vLLM with DISABLE_PREFIX_CACHING=1 and re-verify.")
    return verdict


# Prometheus' standard process metric. vLLM exposes it, and it changes iff the
# server process was restarted -- the event lock 3A cares about, and the one a
# spot preemption forces.
_PROCESS_START_RE = None


def server_process_epoch(base_url: str, override: str | None = None) -> str:
    """An identifier for the vLLM process a point is being driven against.

    Read from the server rather than passed, so it cannot be stale: if vLLM is
    restarted mid-session the next point picks up a different value on its own,
    and `metrics/classification.py` refuses to combine epochs offline.

    Lives beside the prefix-cache gate because both are "ask the running server
    what it actually is" checks, and both must be identical in every driver --
    the floor, the scout, the steady reference and the headline family all
    stamp the same value or the epoch cannot be compared across them.

    Falls back to an explicit token, then to a marker that is deliberately NOT
    a plausible epoch: a driver that could not identify the process must not
    hand out an identifier that looks like it did.
    """
    global _PROCESS_START_RE
    if override:
        return override
    import re

    import httpx

    if _PROCESS_START_RE is None:
        _PROCESS_START_RE = re.compile(r"^process_start_time_seconds\s+([\d.eE+-]+)", re.M)
    try:
        with httpx.Client(timeout=10.0) as client:
            text = client.get(f"{base_url.rstrip('/')}/metrics").text
        match = _PROCESS_START_RE.search(text)
        if match:
            return f"vllm-start-{float(match.group(1)):.0f}"
    except Exception:  # noqa: BLE001 -- recorded as unknown, never guessed
        pass
    return "UNKNOWN-PROCESS-EPOCH"


@dataclass(frozen=True)
class ProbeResult:
    """One prompt, served twice, at concurrency 1."""
    prompt_id: int
    char_len: int
    first_ttft_ms: float
    replay_ttft_ms: float

    @property
    def ratio(self) -> float:
        return self.replay_ttft_ms / self.first_ttft_ms

    def to_dict(self) -> dict:
        return {
            "prompt_id": self.prompt_id,
            "char_len": self.char_len,
            "first_ttft_ms": self.first_ttft_ms,
            "replay_ttft_ms": self.replay_ttft_ms,
            "ratio": self.ratio,
        }


def evaluate(probes: list[ProbeResult],
             metrics_hits: int | None = None,
             metrics_queries: int | None = None,
             engine_config_flag: bool | None = None) -> dict:
    """Verdict on whether prefix caching is live.

    `metrics_*` and `engine_config_flag` are supporting evidence and are
    recorded either way. They can only *strengthen* an ENABLED verdict, never
    override a behavioural one: a counter that does not exist in this vLLM
    build would otherwise silently vote "disabled".
    """
    if not probes:
        raise ValueError("prefix-cache verification needs at least one probe")

    too_short = [p for p in probes if p.char_len < MIN_PROBE_PROMPT_CHARS]
    if too_short:
        raise ValueError(
            f"probe prompts {[p.prompt_id for p in too_short]} are under "
            f"{MIN_PROBE_PROMPT_CHARS} chars. On a short prompt a cache hit and a cache miss "
            "both land near the no-load TTFT floor, so the ratio cannot discriminate and a "
            "'disabled' verdict would be meaningless.")

    ratios = [p.ratio for p in probes]
    worst = min(ratios)  # the most cache-hit-shaped observation
    reasons = []

    if worst <= CACHE_HIT_RATIO_CEILING:
        verdict = ENABLED
        reasons.append(
            f"a replay served in {worst:.2f}x the time of its first serving "
            f"(<= {CACHE_HIT_RATIO_CEILING}); load cannot speed up prefill, so the second "
            "serving came from cache")
    elif min(ratios) >= COLD_RATIO_FLOOR:
        verdict = DISABLED
        reasons.append(
            f"every replay paid full prefill again (ratios "
            f"{', '.join(f'{r:.2f}' for r in ratios)}, all >= {COLD_RATIO_FLOOR})")
    else:
        verdict = AMBIGUOUS
        reasons.append(
            f"replay ratios {', '.join(f'{r:.2f}' for r in ratios)} fall between the cache-hit "
            f"ceiling ({CACHE_HIT_RATIO_CEILING}) and the cold floor ({COLD_RATIO_FLOOR}) -- "
            "neither clearly cached nor clearly cold")

    if metrics_hits is not None and metrics_hits > 0:
        reasons.append(f"Prometheus reports {metrics_hits} prefix-cache hits")
        verdict = ENABLED
    elif metrics_hits == 0 and metrics_queries:
        reasons.append(f"Prometheus reports 0 hits over {metrics_queries} queries")

    if engine_config_flag is True:
        # Reporting the flag, not endorsing it: prefix caching must not be
        # enabled for the controlled headline (L6, WEEK2_PLAN.md 10.8), and
        # this branch exists to say so loudly.
        reasons.append("the engine config line reports enable_prefix_caching=True, which "
                       "must not be enabled for the controlled headline")
        verdict = ENABLED
    elif engine_config_flag is False:
        reasons.append("the engine config line reports enable_prefix_caching=False")

    return {
        "verdict": verdict,
        "safe_for_controlled_headline": verdict == DISABLED,
        "reasons": reasons,
        "probes": [p.to_dict() for p in probes],
        "min_ratio": worst,
        "thresholds": {
            "cache_hit_ratio_ceiling": CACHE_HIT_RATIO_CEILING,
            "cold_ratio_floor": COLD_RATIO_FLOOR,
            "min_probe_prompt_chars": MIN_PROBE_PROMPT_CHARS,
        },
        "supporting_evidence": {
            "prometheus_prefix_cache_hits": metrics_hits,
            "prometheus_prefix_cache_queries": metrics_queries,
            "engine_config_enable_prefix_caching": engine_config_flag,
            "note": "Supporting only. The behavioural probe decides, because a counter or a "
                    "config line can be missing or stale while the behaviour cannot.",
        },
    }

"""The prefix-cache preflight gate (R4 README L6; `WEEK2_PLAN.md` §10.8).

L6 requires verifying the *effective runtime configuration*, not the CLI
string. The distinction matters because every way this fails produces a
launch command that looks correct: a flag renamed between vLLM releases, a
flag applied to a different server than the one being driven, an environment
variable overriding it. The first session did not even get as far as being
wrong about it — prefix caching was on because it is the default, and nobody
had asked.

The decision logic is tested here with injected measurements, because the
thing under test is the verdict, not the HTTP plumbing. Both directions must
hold: a cache-hit-shaped replay must be REFUSED, and a cold-shaped one must
be allowed — a gate that only did the second would let the first session's
configuration straight through.

The ratios used are the ones actually measured on first-session data
(0.20x and 0.42x for warm replays), not invented ones.
"""

from __future__ import annotations

import pytest

from loadgen.prefix_cache import (
    AMBIGUOUS,
    DISABLED,
    ENABLED,
    MIN_PROBE_PROMPT_CHARS,
    ProbeResult,
    evaluate,
)

pytestmark = pytest.mark.redesign

LONG = 14960  # the first session's prompt 458


def _probe(first: float, replay: float, char_len: int = LONG, prompt_id: int = 458):
    return ProbeResult(prompt_id=prompt_id, char_len=char_len,
                       first_ttft_ms=first, replay_ttft_ms=replay)


# ---------------------------------------------------------------------------
# The control: measured cache-hit behaviour must be refused.
# ---------------------------------------------------------------------------


def test_control_the_measured_first_session_ratio_is_refused():
    """prompt 458: 523.3ms cold, 103.9ms warm -- ratio 0.20."""
    verdict = evaluate([_probe(523.3, 103.9)])
    assert verdict["verdict"] == ENABLED
    assert verdict["safe_for_controlled_headline"] is False
    assert "cache" in " ".join(verdict["reasons"])


def test_control_the_within_floor_ratio_is_also_refused():
    """prompt 1903: 197.7ms first serving, 83.9ms immediate replay -- 0.42."""
    verdict = evaluate([_probe(197.7, 83.9, char_len=4992, prompt_id=1903)])
    assert verdict["verdict"] == ENABLED


def test_control_one_bad_probe_among_good_ones_still_refuses():
    """The verdict keys off the WORST probe. A cache that only holds some
    prompts is still a cache."""
    verdict = evaluate([_probe(500.0, 495.0), _probe(500.0, 505.0), _probe(523.3, 103.9)])
    assert verdict["verdict"] == ENABLED


def test_cold_replays_are_allowed():
    verdict = evaluate([_probe(523.3, 519.0), _probe(410.0, 425.0), _probe(380.0, 372.0)])
    assert verdict["verdict"] == DISABLED
    assert verdict["safe_for_controlled_headline"] is True


def test_the_ambiguous_middle_is_not_treated_as_disabled():
    """A ratio between the two thresholds is reported as ambiguous and blocks
    the run. 'Not obviously cached' is not evidence of 'not cached'."""
    verdict = evaluate([_probe(500.0, 400.0)])  # 0.80
    assert verdict["verdict"] == AMBIGUOUS
    assert verdict["safe_for_controlled_headline"] is False


# ---------------------------------------------------------------------------
# The probe has to be capable of discriminating at all.
# ---------------------------------------------------------------------------


def test_control_short_probe_prompts_are_refused():
    """On a short prompt a hit and a miss both land near the ~82ms floor, so a
    'disabled' verdict from one would be meaningless."""
    with pytest.raises(ValueError, match="under"):
        evaluate([_probe(84.0, 82.0, char_len=120, prompt_id=1)])


def test_no_probes_is_an_error_not_a_pass():
    with pytest.raises(ValueError, match="at least one probe"):
        evaluate([])


def test_min_probe_length_is_where_prefill_becomes_visible():
    """Corpus q95. Below it, intrinsic cost is a small fraction of TTFT."""
    assert MIN_PROBE_PROMPT_CHARS == 4566


# ---------------------------------------------------------------------------
# Supporting evidence strengthens ENABLED but never overrides behaviour.
# ---------------------------------------------------------------------------


def test_prometheus_hits_force_an_enabled_verdict():
    verdict = evaluate([_probe(500.0, 495.0)], metrics_hits=1234, metrics_queries=99999)
    assert verdict["verdict"] == ENABLED, (
        "the server reported cache hits; behaviour that looked cold cannot outvote that")


def test_the_engine_config_flag_can_only_strengthen_a_refusal():
    verdict = evaluate([_probe(500.0, 495.0)], engine_config_flag=True)
    assert verdict["verdict"] == ENABLED


def test_absent_counters_do_not_vote_disabled():
    """A vLLM build without these metrics must not silently supply a clean
    bill of health."""
    cold = evaluate([_probe(500.0, 495.0)], metrics_hits=None, metrics_queries=None)
    assert cold["verdict"] == DISABLED  # from the probe alone

    warm = evaluate([_probe(523.3, 103.9)], metrics_hits=None, metrics_queries=None)
    assert warm["verdict"] == ENABLED  # still refused, on behaviour alone


def test_all_evidence_is_recorded_either_way():
    verdict = evaluate([_probe(523.3, 519.0)], metrics_hits=0, metrics_queries=500,
                       engine_config_flag=False)
    support = verdict["supporting_evidence"]
    assert support["prometheus_prefix_cache_hits"] == 0
    assert support["prometheus_prefix_cache_queries"] == 500
    assert support["engine_config_enable_prefix_caching"] is False
    assert verdict["probes"][0]["ratio"] == pytest.approx(519.0 / 523.3)


# ---------------------------------------------------------------------------
# The launch script must actually pass the flag.
# ---------------------------------------------------------------------------


def test_launch_script_disables_prefix_caching_by_default():
    from pathlib import Path

    script = (Path(__file__).resolve().parents[2]
              / "scripts" / "gpu_session" / "setup_and_launch_vllm.sh").read_text(encoding="utf-8")
    assert "--no-enable-prefix-caching" in script
    assert 'DISABLE_PREFIX_CACHING="${DISABLE_PREFIX_CACHING:-1}"' in script, (
        "the default must be OFF: a knob that defaults to vLLM's caching would put the "
        "confound back the moment someone forgets an env var")

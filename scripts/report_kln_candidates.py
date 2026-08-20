#!/usr/bin/env python
"""Joint k / L / N candidate table and the R3 evidence package
(Redesign README R3 and 11).

Reads the three analyses that precede it -- corpus tail structure (R1),
measured prompt cost, run-order effects, and the p99 sample-size bootstrap
(R2) -- and combines them into the one table the human reads at Hard Stop R3,
plus a markdown package.

The combination rule is the README's:

    N_candidate = max(N_prompt_tail_requirement, N_p99_stability_requirement)

Both halves are reported per candidate threshold rather than collapsed to a
single number, because R3 explicitly reserves the definition of "acceptable"
for the human. Nothing here is self-approved.

Usage:
    .venv/Scripts/python.exe scripts/report_kln_candidates.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

CAL_DIR = REPO_ROOT / "benchmarks" / "calibration" / "week2_redesign"
CORPUS_ANALYSIS = CAL_DIR / "corpus_tail_analysis.json"
PROMPT_COST = CAL_DIR / "prompt_cost_analysis.json"
RUN_ORDER = CAL_DIR / "run_order_effects.json"
P99_STUDY = CAL_DIR / "p99_sample_size.json"
OUT_JSON = CAL_DIR / "kln_candidates.json"
OUT_MD = CAL_DIR / "R3_EVIDENCE_PACKAGE.md"

# Tail-support thresholds: how many canonical prompts must sit above L. Not
# locked -- the grid exists so the human can pick a row.
TAIL_SUPPORT_TARGETS = (10, 20, 30, 50)

# Runtime model inputs. The breach region from the first session is low
# single-digit RPS (handoff 19), and the LOWEST lambda dominates wall clock
# because duration ~ N / lambda.
FINE_SWEEP_LAMBDAS = (1.5, 2.0, 2.5, 3.0, 4.0)
REPEATS = 3
WARMUP_S = 30.0  # placeholder: the real warmup N is still open by design
STANDUP_S = 900.0  # model load + health wait, from the first session


def load(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"missing {path.relative_to(REPO_ROOT)} -- run the R1/R2 scripts first")
    return json.loads(path.read_text(encoding="utf-8"))


def tail_requirement(corpus: dict, l_pct: float, target: int) -> int | None:
    """Smallest candidate N whose canonical multiset holds >= `target` prompts
    above L, and that the corpus can actually supply."""
    rows = [r for r in corpus["tail_support"] if r["L_pct"] == l_pct]
    for r in sorted(rows, key=lambda r: r["N"]):
        if r["canonical_prompts_above_L"] >= target and r["feasible_without_replacement"]:
            return r["N"]
    return None


def runtime_for(n: int) -> dict:
    per_repeat_s = sum(n / lam for lam in FINE_SWEEP_LAMBDAS) + WARMUP_S * len(FINE_SWEEP_LAMBDAS)
    total_s = REPEATS * per_repeat_s + STANDUP_S
    return {
        "seconds_at_lowest_lambda_per_point": n / min(FINE_SWEEP_LAMBDAS) + WARMUP_S,
        "seconds_per_repeat_full_sweep": per_repeat_s,
        "hours_total_headline": total_s / 3600.0,
        "assumes": {
            "fine_sweep_lambdas": list(FINE_SWEEP_LAMBDAS),
            "repeats": REPEATS,
            "warmup_s": WARMUP_S,
            "standup_s": STANDUP_S,
            "note": "headline matched workload only -- excludes the unloaded floor, the "
                    "natural-random secondary curve (R11), steady reference and adversarial. "
                    "Duration per point is the EXPECTED N/lambda; the materialized Poisson "
                    "realization decides the actual value (R6).",
        },
    }


def build(corpus: dict, p99: dict) -> dict:
    grid = corpus["candidate_N"]
    combo = p99["combination_rule"]["per_criterion"]
    max_feasible = max(
        (c["max_feasible_N_on_grid"] or 0) for c in corpus["candidate_constructions"]
    )

    rows = []
    for construction in corpus["candidate_constructions"]:
        for l_pct in corpus["candidate_L"]:
            for target in TAIL_SUPPORT_TARGETS:
                n_tail = tail_requirement(corpus, l_pct, target)
                if n_tail is None:
                    continue
                for flip_key, n_stab in combo["flip_rate_at_most"].items():
                    if n_stab is None:
                        continue
                    n_candidate = max(n_tail, n_stab)
                    feasible = (
                        construction["max_feasible_N_on_grid"] is not None
                        and n_candidate <= construction["max_feasible_N_on_grid"]
                        and n_candidate in grid
                    )
                    rows.append({
                        "construction": construction["name"],
                        "k": construction["k"],
                        "L_pct": l_pct,
                        "L_chars": next(r["L_chars"] for r in corpus["tail_support"]
                                        if r["L_pct"] == l_pct),
                        "tail_support_target": target,
                        "N_prompt_tail_requirement": n_tail,
                        "flip_rate_criterion": float(flip_key),
                        "N_p99_stability_requirement": n_stab,
                        "N_candidate": n_candidate,
                        "prompts_above_L_at_N": int(n_candidate * (100.0 - l_pct) / 100.0),
                        "top_1pct_support_at_N": n_candidate / 100.0,
                        "feasible_without_replacement": feasible,
                        "construction_N_ceiling": construction["max_feasible_N_on_grid"],
                        "runtime": runtime_for(n_candidate),
                    })

    return {
        "what": "Joint k/L/N candidates combining corpus tail support (R1) with p99 stability "
                "(R2), plus GPU runtime implications (README R3).",
        "status": "RECOMMENDATION -- k, L, N and N_max are locked by the human, not here",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "corpus_tail_analysis": str(CORPUS_ANALYSIS.relative_to(REPO_ROOT)).replace("\\", "/"),
            "p99_sample_size": str(P99_STUDY.relative_to(REPO_ROOT)).replace("\\", "/"),
            "prompt_cost_analysis": str(PROMPT_COST.relative_to(REPO_ROOT)).replace("\\", "/"),
            "run_order_effects": str(RUN_ORDER.relative_to(REPO_ROOT)).replace("\\", "/"),
        },
        "combination_rule": "N_candidate = max(N_prompt_tail_requirement, "
                            "N_p99_stability_requirement)",
        "structural_ceilings": {
            "corpus_size": corpus["corpus"]["total_prompts"],
            "max_feasible_N_without_repeating_a_prompt": max_feasible,
            "why": "Selection without replacement within a stratum caps N at the corpus size. "
                   "Repeating prompts inside one run would lift the cap and invite prefix-cache "
                   "reuse, which the first session shows is a live, large effect "
                   "(run_order_effects.json).",
        },
        "candidates": rows,
        "runtime_model": runtime_for(1000)["assumes"],
    }


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def write_markdown(corpus: dict, cost: dict, order: dict, p99: dict, joint: dict, out: Path) -> None:
    q = corpus["length_summary"]["quantiles"]
    fit = cost["unloaded_floor"]["fit"]
    proj = cost["corpus_wide_projection"]
    s15 = p99["studies"]["poisson_rps1.5"]
    s20 = p99["studies"]["poisson_rps2"]

    lines: list[str] = []
    A = lines.append

    A("# Week 2 redesign — R3 evidence package")
    A("")
    A("**Status: recommendations, not decisions.** `k`, `L`, `N` and `N_max` are locked by the")
    A("human at Hard Stop R3 (Redesign README §4). Every number below is an input to that read.")
    A("")
    A(f"Generated {joint['generated_at']} from:")
    for name, path in joint["inputs"].items():
        A(f"- `{path}`")
    A("")
    A("Regenerate the whole package with:")
    A("")
    A("```")
    A("python scripts/analyze_corpus_tail.py")
    A("python scripts/analyze_prompt_cost.py")
    A("python scripts/analyze_run_order_effects.py")
    A("python scripts/calibrate_p99_sample_size.py")
    A("python scripts/report_kln_candidates.py")
    A("```")
    A("")

    # ---- 1. corpus tail --------------------------------------------------
    A("## 1. Corpus tail structure (R1)")
    A("")
    A(f"Pinned corpus: `{corpus['corpus']['path']}`, "
      f"{corpus['corpus']['total_prompts']} prompts, "
      f"`sha256={corpus['corpus']['sha256'][:16]}…`")
    A("")
    A("Prompt length in characters is strongly right-skewed — the mean sits above the 80th")
    A("percentile, so \"average prompt\" describes almost nothing about the requests that")
    A("decide a p99.")
    A("")
    A(_md_table(
        ["quantile", "char_len", "prompts at or above"],
        [[f"p{k}", f"{v:,.0f}",
          f"{corpus['counts_above_quantile'][k]['count']:,}" if k in corpus["counts_above_quantile"] else "—"]
         for k, v in q.items()],
    ))
    A("")
    A("Histogram (log-spaced bins):")
    A("")
    edges = corpus["histogram"]["bin_edges_chars"]
    counts = corpus["histogram"]["counts"]
    peak = max(counts) or 1
    A("```")
    for i, c in enumerate(counts):
        bar = "#" * int(round(40 * c / peak))
        A(f"{edges[i]:>7,} - {edges[i + 1]:>7,}  {c:>5}  {bar}")
    A("```")
    A("")

    # ---- 2. candidate constructions --------------------------------------
    A("## 2. Candidate `k` / `L` constructions (R1)")
    A("")
    A("Allocation is **proportional to each stratum's natural population share**, largest-")
    A("remainder, selected **without replacement** inside a stratum. Proportional rather than")
    A("tail-inflating because D3 asks for *controlled representative* coverage: the point is to")
    A("make the realized composition deterministic, not to reshape it.")
    A("")
    A(_md_table(
        ["construction", "k", "quantile edges", "scarcest stratum", "implied N ceiling",
         "largest grid N", "rationale"],
        [[f"`{c['name']}`", str(c["k"]), "/".join(str(e) for e in c["edges_pct"]),
          f"#{c['binding_stratum']['index']}",
          f"{c['binding_stratum']['implied_N_ceiling']:,}",
          f"{c['max_feasible_N_on_grid']:,}",
          c["rationale"].split(". ")[0].rstrip(".") + "."]
         for c in corpus["candidate_constructions"]],
    ))
    A("")
    A("*Implied ceiling* is where the scarcest stratum runs out under proportional allocation;")
    A("*largest grid N* is the biggest candidate `N` at or below it. They differ because the")
    A("grid is coarse — `k6` can serve 4,800 in principle but 5,000 is the next grid step up.")
    A("")
    A("Tail support — canonical prompts above `L`, per candidate `N`:")
    A("")
    ns = corpus["candidate_N"]
    rows = []
    for l_pct in corpus["candidate_L"]:
        sub = [r for r in corpus["tail_support"] if r["L_pct"] == l_pct]
        r0 = sub[0]
        cells = []
        for n in ns:
            r = next(x for x in sub if x["N"] == n)
            cells.append(str(r["canonical_prompts_above_L"]) if r["feasible_without_replacement"]
                         else f"**{r['canonical_prompts_above_L']}!**")
        rows.append([f"q{l_pct:g}", f"{r0['L_chars']:,.0f}", f"{r0['corpus_prompts_above_L']}"] + cells)
    A(_md_table(["L", "L chars", "in corpus"] + [f"N={n:,}" for n in ns], rows))
    A("")
    A("`!` = the construction would need more prompts above `L` than the corpus holds.")
    A("")

    # ---- 3. what L should mean -------------------------------------------
    A("## 3. What makes a tail boundary meaningful (measured, not assumed)")
    A("")
    A("A quantile edge is a fact about the corpus, not about latency. The unloaded floor")
    A("(concurrency 1, 248 prompts, 0 errors) measures the intrinsic relation directly:")
    A("")
    A("```")
    A(f"TTFT_unloaded  =  {fit['intercept_ms']:.1f}ms  +  "
      f"{fit['slope_ms_per_char'] * 1000:.2f}ms per 1000 chars")
    A(f"pearson r = {fit['pearson_r']:.3f}     R^2 = {fit['r_squared']:.3f}     n = {fit['n']}")
    A("```")
    A("")
    A(f"Prompt length alone explains **{fit['r_squared'] * 100:.0f}%** of unloaded TTFT variance.")
    A("Per candidate stratum:")
    A("")
    A(_md_table(
        ["char range", "n", "TTFT p50", "TTFT max", "over 500ms"],
        [[f"{s['char_len_range'][0]:,.0f} – {s['char_len_range'][1]:,.0f}", str(s["n"]),
          f"{s['ttft_p50_ms']:.0f}ms" if s["n"] else "—",
          f"{s['ttft_max_ms']:.0f}ms" if s["n"] else "—",
          f"{s['fraction_over_slo'] * 100:.0f}%" if s["n"] else "—"]
         for s in cost["unloaded_floor"]["by_candidate_stratum"]],
    ))
    A("")
    A("Projecting that fit across the whole corpus (an **extrapolation**, flagged as such in the")
    A("JSON) gives the headroom the headline experiment has to work with:")
    A("")
    A(f"- projected unloaded p99 TTFT ≈ **{proj['p99_ms']:.0f}ms**")
    A(f"- headroom to the 500ms SLO ≈ **{500 - proj['p99_ms']:.0f}ms** "
      f"({(500 - proj['p99_ms']) / 5:.0f}% of the SLO)")
    A(f"- a prompt reaches 500ms *unloaded* at ≈ **{proj['char_len_at_slo']:,.0f} chars**, the "
      f"{proj['corpus_percentile_at_slo_length']:.2f}th corpus percentile")
    A("")
    A("So the curve is not being measured in open space: interference only has to add ~130ms at")
    A("the tail to cross the line. That argues for placing `L` where intrinsic cost starts to be")
    A("a material fraction of the SLO — q99 (11,471 chars, ~370ms unloaded) rather than q90")
    A("(2,358 chars, ~140ms), which is a length the SLO barely notices.")
    A("")

    # ---- 4. bootstrap ----------------------------------------------------
    A("## 4. p99 stability vs `N` (R2) — the two sources, separately")
    A("")
    A(f"Nonparametric bootstrap, {p99['config']['resamples_per_N']:,} resamples per `N`, "
      f"master seed {p99['config']['master_seed']}, percentile method "
      f"`{p99['config']['primary_percentile_method']}`.")
    A("")
    A("**These are shown separately and combined conservatively. They are never averaged** —")
    A("README R2, and see §6 for why that matters more than it looks.")
    A("")
    for label, st in (("4.1 — 2 RPS (near-boundary)", s20), ("4.2 — 1.5 RPS (sparse low-load)", s15)):
        m = st["source"]
        A(f"### {label}")
        A("")
        A(f"Source: `{m['samples_path']}` `sha256={m['samples_sha256'][:16]}…`  ")
        A(f"n = {m['post_warmup_sample_count']} post-warmup samples, "
          f"nominal λ = {m['nominal_lambda_rps']} RPS, "
          f"materialized schedule = {m['materialized_schedule_count']}, "
          f"censoring = {m['censoring_rate'] * 100:.1f}%, "
          f"warmup = {m['warmup_rule'].split(',')[0]}  ")
        A(f"Matches the committed point record: **{m['matches_known_first_session_point']}** "
          f"(record p99 {m['committed_point_record_p99_ms']:.1f}ms)  ")
        A(f"Point estimate {st['point_estimate_ms']:.1f}ms → **{st['point_classification']}**")
        A("")
        A(_md_table(
            ["N", "top-1% support", "p99 median", "95% interval", "width", "rel width",
             "flip rate", "straddles 500ms"],
            [[f"{n:,}", f"{st['per_candidate_N'][str(n)]['top_1pct_support']:.0f}",
              f"{st['per_candidate_N'][str(n)]['p99_median_ms']:.1f}ms",
              f"[{st['per_candidate_N'][str(n)]['p99_ci95_ms'][0]:.1f}, "
              f"{st['per_candidate_N'][str(n)]['p99_ci95_ms'][1]:.1f}]",
              f"{st['per_candidate_N'][str(n)]['p99_ci95_width_ms']:.1f}ms",
              f"{st['per_candidate_N'][str(n)]['p99_ci95_relative_width']:.2f}",
              f"{st['per_candidate_N'][str(n)]['flip_rate'] * 100:.1f}%",
              "**yes**" if st["per_candidate_N"][str(n)]["ci_straddles_slo"] else "no"]
             for n in p99["config"]["candidate_N"]],
        ))
        A("")
        c = st["candidate_criteria"]
        A("Smallest grid `N` per candidate criterion (none of these thresholds is locked):")
        A("")
        A(_md_table(
            ["criterion", "threshold", "smallest N"],
            [["flip rate ≤", k, str(v)] for k, v in c["flip_rate_at_most"].items()]
            + [["95% CI width ≤", f"{k}ms", str(v)] for k, v in c["ci95_width_ms_at_most"].items()]
            + [["95% CI relative width ≤", k, str(v)]
               for k, v in c["ci95_relative_width_at_most"].items()]
            + [["95% CI entirely clear of 500ms", "—", str(c["ci95_clears_slo_entirely"])]],
        ))
        A("")

    A("### 4.3 — the two disagree, and the reason is not sample size")
    A("")
    A("The 1.5-RPS array is satisfied at the smallest `N` on the grid under every criterion; the")
    A("2-RPS array needs thousands. Read naively that says 1.5 RPS is an easy point. It is not")
    A("what the data says. The 1.5-RPS array is **prefix-cache contaminated** (§6): its TTFT")
    A("distribution is compressed, so its bootstrap interval is narrow for a reason that has")
    A("nothing to do with how many samples were taken.")
    A("")
    A("This is exactly why README R2 forbids averaging. Conservative combination, per criterion:")
    A("")
    combo = p99["combination_rule"]["per_criterion"]
    A(_md_table(
        ["criterion", "threshold", "1.5 RPS", "2 RPS", "max()"],
        [["flip rate ≤", k, str(s15["candidate_criteria"]["flip_rate_at_most"][k]),
          str(s20["candidate_criteria"]["flip_rate_at_most"][k]), f"**{v}**"]
         for k, v in combo["flip_rate_at_most"].items()]
        + [["95% CI width ≤", f"{k}ms", str(s15["candidate_criteria"]["ci95_width_ms_at_most"][k]),
            str(s20["candidate_criteria"]["ci95_width_ms_at_most"][k]), f"**{v}**"]
           for k, v in combo["ci95_width_ms_at_most"].items()],
    ))
    A("")
    A("**The single most decisive number in this package:** at `N = 250` — close to the "
      f"n = {s20['source']['post_warmup_sample_count']} the first session actually had — the 2-RPS")
    A(f"point flips its own classification in **{s20['per_candidate_N']['250']['flip_rate'] * 100:.0f}%**")
    A("of resamples. The first session's breach read was a coin toss, and `n ≥ 100` cannot")
    A("distinguish that from a measurement.")
    A("")

    # ---- 5. joint --------------------------------------------------------
    A("## 5. Joint `k` / `L` / `N` candidates with runtime (R3)")
    A("")
    A(f"`{joint['combination_rule']}`")
    A("")
    sc = joint["structural_ceilings"]
    A(f"**Structural ceiling:** the pinned corpus holds {sc['corpus_size']:,} prompts, so the")
    A(f"largest canonical multiset selectable without repeating a prompt is "
      f"**{sc['max_feasible_N_without_repeating_a_prompt']:,}**.")
    A("")
    # The table is held at L = q99, on the measured grounds in section 3. The
    # candidate constructions do not change N_tail for a given L -- they differ
    # only in the ceiling they impose -- so k is carried as the ceiling column
    # rather than as four near-identical copies of every row. Every (k, L, N)
    # combination is in kln_candidates.json.
    min_ceiling = min(c["construction_N_ceiling"] for c in joint["candidates"]
                      if c["construction_N_ceiling"])
    seen = set()
    rows = []
    for r in joint["candidates"]:
        if r["L_pct"] != 99.0 or r["construction"] != "k3_coarse":
            continue
        key = (r["tail_support_target"], r["flip_rate_criterion"])
        if key in seen:
            continue
        seen.add(key)
        n = r["N_candidate"]
        rows.append([
            str(r["tail_support_target"]), f"{r['flip_rate_criterion'] * 100:.0f}%",
            f"{r['N_prompt_tail_requirement']:,}", f"{r['N_p99_stability_requirement']:,}",
            f"**{n:,}**", str(r["prompts_above_L_at_N"]),
            f"{r['top_1pct_support_at_N']:.0f}",
            f"{r['runtime']['seconds_at_lowest_lambda_per_point'] / 60:.0f} min",
            f"{r['runtime']['hours_total_headline']:.1f} h",
            "yes" if n <= min_ceiling else "**NO**",
        ])
    A(f"Held at `L = q99` (11,471 chars) on the measured grounds in §3. The four candidate")
    A(f"constructions do not change `N` for a given `L` — they differ only in the ceiling they")
    A(f"impose, the tightest being **{min_ceiling:,}** (`k6_readme_example`). Every")
    A("`(k, L, N)` combination is in `kln_candidates.json`.")
    A("")
    A(_md_table(
        ["prompts > L target", "flip ≤", "N from tail", "N from p99", "**N candidate**",
         "prompts > L", "top-1% support", "1 point @1.5 RPS", "headline total",
         f"fits {min_ceiling:,} ceiling"],
        rows,
    ))
    A("")
    rm = joint["runtime_model"]
    A(f"Runtime model: fine sweep at λ ∈ {rm['fine_sweep_lambdas']}, {rm['repeats']} repeats,")
    A(f"{rm['warmup_s']:.0f}s warmup per point, {rm['standup_s'] / 60:.0f} min standup. "
      f"{rm['note']}")
    A("")

    # ---- 6. findings -----------------------------------------------------
    A("## 6. Two findings that were not on the R0–R3 worklist")
    A("")
    A("### 6.1 — Prefix caching makes run order an experimental variable")
    A("")
    A("The server ran with `enable_prefix_caching=True` and `enable_chunked_prefill=True` "
      "(vLLM defaults;")
    A("neither was set by the runbook). Every Stage A schedule was built from the same master")
    A("seed, so the shorter schedules are strict **prefixes** of the longer ones — every point")
    A("replays the prompts of every shorter point.")
    A("")
    A("Joining each loaded point against the unloaded floor on `prompt_id`:")
    A("")
    A(_md_table(
        ["point", "prompts ≥ q95 in common", "median loaded/unloaded TTFT", "verdict"],
        [[f"`{c['tag']}`", str(c["long_prompts_only"]["n"]),
          f"{c['long_prompts_only']['median_ratio']:.2f}×", c["verdict"].split(":")[0]]
         for c in order["comparisons"]],
    ))
    A("")
    A("Worked example — the same prompt, same model, same server:")
    A("")
    d = order["comparisons"][0]["long_prompt_detail"][0]
    A("```")
    A(f"prompt {d['prompt_id']} ({d['char_len']:,.0f} chars)")
    A(f"  concurrency 1, no load      {d['unloaded_ttft_ms']:>7.1f}ms")
    A(f"  under 1.5 RPS of load       {d['loaded_ttft_ms']:>7.1f}ms   ({d['ratio']:.2f}x)")
    A("```")
    A("")
    hr = order["prefix_cache_hit_rate_summary"]
    blk = hr["final_active_block"]
    A("Load cannot make prefill five times faster. The 1.5-RPS point was driven **last**, after")
    A("the sweep and after the unloaded floor had just re-loaded those exact prompts. vLLM's")
    A(f"reported hit rate ends the session at {hr['last_pct']:.1f}%, and the final low-load block")
    A(f"({blk['from_time']}–{blk['to_time']}, peak concurrency {blk['peak_running']}) accounts for")
    A(f"{blk['from_pct']:.1f}% → {blk['to_pct']:.1f}% of that on its own — the contamination")
    A("happening in real time, not a session-wide average.")
    A("")
    A("**Why this outlives the old data.** D2 fixes one canonical prompt multiset across every")
    A("RPS point *and* every repeat; D4 forbids restarting vLLM between repeats. Together they")
    A("guarantee that every point after the first replays prompts the server has already cached")
    A("— a drift aligned with run order, which is the same class of confound as the prompt tail")
    A("the redesign exists to remove, but systematic rather than random.")
    A("")
    A("Options, for the human (full trade-offs in `run_order_effects.json`):")
    A("")
    for o in order["options_for_the_human"]:
        A(f"- **{o['option']}** — {o['effect']} *Cost:* {o['cost']}")
    A("")
    A("Whatever is chosen, prefix cache hit rate is currently **not** recorded per point. It")
    A("should become a per-point covariate so a contaminated point is visible in its own")
    A("artifact instead of reconstructed from a server log.")
    A("")

    A("### 6.2 — Two percentile conventions already coexist in the evidence")
    A("")
    ms = cost["percentile_method_sensitivity"]
    A(f"The promoted `unloaded_floor.metrics.json` reports p99 = "
      f"{ms['committed_floor_record_p99_ms']:.3f}ms. On the same 248 samples,")
    A(f"`metrics.compute.percentile` (linear interpolation — the method every Stage A point")
    A(f"record uses) gives {ms['unloaded_floor']['linear']:.3f}ms. The floor was produced by a")
    A("one-off on-instance script that is not in the repo.")
    A("")
    A("At the boundary this is not cosmetic. The 2-RPS point's p99, same samples:")
    A("")
    A(_md_table(
        ["method", "p99", "classification"],
        [[m, f"{v:.1f}ms", "OVER" if v >= 500 else "UNDER"]
         for m, v in s20["source"]["observed"]["p99_by_method_ms"].items()],
    ))
    A("")
    A("**The percentile method alone flips the verdict.** The bootstrap shows the disagreement")
    A("is a small-sample effect — by `N ≥ 1000` every method agrees — which is one more")
    A("independent argument for a large `N`, and an argument for locking the method explicitly")
    A("as part of the classification rule rather than inheriting it from whichever script ran.")
    A("")

    # ---- 7. recommendations ---------------------------------------------
    A("## 7. Recommendations — for the human to lock, reject or replace")
    A("")
    A("**None of the following is a decision.** They are the reads this evidence supports, with")
    A("the reasoning attached so a different call can be made against the same data.")
    A("")
    A("### `k` — recommend `k6_readme_example` (6 strata: 0/50/90/95/99/99.5/100)")
    A("")
    A("Because the fixed multiset is reused everywhere, tail *composition* is held constant at")
    A("any `k`. What `k` actually buys is fidelity of the fixed multiset to the corpus's natural")
    A("shape, and control over *which* prompts fill the top stratum. Inside a single 99–100")
    A("stratum the char range runs 11,471 → 44,445 — a 4× spread whose projected unloaded TTFT")
    A("runs ~370ms → ~1,200ms. Splitting it at q99.5 stops the selection from filling the top")
    A("1% from its cheaper half. Cost: the tightest implied `N` ceiling of the four candidates")
    A(f"(4,800; {min_ceiling:,} once rounded to this grid — though `k4_tail_split` and")
    A("`k5_deep_tail` round to the same place, so on this grid the cost is only against")
    A("`k3_coarse`). If `N > 4,000` is wanted, only `k3_coarse` reaches 5,000, and it buys that")
    A("by giving up all intra-tail control.")
    A("")
    A("### `L` — recommend `q99` = 11,471 chars")
    A("")
    A("On measured grounds, not roundness (§3): a q99-length prompt costs ~370ms of TTFT with")
    A("**no load at all**, i.e. ~74% of the SLO, so it is where prompt length starts deciding")
    A("the verdict. q90 (2,358 chars, ~140ms) is a length the SLO barely notices, and gating on")
    A("it would call 500 prompts \"tail\" while controlling nothing that moves a p99. `L = q99`")
    A("also makes tail support and top-1% support the same quantity, which keeps the two halves")
    A("of the `N` requirement on one axis.")
    A("")
    A("### `N` — recommend 4,000, with 2,500 as the budget alternative")
    A("")
    A("| | N = 2,500 | N = 4,000 |")
    A("|---|---|---|")
    A("| per-run flip rate (2 RPS source) | ~8% | ~3% |")
    A("| prompts above `L` | 25 of 50 available | 40 of 50 available |")
    A("| one point at λ=1.5 | ~28 min | ~45 min |")
    A("| headline total (3 repeats × 5 λ) | ~4.9 h | ~7.5 h |")
    A(f"| fits the `k6` ceiling ({min_ceiling:,}) | yes | exactly |")
    A("")
    A("4,000 is the smallest grid `N` reaching a ≤5% per-run flip rate, and it lands exactly on")
    A("the `k6` ceiling — so it is simultaneously the most evidence this construction can carry")
    A("and the least that meets the criterion. That coincidence is worth noticing rather than")
    A("relying on.")
    A("")
    A("**The argument for 2,500 instead is the repeat structure.** D5 gives the verdict to")
    A("independent repeats, not to one run. A 10% per-run flip rate does not mean a 10% chance")
    A("of a wrong verdict when three independent repeats must agree — so per-run stability may")
    A("be worth less than the extra 2.6 hours of session length, and session length is where")
    A("spot preemption risk lives. That trade is the human's; both rows are supported.")
    A("")
    A("### `N_max` / evidence ceiling — recommend 5,000, plus a repeat and wall-clock bound")
    A("")
    A("- **`N_max` = 5,000 — structural, not chosen.** It is the pinned corpus size, hence the")
    A("  largest canonical multiset selectable without repeating a prompt. Going past it means")
    A("  either changing the pinned corpus (locked) or repeating prompts inside a run, which")
    A("  §6.1 shows is not a neutral act on a prefix-caching server.")
    A("- **`repeats_max` = 3 at the locked `N`**, then stop escalating.")
    A("- **headline wall-clock budget ≈ 8 h**, which `N = 4,000` consumes almost entirely.")
    A("")
    A("**The escape hatch is not hypothetical.** A ≤1% per-run flip rate needs `N ≈ 7,500` —")
    A("**above `N_max`, and therefore unreachable with this corpus.** If the crossing is still")
    A("`UNCERTAIN` at the ceiling, R10's interval-valued breach is the outcome the evidence")
    A("actually supports, not a fallback to apologise for.")
    A("")
    A("### Two locks this evidence says are missing")
    A("")
    A("1. **Percentile method** must be locked explicitly as part of the classification rule")
    A("   (§6.2). It is currently inherited from whichever script runs, and at small `n` it")
    A("   flips the verdict on its own.")
    A("2. **Prefix-cache policy** must be decided before the canonical workload is frozen")
    A("   (§6.1), because D2's fixed multiset is what makes the effect systematic.")
    A("")

    # ---- 8. conflicts ----------------------------------------------------
    A("## 8. Tensions found with the authoritative documents")
    A("")
    A("Surfaced, not reconciled (`WEEK2_EXECUTION.md` precedence rule).")
    A("")
    A("### 8.1 — `WEEK2_PLAN.md` §3.4 forbids exactly what D3 requires")
    A("")
    A("§3.4 is LOCKED as *\"Random sample, **no length stratification** — preserves the natural")
    A("length distribution locked in §2.2. Stratifying would shape the distribution toward a")
    A("preferred shape rather than measuring the corpus's natural mix.\"* D3 requires deriving")
    A("prompt-length strata and freezing a fixed membership from them, and §3.4's")
    A("with-replacement i.i.d. draw is replaced by without-replacement selection.")
    A("")
    A("**Assessment:** in scope for supersession — the first session falsified §2.2's premise")
    A("that a fixed seeded distribution holds the prompt contribution constant, and §3.4's rule")
    A("is not in the README §3 keep-locked list. Worth noting that *proportional* allocation")
    A("honours §3.4's stated intent better than the random draw did: it reproduces the natural")
    A("shape exactly instead of approximately, which is what \"measuring the corpus's natural")
    A("mix\" was asking for. **But the amendment README §7 requires has not been written**, and")
    A("it is gated behind this hard stop. Flagged so the lock is not left contradicted in the")
    A("authoritative doc while code implements the opposite.")
    A("")
    A("### 8.2 — the README's own description of the 1.5-RPS source array is falsified")
    A("")
    A("R2 calls it \"the sparser clean low-load diagnostic\". It is not clean (§6.1). Both arrays")
    A("were still used as instructed, and the conservative `max()` rule contains the damage —")
    A("but the array cannot be cited as evidence that 1.5 RPS sits comfortably under the SLO,")
    A("and handoff §19's \"1.5 RPS ... was clearly below\" does not survive either.")
    A("")
    A("### 8.3 — D2 and D4 jointly guarantee the contamination in §6.1")
    A("")
    A("Both are LOCKED redesign decisions, and neither is wrong on its own. Together, on a")
    A("server with prefix caching on, they make cache advantage a monotone function of run")
    A("order. This needs a decision before R4 freezes the canonical workload.")
    A("")
    A("### 8.4 — both R2 source points are `flagged` for a reason D7 declassifies")
    A("")
    A("The promoted point records carry `flagged: true` at −6.25% (2 RPS) and −7.8% (1.5 RPS)")
    A("divergence, and are plotted at *achieved* RPS under Option Y. D7 says finite-Poisson")
    A("realization variance is descriptive metadata and must not fail the driver. So the legacy")
    A("records label as driver divergence precisely what the redesign reclassifies as noise.")
    A("The legacy interpretation is pinned and must not be rewritten (R0.4) — but anyone reading")
    A("those records needs to know the flag is measuring the old semantics.")
    A("")
    A("### 8.5 — `--max-model-len` sizing changes from probabilistic to guaranteed")
    A("")
    A("`WEEK2_PLAN.md` §6.1 requires `--max-model-len` sized to the longest corpus prompt plus")
    A("max output. The first session ran `max_model_len=20000`, and the corpus's longest prompt")
    A("(44,445 chars, `prompt_id` 790) was **never drawn** — the 2-RPS schedule topped out at")
    A("16,781 chars. A canonical multiset with a fixed top stratum will include the extremes")
    A("**at every point of every repeat, by construction**. The sizing must therefore be")
    A("re-verified against the actual tokenizer before R4, not inherited.")
    A("")
    A("### 8.6 — reopened by provenance, noted for completeness")
    A("")
    A("`Y = 120s` (§2.4) and `n ≥ 100` (§2.4/§8) are explicitly reopened by the README, so they")
    A("are not conflicts. Recorded here only because both still read as RESOLVED/LOCKED in")
    A("`WEEK2_PLAN.md` and `STATUS.md`, which is a stale-lock hazard for the next reader.")
    A("")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    args = parser.parse_args()

    corpus, cost, order, p99 = (load(p) for p in (CORPUS_ANALYSIS, PROMPT_COST, RUN_ORDER, P99_STUDY))
    joint = build(corpus, p99)

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(joint, indent=2) + "\n", encoding="utf-8")
    write_markdown(corpus, cost, order, p99, joint, args.out_md)

    print(f"candidates: {len(joint['candidates'])}")
    print(f"structural N ceiling (no prompt repeats): "
          f"{joint['structural_ceilings']['max_feasible_N_without_repeating_a_prompt']:,}")
    print(f"written: {args.out_json.relative_to(REPO_ROOT)}")
    print(f"written: {args.out_md.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

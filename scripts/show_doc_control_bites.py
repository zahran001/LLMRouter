#!/usr/bin/env python
"""Show each documentation-governance control going RED before it goes GREEN.

`WEEK2_EXECUTION.md` Hard Stop 2 states the rule this script exists to serve:
"Do not accept 'all five pass' as a summary -- the reds are the proof." A green
test that never went red proves nothing, and "make the test pass" and "make the
test meaningfully pass" look identical in a checkmark.

`tests/redesign/test_week2_doc_state.py` encodes the R-DOC controls, but it
reports them as passing tests, which shows the reds only by implication. This
runs the broken variant and the real one side by side and PRINTS what each
does, so the failure is legible rather than inferred.

    C-DOC-1  strip DO NOT EXECUTE from a superseded runbook
    C-DOC-2  authorize N=5000 in the machine-readable policy
    C-DOC-3  the REAL stale warmup sentence, and its corrected form
    C-DOC-4  mark a second document as the current GPU runbook
    C-DOC-5  scope: one SUPERSEDED row must not exempt the row beside it
    C-DOC-6  scope: an explicitly historical heading must still hold provenance

C-DOC-3, 5 and 6 exist because the first version of this suite went green over
a real defect. Its C-DOC-3 injected a *synthetic* sentence -- "resolve warmup
after the run with --warmup-n" -- which matched a regex, sat in an unmarked
section and contained no negative word, so it exercised the one path where
every exemption happened to be open. The sentence actually in the repository
was:

    Applying the real N is a re-filter over the committed sidecars,
    never a GPU re-run.

which the checker skipped, because "never" was read as a denial (it denies the
GPU re-run, not the re-filter) and because a SUPERSEDED marker four rows down
exempted the whole table. A control built from real text would have bitten on
day one. C-DOC-3 is now built from that exact sentence class, and C-DOC-5/6
pin the scope rules that let it through.

Each control mutates a real tracked file, runs the real check against it, and
restores the original bytes. Restoration is verified by SHA-256 before the
script exits -- a control demonstration that corrupts the repository would be a
poor trade for the evidence it produces.

Exit code is non-zero if any control fails to bite, i.e. if a broken document
was accepted, or if any file was not restored byte-for-byte.

Usage:
    .venv/Scripts/python.exe scripts/show_doc_control_bites.py
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_FILE = "tests/redesign/test_week2_doc_state.py"
STALE_TEST = "test_active_documents_do_not_assert_stale_headline_semantics"

PYTHON = sys.executable

results: list[tuple[str, bool, str]] = []

# The sentence class that survived an entire documentation cleanup. Kept
# verbatim in shape: a table row, a positive recommendation, and a "never" that
# denies something else.
REAL_STALE_WARMUP_ROW = (
    "| Per-point warmup N | **10s placeholder — OPEN BY DESIGN** | Applying the real "
    "N is a **re-filter over the committed sidecars, never a GPU re-run**: the warmup "
    "filter is metrics-side, so `--warmup-n <N>` re-derives every point |\n"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_check(test_name: str) -> tuple[bool, str, str]:
    """Run one test. Returns (passed, one-line summary, full output)."""
    proc = subprocess.run(
        [PYTHON, "-m", "pytest", f"{TEST_FILE}::{test_name}", "-q", "-p", "no:cacheprovider",
         "--no-header", "-x"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    passed = proc.returncode == 0
    tail = [l for l in proc.stdout.split("\n") if l.strip()]
    summary = tail[-1] if tail else "(no output)"
    return passed, summary, proc.stdout


def report(name: str, red_ok: bool, green_ok: bool, red_detail: str, green_detail: str) -> None:
    ok = red_ok and green_ok
    print(f"\n--- {name} ---")
    print(f"  RED   (broken document must be rejected): {'BITES' if red_ok else 'DID NOT BITE'}")
    print(f"        {red_detail}")
    print(f"  GREEN (real document must be accepted):   {'PASSES' if green_ok else 'FAILED'}")
    print(f"        {green_detail}")
    results.append((name, ok, "" if ok else "control did not bite, or the real document failed"))


def _mutate_and_check(path: Path, original: bytes, mutate, test_name: str):
    """Apply one mutation, run the check, always restore. Returns (passed, summary, out)."""
    text = original.decode("utf-8")
    broken = mutate(text)
    if broken == text:
        return None
    try:
        path.write_text(broken, encoding="utf-8", newline="")
        return run_check(test_name)
    finally:
        path.write_bytes(original)


def control(name: str, rel_path: str, test_name: str, mutate) -> None:
    """Mutate one file, assert the check goes red, restore, assert it goes green."""
    path = REPO_ROOT / rel_path
    original = path.read_bytes()
    before = hashlib.sha256(original).hexdigest()

    outcome = _mutate_and_check(path, original, mutate, test_name)
    if outcome is None:
        report(name, False, False, "mutation was a no-op -- the control never ran", "")
        return
    red_passed, red_summary, _ = outcome
    red_ok = not red_passed  # the check must FAIL on the broken document

    after = sha256(path)
    if after != before:
        report(name, False, False, "FILE NOT RESTORED", f"{before} -> {after}")
        return

    green_passed, green_summary, _ = run_check(test_name)
    report(
        name,
        red_ok,
        green_passed,
        f"{test_name}: {red_summary}",
        f"{test_name}: {green_summary}  (restored, sha256 {after[:12]}...)",
    )


def scope_control(name: str, rel_path: str, stale_block: str, safe_block: str,
                  must_name: str = "", must_not_name: str = "") -> None:
    """Prove the checker rejects a real stale block and accepts a properly marked one.

    Same file, same check, two mutations. The pair is the point: a rule that
    only ever rejects is unusable and gets worked around, so the corrected form
    has to be demonstrably writable.
    """
    path = REPO_ROOT / rel_path
    original = path.read_bytes()
    before = hashlib.sha256(original).hexdigest()

    stale = _mutate_and_check(path, original, lambda t: t + stale_block, STALE_TEST)
    safe = _mutate_and_check(path, original, lambda t: t + safe_block, STALE_TEST)
    after = sha256(path)

    if stale is None or safe is None:
        report(name, False, False, "mutation was a no-op -- the control never ran", "")
        return
    if after != before:
        report(name, False, False, "FILE NOT RESTORED", f"{before} -> {after}")
        return

    red_passed, red_summary, red_out = stale
    red_ok = not red_passed
    detail = f"{STALE_TEST}: {red_summary}"

    # A red is only evidence if it is red for the right reason.
    if red_ok and must_name and must_name not in red_out:
        red_ok = False
        detail = f"rejected, but not for [{must_name}] -- wrong reason"
    if red_ok and must_not_name and must_not_name in red_out:
        red_ok = False
        detail = f"rejected partly for [{must_not_name}], which is correctly marked"

    green_passed, green_summary, _ = safe
    report(
        name,
        red_ok,
        green_passed,
        detail,
        f"corrected form accepted: {green_summary}  (restored, sha256 {after[:12]}...)",
    )


# ---------------------------------------------------------------------------
# C-DOC-1 -- a superseded runbook that no longer refuses execution
# ---------------------------------------------------------------------------

def c_doc_1() -> None:
    control(
        "C-DOC-1  superseded runbook stops saying DO NOT EXECUTE",
        "WEEK2_GPU_IMPLEMENTATION_README.md",
        "test_historical_and_superseded_documents_say_do_not_execute",
        lambda t: t.replace("STATUS: SUPERSEDED — DO NOT EXECUTE", "STATUS: SUPERSEDED", 1),
    )


# ---------------------------------------------------------------------------
# C-DOC-2 -- the policy quietly authorizes the escalation lock 2B forbids
# ---------------------------------------------------------------------------

def c_doc_2() -> None:
    control(
        "C-DOC-2  machine policy authorizes N=5000",
        "benchmarks/workloads/week2_headline/repeat_policy.json",
        "test_repeat_policy_encodes_the_six_locks",
        lambda t: t.replace('"authorized": false,\n      "why_not"', '"authorized": true,\n      "why_not"', 1),
    )


# ---------------------------------------------------------------------------
# C-DOC-3 -- the real stale warmup sentence, and the corrected wording
# ---------------------------------------------------------------------------

def c_doc_3() -> None:
    scope_control(
        "C-DOC-3  the real stale warmup sentence ('never a GPU re-run')",
        "docs/WEEK2_GPU_SESSION_2_PLAN.md",
        stale_block="\n## Warmup resolution\n\n" + REAL_STALE_WARMUP_ROW,
        safe_block=(
            "\n## Warmup resolution\n\n"
            "Post-hoc warmup re-filtering of headline sidecars is not valid for the\n"
            "redesigned exact-N headline. If the 60s boundary proves insufficient,\n"
            "regenerate the schedules offline before Tier B.\n"
        ),
        must_name="post-hoc warmup re-filtering",
    )


# ---------------------------------------------------------------------------
# C-DOC-4 -- two documents claim to be the current GPU runbook
# ---------------------------------------------------------------------------

def c_doc_4() -> None:
    # Promote the superseded session #1 pre-flight into a second runbook row.
    old_row = (
        "| `docs/WEEK2_GPU_PREFLIGHT.md` | SUPERSEDED | The Hard Stop **4** pre-flight "
        "checklist for session #1, including its `GPU SESSION READY` verdict | no | "
        "`docs/WEEK2_GPU_SESSION_2_PREFLIGHT.md` |"
    )
    new_row = (
        "| `docs/WEEK2_GPU_PREFLIGHT.md` | EXECUTABLE | The Hard Stop **4** pre-flight "
        "checklist for session #1, including its `GPU SESSION READY` verdict | **yes** | — |"
    )
    control(
        "C-DOC-4  a second document is marked the current GPU runbook",
        "docs/WEEK2_DOC_INDEX.md",
        "test_exactly_one_current_gpu_runbook",
        lambda t: t.replace(old_row, new_row, 1),
    )


# ---------------------------------------------------------------------------
# C-DOC-5 -- scope: a marker on one row must not vouch for the row beside it
# ---------------------------------------------------------------------------

def c_doc_5() -> None:
    scope_control(
        "C-DOC-5  a SUPERSEDED row must not exempt its neighbour",
        "docs/WEEK2_GPU_SESSION_2_PLAN.md",
        stale_block=(
            "\n## Open calibration values\n\n"
            + REAL_STALE_WARMUP_ROW
            + "| Measurement window Y | **120s** | SUPERSEDED 2026-08-19 by exact-N |\n"
        ),
        safe_block=(
            "\n## Open calibration values\n\n"
            "| Per-point warmup N | **60s frozen boundary** | Validated forward in Tier A |\n"
            "| Measurement window Y | **120s** | SUPERSEDED 2026-08-19 by exact-N |\n"
        ),
        must_name="post-hoc warmup re-filtering",
        must_not_name="fixed 120s headline window",
    )


# ---------------------------------------------------------------------------
# C-DOC-6 -- scope: history stays writable under an explicit historical heading
# ---------------------------------------------------------------------------

def c_doc_6() -> None:
    scope_control(
        "C-DOC-6  an explicitly historical heading still holds provenance",
        "docs/WEEK2_GPU_SESSION_2_PLAN.md",
        # Same stale text, no heading marker: must be rejected.
        stale_block=(
            "\n## How warmup was resolved\n\n"
            + REAL_STALE_WARMUP_ROW
            + "\nStage A extended upward live and added lower points when the sweep\n"
            "stayed under.\n"
        ),
        # Identical text under a heading that names the state: must be accepted.
        safe_block=(
            "\n## Superseded procedure, kept for the session #1 record\n\n"
            + REAL_STALE_WARMUP_ROW
            + "\nStage A extended upward live and added lower points when the sweep\n"
            "stayed under.\n"
        ),
        must_name="post-hoc warmup re-filtering",
    )


def main() -> int:
    print("=" * 78)
    print("Week 2 documentation-governance controls (Hard Stop R-DOC)")
    print("Each control breaks a real tracked file, proves the check catches it,")
    print("and restores the original bytes. Restoration is hash-verified.")
    print("=" * 78)

    c_doc_1()
    c_doc_2()
    c_doc_3()
    c_doc_4()
    c_doc_5()
    c_doc_6()

    print("\n" + "=" * 78)
    failed = [(n, why) for n, ok, why in results if not ok]
    for name, ok, _ in results:
        print(f"  {'OK  ' if ok else 'FAIL'}  {name}")
    print("=" * 78)
    if failed:
        print(f"\n{len(failed)} control(s) did not bite:")
        for name, why in failed:
            print(f"  - {name}: {why}")
        return 1
    print(f"\nAll {len(results)} documentation controls went RED on a broken document "
          f"and GREEN on the real one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

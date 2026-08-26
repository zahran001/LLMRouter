"""Documentation-governance controls (Hard Stop R-DOC).

R4-R11 made the *code* enforce the redesign. They could not make the
*documents* stop describing the old experiment. Week 2 carries two design
generations, four executed implementation briefs, a superseded GPU runbook and
a superseded pre-flight -- every one correct when written, several of which
would still run if someone followed them.

So the failure this suite exists to catch is narrow and specific:

    A fresh agent or operator reads a Week 2 document that was correct when it
    was written, and executes it against GPU session #2.

`WEEK2_DOC_INDEX.md` is the single source of authority, and these tests
hold the repository to it. Each check is paired with the broken variant it has
to reject -- `scripts/show_doc_control_bites.py` runs those variants and prints
the reds, because a green that has never gone red proves nothing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import NamedTuple

import pytest

pytestmark = pytest.mark.redesign

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "WEEK2_DOC_INDEX.md"
RUNBOOK_PATH = "WEEK2_GPU_SESSION_2_PLAN.md"
POLICY_PATH = REPO_ROOT / "benchmarks" / "workloads" / "week2_headline" / "repeat_policy.json"

STATES = {"AUTHORITATIVE", "EXECUTABLE", "EVIDENCE", "HISTORICAL", "SUPERSEDED"}
DEAD_STATES = {"HISTORICAL", "SUPERSEDED"}
ACTIVE_STATES = {"AUTHORITATIVE", "EXECUTABLE"}


# ---------------------------------------------------------------------------
# Parsing the index. The index is the contract, so it is read, never assumed.
# ---------------------------------------------------------------------------

_ROW = re.compile(
    r"^\|\s*`([^`]+)`\s*\|\s*(\w+)\s*\|\s*(.+?)\s*\|\s*(\*\*yes\*\*|yes|no)\s*\|\s*(.+?)\s*\|\s*$"
)


def parse_index_rows(text: str) -> list[dict]:
    rows = []
    for line in text.split("\n"):
        m = _ROW.match(line)
        if not m:
            continue
        path, state, role, runbook, successor = m.groups()
        if state not in STATES:
            continue
        rows.append(
            {
                "path": path,
                "state": state,
                "role": role,
                "runbook": runbook.replace("*", "") == "yes",
                "successor": None if successor.strip() in {"—", "-"} else successor.strip("` "),
            }
        )
    return rows


@pytest.fixture(scope="module")
def index_text() -> str:
    assert INDEX_PATH.exists(), (
        "WEEK2_DOC_INDEX.md is missing -- it is the entry point the whole "
        "documentation-authority system hangs off (Hard Stop R-DOC)"
    )
    return INDEX_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rows(index_text) -> list[dict]:
    parsed = parse_index_rows(index_text)
    assert len(parsed) >= 15, (
        f"only {len(parsed)} classified documents parsed out of the index -- either the "
        "table format changed or documents went missing from it"
    )
    return parsed


def declared_state(path: Path) -> str | None:
    """The state a document declares in its own banner.

    JSON policy files carry a `status` field instead of a markdown banner;
    everything else declares `STATUS: <STATE>` near the top.
    """
    if path.suffix == ".json":
        status = json.loads(path.read_text(encoding="utf-8")).get("status", "")
        return "AUTHORITATIVE" if status == "LOCKED" else status or None
    head = "\n".join(path.read_text(encoding="utf-8").split("\n")[:40])
    m = re.search(r"STATUS:\s*([A-Z]+)", head)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# T-DOC-1 -- every Week 2 process document declares a state, and it agrees
# ---------------------------------------------------------------------------


def test_every_indexed_document_declares_its_state(rows):
    missing, disagreeing = [], []
    for row in rows:
        path = REPO_ROOT / row["path"]
        if not path.exists():
            continue  # T-DOC-6 owns existence
        got = declared_state(path)
        if got is None:
            missing.append(row["path"])
        elif got != row["state"]:
            disagreeing.append(f"{row['path']}: index says {row['state']}, banner says {got}")

    assert not missing, (
        "these documents carry no status banner, so a reader cannot tell whether "
        f"they are current: {missing}"
    )
    assert not disagreeing, (
        "a document and the index disagree about the document's own authority. That is "
        "exactly the ambiguity R-DOC exists to remove -- fix the banner or the index, "
        f"do not leave both: {disagreeing}"
    )


# ---------------------------------------------------------------------------
# T-DOC-2 -- dead documents are visibly non-executable
# ---------------------------------------------------------------------------


def test_historical_and_superseded_documents_say_do_not_execute(rows):
    """Uniform rule: every dead document says so, whether or not it looks like a
    runbook. 'Does this contain runbook-like commands?' is a judgment call, and
    a judgment call is the thing that fails at 2am on a metered session.

    As of 2026-08-20 the dead documents were **deleted** rather than kept
    banner-marked -- removal is the stronger guarantee, since a file that is not
    in the tree cannot be followed by mistake. So the index may legitimately
    carry no dead rows, and this check is written to bite from either side: any
    dead row must carry the banner, and any file *declaring* a dead state must
    be indexed. Neither an unmarked dead row nor an unindexed dead file passes.
    """
    offenders = []

    for row in [r for r in rows if r["state"] in DEAD_STATES]:
        path = REPO_ROOT / row["path"]
        if not path.exists():
            continue
        head = "\n".join(path.read_text(encoding="utf-8").split("\n")[:40])
        if "DO NOT EXECUTE" not in head:
            offenders.append(f"{row['path']} ({row['state']}): no 'DO NOT EXECUTE'")
        elif "WEEK2_DOC_INDEX.md" not in head and "WEEK2_GPU_SESSION_2_PLAN.md" not in head:
            offenders.append(f"{row['path']} ({row['state']}): does not point anywhere current")

    # The other direction: a file that calls itself dead must be in the index,
    # or the index is not the authority it claims to be.
    indexed = {r["path"] for r in rows}
    for path in sorted(REPO_ROOT.glob("*.md")) + sorted((REPO_ROOT / "docs").glob("*.md")):
        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        state = declared_state(path)
        if state in DEAD_STATES and rel not in indexed:
            offenders.append(f"{rel}: declares {state} but the index does not list it")

    assert not offenders, (
        "a dead document must both refuse execution and say where to go instead; "
        f"refusing without redirecting just strands the reader: {offenders}"
    )


# ---------------------------------------------------------------------------
# T-DOC-3 -- exactly one current GPU runbook
# ---------------------------------------------------------------------------


def test_exactly_one_current_gpu_runbook(rows):
    runbooks = [r["path"] for r in rows if r["runbook"]]
    assert runbooks == [RUNBOOK_PATH], (
        "exactly one document may be the active Week 2 GPU-session runbook. Two "
        "executable runbooks is not a documentation problem, it is an experiment "
        f"that runs two different experiments: got {runbooks}"
    )


def test_the_runbook_is_executable_and_self_contained(rows):
    row = next(r for r in rows if r["runbook"])
    assert row["state"] == "EXECUTABLE", f"the runbook is classified {row['state']}"

    text = (REPO_ROOT / row["path"]).read_text(encoding="utf-8")
    # The operator must not have to leave this file for any of these.
    required = {
        "membership id": "a49ecdd8",
        "max_model_len": "20000",
        "output token policy": "512",
        "concurrency cap": "3000",
        "percentile method": "nearest-rank",
        "prefix cache gate": "verify_prefix_cache_disabled",
        "teardown wrapper": "teardown_week2.sh",
        "artifact pull": "pull_artifacts.sh",
        "no-improvisation matrix": "NOT AUTHORIZED",
    }
    missing = [name for name, needle in required.items() if needle not in text]
    assert not missing, (
        "the session runbook is the one file kept open while the meter runs; these "
        f"facts would force the operator to go hunting mid-session: {missing}"
    )


# ---------------------------------------------------------------------------
# T-DOC-4 -- active documents do not assert superseded headline semantics
#
# The first version of this check carried two unsound exemptions, and real
# stale text walked through both of them at once:
#
#     | Per-point warmup N | ... Applying the real N is a re-filter over the
#       committed sidecars, never a GPU re-run ... `--warmup-n <N>` ... |
#
# It skipped the line because the line contained "never" -- but that "never"
# denies *a GPU re-run*, not the re-filter. The sentence recommends the
# superseded procedure. And it skipped the whole surrounding table anyway,
# because a different row said SUPERSEDED about a different value.
#
# Exemption is therefore structural and local. A stale claim counts as dead
# only where the document says so, at the claim:
#
#   1. HEADING -- the section's own heading declares it historical; or
#   2. UNIT    -- the logical unit carrying the claim (one table row, one list
#                 item, one paragraph, one fenced block) carries an explicit
#                 historical marker; or
#   3. DENIAL  -- that same unit denies *that concept*, from a narrow
#                 per-concept phrase list. There is no general "contains a
#                 negative word" rule any more: it read "never a GPU re-run"
#                 as a denial of re-filtering, which is the opposite of what
#                 the sentence says.
#
# A unit is the scope an exemption may cover. It may never reach past one.
# ---------------------------------------------------------------------------


class Concept(NamedTuple):
    """A superseded claim, and the phrases that count as denying *it*."""

    pattern: re.Pattern
    denials: tuple  # tuple[re.Pattern, ...]


def _concept(pattern: str, *denials: str) -> Concept:
    return Concept(re.compile(pattern), tuple(re.compile(d, re.I) for d in denials))


# Statistical semantics the redesign superseded (cleanup brief section 9), plus
# the session #1 execution procedure it replaced. Each concept owns the phrases
# that deny it -- deliberately narrow, and never shared between concepts.
STALE_CONCEPTS = {
    "n >= 100 sufficiency": _concept(
        r"n\s*(?:>=|≥)\s*100",
        r"(?:no longer|not|never)\s+(?:a\s+)?(?:sufficient|enough|valid)",
        r"insufficient",
    ),
    "fixed 120s headline window": _concept(
        r"Y\s*=\s*120|120s (?:window|measurement)",
        r"(?:no longer|not|never)\s+(?:the\s+)?(?:headline|current|valid|authoritative)",
    ),
    "post-hoc warmup re-filtering": _concept(
        r"re-?filter\w*\s+(?:over\s+)?(?:the\s+)?(?:committed\s+|headline\s+)?sidecars"
        # The same claim with none of the same words: "re-running
        # compute_point_metrics over the committed sidecars". This is the form
        # that survived in loadgen/_cli.py, above the constant the scout path
        # used.
        r"|re-?run\w*[^\n]{0,80}over\s+(?:the\s+)?committed\s+sidecars"
        r"|resolve\s+(?:the\s+)?warmup\s+(?:after|later)"
        r"|--warmup-n\b"
        # The four survivors of the first fix: the *rows* were corrected while
        # the section lead-ins above them still called the warmup an open value
        # to be read off the run. Same claim, none of the same words.
        r"|warmup N[^.]{0,80}resolved from[^.]{0,60}(?:transient|Block F)"
        r"|(?:one row|the warmup N?)[^.]{0,40}remains open"
        r"|deliberately post-GPU",
        r"(?:not|never|no longer)\s+(?:a\s+)?valid",
        r"\binvalid\b",
        r"must not be (?:applied|used)",
        r"refuses it",
        r"never re-?filtered after the fact",
    ),
    # Added 2026-08-21. The Tier A defect was a *shell* line, not a document:
    # `remote_loadgen.sh` read `provenance.master_seed` from a schedule format
    # that does not carry it. A scan that only reads Markdown could never have
    # seen it, and the comment above it asserted the replay contract that made
    # it look correct.
    "legacy master_seed on a replay path": _concept(
        r"master_seed",
        r"loadgen-schedule-v1|legacy|v1 provenance|generation",
        r"do(?:es)? not carry it",
        r"never asks",
    ),
    "prefix caching enabled": _concept(
        r"prefix cach(?:e|ing)\s+(?:is\s+)?enabled|enable_prefix_caching\s*=\s*True",
        r"\bdisabled\b",
        r"must not be enabled",
    ),
    "majority vote resolves repeats": _concept(
        r"majority\s+(?:vote|verdict|voting)",
        r"no majority\s+(?:vote|voting|verdict)",
        r"not\s+(?:a\s+)?majority",
        r"must not.{0,40}majority",
        r"never\s+majority",
        r"majority_vote\s+false",
    ),
    "N=5000 authorized": _concept(
        r"N\s*=\s*5,?000[^\n]{0,60}authoriz",
        r"not\s+authoriz",
        r"unauthoriz",
    ),
    "old 1.5/2/5 bracket": _concept(
        r"\b1\.5\s*/\s*2\s*/\s*5\b",
        r"not authoritative",
        r"must not be used",
    ),
    "402.3ms definitive floor": _concept(
        r"402\.3",
        r"no longer citable",
        r"not\s+(?:a\s+)?(?:the\s+)?definitive",
        r"at or above",
        r"CACHE_INFLUENCED_DIAGNOSTIC",
    ),
    # -- session #1 execution procedure (cleanup brief section C) -------------
    # These are not statistics, they are instructions, and they are the ones a
    # reader would actually *do*. An active document may narrate them only as
    # history; no denial phrase makes them current, so they have none.
    # A resolved calibration still described as open is the same failure as a
    # superseded procedure still described as current: the operator believes the
    # repository, and the repository is wrong. The Linux spin margin was
    # calibrated on 2026-08-18 and is platform-dispatched (0ms on Linux), but two
    # active documents went on telling the reader not to run on Linux unverified.
    "uncalibrated Linux spin margin": _concept(
        r"not yet Linux-calibrated|Windows-tuned[^.]{0,60}(?:unverified|not yet)",
        r"resolved",
        r"platform-dispatched",
    ),
    "session #1 Stage A/B sweep": _concept(r"\bStage [AB]\b"),
    # Both take an explicit prohibition as a denial. A document that names the
    # forbidden action IN ORDER TO forbid it is the correct way to write the
    # rule down; without this, stating the rule at all fails the scan, which
    # pushes the rule out of the documents instead of out of the behaviour.
    "on-meter lambda improvisation": _concept(
        r"extend\s+(?:the sweep\s+)?upward|add lower points",
        r"\bforbidden\b",
        r"NOT AUTHORIZED",
        r"(?:must not|may not|never)\s+\w+",
    ),
    "mid-session schedule generation": _concept(
        r"generate\s+(?:fine|Stage B)\s+schedules"
        r"|schedules?[^\n]{0,40}mid-session"
        r"|mid-session[^\n]{0,40}schedules?",
        r"\bforbidden\b",
        r"new benchmark SHA",
        r"(?:must not|may not|never)\s+\w+",
    ),
}

# Unit-scoped historical markers. Explicit words only -- each names the document
# state directly, so a reader sees the same thing the parser does.
LOCAL_HISTORICAL_MARKERS = (
    "HISTORICAL",
    "Historical",
    "historical",
    "SUPERSEDED",
    "Superseded",
    "superseded",
    "supersedes",
    "supersession",
    "falsified",
    "session #1",
    "Session #1",
    "first session",
    "First session",
    "DO NOT EXECUTE",
)

# A heading may exempt its whole section, because a heading is the one place a
# reader cannot miss the label.
HISTORICAL_HEADING = re.compile(
    r"HISTORICAL|Historical|historical|SUPERSEDED|Superseded|supersede[sd]"
    r"|supersession|falsified|session #1|Session #1|never be reachable"
)

_TABLE_ROW = re.compile(r"^\s*\|")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_FENCE = re.compile(r"^\s*(?:```|~~~)")


def iter_units(text: str, code: bool = False) -> list:
    """Split a document into (heading, unit) pairs.

    A *unit* is the smallest block a reader takes in as one claim: a table row,
    a list item, a paragraph, a fenced block. It is the largest scope a local
    exemption may cover -- one row may not vouch for the next.

    `code=True` for Python and shell sources, where `#` starts a COMMENT rather
    than a heading. Without it every comment line is read as a heading and its
    text is never scanned at all -- which would make the whole active-code scan
    inert while looking green, since a stale claim in a comment is exactly what
    it exists to find. (Found by its own control, which is why the control is
    built from the real pre-fix text.)
    """
    units: list = []
    heading = ""
    cur: list = []
    in_fence = False

    def close() -> None:
        nonlocal cur
        if cur:
            units.append((heading, cur))
            cur = []

    for i, line in enumerate(text.split("\n"), 1):
        if _FENCE.match(line):
            if in_fence:
                cur.append((i, line))
                close()
            else:
                close()
                cur.append((i, line))
            in_fence = not in_fence
            continue
        if in_fence:
            cur.append((i, line))
            continue
        if line.startswith("#") and not code:
            close()
            heading = line
            continue
        if not line.strip():
            close()
            continue
        if _TABLE_ROW.match(line):
            close()
            cur.append((i, line))
            close()
            continue
        if _LIST_ITEM.match(line):
            close()
        cur.append((i, line))
    close()
    return units


def scan_text(label: str, text: str, code: bool = False) -> list:
    """Every stale claim in one document that nothing local marks as dead."""
    violations = []
    for heading, unit in iter_units(text, code=code):
        if HISTORICAL_HEADING.search(heading):
            continue  # rule 1: the heading owns its whole section
        unit_text = "\n".join(line for _, line in unit)
        # Match against the unit with its line wrapping flattened: a claim that
        # happens to break across two lines -- "resolved from Stage\nA's
        # transient" -- is the same claim to a reader, and was invisible to a
        # per-line matcher.
        flat = re.sub(r"\s+", " ", unit_text)
        if any(m in flat for m in LOCAL_HISTORICAL_MARKERS):
            continue  # rule 2: this unit, and only this unit, is marked
        for name, concept in STALE_CONCEPTS.items():
            hit = concept.pattern.search(flat)
            if not hit:
                continue
            if any(d.search(flat) for d in concept.denials):
                continue  # rule 3: this unit denies this concept
            lineno = next(
                (n for n, line in unit if concept.pattern.search(line)), unit[0][0]
            )
            violations.append(
                f"{label}:{lineno} [{name}] under heading "
                f"{heading.strip() or '(top)'!r}: {hit.group(0).strip()[:60]!r} in "
                f"{unit_text.strip()[:110]}"
            )
    return violations


def test_active_documents_do_not_assert_stale_headline_semantics(rows):
    active = [r for r in rows if r["state"] in ACTIVE_STATES]
    assert active, "no active documents classified"

    violations = []
    for row in active:
        path = REPO_ROOT / row["path"]
        if not path.exists() or path.suffix == ".json":
            continue
        violations += scan_text(row["path"], path.read_text(encoding="utf-8"))

    assert not violations, (
        "an active document asserts semantics the redesign superseded, with nothing "
        "at the claim to say it is dead. A reader has no way to tell:\n  "
        + "\n  ".join(violations)
    )


# ---------------------------------------------------------------------------
# The scope rules are the part that failed before, so they carry their own
# controls: each proves the checker reaches a real defect, and stops where it
# should. `scripts/show_doc_control_bites.py` runs the file-mutating versions.
# ---------------------------------------------------------------------------

# The exact shape of the sentence that stayed green through a whole cleanup.
REAL_STALE_WARMUP_ROW = (
    "| Per-point warmup N | **10s placeholder** | Applying the real N is a "
    "**re-filter over the committed sidecars, never a GPU re-run**: the warmup "
    "filter is metrics-side, so `--warmup-n <N>` re-derives every point |\n"
)


def test_the_real_stale_warmup_sentence_is_a_violation():
    """C-DOC-3's real form: 'never a GPU re-run' does not deny re-filtering."""
    doc = "## Open [CALIBRATE] values\n\n" + REAL_STALE_WARMUP_ROW
    found = scan_text("synthetic.md", doc)
    assert any("post-hoc warmup re-filtering" in v for v in found), (
        f"the sentence this suite exists to catch is not caught: {found}"
    )


def test_the_corrected_warmup_sentence_is_accepted():
    doc = (
        "## Open [CALIBRATE] values\n\n"
        "| Per-point warmup N | **frozen at 60s** | Post-hoc warmup re-filtering of "
        "headline sidecars is not valid for the redesigned exact-N headline. If the "
        "60s boundary is insufficient, schedules are regenerated offline before "
        "Tier B |\n"
    )
    assert scan_text("synthetic.md", doc) == [], (
        "the corrected wording must pass, or the rule is unusable and gets worked "
        "around rather than followed"
    )


def test_a_superseded_row_does_not_exempt_its_neighbour():
    """The scope bug, stated as a test: one row may not vouch for another."""
    doc = (
        "## Open [CALIBRATE] values\n\n"
        + REAL_STALE_WARMUP_ROW
        + "| Measurement window Y | **120s** | SUPERSEDED 2026-08-19 by exact-N |\n"
    )
    found = scan_text("synthetic.md", doc)
    assert any("post-hoc warmup re-filtering" in v for v in found), (
        "a SUPERSEDED marker on one table row suppressed a stale claim on another. "
        "That exemption is what let the warmup re-filter survive the cleanup"
    )
    assert not any("120s" in v for v in found), "the marked row must stay exempt"


def test_an_explicitly_historical_heading_still_preserves_provenance():
    """Provenance stays writable, or the rule buys safety by deleting history."""
    doc = (
        "### Superseded procedure, kept for the session #1 record\n\n"
        + REAL_STALE_WARMUP_ROW
        + "\nStage A extended upward live and added lower points when the sweep "
        "stayed under.\n"
    )
    assert scan_text("synthetic.md", doc) == [], (
        "history under an explicitly historical heading must still be writable"
    )

# ---------------------------------------------------------------------------
# T-DOC-5 -- the machine-readable policy matches the human locks
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_repeat_policy_is_no_longer_proposed(policy):
    assert policy["status"] == "LOCKED", (
        f"repeat_policy.json is {policy['status']!r}. A PROPOSED policy cannot govern a "
        "metered session -- it means nobody has signed off on how the evidence is read"
    )


def test_repeat_policy_encodes_the_six_locks(policy):
    p = policy["policy"]
    # 1A -- three repeats, unanimity, no majority vote
    assert p["min_valid_repeats"] == 3
    assert p["require_unanimous"] is True
    assert p["majority_vote"] is False, "majority voting turns an honest UNCERTAIN into a verdict"
    assert p["split_verdict"] == "UNCERTAIN"
    # 2B -- N=4000, N=5000 unauthorized, interval fallback
    assert p["n_per_run"] == 4000
    assert p["n_max"] == 5000
    assert policy["escalation"]["n5000"]["authorized"] is False, "lock 2B: N=5000 is NOT authorized"
    assert policy["escalation"]["authorized"] is False
    assert p["unresolved_boundary"] == "interval"
    # 3A -- process epochs
    assert p["cross_process_epoch_combination"] is False
    # 4A -- frozen warmup boundary, no post-hoc re-filter
    assert p["warmup_boundary_s"] == 60
    assert p["post_hoc_warmup_refilter"] is False
    # 5A -- bounded scout fallback
    fallback = policy["scout"]["preauthorized_fallback"]
    assert fallback["if_lambda_1_is_already_over"] == [0.5]
    assert fallback["if_lambda_8_is_still_under"] == [16]
    assert policy["scout"]["lambdas"] == [1, 2, 4, 8]
    # 6A -- secondary scope survives
    required = policy["secondary_scope"]["required_before_week2_closeout"]
    for scenario in ("natural-random secondary", "steady-arrival reference", "adversarial scenario"):
        assert scenario in required, f"{scenario} dropped from Week 2 scope"
    assert policy["secondary_scope"]["headline_defining"] == "controlled Poisson headline"


def test_all_six_locks_are_recorded_by_name(policy):
    locks = policy["human_locks"]
    assert set(locks) == {f"D-CLEAN-{i}" for i in range(1, 7)}
    for name, (letter) in zip(sorted(locks), ["1A", "2B", "3A", "4A", "5A", "6A"]):
        assert locks[name].startswith(letter), f"{name} does not record option {letter}"


def test_plan_and_index_carry_the_locks_too(index_text):
    """The locks must be readable by a human, not only by a parser."""
    plan = (REPO_ROOT / "WEEK2_PLAN.md").read_text(encoding="utf-8")
    assert "## 11. Session #2 evidence locks" in plan
    for letter in ("1A", "2B", "3A", "4A", "5A", "6A"):
        assert letter in plan, f"lock {letter} missing from WEEK2_PLAN.md"
        assert letter in index_text, f"lock {letter} missing from the doc index"


# ---------------------------------------------------------------------------
# T-DOC-6 -- the current execution chain actually resolves
# ---------------------------------------------------------------------------


def test_every_indexed_path_exists(rows):
    missing = [r["path"] for r in rows if not (REPO_ROOT / r["path"]).exists()]
    assert not missing, (
        f"the index points at documents that do not exist: {missing}. An index with a "
        "dead link is worse than no index -- it looks authoritative"
    )


def test_every_successor_exists(rows):
    missing = []
    for row in rows:
        succ = row["successor"]
        if not succ:
            continue
        target = succ.split()[0].strip("`")  # successors may read "WEEK2_PLAN.md §10"
        if target.endswith(".md") and not (REPO_ROOT / target).exists():
            missing.append(f"{row['path']} -> {target}")
    assert not missing, f"superseded documents redirect to files that do not exist: {missing}"


def test_the_execution_chain_is_reachable_from_the_root_readme():
    """README -> STATUS -> index -> {plan, execution, runbook, policy}."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "STATUS.md" in readme
    assert "WEEK2_DOC_INDEX.md" in readme, (
        "a cold reader starting at README.md must be able to find the authority index "
        "without knowing it exists"
    )

    status = (REPO_ROOT / "STATUS.md").read_text(encoding="utf-8")
    assert "WEEK2_DOC_INDEX.md" in status
    assert RUNBOOK_PATH in status

    index = INDEX_PATH.read_text(encoding="utf-8")
    for link in ("WEEK2_PLAN.md", "WEEK2_EXECUTION.md", RUNBOOK_PATH, "repeat_policy.json"):
        assert link in index, f"the index does not name {link} as part of the execution chain"


# The index can only govern documents it knows about. T-DOC-1 checks that every
# indexed document declares a state; this checks the other direction, because a
# Week 2 brief dropped in the repository root and never indexed is exactly the
# document a fresh agent would find and follow. New markdown at these levels
# fails closed: index it, or name it here as not-Week-2.
NON_WEEK2_ROOT_DOCS = {
    "README.md",  # the entry point itself; the index's section 1 owns the chain
    "BENCHMARKS.md",
    "LOADGEN_PATTERN_VALIDATION.md",
    "METRICS_TEST_SUITE.md",
    "MOCK_TRUST_BOUNDARY.md",
    "WEEK1_MEASUREMENT_SPEC.md",
    # Week 3 process documents. WEEK2_DOC_INDEX.md is a Week 2 index by
    # name and scope; Week 3's own authority chain is STATUS.md's
    # "Week 3 -- closed" section -> WEEK3_EVIDENCE_PACKAGE.md, not this index.
    "WEEK3_KV_REQUEST_COST_INVESTIGATION_README.md",
    "WEEK3_KV_REQUEST_COST_INVESTIGATION_REPORT.md",
    "WEEK3_IMPLEMENTATION_README.md",
    "WEEK3_COST_CONTRACT.md",
    "WEEK3_EVIDENCE_PACKAGE.md",
}
NON_WEEK2_DOCS_DIR = {"README.md", "architecture.md"}


def test_every_week2_process_document_is_in_the_index(rows):
    indexed = {r["path"] for r in rows}
    unindexed = []
    for path in sorted(REPO_ROOT.glob("*.md")):
        if path.name not in NON_WEEK2_ROOT_DOCS and path.name not in indexed:
            unindexed.append(path.name)
    for path in sorted((REPO_ROOT / "docs").glob("*.md")):
        rel = f"docs/{path.name}"
        if path.name not in NON_WEEK2_DOCS_DIR and rel not in indexed:
            unindexed.append(rel)

    assert not unindexed, (
        "these documents sit where a reader will find them but carry no entry in "
        "WEEK2_DOC_INDEX.md, so nothing says whether they are current. Add a "
        f"row, or add them to the not-Week-2 allowlist in this test: {unindexed}"
    )


# ---------------------------------------------------------------------------
# T-DOC-7 -- the scan covers ACTIVE CODE, not only Markdown
# ---------------------------------------------------------------------------
#
# Added 2026-08-21, because the defect that triggered this pass lived in a
# shell script. `remote_loadgen.sh` read `provenance.master_seed` from a
# schedule format that has never carried it, and `loadgen/_cli.py` documented
# the post-hoc warmup re-filter -- lock 4A's forbidden resolution -- in a
# comment sitting directly above the constant the scout path used. Both were
# invisible to a scanner that only globs `*.md`.
#
# Scope is deliberately narrow: the modules and scripts a session #2 stage
# actually executes. The legacy session #1 generators are excluded by name and
# with a reason, not by a wildcard -- they are correct under their own frozen
# semantics, and rewriting them to satisfy this scan would be falsifying
# history to make a test green.

ACTIVE_CODE = (
    "loadgen/_cli.py",
    "loadgen/redesign_point.py",
    "loadgen/headline_schedule.py",
    "loadgen/prefix_cache.py",
    "loadgen/repeat_runner.py",
    "metrics/headline_point.py",
    "metrics/floor_point.py",
    "metrics/classification.py",
    "scripts/gpu_session/remote_loadgen.sh",
    "scripts/gpu_session/run_on_instance.sh",
    "scripts/gpu_session/drive_scenario_point.py",
    "scripts/gpu_session/drive_headline_family.py",
    "scripts/gpu_session/drive_unloaded_floor.py",
    "scripts/gpu_session/scenario_contract.py",
    "scripts/gpu_session/check_scenario.py",
    "scripts/gpu_session/verify_prefix_cache_disabled.py",
    "scripts/generate_secondary_scenarios.py",
)

# Excluded, each for a stated reason. A wildcard here would let a genuinely
# stale active file hide behind a pattern.
CODE_EXCLUDED = {
    "metrics/point.py": "frozen session #1 reader; its semantics ARE the stale ones, and "
                        "session #1's promoted artifacts are read under them",
    "scripts/generate_schedules.py": "session #1 Stage A/B generator, kept to replay history",
    "scripts/generate_stage_a_schedules.py": "same",
    "scripts/compute_point_metrics.py": "offline recompute for session #1 records",
    "loadgen/steady.py": "v1 entry point; the session #2 steady reference is frozen "
                         "and driven through drive_scenario_point.py",
    "loadgen/adversarial.py": "v1 entry point; the session #2 adversarial scenario is frozen",
    "loadgen/poisson.py": "v1 entry point, used for the frozen v1 secondary replays",
}


def test_active_code_does_not_assert_stale_headline_semantics():
    violations = []
    for rel in ACTIVE_CODE:
        path = REPO_ROOT / rel
        assert path.exists(), f"{rel} is in the active-code scan list but does not exist"
        violations += scan_text(rel, path.read_text(encoding="utf-8"), code=True)

    assert not violations, (
        "active code asserts semantics the redesign superseded. A stale comment above a "
        "live constant is how the Tier A defect survived review:\n  "
        + "\n  ".join(violations)
    )


def test_the_active_code_scan_list_covers_every_session_2_driver():
    """A driver that is not scanned is a driver whose comments nobody checks."""
    gpu_session = REPO_ROOT / "scripts" / "gpu_session"
    drivers = {f"scripts/gpu_session/{p.name}" for p in gpu_session.glob("*.py")}
    drivers |= {f"scripts/gpu_session/{p.name}" for p in gpu_session.glob("*.sh")}
    unscanned = drivers - set(ACTIVE_CODE) - set(CODE_EXCLUDED)
    # Instance lifecycle scripts decide no measurement semantics.
    lifecycle = {"scripts/gpu_session/create_instance.sh",
                 "scripts/gpu_session/teardown_week2.sh",
                 "scripts/gpu_session/pull_artifacts.sh",
                 "scripts/gpu_session/setup_and_launch_vllm.sh",
                 "scripts/gpu_session/tunnel.sh"}
    unscanned -= lifecycle
    assert not unscanned, (
        f"these session #2 scripts are neither scanned nor explicitly excluded: {unscanned}")


def test_control_the_code_scan_catches_the_defect_it_was_built_from():
    """Non-vacuity, against the two real pre-fix texts.

    Both are quoted from what was actually in the tree on 2026-08-21, not
    invented to match the pattern -- the mistake C-DOC-3 was rebuilt to avoid.
    """
    shell_defect = (
        '  # Offered RPS / duration / seed come from the schedule\'s OWN provenance,\n'
        '  # never from the filename or a hand-typed flag.\n'
        '  seed="$(py -c \'import json,sys; '
        'print(json.load(open(sys.argv[1]))["provenance"]["master_seed"])\' "$schedule")"\n'
    )
    assert scan_text("remote_loadgen.sh", shell_defect, code=True), (
        "the code scan does not catch the master_seed extraction that broke Tier A")

    comment_defect = (
        "# [CALIBRATE], same placeholder the committed Stage A schedules were\n"
        "# sized against. The real N comes off the Block F transient plot; because\n"
        "# the filter is metrics-side and time-based, resolving N later means\n"
        "# re-running compute_point_metrics.py over the committed sidecars, NOT\n"
        "# re-running anything on the GPU.\n"
        "DEFAULT_WARMUP_N_S = 10.0\n"
    )
    assert scan_text("_cli.py", comment_defect, code=True), (
        "the code scan does not catch the post-hoc re-filter comment that sat above the "
        "constant the scout path used")

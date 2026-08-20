"""Week 2 teardown target resolution (WEEK2_PLAN.md §6.1/§6.4).

The failure this guards is a money leak, not a wrong number: `teardown.sh` is
a generic primitive whose default is Week 1's `llmrouter-vllm-l4`, while Week 2
creates `llmrouter-vllm-l4-week2`. Run bare against a Week 2 session it
describes an instance that does not exist, prints "nothing to tear down" and
exits **0** -- exactly §6.1's "a silent no-op teardown is how a forgotten L4
runs all weekend."

These are static/textual checks, deliberately: they must run in CI with no
cloud credentials and must never touch a real instance. What they pin is that
the wrapper owns the right target and that no Week 2 runbook path routes
around it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GPU_SESSION = REPO_ROOT / "scripts" / "gpu_session"

WEEK2_INSTANCE = "llmrouter-vllm-l4-week2"
WEEK1_INSTANCE = "llmrouter-vllm-l4"

WRAPPER = GPU_SESSION / "teardown_week2.sh"
GENERIC = REPO_ROOT / "scripts" / "teardown.sh"
CREATE = GPU_SESSION / "create_instance.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _default_of(script: Path, var: str) -> str | None:
    """Innermost fallback of `VAR="${VAR:-...}"`.

    Tolerates an intermediate session-file layer --
    `VAR="${VAR:-${SESSION_VAR:-default}}"` -- because the wrapper now prefers
    the instance/zone `create_instance.sh` actually created over its own
    built-in default. The built-in default is still what this returns: it is
    the value that applies when no session record exists.
    """
    m = re.search(rf'^{var}="(\$\{{{var}:-.*)"$', _read(script), re.MULTILINE)
    if not m:
        return None
    return m.group(1).rsplit(":-", 1)[1].rstrip("}")


def test_wrapper_exists():
    assert WRAPPER.exists(), "the Week 2 teardown wrapper is missing"


def test_wrapper_defaults_to_the_week2_instance_and_zone():
    assert _default_of(WRAPPER, "INSTANCE_NAME") == WEEK2_INSTANCE
    assert _default_of(WRAPPER, "ZONE") == _default_of(CREATE, "ZONE"), (
        "the wrapper's default zone must match the zone create_instance.sh actually creates in"
    )


def test_wrapper_targets_exactly_what_create_instance_creates():
    """The two must not be able to drift apart -- that drift IS the bug."""
    assert _default_of(CREATE, "INSTANCE_NAME") == _default_of(WRAPPER, "INSTANCE_NAME")


def test_generic_primitive_is_left_generic():
    """The wrapper is the fix, not editing the shared primitive: Week 1's
    reproduction path still depends on the old default."""
    assert _default_of(GENERIC, "INSTANCE_NAME") == WEEK1_INSTANCE


def _invocation_index(body: str) -> int:
    """Offset of the line that actually calls the generic primitive -- not the
    header comment that merely explains why this wrapper exists."""
    for i, line in enumerate(body.splitlines()):
        if "teardown.sh" in line and not line.lstrip().startswith("#"):
            return sum(len(l) + 1 for l in body.splitlines()[:i])
    raise AssertionError("wrapper never invokes scripts/teardown.sh")


def test_wrapper_prints_the_resolved_target_before_deleting():
    body = _read(WRAPPER)
    header = body[: _invocation_index(body)]
    assert 'echo "  instance: $INSTANCE_NAME"' in header, (
        "the resolved instance must be printed BEFORE the deletion, so an operator can see "
        "what is about to be destroyed"
    )
    assert 'echo "  zone:     $ZONE"' in header, "the resolved zone must be printed too"


def test_wrapper_verifies_deletion_after_the_delete():
    """§6.4: 'verify the instance is actually deleted -- do not trust the
    script's exit code alone.'"""
    body = _read(WRAPPER)
    after = body[_invocation_index(body):]
    # The wrapper factors the existence probe into an `exists()` helper, so
    # look for the call, not the raw gcloud string.
    assert "exists" in after, "no post-delete existence check"
    assert "exit 1" in after, "a still-present instance must fail loudly, not pass quietly"
    assert "instances describe" in body, "the existence probe must actually ask the API"


def test_wrapper_supports_a_dry_run():
    assert "DRY_RUN" in _read(WRAPPER)


@pytest.mark.parametrize(
    "path",
    [
        GPU_SESSION / "pull_artifacts.sh",
        GPU_SESSION / "run_on_instance.sh",
        REPO_ROOT / "scripts" / "README.md",
        # docs/WEEK2_GPU_PREFLIGHT.md was here until 2026-08-20, when session
        # #1's pre-flight was deleted. Its successor is covered below.
        REPO_ROOT / "WEEK2_GPU_SESSION_2_PREFLIGHT.md",
        REPO_ROOT / "WEEK2_GPU_SESSION_2_PLAN.md",
    ],
)
def test_no_week2_runbook_path_recommends_the_bare_generic_teardown(path):
    """Every Week 2 instruction to tear down must name the wrapper. A bare
    `bash scripts/teardown.sh` is the money-leak path."""
    offenders = []
    for i, line in enumerate(_read(path).splitlines(), start=1):
        if "teardown.sh" not in line or "teardown_week2.sh" in line:
            continue
        # A line is safe if it passes INSTANCE_NAME explicitly, or is prose
        # explaining precisely why the bare form must not be used.
        if "INSTANCE_NAME=" in line:
            continue
        if re.search(r"never|not a Week 2|generic|would target|bare", line, re.IGNORECASE):
            continue
        offenders.append(f"{path.name}:{i}: {line.strip()}")
    assert not offenders, "Week 2 path recommends bare teardown.sh:\n" + "\n".join(offenders)


# --- the zone axis: target what was created, not what was assumed ------------
#
# Owning the instance NAME is not enough. A single-zone capacity stockout is
# routine -- us-central1-a had no g2-standard-8+L4 to give on 2026-08-18 -- and
# a session that moves to -b or -c leaves the wrapper's default zone pointing at
# nothing: "no instance named ... nothing would be deleted", exit 0, meter still
# running. Same money leak as SS6.1, one field over.

SESSION_FILE_NAME = ".gpu_session_target"
NL_REAL = chr(10)


def test_create_records_the_session_target():
    body = _read(CREATE)
    assert SESSION_FILE_NAME in body, "create_instance.sh must record what it created"
    assert "SESSION_INSTANCE_NAME=$INSTANCE_NAME" in body
    assert "SESSION_ZONE=$ZONE" in body, (
        "the zone actually created in must be recorded -- that is the whole point"
    )


def test_wrapper_prefers_the_recorded_target_over_its_default():
    body = _read(WRAPPER)
    assert SESSION_FILE_NAME in body, "the wrapper must read the session record"
    for var, session_var in (
        ("INSTANCE_NAME", "SESSION_INSTANCE_NAME"),
        ("ZONE", "SESSION_ZONE"),
    ):
        m = re.search(rf'^{var}="(.*)"$', body, re.MULTILINE)
        assert m, f"{var} is not resolved in the wrapper"
        expr = m.group(1)
        assert expr.index("${" + var + ":-") < expr.index(session_var), (
            f"an explicit {var}= must win over the session record, not the reverse"
        )


def test_session_record_is_gitignored():
    """`run_on_instance.sh bootstrap` refuses a dirty tree. If creating an
    instance dirtied the tree, the next runbook step would fail.

    Matched as a whole line, not a substring: `.gpu_session_target_TYPO`
    contains the name but ignores nothing, and a substring check calls that
    green. (Found by mutating this very test -- it was blind as first written.)
    """
    entries = {
        line.strip()
        for line in _read(REPO_ROOT / ".gitignore").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert SESSION_FILE_NAME in entries, (
        f"{SESSION_FILE_NAME} is not an active .gitignore rule; entries={sorted(entries)}"
    )


def test_wrapper_clears_the_record_after_verified_deletion():
    body = _read(WRAPPER)
    after = body[_invocation_index(body):]
    assert "rm -f" in after and "SESSION_FILE" in after, (
        "a stale record would point the next teardown at an instance already gone"
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash to run the wrapper")
def test_recorded_zone_actually_wins_at_runtime(tmp_path):
    """Behavioural rather than textual -- and still cloud-free: `gcloud` is
    stubbed to a failing no-op, and DRY_RUN returns before anything is deleted.

    The textual checks above would pass on plumbing that resolves in the wrong
    order; this one only passes if the resolution really happens.
    """
    stub = tmp_path / "bin"
    stub.mkdir()
    gcloud = stub / "gcloud"
    gcloud.write_text("#!/bin/sh@exit 1@".replace("@", NL_REAL), encoding="utf-8")
    gcloud.chmod(0o755)

    session = tmp_path / SESSION_FILE_NAME
    session.write_text(
        "SESSION_INSTANCE_NAME=llmrouter-vllm-l4-week2@SESSION_ZONE=us-central1-c@".replace(
            "@", NL_REAL
        ),
        encoding="utf-8",
    )

    env = {
        **os.environ,
        "PATH": f"{stub}{os.pathsep}{os.environ['PATH']}",
        "DRY_RUN": "1",
        "SESSION_FILE": str(session),
    }
    env.pop("ZONE", None)
    env.pop("INSTANCE_NAME", None)

    out = subprocess.run(
        ["bash", str(WRAPPER)], capture_output=True, text=True, env=env, timeout=120
    ).stdout
    assert "us-central1-c" in out, f"the recorded zone was ignored; wrapper said:@{out}".replace(
        "@", NL_REAL
    )

    # ...and an explicit override still beats the record.
    out2 = subprocess.run(
        ["bash", str(WRAPPER)],
        capture_output=True,
        text=True,
        timeout=120,
        env={**env, "ZONE": "us-central1-b"},
    ).stdout
    assert "us-central1-b" in out2, f"explicit ZONE= lost to the record:@{out2}".replace(
        "@", NL_REAL
    )

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

import re
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
    m = re.search(rf'^{var}="\$\{{{var}:-([^}}]*)\}}"', _read(script), re.MULTILINE)
    return m.group(1) if m else None


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
        REPO_ROOT / "docs" / "WEEK2_GPU_PREFLIGHT.md",
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

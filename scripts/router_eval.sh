#!/usr/bin/env bash
#
# router_eval.sh — the Week 1 router gate (WEEK1_ROUTER_IMPL.md §4-§6).
#
# Runs the router's unit tests, then the eval, then the negative controls,
# and treats a *missing* negative control as harshly as a passing one: an
# eval whose teeth quietly fall out is exactly the failure mode the controls
# exist to prevent (§5, "a negative control that silently starts passing is
# itself a failure").
#
# Usage:
#   scripts/router_eval.sh            # one pass (what CI runs)
#   scripts/router_eval.sh 5          # the 5x determinism check (§5)
#
# Requires: cargo, and a Python env with requirements.txt installed. Set
# PYTHON=... to point at a specific interpreter.

set -euo pipefail

REPEAT="${1:-1}"
PYTHON="${PYTHON:-python}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# The five controls in tests/router/test_negative_controls.py: S1, S2 and O1
# against WRONG_ROUTER_BUFFERS, F1 against WRONG_ROUTER_REEMIT, and F2's
# *pass* against the same re-emit router (the divergence between F1 and F2 is
# what proves F1 tests bytes rather than meaning). Bump this deliberately if
# a control is added; never lower it to make a run go green.
EXPECTED_NEGATIVE_CONTROLS=5

echo "=== router unit tests (default build) ==="
cargo test --manifest-path router/Cargo.toml

echo "=== router unit tests (--features wrong-routers) ==="
cargo test --manifest-path router/Cargo.toml --features wrong-routers

for i in $(seq 1 "$REPEAT"); do
    echo
    echo "########## router eval pass $i/$REPEAT ##########"

    echo "=== negative-control inventory ==="
    collected=$("$PYTHON" -m pytest tests/router/test_negative_controls.py --collect-only -q \
        | tail -1 | awk '{print $1}')
    if [ "$collected" != "$EXPECTED_NEGATIVE_CONTROLS" ]; then
        echo "FAIL: expected $EXPECTED_NEGATIVE_CONTROLS negative controls, collected $collected." >&2
        echo "      A control was removed, renamed or skipped — the eval has lost teeth." >&2
        exit 1
    fi
    echo "ok: $collected negative controls present"

    # Must-fail wiring: each of these drives a deliberately-wrong router
    # through the real eval's assertion helper and asserts it raises. They
    # PASS here precisely when the wrong routers FAIL the gate.
    echo "=== negative controls (must catch the wrong routers) ==="
    "$PYTHON" -m pytest tests/router -m "router and negative_control" -q -s

    echo "=== router eval (fidelity, streaming, overhead, headers/errors) ==="
    "$PYTHON" -m pytest tests/router -m "router and not negative_control" -q -s
done

echo
echo "router eval green ($REPEAT pass(es))"

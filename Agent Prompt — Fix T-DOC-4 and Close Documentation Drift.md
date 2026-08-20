# Agent Prompt — Fix T-DOC-4 and Close Documentation Drift

> **STATUS: HISTORICAL — DO NOT EXECUTE**
>
> Role: the brief for the T-DOC-4 scope fix and the documentation drift it
> exposed. Already executed; the evidence is
> `docs/WEEK2_GPU_SESSION_2_PREFLIGHT.md`.
>
> This document records an earlier Week 2 state. It is preserved for
> provenance, and nothing in it may drive GPU session #2.
> Current entry point: `docs/WEEK2_DOC_INDEX.md`.

You are at **Week 2 documentation cleanup, before Hard Stop R-DOC**.

Do **not** proceed to GPU work.

A defect has been found in `T-DOC-4`: the documentation-governance test can report green while real stale Week 2 instructions remain in active authoritative documents.

Your task is to **fix both the underlying stale documentation and the test/control design that failed to detect it**, then halt for human review.

# Context

The current redesigned headline experiment is locked around:

- exact-N schedules,
- `N = 4000`,
- fixed canonical prompt membership,
- nearest-rank p99,
- prefix caching disabled,
- censoring-aware validity,
- independent repeats,
- frozen **60s warmup boundary**,
- no post-hoc warmup re-filtering,
- diagnostic scouting before full Tier-B evidence.

Human decisions already locked:

```text
1A — 3 repeats; unanimous agreement required; 2–1 = UNCERTAIN
2B — N=5000 is NOT authorized for session #2; unresolved → interval
3A — repeats from different vLLM process epochs cannot be combined
4A — 60s warmup boundary; if insufficient, STOP + regenerate schedules
5A — scout 1/2/4/8; fallback 0.5 if 1 OVER, 16 if 8 UNDER
6A — controlled headline + natural-random + steady + adversarial remain Week 2 scope
```

Do not reopen these decisions.

# Defect found

`tests/redesign/test_week2_doc_state.py::T-DOC-4` currently uses broad keyword exemptions that can hide genuine stale instructions.

Three concrete failures were identified.

## 1. Negation exemption is semantically unsafe

Current logic effectively asks:

```text
Does this line contain a word like:
never / not / cannot / must not / do not / ...
```

and assumes that means the stale claim is being denied.

This is false.

Real stale text currently contains wording equivalent to:

```text
Applying the real N is a re-filter over the committed sidecars,
never a GPU re-run.
```

The word `never` does **not** negate re-filtering.

It positively recommends re-filtering while contrasting it against a GPU rerun.

This real line must be treated as a violation.

## 2. Section-level supersession exemption is too broad

Current logic exempts an entire markdown section when any supersession/historical marker appears anywhere inside that section.

This allows:

```text
row A → stale active instruction
row B → correctly says SUPERSEDED
```

to result in the whole section being ignored.

That is invalid.

Historical/superseded scope must be local and explicit.

## 3. Stale-pattern coverage misses old execution procedures

The checker focuses largely on statistical assumptions such as:

- fixed `120s`,
- `n >= 100`,
- percentile semantics,
- post-hoc warmup,
- N escalation.

It does not adequately detect obsolete session-#1 execution procedures such as:

```text
Stage A
Stage B
extend upward live
add lower points
generate fine schedules mid-session
mid-session schedule generation
```

These may remain as historical provenance, but they must not remain executable-looking current instructions in an `AUTHORITATIVE` or `EXECUTABLE` document.

# Required work

## A. Fix the actual stale documentation first

Inspect the active Week 2 authority chain, especially:

```text
WEEK2_PLAN.md
WEEK2_EXECUTION.md
STATUS.md
docs/WEEK2_GPU_SESSION_2_PLAN.md
docs/WEEK2_DOC_INDEX.md
```

and any other document classified `AUTHORITATIVE` or `EXECUTABLE`.

Do not merely make the test tolerate the current prose.

Correct the prose so current instructions accurately encode session #2.

In particular:

### Warmup

Current active meaning must be:

```text
The 60s warmup boundary is frozen into the exact-N schedule.

Tier A validates whether the transient has stabilized by 60s.

If it has NOT:
    STOP
    preserve/pull diagnostic evidence
    regenerate schedules with a larger frozen boundary
    rerun required GPU-free verification
    return to pre-GPU approval

Do NOT apply a later warmup by re-filtering the headline sidecars.
```

Any old statement saying the resolved warmup can simply be applied using:

```text
--warmup-n
re-filter sidecars
re-derive every point
```

must either:

1. be removed from the active procedure, or
2. remain only inside explicitly historical/superseded context.

### Old Stage A / Stage B procedure

Do not leave session-#1 procedures executable in current authority.

Historical text may describe that the old experiment:

```text
extended upward live
added lower points
generated Stage B mid-session
```

but current session #2 execution is:

```text
Tier A diagnostic scout:
    λ = 1 / 2 / 4 / 8
    fallback 0.5 / 16 only

Hard Stop GPU-1:
    confirm bracket
    confirm 60s warmup sufficiency

Tier B:
    selected 3 λ
    3 repeats
    N=4000
```

No arbitrary λ improvisation is authorized.

## B. Fix T-DOC-4 exemption scope

Do not attempt full natural-language understanding.

Prefer explicit structural rules.

### Section-level historical exemption

A whole section may be exempted only if the **section heading itself** clearly marks it historical/superseded, for example:

```text
## Historical
## Historical note
## Superseded
## Superseded behavior
```

A marker buried somewhere in the body must not exempt neighboring lines or table rows.

### Row/line-level historical exemption

A specific line/table row may be exempt only if that same logical line/row explicitly marks the claim as historical/superseded/falsified.

Examples that should be allowed:

```text
Historical: Y=120s was used in session #1.
```

```text
`n >= 100` — SUPERSEDED by §10.2.
```

```text
The old Stage A procedure extended upward live; this is historical and must not be executed.
```

A different row containing `SUPERSEDED` must not exempt it.

### Generic negation

Remove the broad rule:

```text
contains "never" / "not" / "cannot" → automatically safe
```

Generic negative-word presence is not adequate evidence of semantic negation.

If line-level denial handling is retained, make it narrowly tied to the stale assertion itself.

For example these should be accepted:

```text
Post-hoc warmup re-filtering is NOT valid for the redesigned headline.
```

```text
N=5000 is NOT AUTHORIZED.
```

```text
The old 1.5/2/5 bracket must NOT be used.
```

But this must still fail:

```text
Applying the real N is a re-filter over the sidecars, never a GPU re-run.
```

If a reliable narrow rule is awkward, prefer explicit historical markers and narrowly defined approved denial phrases over a large `NEGATIONS` keyword set.

# C. Expand stale procedural detection

Add coverage for obsolete execution semantics in active docs.

At minimum evaluate patterns/concepts around:

```text
Stage A
Stage B
extend upward live
add lower points
mid-session
generate fine schedules mid-session
generate Stage B on the meter
```

Do not blindly reject every historical occurrence.

The rule is:

> In current `AUTHORITATIVE` / `EXECUTABLE` documents, these phrases are allowed only when they are locally and explicitly described as historical/superseded or clearly contrasted with the current session #2 procedure.

The active executable runbook may use terms such as Tier A / Tier B; do not conflate those with historical Stage A / Stage B merely because both contain `A` and `B`.

# D. Replace the weak C-DOC-3 control

The current synthetic control:

```text
resolve warmup after the run with --warmup-n
```

only proves that a simple regex can fire.

It does not exercise the defective exemptions.

Build the control from **real historical/stale text resembling the repository defect**.

At minimum include a case equivalent to:

```text
Applying the real N is a re-filter over the committed sidecars,
never a GPU re-run.
```

Expected:

```text
RED
```

Then a corrected form:

```text
Post-hoc warmup re-filtering is not valid for the redesigned exact-N headline.
If the 60s boundary is insufficient, regenerate schedules before Tier B.
```

Expected:

```text
GREEN
```

Also add controls proving scope.

## Required scope control

Construct a section/table equivalent to:

```text
| Warmup | Applying the real N is a re-filter over sidecars |
| Window | Y=120s — SUPERSEDED |
```

Expected:

```text
warmup row → RED
```

The `SUPERSEDED` marker in the second row must not suppress the first.

## Required heading control

Place known historical stale text underneath an explicitly historical heading.

Expected:

```text
GREEN
```

This proves historical provenance can still be preserved.

# E. Audit the real repository after changing the checker

Run the improved T-DOC-4 logic against the real current documents.

Do not stop at the first hit.

Produce a list containing:

```text
path
line/row
matched stale concept
classification:
    STALE
    EXPLICIT_HISTORICAL
    CURRENT_DENIAL
action taken
```

For every genuine `STALE` hit:

- correct the active documentation;
- preserve historical provenance where useful;
- do not silently erase why the old procedure existed.

Final condition:

```text
unexplained stale active hits = 0
```

# F. Preserve authority hierarchy

Do not create another authority document.

Current intended path remains:

```text
README.md
→ STATUS.md
→ docs/WEEK2_DOC_INDEX.md

Experiment authority:
    WEEK2_PLAN.md

Execution/gating:
    WEEK2_EXECUTION.md

GPU run:
    docs/WEEK2_GPU_SESSION_2_PLAN.md

Machine policy:
    repeat_policy.json
```

Historical evidence packages remain evidence, not execution instructions.

# G. Regression

After the fixes, run:

```text
documentation-governance tests
redesign suite
full non-router suite
router tier
all documentation negative controls
legacy artifact/hash verification
canonical workload verification
```

Do not modify historical evidence bytes.

Verify again:

```text
git diff HEAD -- benchmarks/schedules/stage_a corpus/
```

remains empty unless there is an already-authorized unrelated reason; there should not be one in this task.

Promoted first-session hashes must remain unchanged.

# H. Fresh-context integration test

Repeat the fresh-context documentation test after the real fixes.

Starting only from the root repository, the reviewer should arrive at:

```text
README.md
→ STATUS.md
→ docs/WEEK2_DOC_INDEX.md
→ docs/WEEK2_GPU_SESSION_2_PREFLIGHT.md
→ docs/WEEK2_GPU_SESSION_2_PLAN.md
```

and correctly report:

```text
N = 4000
N=5000 unauthorized
3 repeats, unanimity required
2–1 = UNCERTAIN
60s frozen warmup boundary
no post-hoc headline warmup re-filter
process epochs cannot mix
scout 1/2/4/8 with 0.5/16 fallback
```

If a fresh-context reviewer can reasonably conclude that the old Stage A/B or post-hoc warmup procedure is current, the cleanup is not complete.

# Constraints

- No GPU instance.
- No GPU benchmark.
- No historical artifact rewriting.
- No design changes to R4–R11.
- Do not weaken T-DOC-4 merely to get green.
- Do not solve the problem only by adding more regex exemptions.
- Prefer explicit document structure and local scope over heuristic natural-language interpretation.
- Do not commit until the entire cleanup is reviewed.
- Do not proceed past Hard Stop R-DOC.

# Definition of done

The task is complete when:

- [ ] Real stale warmup instructions are corrected.
- [ ] Old Stage A/B live-improvisation instructions are corrected or explicitly historical.
- [ ] Section-wide marker exemptions no longer hide unrelated stale lines.
- [ ] Generic negation words no longer automatically suppress violations.
- [ ] Procedural stale patterns are covered.
- [ ] C-DOC-3 uses the real stale warmup sentence class and demonstrably goes RED.
- [ ] A row-level scope control proves one `SUPERSEDED` row cannot exempt another row.
- [ ] A historical-heading control proves legitimate provenance can remain.
- [ ] Real-repo T-DOC-4 scan has zero unexplained stale active hits.
- [ ] Documentation suite is green.
- [ ] Existing redesign/full/router suites remain green.
- [ ] Legacy evidence/hashes remain unchanged.
- [ ] Fresh-context integration test passes.
- [ ] No GPU was created.
- [ ] Nothing is committed yet.

# Hard Stop R-DOC output

When complete, halt and report:

1. **Real inconsistencies fixed**
   - file
   - old semantic meaning
   - new semantic meaning

2. **T-DOC-4 implementation change**
   - old exemption behavior
   - new scoping behavior

3. **Controls**
   - real stale warmup sentence → RED
   - corrected warmup sentence → GREEN
   - cross-row supersession case → RED
   - explicit historical-heading case → GREEN

4. **Repository scan**
   - total candidate hits
   - stale corrected
   - explicit historical
   - current denials
   - unexplained = 0

5. **Regression**
   - documentation tests
   - redesign tests
   - non-router tests
   - router tier
   - legacy verification

6. **Fresh-context result**

7. **Git/cloud state**
   - working tree
   - commit status
   - GPU instances = none

Then stop for explicit human **R-DOC PASS**.

Do not start GPU session #2.
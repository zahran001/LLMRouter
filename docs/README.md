# docs

Architecture notes and Architecture Decision Records (ADRs) for LLMRouter.

## Week 2 — the GPU sessions

> **`WEEK2_DOC_INDEX.md` is the entry point.** It classifies every Week 2
> process document — authoritative, executable, evidence, historical,
> superseded — and names the single current GPU runbook. This directory holds
> both the live runbook and two dead ones; the directory name is not authority.

Read in this order if you are picking Week 2 up cold:

0. **`WEEK2_DOC_INDEX.md`** — which documents govern, and which must not be
   executed.
1. **`WEEK2_GPU_SESSION_FINDINGS.md`** — what GPU session #1 (2026-08-18)
   measured, what it falsified, and the explicit statement that it produced **no
   breach RPS**. Start here: several first-session numbers are still quoted
   around the repo and this says which of them survive.
2. **`../WEEK2_PLAN.md` §10** — every redesign supersession with the evidence
   behind it, plus §10.9's list of what did *not* change.
3. **`WEEK2_R4_EVIDENCE_PACKAGE.md`** — the R3-closeout and R4→R11
   implementation evidence, halted for review at Hard Stop R-PREGPU.
4. **`WEEK2_GPU_SESSION_2_PLAN.md`** — **the** session #2 runbook: two tiers,
   the six locks, the no-improvisation matrix, the artifact gate and teardown.
   The one file to keep open while the meter runs.

Session-operational notes:

- **`GPU_SESSION_NOTES.md`** — the working `gcloud` + vLLM sequence and the
  environment-specific bugs already worked around.
- **`WEEK2_GPU_SESSION_2_PREFLIGHT.md`** — the R-DOC / R-PREGPU evidence
  checklist for session #2.
- *(`WEEK2_GPU_PREFLIGHT.md` — session #1's Hard Stop 4 checklist — removed 2026-08-20; in git history at 39ed3f1.)*
  **SUPERSEDED — do not execute.**
- **`WEEK2_PRE_GPU_AUDIT.md`**, **`WEEK2_REMEDIATION_REPORT.md`** — the
  pre-session-#1 audit trail.
- **`WEEK2_MOCK_VALIDATION.md`** — the five mock validations and their negative
  controls.

`archive/` holds completed Week 1 process docs.

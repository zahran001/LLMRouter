# docs

Architecture notes and Architecture Decision Records (ADRs) for LLMRouter.

## Week 2 — the GPU sessions

Read in this order if you are picking Week 2 up cold:

1. **`WEEK2_GPU_SESSION_FINDINGS.md`** — what GPU session #1 (2026-08-18)
   measured, what it falsified, and the explicit statement that it produced **no
   breach RPS**. Start here: several first-session numbers are still quoted
   around the repo and this says which of them survive.
2. **`../WEEK2_PLAN.md` §10** — every redesign supersession with the evidence
   behind it, plus §10.9's list of what did *not* change.
3. **`WEEK2_R4_EVIDENCE_PACKAGE.md`** — the R3-closeout and R4→R11
   implementation evidence, halted for review at Hard Stop R-PREGPU.
4. **`WEEK2_GPU_SESSION_2_PLAN.md`** — the proposed two-tier second session,
   with its cost, its pre-authorized branches, and the decisions it still needs
   from a human.

Session-operational notes:

- **`GPU_SESSION_NOTES.md`** — the working `gcloud` + vLLM sequence and the
  environment-specific bugs already worked around.
- **`WEEK2_GPU_PREFLIGHT.md`** — the Hard Stop 4 evidence checklist.
- **`WEEK2_PRE_GPU_AUDIT.md`**, **`WEEK2_REMEDIATION_REPORT.md`** — the
  pre-session-#1 audit trail.
- **`WEEK2_MOCK_VALIDATION.md`** — the five mock validations and their negative
  controls.

`archive/` holds completed Week 1 process docs.

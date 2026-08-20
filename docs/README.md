# docs

Architecture notes and Architecture Decision Records (ADRs) for LLMRouter.

## Week 2 — the GPU sessions

> **The Week 2 entry point is `../WEEK2_DOC_INDEX.md`, at the repository root.**
> It classifies every Week 2 process document and names the single current GPU
> runbook. **The documents you execute from now live at the root**, not here —
> this directory keeps the evidence they rest on.

Read in this order if you are picking Week 2 up cold:

0. **`../WEEK2_DOC_INDEX.md`** — which documents govern.
1. **`WEEK2_GPU_SESSION_FINDINGS.md`** *(here)* — what GPU session #1
   (2026-08-18) measured, what it falsified, and the explicit statement that it
   produced **no breach RPS**. Start here: several first-session numbers are
   still quoted around the repo and this says which of them survive.
2. **`../WEEK2_PLAN.md` §10** — every redesign supersession with the evidence
   behind it, plus §10.9's list of what did *not* change.
3. **`WEEK2_R4_EVIDENCE_PACKAGE.md`** *(here)* — the R3-closeout and R4→R11
   implementation evidence.
4. **`../WEEK2_GPU_SESSION_2_PLAN.md`** — **the** session #2 runbook: two tiers,
   the six locks, the no-improvisation matrix, the artifact gate and teardown.
   The one file to keep open while the meter runs.

### Moved to the repository root (2026-08-20)

Kept together with `README.md` / `STATUS.md` / `WEEK2_PLAN.md` /
`WEEK2_EXECUTION.md`, so the whole live Week 2 set is in one place during a
session. Moved, not copied — there is exactly one of each:

| Now at root | Role |
|---|---|
| `../WEEK2_DOC_INDEX.md` | Which documents govern |
| `../WEEK2_GPU_SESSION_2_PLAN.md` | **The** session #2 runbook |
| `../WEEK2_GPU_SESSION_2_PREFLIGHT.md` | R-DOC / R-PREGPU evidence checklist |
| `../GPU_SESSION_NOTES.md` | Working `gcloud` + vLLM sequence, environment bugs |

### Still here — the evidence

- **`WEEK2_GPU_SESSION_FINDINGS.md`** — the permanent interpretation of session #1.
- **`WEEK2_R4_EVIDENCE_PACKAGE.md`** — R3 closeout and R4→R11 evidence.
- **`WEEK2_PRE_GPU_AUDIT.md`**, **`WEEK2_REMEDIATION_REPORT.md`** — the
  pre-session-#1 audit trail.
- **`WEEK2_MOCK_VALIDATION.md`** — the five mock validations and their negative
  controls.

*(Session #1's Hard Stop 4 pre-flight, `WEEK2_GPU_PREFLIGHT.md`, was deleted on
2026-08-20 along with the other dead Week 2 documents — recoverable at
`39ed3f1`.)*

`archive/` holds completed Week 1 process docs.

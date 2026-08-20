# Week 2 — document authority index

> **STATUS: AUTHORITATIVE — WEEK 2**
>
> Role: the single index of Week 2 process documents and their authority.
> This file decides which documents govern the next GPU session. If another
> document disagrees with this one about its own state, **HALT and surface the
> conflict** — do not reconcile it silently.

Week 2 accumulated a large amount of genuinely valuable history: two design
generations, a GPU session that falsified its own experiment, four
implementation briefs, and the evidence packages behind each. None of it is
being deleted. But history and instructions look identical in a markdown file,
and the failure this index exists to prevent is narrow and specific:

> A fresh agent or operator reads a Week 2 document that was correct when it
> was written, and executes it against GPU session #2.

So: **history stays, evidence stays, rationale stays — but only one execution
path is live.**

---

## 1. The current execution chain

```
START
  │
  ▼
README.md                              what the project is
  │
  ▼
STATUS.md                              where the project currently is
  │
  ▼
WEEK2_DOC_INDEX.md                     (this file) which documents govern
  │
  ├── Experimental authority ────────  WEEK2_PLAN.md
  │      what is measured, what is locked, and why
  │
  ├── Ordering / hard stops ─────────  WEEK2_EXECUTION.md
  │      block order, gates, definitions of done
  │
  ├── Current GPU mechanics ─────────  WEEK2_GPU_SESSION_2_PLAN.md
  │      THE session #2 runbook — the one file to keep open on the meter
  │
  └── Machine-readable policy ───────  benchmarks/workloads/week2_headline/
                                       repeat_policy.json
```

Nothing outside that chain may direct GPU session #2.

**Where the project is right now:** R4–R11 are implemented; the redesigned
benchmark is frozen; **Hard Stop R-DOC PASSED 2026-08-19**, and **Hard Stop
R-PREGPU** is next. No GPU instance exists, and none may be created before
R-PREGPU passes too.

---

## 2. What the states mean

| State | Meaning | May it direct execution? |
|---|---|---|
| `AUTHORITATIVE` | Defines current experiment decisions | Only via the docs it governs |
| `EXECUTABLE` | May be followed during the current GPU workflow | **Yes** |
| `EVIDENCE` | Supports decisions; never defines execution by itself | No |
| `HISTORICAL` | Preserved record of an earlier project state | **No — `DO NOT EXECUTE`** |
| `SUPERSEDED` | Contains procedure that was valid before the redesign | **No — `DO NOT EXECUTE`** |

`HISTORICAL` and `SUPERSEDED` differ only in *why* they are dead. A
`HISTORICAL` document records a state the project has left. A `SUPERSEDED`
document records a **procedure that would still run** if someone followed it,
and would produce evidence that looks legitimate and is not. Both carry
`DO NOT EXECUTE`; the second is the more dangerous of the two.

Every document in §3 declares its own state in a banner near its top, and
`tests/redesign/test_week2_doc_state.py` fails if a banner and this table
disagree. Directory names are not authority: `docs/` holds both the live
runbook and two dead ones.

---

## 3. Week 2 process documents

Every row here carries a status banner in the file itself. `Runbook?` marks
the **single** document authorized to drive a GPU session — exactly one row may
say yes.

### Authoritative — current decisions

| Path | State | Role | Runbook? | Superseded by |
|---|---|---|---|---|
| `STATUS.md` | AUTHORITATIVE | Where the project currently is; the session #1 do-not-cite list | no | — |
| `WEEK2_PLAN.md` | AUTHORITATIVE | The decision record: workload, p99 definition, censoring, N, prefix-cache policy, repeat meaning, secondary scope, supersession provenance | no | — |
| `WEEK2_EXECUTION.md` | AUTHORITATIVE | Execution order, hard stops (R0→R11, R-DOC, R-PREGPU), definitions of done | no | — |
| `WEEK2_DOC_INDEX.md` | AUTHORITATIVE | This index | no | — |
| `docs/WEEK2_MOCK_VALIDATION.md` | AUTHORITATIVE | The V1–V5 mock-validation procedure and its negative controls (GPU-free) | no | — |
| `benchmarks/workloads/week2_headline/repeat_policy.json` | AUTHORITATIVE | Machine-readable repeat/evidence policy — `"status": "LOCKED"` | no | — |

### Executable — may be followed on the meter

| Path | State | Role | Runbook? | Superseded by |
|---|---|---|---|---|
| `WEEK2_GPU_SESSION_2_PLAN.md` | EXECUTABLE | **The** GPU session #2 runbook. Self-contained: benchmark identity, server and client configuration, Tier A/B, validity states, the no-improvisation matrix, artifact gate, teardown | **yes** | — |
| `GPU_SESSION_NOTES.md` | EXECUTABLE | GCP + vLLM environment knowledge (working `gcloud` invocation, PuTTY/pscp, flashinfer). Setup reference, **not** the session runbook — it decides no experimental policy | no | — |

### Evidence — why we believe things

| Path | State | Role | Runbook? | Superseded by |
|---|---|---|---|---|
| `WEEK2_GPU_SESSION_2_PREFLIGHT.md` | EVIDENCE | The R-DOC / R-PREGPU evidence checklist for session #2 | no | — |
| `docs/WEEK2_GPU_SESSION_FINDINGS.md` | EVIDENCE | The permanent interpretation of GPU session #1: what it falsified, what survives | no | — |
| `docs/WEEK2_R4_EVIDENCE_PACKAGE.md` | EVIDENCE | R3-closeout and R4→R11 implementation evidence | no | — |
| `docs/WEEK2_PRE_GPU_AUDIT.md` | EVIDENCE | The 2026-08-17 pre-GPU audit and how each finding was closed | no | — |
| `docs/WEEK2_REMEDIATION_REPORT.md` | EVIDENCE | What the 2026-08-18 remediation changed and what it proved | no | — |
| `benchmarks/evidence/week2/first_session/README.md` | EVIDENCE | The promoted session #1 artifacts and what each may be cited for | no | — |
| `benchmarks/calibration/week2_redesign/R3_EVIDENCE_PACKAGE.md` | EVIDENCE | The offline calibration `k` / `L` / `N` / `N_max` were read off at Hard Stop R3 | no | — |

### Removed — the dead documents are gone from the working tree

**Deleted 2026-08-20 by human decision.** Eight documents — two `SUPERSEDED`,
six `HISTORICAL` — were removed rather than kept banner-marked. They are not
lost: every one is intact in git history and recoverable at any time.

```bash
git show 39ed3f1:WEEK2_GPU_IMPLEMENTATION_README.md
git show 39ed3f1:docs/WEEK2_GPU_PREFLIGHT.md
git log --diff-filter=D --name-only 39ed3f1..   # the full list
```

| Removed | Was | What it was | Where its content lives now |
|---|---|---|---|
| `WEEK2_GPU_IMPLEMENTATION_README.md` | SUPERSEDED | Session #1's GPU runbook (Stage A/B sweep, post-hoc warmup) | `WEEK2_GPU_SESSION_2_PLAN.md` |
| `docs/WEEK2_GPU_PREFLIGHT.md` | SUPERSEDED | Session #1's Hard Stop 4 checklist, incl. its `GPU SESSION READY` verdict | `WEEK2_GPU_SESSION_2_PREFLIGHT.md` |
| `WEEK2_GPU_REDESIGN_HANDOFF.md` | HISTORICAL | The brief that opened the redesign after session #1 | `WEEK2_PLAN.md` §10 |
| `WEEK2_GPU_REDESIGN_IMPLEMENTATION_README_UPDATED.md` | HISTORICAL | The R0–R3 implementation brief | `docs/WEEK2_R4_EVIDENCE_PACKAGE.md` |
| `WEEK2_R3_CLOSEOUT_AND_R4_IMPLEMENTATION_README.md` | HISTORICAL | The R4→R11 implementation brief | `docs/WEEK2_R4_EVIDENCE_PACKAGE.md` |
| `Week 2 Pre-GPU Remediation.md` | HISTORICAL | The pre-session-#1 remediation brief | `docs/WEEK2_REMEDIATION_REPORT.md` |
| `Week 2 Pre-GPU Documentation Cleanup — Implementation README.md` | HISTORICAL | The brief for the documentation cleanup | `WEEK2_GPU_SESSION_2_PREFLIGHT.md` |
| `Agent Prompt — Fix T-DOC-4 and Close Documentation Drift.md` | HISTORICAL | The brief for the T-DOC-4 scope fix | `WEEK2_GPU_SESSION_2_PREFLIGHT.md` |

Removal is a stronger guarantee than a banner: a document that is not in the
working tree cannot be found, read, or followed by mistake. The **rule** stays
in force for anything added later — §2's states, the `DO NOT EXECUTE`
requirement, and `tests/redesign/test_week2_doc_state.py` all still apply the
moment a `HISTORICAL` or `SUPERSEDED` row reappears in §3.

What is genuinely lost is provenance-at-a-glance: the reasoning behind each
superseded decision now needs `git show` rather than a scroll. The decisions
themselves are not affected — every one is recorded in `WEEK2_PLAN.md` §10 and
§11, and in the evidence packages above, which is where a reader should look
first regardless.

---

## 4. Evidence never points at execution

The dependency runs one way, and only one way:

```
WEEK2_GPU_SESSION_2_PLAN.md  ──references──▶  evidence documents
                                                   (for rationale)

evidence documents  ──X──▶  execution
```

An evidence package answers *why do we believe this?* It never answers *what
shell command should I run next?* Several of them contain command text — that
text is the record of what was run at the time, not an instruction. Each says
so in its banner.

---

## 5. The six human locks governing GPU session #2

Locked ahead of Hard Stop R-DOC. Recorded in `WEEK2_PLAN.md` §11 with their
reasoning, and machine-readably in `repeat_policy.json`.

| Lock | Decision |
|---|---|
| **D-CLEAN-1 / 1A** | Three independent repeats per headline λ; final classification requires **agreement**. A 2–1 split is `UNCERTAIN`. **No majority voting.** |
| **D-CLEAN-2 / 2B** | `N = 4000` is the authorized headline evidence size. **`N = 5000` is NOT AUTHORIZED.** An unresolved crossing is reported as a **breach interval**. |
| **D-CLEAN-3 / 3A** | Headline repeats from different vLLM **process epochs** must not be combined into one classification family. |
| **D-CLEAN-4 / 4A** | The **60-second warmup boundary is frozen** into the exact-N schedules and validated during Tier A. If it is insufficient: **STOP and regenerate schedules.** Post-hoc re-filtering of headline sidecars is **not** a valid resolution. |
| **D-CLEAN-5 / 5A** | Scout λ = 1, 2, 4, 8, with **0.5** and **16** pre-authorized as fallback. If the fallback still fails to bracket: **STOP.** No other λ may be invented on the meter. |
| **D-CLEAN-6 / 6A** | Week 2 is not closed until the controlled Poisson headline, natural-random secondary, steady-arrival reference and adversarial scenario are accounted for. Only the **controlled Poisson** workload defines the headline breach; adversarial runs last. |

---

## 6. What must never be reachable as a current claim

These are session #1 numbers. They remain in evidence and history, and
`docs/WEEK2_GPU_SESSION_FINDINGS.md` holds their permanent interpretation. No
current document may present any of them as a live result:

| Dead claim | Why |
|---|---|
| breach RPS = 2 | Flips on one extreme prompt, and again on the percentile convention |
| 1.5 RPS = clean UNDER anchor | Driven last against a warm prefix cache |
| 402.3 ms = definitive unloaded floor | `CACHE_INFLUENCED_DIAGNOSTIC`; a new clean floor is collected in session #2 |
| 10/20/30 RPS survivor p99 = ordinary latency | 33–81% censored by the 60s client timeout; survivorship artifacts |
| `n >= 100` = sufficient p99 evidence | Superseded by calibrated `N = 4000` + independent repeats |
| `Y = 120s` fixed window = the headline basis | Superseded by exact-N schedules |

---

## 7. Reading order for a cold start

1. `README.md` — what the project is.
2. `STATUS.md` — where it is.
3. **this file** — which documents govern.
4. `docs/WEEK2_GPU_SESSION_FINDINGS.md` — why the experiment was redesigned.
5. `WEEK2_PLAN.md` §10 and §11 — every supersession, and the six locks.
6. `WEEK2_EXECUTION.md` — the block order and the hard stops still ahead.
7. `WEEK2_GPU_SESSION_2_PLAN.md` — only when a GPU session is actually
   authorized.

If a document you found is not in §3, it is not a Week 2 process document —
check `README.md`'s document map for the component and spec docs.

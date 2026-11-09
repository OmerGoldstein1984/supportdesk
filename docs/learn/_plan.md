# SupportDesk — learn/ improvement plan

Base branches (never touch `main`):
- `learn/annotated` — original code + teaching comments/docs only. Zero logic change.
- `learn/improved` — branched from `learn/annotated`; all fixes and rewrites.

Current branch: `learn/annotated` (pristine commit `42479a6`).
Baseline tests: `pytest -m "unit or integration"` → 43 passed.

## Issue order (severity first)

| Order | Issue | Branch | Type | Files |
|-------|-------|--------|------|-------|
| 1 | P1-1 `datetime.utcnow()` deprecation | learn/improved | bug fix | database.py, repositories.py, models.py, seed_data.py |
| 2 | P1-2 hermetic per-test SQLite DB | learn/improved | test fix | conftest.py |
| 3 | P0-2 harden prompt-injection detector | learn/improved | security | security.py |
| 4 | P0-1 authN — resolve real caller from header | learn/improved | security | main.py, graph.py (+ tests) |
| 5 | P1-3 rate-limiting middleware | learn/improved | reliability | main.py (new middleware) |
| 6 | P3-1 explicit coverage gate in CI | learn/improved | polish | .github/workflows/ci.yml |

## Phase mapping

- **Phase 0 (recon):** `docs/learn/07_issues_found.md` (this list), `docs/learn/_plan.md` (this file), `docs/learn/00_START_HERE.md` — written on `learn/annotated`.
- **Phase 1 (annotate):** teaching comments/docstrings on `learn/annotated`, comment-only, verified by AST/stripped-source comparison + tests.
- **Phase 2 (docs):** `01_business_context.md`, `02_architecture.md`, `03_glossary.md`, `04_gap_bridge.md`, `05_trace_walkthrough.md` — against annotated code.
- **Phase 3 (improve):** issues 1–6 on `learn/improved`, one commit per issue, each with a change record in `docs/learn/changes/NNN-title.md` and a characterization/failure-injection test.
- **Phase 4 (interview pack):** `06_interview_pack.md`, `08_exercises.md`.
- **Phase 5 (reading guide):** `00_START_HERE.md` study order.
- **Phase 6 (verification):** annotated == original logic; improved tests green; linters/type checks pass.

## File-ownership (disjoint, single coordinator)

Coordinator (this agent): plan, issues list, authN fix, change records, verification.
All file edits touch non-overlapping sets so no two writers collide in one worktree.

## Definition of done per fix

- Characterization test written (or existing behavior recorded) before the change.
- One commit, single concern, message describes the lesson.
- Change record `docs/learn/changes/NNN-title.md` complete (all 8 fields).
- Tests green: `pytest -m "unit or integration"` + ruff + mypy.
- At least one failure-injection test for each P0/P1 fix.

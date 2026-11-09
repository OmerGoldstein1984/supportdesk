# SupportDesk — prioritized issues found (Phase 0 recon)

Baseline: pristine initial commit `42479a6` on `main`/`master`.
Test baseline: `pytest -m "unit or integration"` → **43 passed, 2 deselected**.
Lint: `ruff check` clean, `ruff format` clean, `mypy src` clean.
CI: GitHub Actions runs lint → test → eval gate on `main` pushes/PRs.

These are ranked P0 → P3. The repo's own `docs/08-weaknesses-and-next-steps.md`
already documents several of these as intentional "prototype-grade" items (the
project is a portfolio/interview demo). This list separates **real bugs to fix
now** from **known limitations to leave as future work** (marked `[ACKNOWLEDGED]`).

## P0 — security / data loss / crash (fix first)

### P0-1: API trusts client-supplied `customer_id` (no authN)
- **File:** `src/supportdesk/main.py` (`/chat`, `/approve`), `src/supportdesk/graph.py` (`run`, `resume`)
- **Problem:** The API accepts `customer_id` from the request body and passes it straight into the graph. The repository layer scopes reads to that customer, but nothing proves the caller *is* that customer. A caller can set `"customer_id": 42` and read customer 42's invoices, tickets, and refunds.
- **Impact:** Cross-customer data exposure — money, trust, compliance.
- **Why now:** This is the highest-severity issue in the repo. Listed in `docs/08` as limitation #3 ("No authentication beyond customer-ID scoping") and flagged "Fix at 100x". For an FDE interview, "the client-supplied customer_id is trusted" is a classic, defensible finding.
- **Fix scope:** Add a simple authN layer that resolves the real caller from a request header (e.g. `X-Customer-Id` or an API key) and rejects/overrides a client-supplied `customer_id` that doesn't match. Keep it teachable — no full OAuth.
- **Learner relevance:** The learner is strong on APIs, weak on authN/authZ. This is the canonical teaching example.

### P0-2: Prompt-injection defense is regex-only, easily obfuscatable
- **File:** `src/supportdesk/security.py` (`_INJECTION_PATTERNS`)
- **Problem:** Injection detection is a fixed list of case-insensitive regexes (`ignore previous instructions`, `reveal the system prompt`, …). An attacker can obfuscate (whitespace, unicode, encoding) and bypass it. The same list is applied to tool outputs, which is good defense-in-depth, but the patterns are brittle.
- **Impact:** Prompt injection → unauthorized tool calls (e.g. refund), data exfiltration.
- **Fix scope:** Harden the detector (normalize whitespace, add common obfuscation variants) and document that regex is a first line of defense, not a guarantee.

## P1 — reliability / correctness

### P1-1: `datetime.datetime.utcnow()` is deprecated (will break)
- **File:** `src/supportdesk/database.py` (line 63 default, `mark_paid`), `src/supportdesk/repositories.py` (lines 68, 117), `src/supportdesk/models.py` (line 63 default), `src/supportdesk/scripts/seed_data.py`
- **Problem:** SQLAlchemy and Python deprecate `datetime.utcnow()` (naive UTC). It emits `DeprecationWarning` on every model default / `paid_at` / `failed_at` write, and will be removed in a future Python/SQLAlchemy version → crash on startup/write.
- **Impact:** Test noise (38 deprecation warnings), future breakage.
- **Fix scope:** Replace with `datetime.datetime.now(datetime.UTC)` (timezone-aware). One-line mechanical change across 4 files.
- **Learner relevance:** Teaches naive vs aware datetimes, deprecation handling.

### P1-2: Shared `test.db` leaks state between tests
- **File:** `tests/conftest.py` (`db_session`, `seeded_db` fixtures), CI runs `DATABASE_URL=sqlite:///./test.db`
- **Problem:** `test.db` is a single shared, gitignored SQLite file. `db_session` clears tables after each test, but `seeded_db` hard-codes customer/invoice ids (1, 50, 120). Parallel runs or a stale DB from a previous run cause fixture conflicts (we saw 18 errors on a stale DB on first run after branching).
- **Impact:** Flaky, non-deterministic tests; CI can fail spuriously.
- **Fix scope:** Use an in-memory SQLite (`:memory:`) or a per-test temp file DB, and seed deterministically per test. Keep the DB out of the repo (already gitignored `*.db`).
- **Learner relevance:** QA background — test isolation and hermeticity are directly in their wheelhouse.

### P1-3: No rate limiting / abuse protection
- **File:** `src/supportdesk/main.py` (FastAPI app, no middleware)
- **Problem:** No per-customer or per-API-key rate limit. A malicious user can spam the LLM (each `/chat` triggers router + specialist + critic LLM calls) and run up cost. Listed in `docs/08` as limitation #9.
- **Impact:** Cost abuse, denial of service.
- **Fix scope:** Add a simple in-memory token-bucket / fixed-window rate limiter keyed by customer id (or API key) as FastAPI middleware. Document that production needs Redis-backed distributed limiting.
- **Learner relevance:** Rate-limited APIs and event pipelines are in the learner's background.

## P2 — design / maintainability (acknowledged limitations; leave as future work unless a fix is cheap and high-value)

These are documented in `docs/08-weaknesses-and-next-steps.md` as intentional
prototype-grade choices ("Fix at 100x"). They are **not bugs** — fixing them is
large architectural work. List them here for completeness and so the learner
understands the boundary between "fix now" and "v2".

| # | Issue | Docs ref | Why leave for v2 |
|---|-------|----------|------------------|
| P2-1 | In-memory `InMemorySaver` checkpointer (state lost on restart) | limitation #2 | Needs Postgres checkpointer + ops |
| P2-2 | SQL `ILIKE` keyword RAG (no vector/semantic search) | limitation #1 | Needs embedding model + vector store |
| P2-3 | Eval uses keyword-driven fake LLM (not real model quality) | limitation #7 | Needs live-LLM smoke suite |
| P2-4 | Single monolith FastAPI process | limitation #8 | Needs per-agent services + gateway |
| P2-5 | Hand-rolled ReAct loop (not prebuilt LangGraph agent) | limitation #4 | Intentional for interview explainability |
| P2-6 | Hand-rolled LLM retry/fallback (no circuit breaker) | limitation #5 | Needs battle-tested client |
| P2-7 | No customer-facing chat UI / admin dashboard | limitation #6 | Frontend work, out of scope |
| P2-8 | `_ormsgpack_shim.py` workaround for blocked extension | infra | Document as infra shim, keep working |

## P3 — polish

### P3-1: Coverage gate not visibly enforced in CI command
- `pyproject.toml` sets `fail_under = 85` under `[tool.coverage.report]`, but the CI test command runs `pytest ... --cov=supportdesk` without `--cov-fail-under`. `pytest-cov` reads `fail_under` from config, so it likely works, but it's not explicit in CI. Verify and document.
- **Fix scope:** Make the gate explicit in CI or document that config enforces it.

## Plan of attack (severity order)

1. P1-1: `datetime.utcnow()` → `datetime.now(UTC)` (4 files) — quick, high-value, teachable.
2. P1-2: hermetic per-test SQLite DB (test isolation) — QA-relevant, removes flakiness.
3. P0-2: harden prompt-injection detector — security, small scope.
4. P0-1: authN — resolve real caller from header, ignore/override client `customer_id` — the headline interview finding.
5. P1-3: rate-limiting middleware — cost abuse protection.
6. P3-1: make coverage gate explicit.

P2 items are recorded here and deferred to v2 (they are large architectural changes and explicitly acknowledged in the repo).

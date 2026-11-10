# SupportDesk — Web App Way vs Production Way (Gap Bridge)

This document bridges the gap between how a typical web app is built and how
SupportDesk is built for production-grade, interview-explainable AI agent
deployment. Each item contrasts the "web app way" (common startup approach)
with the "production way" (SupportDesk approach), explaining why.

---

## 1. LLM Prompting

**Web app way:** Hardcode prompts in Python strings, send raw text to the LLM,
hope the model returns JSON. Parse with json.loads() and hope it parses.

**SupportDesk way:** LangChain structured output (Pydantic v2 schemas).
`RouterOutput`, `CriticOutput`, and tool schemas (`GetInvoiceArgs`,
`IssueRefundArgs`, etc.) constrain the LLM to return typed JSON.

**Why:** Free-text LLM output is unreliable for downstream code. Structured
output guarantees the schema, eliminates JSON parsing errors, and makes the
agent's decisions inspectable and testable.

**Interview:** "Why not just parse JSON from the LLM?" Answer: Because LLMs
can return malformed JSON, extra text, or wrong field types. Structured output
makes the contract explicit and failures predictable.

---

## 2. Tool Calling

**Web app way:** The LLM generates a JSON string describing a tool call; the
app parses it and calls the function. No validation, no allowlist, no risk
policy.

**SupportDesk:** LangChain tools with Pydantic v2 arg schemas, routed through
a plain-code `ToolGate` that enforces per-agent allowlists, schema validation,
and risk policy (refund threshold) before any repository call.

**Why:** Tool use is the most dangerous part of an agent — it can change state
(refund money, change plans, create tickets). Centralizing the gate in one
deterministic class makes it testable and auditable.

**Interview:** "Why not let the LLM call any tool?" Answer: Because a billing
agent should never call a technical tool, and refunds above $100 need human
approval. The allowlist enforces separation of duties.

---

## 3. Human-in-the-Loop

**Web app way:** The LLM executes refunds directly. No human in the loop. No
audit trail of approvals.

**SupportDesk:** LangGraph `interrupt()` pauses the graph for refunds above
$100. A human approves or rejects via `POST /approve`. The decision is
recorded in conversation state and the graph resumes via `Command(resume=...)`.

**Why:** High-risk actions (refunds above $100) need human approval. The
checkpointer persists conversation state across the pause/resume cycle.

**Interview:** "What if the human never responds?" Answer: The graph stays
paused until resumed. In production, you'd add a timeout escalation.

---

## 4. Conversation State

**Web app way:** Stateless HTTP. Each request is independent. No memory of
past messages.

**SupportDesk:** LangGraph `InMemorySaver` checkpointer keyed by
`conversation_id` (thread_id). State persists across turns and interrupt/resume
cycles.

**Why:** Customer support is multi-turn. The router, specialist, critic, and
escalation nodes all read and write shared state (`AgentState`).

**Interview:** "What happens on server restart?" Answer: In-memory checkpointer
loses state. Production would use LangGraph's `PostgresSaver`. Documented as a
"100x" fix in docs/08.

---

## 5. Tool Output Handling

**Web app way:** Tool outputs are fed directly back to the LLM. No sanitization.
No risk of prompt injection via tool output.

**SupportDesk:** `sanitize_tool_output()` redacts PII and scans for injection
patterns before feeding tool output back to the LLM. Defense in depth.

**Why:** Tool outputs may contain customer records (emails, phones, cards) or
compromised tool outputs may contain injection attempts. Both must be scrubbed.

**Interview:** "Why sanitize tool output?" Answer: Defense in depth — a
compromised tool could embed an injection attempt that the LLM reads directly.

---

## 6. Data Access

**Web app way:** SQL queries with user-supplied IDs. `SELECT * FROM invoices
WHERE id = {id}`. Cross-customer access possible if you forget a WHERE clause.

**SupportDesk:** Repository layer filters every read by `customer_id`. A
customer can never read another customer's invoices, tickets, or account data.
Data-layer enforcement, not just LLM-level.

**Why:** Cross-customer data access is a catastrophic trust breach. Enforcing
it at the data layer means even if the LLM is tricked, the repository returns
None.

**Interview:** "Why not enforce scoping at the tool gate?" Answer: The gate has
no database access. Row-level filtering needs the ORM session, which lives in
the repositories.

---

## 7. Secrets

**Web app way:** API keys hardcoded in source or committed to git.

**SupportDesk:** All settings via environment variables (.env file). `.env` is
gitignored. `config.py` uses pydantic-settings `BaseSettings`.

**Why:** Secrets never in code. Environment-based config means the same image
runs dev/staging/prod.

**Interview:** "Where does the NVIDIA API key live?" Answer: In `.env`, loaded
via pydantic-settings. `.env` is gitignored. Never committed.

---

## 8. Testing & Evals

**Web app way:** Unit tests for individual functions. No eval baseline. No
regression guard for agent decision quality.

**SupportDesk:** Unit + integration tests (fake LLM, SQLite) + eval harness
(labeled 150+ ticket corpus, routing/tool accuracy, committed baseline, CI
regression gate: fail if accuracy drops >5 points).

**Why:** Code correctness tests don't capture agent decision quality. Evals
measure whether the agent picks the right specialist and tool. The baseline
gate prevents regressions.

**Interview:** "Why evals separate from tests?" Answer: Tests prove code
correctness. Evals prove decision quality. A function can be correct but the
agent can still pick the wrong specialist.

---

## 9. Deployment

**Web app way:** `pip install` and `python app.py`. Local dev only.

**SupportDesk:** Docker + docker-compose (SQLite or Postgres), GitHub Actions
CI (lint → test → eval gate → coverage upload). One-command seed.

**Why:** Reproducible, CI-gated, deployable. The CI gate ensures every push
passes lint, tests, and eval regression.

**Interview:** "Why Docker?" Answer: Reproducible environment, same image
dev/staging/prod. Docker Compose for local Postgres + app.

---

## 10. Observability

**Web app way:** `print()` statements. No structured logs. No trace endpoint.

**SupportDesk:** structlog JSON logging with PII redaction. `/trace/{id}`
endpoint inspects conversation state (interview demo).

**Why:** JSON logs are machine-parseable. PII redaction prevents sensitive data
in logs. `/trace` lets an interviewer inspect conversation state.

**Interview:** "How do you debug a conversation?" Answer: `/trace/{id}` shows
conversation state. Structured JSON logs are PII-redacted.

---

## Summary Table

| Concern | Web App Way | SupportDesk (Production Grade) |
|---------|-------------|-------------------------------|
| LLM output | Free text, JSON.parse() | Structured output (Pydantic schemas) |
| Tool calls | Direct execution | Allowlist + schema + risk policy gate |
| Refunds > $100 | Auto-execute | Human-in-the-loop (LangGraph interrupt) |
| Conversation state | Stateless | InMemorySaver checkpointer (thread_id) |
| Tool output | Raw to LLM | PII redacted + injection scanned |
| Data access | SQL with customer_id | Repository layer customer scoping |
| Secrets | Hardcoded | Environment variables (.env, gitignored) |
| Testing | Unit tests only | Unit + integration + eval regression gate |
| Deploy | python app.py | Docker + Docker Compose + GitHub Actions CI |
| Logging | print() | structlog JSON with PII redaction + /trace |

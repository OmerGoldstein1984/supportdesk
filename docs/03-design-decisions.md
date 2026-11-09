# SupportDesk — design decisions

This document records the major architectural choices, the alternatives
considered, and why we went the way we did. It is written to be defensible in an
interview.

## 1. LangChain v1 agents + LangGraph supervisor (instead of AgentExecutor)

**Decision:** Each specialist is implemented as a small, explicit ReAct tool-calling
loop over its allowlisted LangChain `@tool` functions, coordinated by a single
LangGraph `StateGraph` supervisor (Router → specialist → Critic → reply).

**Why not `create_tool_calling_agent` / `AgentExecutor`:**
- In modern LangChain (0.3+), `create_tool_calling_agent` / `AgentExecutor` have
  import instability and are the legacy, harder-to-control path.
- LangGraph's `StateGraph` is the supported, checkpointer-native way to build
  multi-agent workflows with shared conversation memory and interrupt/resume.

**Trade-off:** We hand-wrote the ReAct loop instead of using a prebuilt agent
constructor. This is more code but gives us full control over tool execution,
allowlist enforcement, risk policy, and the human-in-the-loop interrupt — all of
which are central to the product and easy to explain in an interview.

## 2. Plain-code tool gate (not an LLM-based guardrail)

**Decision:** Every tool call passes through a deterministic `ToolGate` that checks
(1) per-agent allowlist, (2) Pydantic v2 schema validation, (3) customer scoping,
and (4) risk policy (refunds above the threshold require approval).

**Why not an LLM guardrail:** LLMs are non-deterministic and can be bypassed with
prompt injection. The gate is plain Python — it cannot be "talked into" allowing a
billing agent to call a technical tool, nor can it be tricked into approving a
large refund.

**Trade-off:** The gate must be kept in sync when tools change. We mitigate this
with unit tests that assert the allowlist and risk policy directly.

## 3. Critic agent on every draft

**Decision:** A dedicated Critic agent reviews every draft reply for (1) policy
compliance, (2) PII leakage, and (3) hallucination before it reaches the customer.

**Why not trust the specialist:** Specialists optimize for being helpful, which
means they can over-promise (e.g. "I'll refund you no matter what") or repeat
PII. A separate critic with a different goal (caution) catches these.

**Trade-off:** Extra LLM latency and cost per turn. For a support bot, correctness
and safety matter more than a few hundred milliseconds.

## 4. Human-in-the-loop for large refunds

**Decision:** Refunds above `refund_auto_approve_threshold` (default $100) return
an `APPROVAL_REQUIRED` signal. The graph pauses at `interrupt()`, surfaces the
invoice and amount to a human via `/approve`, and only executes on an explicit
approve. Rejection escalates.

**Why not auto-approve everything:** Financial actions are the highest-risk
operation. A human in the loop is the safest default and is easy to demo.

**Trade-off:** Slower resolution for large refunds. Acceptable — those are rare
and high-stakes.

## 5. Fallbacks route to Escalation

**Decision:** Router confidence below threshold, two failed tool validations, or
Critic rejection after one revision all route to Escalation with a full case
summary.

**Why:** When the system is unsure, the safest action is to hand a human a clear
summary rather than guess and risk a wrong answer or a data leak.

## 6. Evals separate from tests

**Decision:** We have (a) deterministic tests (unit/integration/e2e with a fake
LLM) and (b) an eval harness that runs a 150-ticket labeled corpus through a
deterministic fake LLM and reports routing accuracy and tool-selection accuracy
against a committed baseline. CI fails if accuracy drops more than 5 points.

**Why not only tests:** Tests assert correctness of code. Evals measure quality of
non-deterministic agent decisions. You need both.

## 7. Test pyramid

**Decision:**
- **Unit** (fast, no network, fake LLM): tool schemas, allowlist, risk policy,
  gate, router parsing, critic logic, PII redaction, config. 85% coverage gate.
- **Integration:** agents + tools + real DB, RAG, FastAPI TestClient, interrupt/
  resume, fallback paths, retry/fallback behavior (fake LLM in CI).
- **E2E:** full HTTP scenarios against `docker compose up`.
- **Eval:** labeled corpus, routing/tool accuracy, LLM-as-judge (on demand /
  nightly against the real NVIDIA API).

## 8. Security decisions

- **No secrets in code:** all config via environment variables (`.env.example`
  provided; `.env` is gitignored).
- **Per-agent tool allowlists:** billing cannot call technical tools and vice
  versa — enforced in code, not by the LLM.
- **Customer scoping:** repositories only ever return rows belonging to the
  requesting `customer_id` — cross-customer access is impossible at the data
  layer.
- **PII redaction in logs:** emails, phones, card numbers, SSNs are replaced
  before logging.
- **Prompt-injection defense:** user input and tool outputs are scanned for
  injection patterns; matches are rejected.

## 9. Database: SQLite locally, Postgres in docker-compose

**Decision:** SQLAlchemy models with `DATABASE_URL` selecting SQLite (default) for
local/dev/test and Postgres for docker-compose.

**Why:** Zero-setup local development and tests; Postgres parity for production
deployment via the same code.

## 10. What we intentionally did NOT build

- A real vector store / RAG retrieval (the Technical agent searches articles with
  SQL `ILIKE`; production would add a vector store).
- Auth / multi-tenancy beyond customer-scoping by ID.
- A real frontend beyond the minimal approval endpoint and `/trace`.

These are listed as next steps in `docs/08-weaknesses-and-next-steps.md`.

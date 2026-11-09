# SupportDesk — glossary (learning copy)

Every term, library, and pattern in the codebase, with `file:line` references and a one-line analogy. Written for a senior QA/automation engineer (telecom/eSIM, IoT) — analogies draw from event feeds, provisioning queues, test pipelines, and rate-limited APIs.

## People & roles (the learner)

**FDE (Forward Deployed Engineer)** — the persona. An AI Solutions Engineer who explains and defends technical decisions to customers, as if they wrote the code themselves.

## The six agents

**Router** (`src/supportdesk/graph.py:86`)
Classifies the customer's message into intent/urgency/confidence via structured output. Like a **triage nurse in a telecom NOC** routing an incident to the right specialty team.

**Specialist** (`src/supportdesk/agents/specialist.py`)
Runs a bounded ReAct loop over its allowlisted LangChain tools. Like an **on-call engineer with a restricted tool belt** — they can only run the tools their team is authorized for.

**Critic** (`src/supportdesk/agents/critic.py`)
Reviews the draft reply for policy, PII leakage, hallucination; decides approve / revise / reject. Like a **QA reviewer approving, requesting a rewrite of, or rejecting a test case**.

**Escalation** (`src/supportdesk/agents/specialist.py:39`)
Creates support tickets and notifies human agents. Like the **escalation queue in a ticketing system** when front-line can't resolve.

**Router / Critic** have empty tool allowlists — they never call tools, only classify and review.

## Core patterns

**ReAct loop** (`src/supportdesk/agents/base.py:31`)
The specialist's explicit "reason → act → observe" loop: the LLM picks a tool, the gate executes it, the result is fed back, and the loop repeats up to `max_tool_steps`. Like **investigate → run a diagnostic → interpret the result** in a support incident.

**Tool gate / allowlist** (`src/supportdesk/tool_gate.py`)
Plain-code middleware that enforces, for every tool call: (1) per-agent allowlist (billing can't call technical tools), (2) Pydantic v2 schema validation, (3) customer scoping via `customer_id`, (4) risk policy (refunds above `$100` flagged for approval). Like a **change-control allowlist** saying which tools a team may run in production.

**Schema validation** (`src/supportdesk/schemas.py`, `tool_gate.py:104`)
Every tool's arguments validated against a Pydantic v2 model before execution. Like **schema validation in an API gateway** rejecting malformed requests.

**Risk policy** (`src/supportdesk/tool_gate.py:128`)
Refunds above `refund_auto_approve_threshold` ($100) return an `APPROVAL_REQUIRED:…` marker instead of executing. Like a **high-value refund needing manager approval** in a billing system.

**Prompt injection** (`src/supportdesk/security.py:18`)
Instruction-hijack patterns ("ignore previous instructions", "reveal the system prompt") scanned in user input and tool outputs. Like **social engineering over a support chat** — an attacker tries to make the agent act against its instructions.

**PII redaction** (`src/supportdesk/security.py:38`)
Emails, phones, card numbers, SSNs replaced with `[EMAIL]`/`[PHONE]`/`[CARD]`/`[SSN]` tokens. Like **masking customer data in logs** so it never reaches plain text.

## Human-in-the-loop

**Human-in-the-loop / interrupt** (`src/supportdesk/graph.py:140`)
LangGraph `interrupt()` pauses the graph and waits for a human to approve/reject a large refund before resuming. Like a **change-approval window in CI/CD** — a manual gate before a production action.

**Checkpointer** (`src/supportdesk/graph.py:270`)
`InMemorySaver` snapshots conversation state keyed by `conversation_id` (`thread_id`), so state persists across turns and interrupt/resume cycles. Like **session state in a test pipeline** keyed by a correlation ID.

**APPROVAL_REQUIRED marker** (`src/supportdesk/tools/base.py:19`)
A refund above the threshold returns `"APPROVAL_REQUIRED:issue_refund|{...}|reason"` instead of executing, so the graph can interrupt for human approval. Like a **high-value refund flagged for secondary approval**.

## Data & access control

**Customer scoping** (`src/supportdesk/repositories.py`)
Every repository read that takes `customer_id` only returns rows belonging to that customer — enforced at the data layer, not just in the LLM. Like **row-level security / multi-tenant data isolation** in a SaaS platform.

**Cross-customer data access denied** — a customer can never read another customer's invoices, tickets, or account data. Like **tenant isolation** preventing one subscriber from seeing another's usage.

## Libraries & frameworks

**LangChain v1** (`pyproject.toml:8`) — the LLM application framework used for structured output and tool calling.

**LangGraph** (`pyproject.toml:10`) — builds the stateful supervisor graph with checkpointer. Like a **workflow engine for AI agents**.

**FastAPI** (`pyproject.toml:12`) — the web framework serving `/chat`, `/approve`, `/trace`. Like the **REST API layer**.

**SQLAlchemy** (`pyproject.toml:15`) — the ORM mapping Python classes to database tables. Like the **database access layer**.

**Pydantic v2** (`pyproject.toml:14`) — data validation for settings, schemas, and structured LLM output. Like **schema enforcement** at the boundary.

**Structured output** (`agents/router.py:17`, `agents/critic.py:16`)
The LLM is constrained to return a typed Pydantic model (RouterOutput / CriticOutput) rather than free text. Like a **structured test result** instead of free-form notes.

**`datetime.utcnow()` → `datetime.now(timezone.utc)`** (`models.py:63`, `repositories.py:68`)
Timezone-aware timestamps replace the deprecated naive `utcnow()`. Like **using UTC timestamps with offset** instead of wall-clock time in event feeds.

## Testing & evals

**Deterministic fake LLM** (`tests/conftest.py`)
`FakePrimary` / `FakeStructured` return canned responses — no network, no NVIDIA API key, stable in CI. Like a **mock server** in a test suite.

**Eval** (`src/supportdesk/evals/harness.py`)
Runs the 150+ labeled ticket corpus through a fake LLM and reports routing accuracy and tool-selection accuracy against a committed baseline. Like a **regression test suite for decision quality**.

**Baseline** (`data/eval_baseline.json`)
Committed accuracy (routing 74%, tool-selection ~41%) that CI must not drop more than 5 points below. Like a **committed test expectation** that guards against regressions.

**Idempotent seed** (`src/supportdesk/scripts/seed_data.py`)
Fixed random seed (`SEED = 42`); re-running creates identical data and skips existing rows. Like **deterministic test data setup** for a test pipeline.

**Coverage gate** (`pyproject.toml:69`, CI `--cov-fail-under=85`)
CI fails if test coverage of `supportdesk` drops below 85%. Like a **coverage threshold** enforced in a quality gate.

**Characterization test** — a test that pins current behavior so a later change can't silently alter it. Like **locking down current behavior before refactoring**.

**Failure-injection test** — feeds bad input (injection attempt, cross-customer ID) and asserts the system blocks it safely. Like **negative testing** in a QA pipeline.

## Conversation & state

**Agent state** (`graph.py:44`)
The `AgentState` TypedDict carried between graph nodes — intent, urgency, confidence, draft reply, critic decision, revision count, etc.

**`thread_id`** / **`conversation_id`** — the key under which conversation state is stored and resumed. Like a **correlation ID** or **ticket ID** threading through a support case.

## Production boundary (prototype vs production-grade)

Items marked "Fix at 100x" in `docs/08-weaknesses-and-next-steps.md` are intentional prototype-grade choices: in-memory checkpointer, SQL `ILIKE` keyword search (no vector RAG), single monolith, no auth beyond the `X-Customer-Id` header, no rate limiting beyond the per-process limiter. They are **documented limitations**, not bugs — the system is designed to be explained in an interview, not deployed to real customers today.

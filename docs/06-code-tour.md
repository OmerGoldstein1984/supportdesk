# SupportDesk — code tour

The five files to open first in an interview, and what to say about each.

## 1. `src/supportdesk/graph.py` — the supervisor graph (open first)

**What it is:** The LangGraph `StateGraph` that wires the whole system together:
Router → specialist → Critic → reply, with checkpointed state and the
human-in-the-loop interrupt for refunds above the limit.

**What to point at:**
- `AgentState` — the shared, checkpointed conversation state (intent, urgency,
  confidence, draft reply, critic decision, approval payload, escalation flag).
- `router_node` / `specialist_node` / `critic_node` / `human_approval_node` /
  `reply_node` / `escalation_node` — the six nodes.
- `route_after_router` / `route_after_specialist` / `route_after_critic` — the
  conditional edges that implement fallbacks (low confidence → escalation,
  refund approval → human interrupt, Critic revise/reject → specialist /
  escalation).
- `run()` / `resume()` — start a conversation and resume a paused approval via
  `Command(resume=...)`.
- `graph = _builder.compile(checkpointer=_checkpointer)` — `InMemorySaver`
  keyed by `conversation_id` (`thread_id`).

**Say:** "This is the heartbeat. Every customer message flows through this graph,
and every safety decision — escalate, approve, reject — is a conditional edge
here, not buried in an LLM prompt."

---

## 2. `src/supportdesk/tool_gate.py` — plain-code tool gate (security)

**What it is:** The deterministic middleware that enforces (1) per-agent
allowlists, (2) Pydantic v2 schema validation, (3) customer scoping, and (4) the
refund risk policy.

**What to point at:**
- `ALLOWLISTS` — `router`/`critic` have empty sets; `billing`/`technical`/
  `account`/`escalation` each have exactly their three/two tools.
- `SCHEMAS` — the Pydantic v2 args schema per tool.
- `ToolGate.validate()` — runs allowlist → schema → risk policy in order.
- `issue_refund` risk policy: amount above `refund_auto_approve_threshold`
  returns `requires_approval=True` instead of executing silently.
- `tool_gate` — the module-level singleton all tools share.

**Say:** "No customer can reach another customer's data, and a billing agent can
never call a technical tool — this is enforced in plain Python, not by asking
the LLM nicely."

---

## 3. `src/supportdesk/agents/base.py` — router, critic, specialist loop

**What it is:** The three non-tool agents and the specialist ReAct loop.

**What to point at:**
- `route_message()` — Router: structured output (intent, urgency, confidence,
  reasoning) via `llm.structured(RouterOutput)`. No tools.
- `critique()` — Critic: approve / revise / reject via structured output. No
  tools.
- `run_specialist()` — the explicit ReAct loop: LLM picks a tool, we execute it
  through the gate, feed the result back, repeat until the LLM gives a final
  answer. Returns the draft plus any `APPROVAL_REQUIRED` signal.
- `SpecialistResult` — `draft` + `approval_signal`.

**Say:** "The Router and Critic use structured output so their decisions are
typed and testable. The specialist loop is hand-written so we control exactly
when the tool gate runs and when we pause for human approval."

---

## 4. `src/supportdesk/tools/base.py` + `src/supportdesk/tools/billing.py`

**What it is:** How every LangChain tool is built and executed through the gate.

**What to point at:**
- `ToolContext` — current customer, conversation, session factory (bound into
  each tool via closure).
- `execute()` — calls `tool_gate.validate(...)`, returns `BLOCKED:` /
  `APPROVAL_REQUIRED:` markers, otherwise runs the tool through a repository.
- `make_billing_tools()` — `get_invoice`, `issue_refund`, `change_plan`, each
  with `@tool(args_schema=...)` and a Pydantic v2 args schema.
- `APPROVAL_REQUIRED_PREFIX` — the marker (`APPROVAL_REQUIRED:`) that pauses
  the graph for human approval.

**Say:** "Every tool is a small function with a typed schema. Before it runs, the
gate checks the agent's allowlist, validates the schema, and enforces the refund
risk policy. Tools only ever touch the current customer's rows."

---

## 5. `src/supportdesk/main.py` — FastAPI API

**What it is:** The three HTTP endpoints: `POST /chat`, `POST /approve`,
`GET /trace/{conversation_id}`.

**What to point at:**
- `/chat` — runs the graph, returns `complete` or `awaiting_approval` plus the
  interrupt payload (invoice, amount) when a human decision is needed.
- `/approve` — resumes a paused approval with `Command(resume=...)`.
- `/trace` — inspects conversation state for the demo/interview.

**Say:** "Three endpoints. Chat starts or continues a conversation. Approve
resumes a human-in-the-loop decision. Trace lets an interviewer inspect the
internal state without exposing message text in logs."

---

## Bonus: where everything else lives

| File | Role |
|------|------|
| `src/supportdesk/config.py` | Env-based settings (Pydantic Settings) |
| `src/supportdesk/database.py` | SQLAlchemy engine/session, `init_db()` |
| `src/supportdesk/models.py` | SQLAlchemy models (Customer, Invoice, Plan, Ticket, Article, …) |
| `src/supportdesk/repositories.py` | Customer-scoped repository layer |
| `src/supportdesk/security.py` | Prompt-injection defense + PII redaction |
| `src/supportdesk/llm.py` | ChatNVIDIA with retry + model fallback |
| `src/supportdesk/graph.py` | Supervisor graph (see #1) |
| `src/supportdesk/agents/` | Router, Critic, specialists |
| `src/supportdesk/tools/` | Billing, Technical, Account, Escalation tools |
| `src/supportdesk/main.py` | FastAPI app + endpoints |
| `src/supportdesk/cli.py` | `seed` / `serve` entrypoint |
| `src/supportdesk/scripts/seed_data.py` | Reproducible test-data seed |
| `scripts/entrypoint.sh` | Docker entrypoint (seed then serve) |
| `tests/` | unit / integration / e2e / eval |
| `docs/` | Interview kit (this folder) |

# SupportDesk — architecture walkthrough (learning copy)

This document walks through how a customer message becomes a reply, where state
lives, and where the trust boundaries are. It is written against the
`learn/annotated` code (original logic, teaching comments added) and is meant
to be read alongside the code, not instead of it.

## 1. Mental model (one picture)

```mermaid
flowchart TD
    C[Customer message] -->|POST /chat| R[Router]
    R -->|intent + confidence| S{Confidence >= 0.70?}
    S -->|no| E[Escalation: ticket + notify human]
    S -->|yes| SP[Specialist: billing / technical / account]
    SP -->|needs approval?| HA[Human approval: interrupt]
    HA -->|approve| CR[Critic]
    HA -->|reject| E
    SP -->|no approval| CR
    CR -->|approve| RE[Reply to customer]
    CR -->|revise (< max)| SP
    CR -->|reject / over limit| E
    RE -->|done| C

    subgraph Guard "Tool gate (every tool call)"
        G1[Allowlist] --> G2[Schema validation]
        G2 --> G3[Risk policy: refund threshold]
    end
    SP -.-> Guard
```

## 2. The graph (supervisor)

File: `src/supportdesk/graph.py`

Six nodes run in a LangGraph `StateGraph` with an `InMemorySaver` checkpointer.
Each conversation is a thread identified by `conversation_id` (`thread_id`), so
state and memory persist across turns and across interrupt/resume cycles.

| Node | Role |
|------|------|
| `router` | Classifies intent, urgency, confidence via structured output (Pydantic v2). |
| `specialist` | Runs a bounded ReAct loop over its allowlisted LangChain tools. |
| `human_approval` | `interrupt()` — pauses for a human to approve/reject a large refund. |
| `critic` | Checks the draft for policy, PII leakage, hallucination; approve / revise / reject. |
| `reply` | Emits the final reply (or the escalation case summary). |
| `escalation` | Creates a ticket and notifies a human agent. |

Conditional edges:
- After router: low confidence or `intent == escalation` → escalation; otherwise specialist.
- After specialist: `needs_approval` → human_approval; otherwise critic.
- After critic: `approve` → reply; `revise` (under `max_revisions`) → specialist; otherwise escalation.

## 3. Data flow of one message

1. **Client → `/chat`**: `POST /chat` with `{conversation_id, customer_id, message}`.
2. **authN**: `get_current_customer_id` reads the required `X-Customer-Id` header — this is the authoritative caller identity; the body's `customer_id` is **not** trusted for authorization.
3. **Router**: `sanitize_user_input` redacts PII and blocks prompt-injection patterns; `router_chain` classifies the message.
4. **Specialist**: a ReAct loop picks tools from the specialist's allowlist. Every tool call passes through `ToolGate` (allowlist + Pydantic schema + risk policy). Refunds above `$100` return an `APPROVAL_REQUIRED:…` marker instead of executing.
5. **Human approval (if needed)**: the graph interrupts; the client `POST /approve` with `approve`/`reject` resumes it.
6. **Critic**: reviews the draft; approves, revises (bounded by `max_revisions`), or rejects → escalation.
7. **Reply → client**: the final reply (or case summary) is returned.

## 4. Trust boundaries

| Boundary | What it enforces |
|----------|------------------|
| Client → API | `X-Customer-Id` header is required and authoritative; body `customer_id` is ignored for authZ. |
| API → graph | Authenticated `customer_id` is threaded into the graph state. |
| Specialist → tool gate | Per-agent allowlist; a billing agent can never call a technical tool. |
| Tool gate → repository | Pydantic v2 schema validation; refunds above `$100` require approval. |
| Repository → database | Every customer-scoped read filters by `customer_id` — cross-customer access is denied at the data layer, not just in the LLM. |
| Tool output → LLM | `sanitize_tool_output` redacts PII and re-scans for injection (defense in depth). |

The core idea: **never trust the client body for identity or authorization.** Identity comes from a server-trusted header; authorization is enforced by the repository layer scoping every read to the caller's customer.

## 5. Where state lives

| State | Store | Survives restart? | Shared across replicas? |
|-------|-------|-------------------|-------------------------|
| Conversation graph state | `InMemorySaver` (keyed by `conversation_id`) | No | No |
| Customer / invoice / ticket / article data | SQLite (`supportdesk.db`) or PostgreSQL (docker-compose) | Yes | Yes (Postgres) |
| Validation failure counts | `ToolGate.validation_failures` (in-memory dict) | No | No |

The in-memory checkpointer is the main scalability limit: conversation state is lost on restart and cannot be shared across multiple API replicas. The documented production fix is a Postgres-backed checkpointer (`LangGraph PostgresSaver`).

## 6. What scales and what doesn't

**Scales well:**
- The repository layer is customer-scoped, so data isolation is correct regardless of volume.
- The tool gate is deterministic and has no LLM calls, so it adds negligible latency.
- Seed data is deterministic (fixed random seed) and idempotent.

**Does not scale (documented "prototype-grade" limits):**
- In-memory checkpointer (single instance, no restart survival).
- SQL `ILIKE` keyword search (no vector/semantic retrieval).
- Single FastAPI monolith (router and specialists cannot be scaled independently).
- No rate limiting beyond the per-process in-memory limiter (added in this effort); no distributed limiting.
- No authN beyond the `X-Customer-Id` header stand-in (production would use OAuth2/OIDC + JWT).

These are intentional prototype choices for an interview/demo project, listed in `docs/08-weaknesses-and-next-steps.md` as "Fix at 100x" items.

## 7. Reading guide

Read in this order:
1. `src/supportdesk/graph.py` — the overall flow (annotated with teaching comments).
2. `src/supportdesk/tool_gate.py` — how every tool call is guarded.
3. `src/supportdesk/security.py` — PII redaction and prompt-injection defense.
4. `src/supportdesk/main.py` — the `/chat` and `/approve` endpoints and authN.
5. `src/supportdesk/repositories.py` — customer-scoped data access.

## Glossary (quick)

- **agent state:** the `AgentState` TypedDict carried between graph nodes.
- **checkpointer:** LangGraph component that snapshots conversation state per `thread_id`.
- **human-in-the-loop / interrupt:** LangGraph pauses the graph and waits for a human decision before resuming.
- **ReAct loop:** the specialist's explicit "reason → act → observe" loop over its allowlisted tools.
- **tool gate:** plain-code middleware enforcing allowlist, schema validation, customer scoping, and risk policy.

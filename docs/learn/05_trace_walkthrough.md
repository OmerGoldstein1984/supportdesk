# SupportDesk — trace walkthrough (learning copy)

Trace one real customer request end-to-end through the SupportDesk supervisor graph, with
real values at each node, plus the failure branches. Written against the improved code
(`learn/improved`), which includes the P0-P3 fixes (timezone-aware datetimes, hermetic test
DB, prompt-injection hardening, X-Customer-Id authN, rate limiting, coverage gate).

This is the document to read when you want to see exactly how a message becomes a reply —
and where it can go wrong.

## Scenario: "Refund invoice 120 for $250"

**Customer:** Alice Chen, `customer_id=1`, authenticated via header `X-Customer-Id: 1`  
**Message:** "Refund invoice 120 for $250, I need it back today."  
**Conversation:** `conv-refund-001`  
**Rate limit:** 30 refunds/minute per customer (P1-3) — this is ticket #1, so allowed

---

## Step 1 — POST /chat

**HTTP:** `POST /chat`  
**Body:** `{"conversation_id":"conv-refund-001","customer_id":1,"message":"Refund invoice 120 for $250, I need it back today."}`  
**Header:** `X-Customer-Id: 1`

**main.py:chat()**
- `get_current_customer_id()` reads `X-Customer-Id` → `current_customer_id = 1`  
  (The body's `customer_id` is ignored for authorization — the header is authoritative.)
- `run("conv-refund-001", 1, "Refund invoice 120 for $250, I need it back today.")`
- RateLimitMiddleware allows the request (first call this minute for customer 1)

**Rate limit note:** If Alice had already made 30 refund requests this minute, request #31 would
get `429 Too Many Requests` with `Retry-After: 60` — no graph execution at all.

---

## Step 2 — Router node

**state:** `{conversation_id: "conv-refund-001", customer_id: 1, message: "Refund invoice 120 for $250, I need it back today."}`

**router_node()** calls `route_message(message)`:
1. `sanitize_user_input(message)` — redacts PII (none here), checks prompt-injection patterns (none)
   → clean message unchanged
2. `router_chain.invoke({message: clean, specialists: "billing, technical, account, escalation"})`
   → structured output: `{intent: "billing", urgency: "medium", confidence: 0.9, reasoning: "refund request"}`

**route_after_router:** confidence 0.9 ≥ 0.70 threshold, intent ≠ escalation → route to **specialist**

**state after router:** `{conversation_id: "conv-refund-001", customer_id: 1, message: "...", intent: "billing", urgency: "medium", confidence: 0.9, specialist: "billing", ...}`

---

## Step 3 — Specialist node (billing)

**specialist_node()** builds a `ToolContext(session_scope, customer_id=1, conversation_id="conv-refund-001")` and runs the billing specialist via `run_specialist()`.

The billing specialist's ReAct loop:
1. LLM decides to call `issue_refund(invoice_id=120, amount=250.0)` — matches the customer's request
2. **Tool gate** (`tool_gate.py:execute`):
   - Allowlist: `issue_refund` ∈ billing's allowlist ✓
   - Schema validation: `IssueRefundArgs(invoice_id=120, amount=250.0)` ✓
   - Risk policy: `amount=250.0 > refund_auto_approve_threshold=100.0` → `requires_approval=True`
3. Returns `APPROVAL_REQUIRED:issue_refund|{"invoice_id": 120, "amount": 250.0}|refund amount 250.0 exceeds auto-approve threshold 100.0`
4. Specialist sets `needs_approval=True`, `approval_payload={"invoice_id": 120, "amount": 250.0}`, draft reply

**route_after_specialist:** `needs_approval=True` → route to **human_approval**

**state after specialist:** `{draft_reply: "...", needs_approval: True, approval_payload: {"invoice_id": 120, "amount": 250.0}, revision_count: 0, ...}`

**Important:** The refund is NOT processed yet. The tool gate flagged it for human approval — no money moves until a human approves (P0-1 authN + P1-3 risk policy working together).

---

## Step 4 — Human approval (interrupt)

**human_approval_node()** calls `interrupt({question: "Approve this refund?", invoice_id: 120, amount: 250.0, reason: "refund amount 250.0 exceeds auto-approve threshold 100.0"})`

**The graph PAUSES here.** LangGraph's checkpointer (`InMemorySaver`) saves state keyed by
`thread_id="conv-refund-001"`. The `/chat` HTTP response returns:

```json
{
  "status": "awaiting_approval",
  "conversation_id": "conv-refund-001",
  "interrupt": {
    "question": "Approve this refund?",
    "invoice_id": 120,
    "amount": 250.0,
    "reason": "refund amount 250.0 exceeds auto-approve threshold 100.0"
  }
}
```

The customer sees: "Your refund of $250.00 for invoice #120 requires manager approval. A human will review it."

**Branching point — the human decides:**

| Human action | Resulting path |
|---|---|
| Approve (`{"approve": true, "note": "ok"}`) | Resume → Critic → Reply (refund processed) |
| Reject (`{"approve": false, "note": "denied"}`) | Resume → Critic → Escalation (refund rejected) |

---

## Step 5A — Approve path (happy path)

**POST /approve** with `{"conversation_id": "conv-refund-001", "approve": true, "note": "ok"}`

**resume("conv-refund-001", ApprovalDecision(approve=True, note="ok"))**
- `graph.invoke(Command(resume={"approve": True, "note": "ok"}), thread_id="conv-refund-001")`
- Graph resumes at `human_approval_node`, which was interrupted
- `decision = {"approve": True, "note": "ok"}` → `approve=True`
- Sets `approved=True, needs_approval=False`, draft_reply = "Refund of $250.00 for invoice #120 approved and processed. Note: ok"

**Critic node:** reviews draft → `CriticOutput(decision="approve", reason="ok", suggested_fix="")`

**route_after_critic:** decision="approve" → route to **reply**

**reply_node:** `final_reply = "Refund of $250.00 for invoice #120 approved and processed. Note: ok"`

**HTTP response:** `{"status": "complete", "conversation_id": "conv-refund-001", "final_reply": "Refund of $250.00 for invoice #120 approved and processed. Note: ok", "intent": "billing"}`

---

## Step 5B — Reject path

**POST /approve** with `{"conversation_id": "conv-refund-001", "approve": false, "note": "denied"}`

**resume("conv-refund-001", ApprovalDecision(approve=False, note="denied"))**
- `approved=False, needs_approval=False, escalation=True`
- `case_summary = "Refund rejected by human: denied"`, `draft_reply = "Refund rejected: denied"`

**Critic node:** reviews draft → `CriticOutput(decision="approve", reason="ok", suggested_fix="")`

**route_after_critic:** decision="approve" → route to **reply**

**reply_node:** `final_reply = "Refund rejected by human: denied"` (escalation is True, so case_summary is used)

**HTTP response:** `{"status": "complete", ..., "final_reply": "Refund rejected by human: denied"}`

---

## Failure branches

| Failure | Where | What happens |
|---|---|---|
| Prompt injection in message | router_node | `sanitize_user_input` raises `InjectionBlocked` → router catches → confidence=0.0, intent=escalation → customer gets safe refusal, no tool called |
| Refund amount ≤ $100 | specialist_tool_gate | `requires_approval=False` → refund auto-processes, no human approval needed |
| Refund amount > $100 | specialist_tool_gate | `requires_approval=True` → graph pauses at human_approval (this scenario) |
| Critic rejects draft | critic_node | decision="reject" → route_after_critic → escalation → human agent ticket created |
| Critic revises > max_revisions (1) | critic_node | Second "revise" → route_after_critic → escalation (loop bounded) |
| Router confidence < 0.70 | router_node | confidence below threshold → escalation (safe default, no guess) |
| Router throws exception | router_node | Caught by `except Exception` → confidence=0.0, intent=escalation → customer escalated |
| Specialist tool throws | specialist_node | **No try/except** — exception propagates and crashes the graph invocation (agent safety gap) |
| Escalation tools fail | escalation_node | Caught by `try/except` → graceful fallback message, customer still gets a reply |
| LLM never stops calling tools | specialist_node | Hard stop at `max_tool_steps=5` → returns last content (possibly blank/incoherent) |
| In-memory checkpointer restart | graph.py | Conversation state lost — `conv-refund-001` mid-approval is forgotten on redeploy |

---

## Key takeaways for an FDE interview

1. **No money moves without human approval.** Refunds above $100 pause at `human_approval_node` and require an explicit `POST /approve` with `approve=true`. The graph persists state via `InMemorySaver` keyed by `thread_id` so the approval can arrive later.

2. **Customer_id is server-trusted, never client-trusted.** The `X-Customer-Id` header is the authoritative identity; the body's `customer_id` is ignored for authorization. The repository layer enforces customer-scoped reads — a billing specialist can never read another customer's invoice.

3. **Every escape hatch leads to a human.** Low router confidence, critic rejection, max revisions exceeded, tool gate block — all route to Escalation, which creates a ticket and notifies a human agent.

4. **The graph is the source of truth for conversation state.** `run()` starts a thread; `resume()` injects a human decision back into a paused thread via `Command(resume=...)`. All state (intent, draft, approval payload, revision count) lives in `AgentState` carried between nodes.

5. **Known limitations (documented in docs/08):** In-memory checkpointer (state lost on restart), SQL `ILIKE` keyword search (no vector RAG), single monolith, no auth beyond the `X-Customer-Id` header stand-in, rate limiting is per-process in-memory (not Redis-distributed). These are intentional prototype choices for an interview demo.

---

## Reading guide

Read this walkthrough alongside:
- `src/supportdesk/graph.py` — annotated with teaching comments on every node and edge
- `src/supportdesk/tool_gate.py` — annotated with the allowlist/schema/risk-policy gate
- `src/supportdesk/security.py` — annotated with prompt-injection + PII redaction
- `src/supportdesk/repositories.py` — annotated with customer-scoped data access
- `docs/learn/02_architecture.md` — data flow, trust boundaries, where state lives
- `docs/learn/03_glossary.md` — every term, library, pattern with file:line

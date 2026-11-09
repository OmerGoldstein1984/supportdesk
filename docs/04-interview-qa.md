# SupportDesk — interview Q&A

30 likely interview questions with short, model answers. The six questions marked
★ are the ones interviewers ask most about this project.

## Routing & tool selection

**1. ★ How do you know it picks the right tool?**
The Router classifies intent into one of four specialists (billing / technical /
account / escalation) using structured Pydantic output. Each specialist has a
strict, plain-code **tool allowlist**: e.g. billing may only call `get_invoice`,
`issue_refund`, and `change_plan`. The `ToolGate` validates every call against
the allowlist and the tool's Pydantic v2 schema before anything runs. We measure
this empirically: the eval harness runs a 150-ticket labeled corpus and reports
tool-selection accuracy against a committed baseline, and CI fails if it drops.

**2. What tools can each agent call?**
- Billing: `get_invoice`, `issue_refund`, `change_plan`
- Technical: `search_knowledge_base`, `get_service_status`, `create_bug_ticket`
- Account: `lookup_user`, `send_password_reset`
- Escalation: `create_ticket`, `notify_human_agent`
Router and Critic have no tools.

**3. Can a billing agent call a technical tool?**
No. The tool gate enforces a per-agent allowlist in plain code, so `billing`
calling `search_knowledge_base` is rejected before it reaches the database. There
is a unit test asserting exactly this.

## Testing non-determinism

**4. ★ How do you test non-deterministic agents?**
Two layers:
- **Deterministic tests** (unit / integration / e2e) use a fake LLM so every code
  path — routing, tool gate, fallback, interrupt/resume — is reproducible.
- **Evals** run the labeled ticket corpus through a deterministic fake LLM and
  report routing accuracy and tool-selection accuracy against a committed
  baseline; CI fails if accuracy drops more than 5 points. A small live-LLM smoke
  suite runs against the NVIDIA Build API on demand / nightly, never on every
  commit.

**5. How do you handle failures?**
Three fallback paths all route to Escalation with a full case summary:
- Router confidence below threshold → escalation.
- Two failed tool validations → escalation.
- Critic rejection after one revision → escalation.
Plus refunds above the threshold pause for human approval (approve / edit /
reject via LangGraph `interrupt` + checkpointer).

## Prompt injection & security

**6. ★ How do you prevent prompt injection?**
Two plain-code checks (no LLM): user messages and tool outputs are scanned for
injection patterns ("ignore previous instructions", "you are now a...",
"reveal the system prompt", jailbreak, override safety...). A match raises
`InjectionBlocked` and the request is refused/escalated. PII (emails, phones,
cards, SSNs) is redacted before logging and before text reaches the LLM.

**7. Can a customer see another customer's data?**
No. Repositories are scoped by `customer_id`: every read filters by the
requesting customer, and foreign keys enforce ownership. A unit test asserts
cross-customer access returns nothing.

**8. Where are secrets kept?**
Environment variables only (NVIDIA API key, database URL, thresholds). `.env`
is gitignored; `.env.example` is provided. Nothing secret is committed.

## LangChain

**9. ★ Why LangChain, and what are its trade-offs?**
- **Why:** Fast to assemble agents, tools, structured output, and a LangGraph
  state machine; good ecosystem (ChatNVIDIA, `with_structured_output`,
  `@tool`).
- **Trade-offs:** Abstractions can hide control flow (mitigated by our explicit
  ReAct loop and plain-code gate), version churn between 0.2/0.3 (we pin
  versions and verified every API against the docs), and it's heavier than
  hand-rolling for a tiny system. For this project the development speed and
  interview recognizability outweigh the cost.

## Scale & operations

**10. ★ What would you change at 100x scale?**
- Swap `InMemorySaver` for Postgres checkpointers (multi-instance, durable).
- Move RAG from SQL `ILIKE` to a real vector store with citations.
- Add rate limiting, per-customer quotas, and authN/authZ.
- Replace `ChatNVIDIA` retry/fallback hand-roll with a battle-tested client and
  circuit breaker; add distributed tracing.
- Break the monolith into per-agent services behind the FastAPI gateway.

## Logistics

**11. How do you run it locally?**
```
cp .env.example .env   # add NVIDIA_API_KEY
pip install -e ".[dev]"
python -m supportdesk.cli seed
python -m supportdesk.cli serve
```
Or `docker compose up --build` (seeds idempotently on startup, then serves).

**12. What's the stack?**
Python 3.12, LangChain v1 + LangGraph, FastAPI, Pydantic v2, SQLAlchemy,
SQLite (local) / Postgres (compose), NVIDIA Build API via ChatNVIDIA, pytest,
ruff, mypy, Docker, GitHub Actions CI.

**13. How do you seed data?**
One command: `python -m supportdesk.cli seed`. Fixed random seed → identical
data every run: 200 customers, 600 invoices, 5 plans, 150 labeled tickets,
50 KB articles (some outdated/conflicting), scripted service incidents, and an
adversarial set. No real personal data.

## Reliability

**14. What happens if the LLM is unavailable?**
`ChatNVIDIA` has retry with exponential backoff, and if the primary model is
exhausted it falls back to a configurable fallback model. If both fail, the
error is caught and the conversation is escalated rather than crashing.

**15. How do you handle a refund above the limit?**
The tool gate flags `issue_refund` over `refund_auto_approve_threshold` as
`APPROVAL_REQUIRED`. The graph pauses at `interrupt()`, returns `{invoice_id,
amount, reason}` to the caller, and waits on `POST /approve` with
`{approve: true/false, note}`. Approval executes the refund; rejection
escalates.

**16. Is every reply reviewed before it's sent?**
Yes — the Critic agent reviews every draft for policy, PII leakage, and
hallucination, and can approve, revise (once), or reject (escalate).

## Data

**17. Is there real customer data?**
No. All data is synthetic with a fixed seed (emails are `@example.com`). The
adversarial set contains no real PII — only clearly-marked test patterns.

**18. What's in the knowledge base?**
40–60 articles across setup, errors, billing FAQ, and security — including some
deliberately outdated or conflicting articles so the system can be tested against
retrieval quality.

## Observability

**19. How do you see what happened in a conversation?**
`GET /trace/{conversation_id}` returns the graph state (intent, urgency,
confidence, specialist, critic decision, approval state, final reply) without
the raw message text. Logs are structured JSON with PII redacted.

**20. How do you track cost and latency?**
The eval harness reports per-run routing/tool accuracy; latency and token cost
are tracked per agent via the LLM wrapper and can be emitted to the structured
logs.

## The graph

**21. How does the supervisor graph work?**
A single LangGraph `StateGraph`: Router → specialist → Critic → reply, with
checkpointed state. Conditional edges handle low confidence (→ escalation),
refund approval (→ human interrupt → approve/reject), Critic revise (→
specialist, once), and Critic reject (→ escalation).

**22. Is conversation memory shared?**
Yes — one `InMemorySaver` checkpointer serves all threads, keyed by
`conversation_id` (`thread_id`), so state persists across turns and interrupt/
resume cycles.

## Deployment

**23. How do you run it with Docker?**
`docker compose up --build`. The entrypoint seeds idempotently on startup, then
serves the FastAPI app on port 8000 (SQLite locally, Postgres via the `db`
service).

**24. What does CI run?**
Lint (ruff), types (mypy strict), unit + integration tests with a fake LLM and
SQLite, coverage report, and the eval gate on a sample of the corpus.

## Honest limitations

**25. What are the main limitations?**
See `docs/08-weaknesses-and-next-steps.md`. In short: SQL `ILIKE` RAG instead of
a vector store, no auth beyond customer-ID scoping, in-memory checkpointer, and
a hand-rolled ReAct loop rather than a prebuilt agent constructor — all known
and documented trade-offs.

**26. How does the system behave when it's unsure?**
It escalates to a human with a case summary rather than guessing — low router
confidence, failed tool validations, and critic rejection all escalate.

**27. Can the Critic block a reply?**
Yes. The Critic can approve, revise once (then re-send), or reject (escalate to
a human). No draft is sent without Critic approval.

**28. Do tools run against a real database?**
Yes — SQLAlchemy repositories against SQLite locally and Postgres in
docker-compose; nothing is hardcoded or mocked in the running system.

**29. How is the seed data generated?**
A seed script with a fixed random seed produces 200 customers, 600 invoices
(paid / overdue / disputed), 5 plans, subscription history, payment failures,
account states, 150+ labeled tickets, 50 KB articles, scripted incidents, and an
adversarial set. It's idempotent and one command.

**30. What would you change at 100x scale?**
(See question 10.) Postgres checkpointers, vector-store RAG, rate limiting,
circuit breakers, distributed tracing, and per-agent services.

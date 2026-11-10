# SupportDesk — Business Context (Learning Copy)

**Customer:** A mid-size SaaS or telecom/eSIM provider with a growing customer base
needing a multi-agent customer-support system. Customers contact support via chat for
invoices, refunds, plan changes, password resets, knowledge-base questions, and bug
reports.

**Pain:** As the customer base grows, a small human support team can't handle volume.
Customers wait hours for responses. Refunds above a threshold need manager approval,
creating delays. Agents inconsistently apply policy — some over-promise, some leak
PII, some hallucinate KB facts. There's no consistent audit trail of tool calls.
The company needs an AI-powered support system that is fast, consistent, safe, and
explainable — suitable for an FDE interview demo.

**Cost of failure:**
- **Refund above limit without approval:** financial loss, compliance violation
- **PII leakage in a reply:** GDPR/privacy incident, customer trust damage
- **Hallucinated policy:** customer charged incorrectly, chargeback, churn
- **Cross-customer data access:** catastrophic trust breach, regulatory exposure
- **Slow response:** churn, poor CSAT, support queue backlog

**Success metrics:**
- Routing accuracy: customer's issue reaches the correct specialist ≥90% of the time
- Tool selection accuracy: the correct tool is invoked ≥90% of the time
- Refunds above $100 always require human approval (0 unauthorized auto-refunds)
- Zero PII leaks in LLM prompts, tool outputs, or logs
- Eval regression: routing/tool-selection accuracy does not drop more than 5 points
  vs committed baseline on CI

**Who the user (FDE) is:**
A Forward Deployed Engineer — an AI Solutions Engineer with a telecom/eSIM, IoT
connectivity background. 10 years of QA, CI/CD, test frameworks. Strong in
Python/JS basics, REST/SOAP APIs, n8n, S3/Athena, event pipelines, idempotency,
Docker, FastAPI, RAG basics, prompt engineering. Weak/unproven in production
architecture patterns, concurrency/async, auth and multi-tenancy, observability,
evals, deployment, cost/latency tradeoffs, customer-facing communication.

**What the FDE needs to explain:**
- How the supervisor graph routes and escalates
- How the tool gate enforces allowlists and risk policy
- How customer scoping prevents cross-customer data access
- How prompt injection and PII are defended
- How human-in-the-loop refund approval works
- How evals guard against regression
- What is prototype-grade vs production-grade (docs/08-weaknesses-and-next-steps.md)

**System boundaries (what is in / out of scope):**
In scope: chat-based support, tool-assisted agents, human-in-the-loop refunds,
eval regression gate, PII redaction, prompt-injection defense, customer-scoped data
access, SQLite/Postgres support, Docker + CI.

Out of scope (prototype-grade, "fix at 100x"): in-memory checkpointer (no
multi-instance durability), SQL ILIKE keyword search (no vector RAG), single
monolith (no per-agent scaling), hand-rolled ReAct (not prebuilt LangGraph agents),
hand-rolled LLM retry/fallback (no circuit breaker), no real frontend, no auth
beyond client-supplied customer_id (this project uses an X-Customer-Id header
stand-in), no rate limiting beyond per-process in-memory limiter.

**Key analogy for the FDE:**
Think of SupportDesk as an AI-powered support desk that works like a well-run
telecom NOC: a router triages incoming tickets to the right team, specialists have
restricted tool belts (allowlists), a QA reviewer (Critic) checks every reply before
it goes to the customer, and refunds above $100 need manager approval (human-in-the-loop).
Everything is observable (structured JSON logs, /trace endpoint), and quality is
guarded by a committed eval baseline (CI regression gate).
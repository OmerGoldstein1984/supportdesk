# SupportDesk

Production-grade multi-agent customer support system built with **LangChain v1 + LangGraph**, **FastAPI**, **Pydantic v2**, and **SQLAlchemy**. Designed as a portfolio project you can fully explain in an AI Solutions / FDE interview.

---

## 🎯 What is SupportDesk?

SupportDesk is a **supervisor-graph multi-agent system** that routes customer messages to the right specialist, executes tool calls through a plain-code gate, checks every reply with a critic agent, and escalates when human approval is needed.

It's designed to be **explainable** — every decision point is explicit, every tool call is gated, and every reply is critiqued before reaching the customer.

---

## 🏗️ Architecture

### The Supervisor Graph

```
Customer Message
       │
       ▼
┌──────────────┐
│   ROUTER     │──► Classifies intent/urgency/confidence
│              │   (structured output, no tools)
└──────────────┘
       │
    low confidence?
       │ Yes
       ▼
┌──────────────┐
│ ESCALATION   │──► Creates ticket + notifies human agent
└──────────────┘
       │
    No
       ▼
┌──────────────┐
│ SPECIALIST   │──► ReAct loop over allowlisted tools
│ (billing/    │   • billing: get_invoice, issue_refund, change_plan
│  technical/  │   • technical: search_kb, service_status, create_bug_ticket
│  account)    │   • account: lookup_user, send_password_reset
└──────────────┘
       │
       ▼
┌──────────────┐
│   CRITIC     │──► Approve / Revise / Reject draft reply
└──────────────┘
       │
       ▼
┌──────────────┐
│   REPLY      │──► Send final reply to customer
└──────────────┘
```

### The Six Agents

| Agent | Role | Tools |
|-------|------|-------|
| **Router** | Classifies intent, urgency, confidence | none (structured output only) |
| **Billing** | Invoices, refunds, plan changes | `get_invoice`, `issue_refund`, `change_plan` |
| **Technical** | KB search, service status, bug tickets | `search_knowledge_base`, `get_service_status`, `create_bug_ticket` |
| **Account** | User lookup, password reset | `lookup_user`, `send_password_reset` |
| **Escalation** | Tickets, human notification | `create_ticket`, `notify_human_agent` |
| **Critic** | Policy, PII, hallucination check on every draft | none |

---

## 🛡️ Safety First

### Plain-Code Tool Gate

Every tool call passes through a deterministic gate (no LLM involved) that enforces:

1. **Per-agent allowlist** — a billing agent can never call a technical tool
2. **Schema validation** — arguments validated against Pydantic v2 schemas
3. **Customer scoping** — every read/write is scoped by `customer_id` at the repository layer
4. **Risk policy** — refunds above `$100` require human approval (not silently executed)

### Human-in-the-Loop

Refunds above the auto-approve threshold pause the graph with `interrupt()`. A human must approve or reject via `POST /approve` before execution continues.

### Prompt-Injection Defense & PII Redaction

User input and tool outputs are scanned for instruction-hijack patterns (e.g., "ignore previous instructions"). PII (emails, phones, cards, SSNs) is redacted before reaching any LLM prompt or log.

---

## 🚀 Quick Start

### One Command

```bash
# 1. Clone and configure
git clone <this-repo> && cd SupportDesk
cp .env.example .env   # add your NVIDIA_API_KEY

# 2. Install and seed (one command seeds reproducible test data)
pip install -e ".[dev]"
python -m supportdesk.cli seed

# 3. Run the API
python -m supportdesk.cli serve   # or: uvicorn supportdesk.main:app --reload

# 4. Run tests
pytest -m "unit or integration" -q
```

### Or with Docker

```bash
# 1. Configure (copy the example file and add your NVIDIA_API_KEY)
cp .env.example .env

# 2. Build and run — the app seeds idempotently on startup, then serves on http://localhost:8000
docker compose up --build
```

Stop with `docker compose down`. The `app` service waits for the healthy Postgres database before starting, and seeds idempotently on every startup, so re-running is safe.

---

## 🧪 Test Markers

| Marker | Description |
|--------|-------------|
| `unit` | Fast, no network, fake LLM |
| `integration` | Agents + tools + real database + FastAPI TestClient |
| `e2e` | Full HTTP scenarios against `docker compose up` |
| `eval` | Labeled ticket corpus, routing/tool accuracy, LLM-as-judge |

```bash
pytest -m "unit or integration" -q   # unit + integration
pytest -m "eval" -q                  # eval reports (CI gate)
```

---

## 📊 Eval Baseline

The eval harness runs a labeled ticket corpus through a deterministic fake LLM and reports routing accuracy and tool-selection accuracy. CI fails if accuracy drops more than 5 points vs. the committed baseline:

| Metric | Baseline |
|--------|----------|
| Routing accuracy | 74% |
| Tool-selection accuracy | ~41% |

---

## 📁 Project Structure

```
SupportDesk/
├── src/supportdesk/
│   ├── main.py              # FastAPI app: /chat, /approve, /trace
│   ├── graph.py             # Supervisor graph: Router → specialist → Critic → reply
│   ├── cli.py               # CLI entrypoint: seed | serve
│   ├── config.py            # Environment-based configuration (pydantic-settings)
│   ├── database.py          # SQLAlchemy engine, session, declarative base
│   ├── logging.py           # Structured JSON logging with PII redaction
│   ├── llm.py               # LLM provider: ChatNVIDIA with retry + fallback
│   ├── security.py          # Prompt-injection defense + PII redaction
│   ├── tool_gate.py         # Plain-code tool gate: allowlist + schema + risk policy
│   ├── agents/              # Router, Critic, Specialist agents
│   ├── tools/               # Billing, technical, account, escalation tools
│   ├── evals/               # Eval harness + CLI
│   └── scripts/             # Seed data script
├── tests/
│   ├── unit/                # Fast, no network, fake LLM
│   ├── integration/         # Agents + tools + real DB + FastAPI TestClient
│   └── eval/                # Labeled ticket corpus evaluation
├── data/                    # Synthetic test data + eval baseline
├── docs/learn/              # Interview prep: architecture, glossary, trace walkthrough
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## 🏗️ Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Plain-code tool gate** | No LLM middleware — deterministic, controllable, interview-explainable |
| **InMemorySaver checkpointer** | Simple checkpointed state; swap to PostgresSaver for production |
| **Structured output (Pydantic)** | Router and Critic return typed schemas, not free text |
| **Manual ReAct loop** | Full control over tool gate and interrupt, unlike prebuilt AgentExecutor |
| **Fake LLM in tests** | Deterministic, no network, stable CI |

---

## 📚 Learn More

See `docs/learn/` for interview-focused documentation:

| Doc | Description |
|-----|-------------|
| `00_START_HERE.md` | Reading guide, study order, mental map |
| `01_business_context.md` | Customer, pain, cost of failure, success metrics |
| `02_architecture.md` | Supervisor graph walkthrough, data flow, trust boundaries |
| `03_glossary.md` | Every term, library, pattern with file:line + analogy |
| `04_gap_bridge.md` | Web app way vs production way, and why |
| `05_trace_walkthrough.md` | One real request traced end-to-end with real values |
| `06_interview_pack.md` | 25+ interview questions with model answers |

---

## 🛡️ Security

- **Prompt-injection defense** on user input and tool outputs
- **PII redaction** in logs, tool outputs, and LLM prompts
- **Per-agent tool allowlists** — cross-agent tool access denied
- **Cross-customer data access denied** at the repository layer
- **No secrets in code** — config via environment variables
- **Refunds above $100 require human approval**

---

## 📄 License

MIT

---

**SupportDesk** — a production-grade multi-agent customer support system, designed to be explained in an interview.
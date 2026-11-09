# SupportDesk

Production-grade multi-agent customer support system built with **LangChain v1** and **LangGraph**, FastAPI, Pydantic v2, and SQLAlchemy. Designed as a portfolio project you can fully explain in an AI Solutions / FDE interview.

## Architecture (6 agents)

| Agent | Role | Tools |
|-------|------|-------|
| Router | Classifies intent, urgency, confidence (structured output) | none |
| Billing | Invoices, refunds, plan changes | `get_invoice`, `issue_refund`, `change_plan` |
| Technical | Knowledge base, service status, bug tickets | `search_knowledge_base`, `get_service_status`, `create_bug_ticket` |
| Account | User lookup, password reset | `lookup_user`, `send_password_reset` |
| Escalation | Tickets, human notification | `create_ticket`, `notify_human_agent` |
| Critic | Policy, PII, hallucination check on every draft | none |

A plain-code **tool gate** (schema validation, per-agent allowlist, permission check, risk policy) guards every tool call. Refunds above a configurable threshold use **LangGraph human-in-the-loop** (`interrupt` + checkpointer) so a human can approve, edit, or reject before execution. A **supervisor graph** routes Router → specialist → Critic → reply, with checkpointed state and shared conversation memory. Low router confidence, repeated tool-validation failures, or critic rejection after one revision all fall back to Escalation with a full case summary.

## Stack

- Python 3.12 (runs on 3.11+)
- LangChain v1 + LangGraph
- FastAPI, Pydantic v2, SQLAlchemy
- SQLite (local) / PostgreSQL (docker-compose)
- NVIDIA Build API via `ChatNVIDIA` (model configurable via env, with retry/fallback middleware)
- pytest, ruff, mypy, Docker, GitHub Actions CI

## Quickstart (one command)

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
pytest -q
```

Or with Docker (runs the full system):

```bash
docker compose up --build
```

The app seeds idempotently on startup, then serves on `http://localhost:8000`.

## Test markers

- `unit` — fast, no network, fake LLM
- `integration` — agents + tools + real database + FastAPI TestClient
- `e2e` — full HTTP scenarios against `docker compose up`
- `eval` — labeled ticket corpus, routing/tool accuracy, LLM-as-judge

```bash
pytest -m "unit or integration" -q        # unit + integration
pytest -m "e2e" -q                        # e2e (requires running server)
pytest -m "eval" -q                       # eval reports
```

## Interview docs

See `docs/` for the interview kit: `01-explain-it-simply.md` through `08-weaknesses-and-next-steps.md`, including a 5-minute demo script and model Q&A.

## Security

- Prompt-injection defense on user input and tool outputs
- PII redaction in logs
- Per-agent tool allowlists; cross-customer data access denied by repository layer
- No secrets in code; config via environment variables

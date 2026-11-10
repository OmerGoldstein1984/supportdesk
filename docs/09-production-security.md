# SupportDesk — production security

How the system is secured today, where it is prototype-grade, and what must
change before it runs real customer traffic. Written for a small team / solo
developer — not a big company with dedicated infra. Every control below maps to
code you can point at, and every gap is honest about what it needs.

SupportDesk is **defense-in-depth by design**: no single control is trusted,
every tool call is gated in plain code, and no secrets live in the image.

---

## What works now (no extra infrastructure)

These are implemented and work in production as-is:

### Rate limiting & abuse protection (`src/supportdesk/main.py`)
A `RateLimitMiddleware` guards `POST /chat` — keyed by `X-Customer-Id`,
defaults to 30 requests per 60-second window, returns `429 + Retry-After`.
If you set `REDIS_URL`, it uses a shared Redis sliding-window counter across
replicas; without Redis it falls back to an in-memory per-process window (single
instance, good for a small deployment).

```python
RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "30"))
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))
```

### Plain-code tool gate (`src/supportdesk/tool_gate.py`)
Every tool call passes through a deterministic gate — no LLM decides what runs:
- Per-agent allowlist (billing can't call technical tools)
- Pydantic v2 schema validation
- Customer scoping (repository layer only returns that customer's data)
- Risk policy (refunds above $100 require human approval)
- Append-only audit log of every gate decision

### Prompt-injection defense & PII redaction (`src/supportdesk/security.py`)
User input and tool outputs are scanned for instruction-hijack patterns and
PII (emails, phones, cards, SSNs → `[EMAIL]`, `[PHONE]`, `[CARD]`, `[SSN]`)
before reaching any LLM prompt or log. Detector uses Unicode NFKC normalization
so obfuscated (fullwidth/zero-width) attempts collapse to matchable signatures.

### Human-in-the-loop refund approvals (`POST /approve`)
Refunds above $100 pause the graph with LangGraph `interrupt()`. A human must
`POST /approve` before execution continues. The approval endpoint is idempotent
(re-calling it returns the cached decision instead of re-resuming the graph).

### Container & runtime hardening (`Dockerfile`, `docker-compose.yml`)
- `python:3.12-slim`, no pip cache, dependency layer cached separately
- Runs as non-root user `supportdesk`
- CPU/memory limits (1 CPU, 1 GB), `restart: unless-stopped`
- App + database healthchecks; app waits on `service_healthy`
- `.dockerignore` keeps `.env`, `*.db`, caches, `.git` out of the image

### CI/CD gates (`.github/workflows/ci.yml`)
Lint (ruff), types (mypy), unit + integration tests with 85% coverage gate, and
an eval regression gate on every push/PR. Dependabot is configured for dependency
updates.

### Observability & audit logging (`src/supportdesk/logging.py`)
Structured JSON logging via structlog with PII redacted from every log value.
Events correlated by `conversation_id` / `customer_id`. `GET /trace/{id}`
exposes conversation state.

---

## What's deferred (needs infrastructure you may not have)

These are honest gaps — not bugs, but infrastructure choices you make when
you're ready:

### Authentication & identity (`X-Customer-Id` header)
**Deferred.** `get_current_customer_id` resolves identity from the
`X-Customer-Id` header — it's authoritative, but it's a placeholder, not real
auth. The request body's `customer_id` is never trusted.

Open source options when you're ready: **Keycloak**, **Authentik**, **Ory
Kratos**, **Dex**, **Authelia**, **SuperTokens**.

### Secrets & configuration (`src/supportdesk/config.py`)
**Deferred.** All settings come from environment variables (`.env` is gitignored;
no secrets in code). `nvidia_api_key` fails loudly at startup in production if
missing. No secret manager integration yet.

Open source options: **HashiCorp Vault**, **SOPS** (encrypted files), **Doppler**.

### Database / durable state
**Deferred beyond SQLite.** Locally the app uses SQLite; `docker-compose.yml`
uses Postgres (`postgres:15-alpine`). Every read/write is scoped by
`customer_id` at the repository layer — cross-customer data access is denied.

**Open source database:** **PostgreSQL** — LangGraph's `PostgresSaver` can
persist conversation state durably across restarts/replicas when you're ready.
Managed options: AWS RDS, Google Cloud SQL, Azure Database for PostgreSQL.

### Observability & audit logging
**Deferred beyond structured JSON logs.** Logs go to stdout (Docker captures
them). Forwarding to a SIEM, alerting on rate-limit trips / tool-gate denials /
approval events — deferred until you choose a destination.

Open source options: **Elastic Stack**, **Grafana Loki + Grafana**, **SigNoz**,
**OpenTelemetry**.

### Image scanning in CI
**Deferred.** Dependabot is configured; image vulnerability scanning (Trivy /
Grype / Clair) is not yet wired into CI.

---

## Production readiness checklist

| Control | Status | What you need to add |
|---------|--------|----------------------|
| Rate limiting | ✅ Implemented | `REDIS_URL` optional; degrades to in-memory |
| Tool gate | ✅ Implemented | Audit log already written |
| Human approval | ✅ Implemented | Durable state needs Postgres checkpointer |
| Prompt injection | ✅ Hardened | NFKC normalization applied |
| Authentication | ❌ Deferred | Pick an OIDC/OIDC provider (Keycloak, Authentik, etc.) |
| Secrets | ❌ Deferred | Pick a secret manager (Vault, SOPS, Doppler) |
| Database | ⚠️ SQLite local / Postgres ready | PostgreSQL for durable, shared state |
| Container | ✅ Implemented | Non-root, limits, healthchecks done |
| Observability | ⚠️ Structured logs only | Forward to SIEM when you choose one |
| CI/CD | ✅ Implemented | Image scanning optional (Trivy/Grype) |

---

## At 100x scale

This is a portfolio project designed to be explained in an interview — not a
service you should deploy to real customers today without addressing the deferred
items above.

The parts that are genuinely production-grade in design: safety (tool
allowlists, customer scoping, refund approval, PII redaction, prompt-injection
defense, no secrets in code), observability (structured logs, `/trace`,
committed eval baseline with a CI regression gate), correctness (85% coverage
gate, mypy strict, ruff clean, deterministic fake-LLM tests), and deployability
(one-command seed, `docker compose up`, GitHub Actions CI).

The parts that remain prototype-grade: in-memory checkpointer, no auth, monolith,
no rate-limiting resilience across replicas, hand-rolled retry/fallback.

**Suggested roadmap, in priority order:**

1. **PostgreSQL checkpointer** — durable, shared conversation state (unlocks
   multi-instance deploys).
2. **AuthN/authZ** — don't trust the client-supplied `customer_id`.
3. **Secret manager** — stop relying on `.env` alone.
4. **Rate limiting resilience** — Redis so the limit is shared across replicas.
5. **Live-LLM eval cadence** — run the smoke suite against the NVIDIA API more
   often; add LLM-as-judge reply-quality scoring.
6. **Observability** — forward logs to a SIEM when you choose one.
7. **Image scanning** — Trivy/Grype in CI.

---

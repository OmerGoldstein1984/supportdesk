# SupportDesk — production security

How the system is secured today, where it is prototype-grade, and what must
change before it runs real customer traffic. Written for an FDE / AI Solutions
interview talk track: every control below maps to code you can point at, and
every gap has a concrete fix.

SupportDesk is **defense-in-depth by design**: no single control is trusted,
every tool call is gated in plain code, and no secrets live in the image.

---

## 1. Rate limiting & abuse protection (`src/supportdesk/main.py:73-110`)

**Status:** Implemented — Redis-backed sliding window with in-memory fallback.

**What exists:** A `RateLimitMiddleware` guards `POST /chat` — the LLM-heavy
endpoint. It is keyed by `X-Customer-Id`, defaults to 30 requests per 60-second
window (overridable via `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` env
vars), and returns `429 + Retry-After` when exceeded.

When `REDIS_URL` is set and reachable, the middleware uses a **Redis
sliding-window counter** shared across all replicas. When Redis is unavailable
or not configured, it falls back to an in-memory fixed window (single replica /
local dev). The Redis client is loaded lazily and degraded gracefully, so the
app starts and passes tests without Redis.

```python
# main.py (RateLimitMiddleware)
RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "30"))
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))
```

Because every chat triggers router + specialist + critic LLM calls, an
unbounded client can run up cost quickly. Rate limiting is the first line of
defense against LLM cost abuse.

> Related: `docs/08-weaknesses-and-next-steps.md` limitation #9 — "No rate
> limiting or abuse protection."

---

## 2. Plain-code tool gate (`src/supportdesk/tool_gate.py`)

**What exists:** Every tool call passes through a deterministic `ToolGate` — no
LLM is involved in the decision. For each call it enforces, in order:

1. **Per-agent allowlist** — e.g. billing can never call technical tools
   (`tool_gate.py:40-47`).
2. **Pydantic v2 schema validation** of arguments (`tool_gate.py:104-116`).
3. **Customer scoping** — `customer_id` is threaded through so the repository
   layer only returns that customer's data (`tool_gate.py:118-119`).
4. **Risk policy** — refunds above `refund_auto_approve_threshold` (default
   `$100`, `config.py:47`) are flagged `requires_approval`, not silently
   executed (`tool_gate.py:128-140`).

Two validation failures on a conversation escalate it
(`tool_gate.py:150-151`, `settings.max_tool_validation_failures`).

**Why this matters:** An attacker who compromises the LLM still cannot make the
billing agent call a technical tool, or read another customer's invoice — the
gate is plain code, deterministic, and reviewable.

**Production fix:** Keep the deterministic gate (do not let an LLM decide which
tools run). Add an immutable audit log of every gate decision (allow / deny /
requires-approval, agent, tool, customer, timestamp), and route allowlist
changes through code review.

---

## 3. Human-in-the-loop — refund approvals (`POST /approve`)

**What exists:** Refunds above the auto-approve threshold pause the graph with
LangGraph `interrupt()`. A human must `POST /approve` (with `approve` /
`reject`) before execution continues (`main.py:184`). The checkpointer holds
conversation state keyed by `conversation_id` (`thread_id`) so resume continues
exactly where it paused.

**Prototype gaps:**
- Checkpointer is `InMemorySaver` — state is lost on restart and cannot be
  shared across API replicas (`docs/08` limitation #2).
- No expiry or notification wiring on pending approvals.

**Open source database/checkpointer:** **PostgreSQL** (open source) — LangGraph's
`PostgresSaver` persists conversation state durably.

**Production fix:** Swap to a **Postgres-backed checkpointer** (`PostgresSaver`)
so state is durable and shared across instances. Make `/approve` idempotent,
add a pending-approval TTL, and wire approvals into an audit trail (who
approved, when, and for what amount).

---

## 4. Prompt-injection defense & PII redaction (`src/supportdesk/security.py`)

**What exists:** Two concerns, both enforced in plain code:

- **Prompt injection:** user input and tool outputs are scanned for
  instruction-hijack patterns (`ignore previous instructions`, `you are now`,
  `reveal the system prompt`, …) via regex plus whitespace-collapsed signatures
  that catch obfuscated attempts (`security.py:18-57`). A match raises
  `InjectionBlocked`.
- **PII redaction:** emails, phones, card numbers, SSNs are replaced with
  `[EMAIL]`, `[PHONE]`, `[CARD]`, `[SSN]` before reaching any LLM prompt, tool
  result, or log (`security.py:66-107`, `logging.py:41-81`).

Tool output is sanitized too — defense in depth against tool-output injection.

**Status:** Hardened — the detector normalizer now applies Unicode NFKC
normalization (`security.py`), so fullwidth, zero-width, and homoglyph
obfuscation collapses to matchable signatures before pattern matching.

**Production fix:** Keep redaction **before** the LLM (never after). Log
redaction/detection counts (not content) for tuning, and consider a dedicated
LLM gateway / model firewall in front of the NVIDIA Build API for additional
inspection.

> Related: `docs/08` limitation #2 — the detector is regex-based and can be
> obfuscated; normalization is a first hardening step, not a guarantee.

---

## 5. Authentication & identity (`src/supportdesk/main.py:61-70`)

**Status:** Deferred — see Deferred items.

**What exists:** `get_current_customer_id` resolves identity from the
`X-Customer-Id` request header — it is **authoritative**. The request body's
`customer_id` is explicitly **not trusted**: a client could spoof it to read
another customer's invoices, tickets, and refunds.

```python
# main.py:61-70
def get_current_customer_id(x_customer_id: int = Header(alias="X-Customer-Id")) -> int:
    return x_customer_id
```

**Open source alternatives:** When you're ready to add real authN/authZ, these
open source options are a good starting point:

| Option | Type | Notes |
|--------|------|-------|
| **Keycloak** | Identity & access management | Self-hosted, OIDC/SAML, rich RBAC, mature |
| **Authentik** | Identity provider | Flexible, Python/Django, good docs |
| **Ory Kratos / Oathkeeper** | Identity & API auth | API-first, Go, cloud-native |
| **Dex** | OIDC identity provider | Connects to other providers (LDAP, GitHub, SAML) |
| **Authelia** | SSO + 2FA | Lightweight, good for self-hosted apps |
| **SuperTokens** | Session + auth | Open source core, flexible integration |

**Production fix:** Replace the header with real authN/authZ — OIDC/OAuth2 +
JWT validation, roles/claims, and per-endpoint authorization. Never accept
`customer_id` from the request body. Enforce ownership at the API gateway
before requests reach the graph.

---

## 6. Secrets & configuration (`src/supportdesk/config.py`)

**What exists:** All settings come from environment variables via
`pydantic-settings.BaseSettings` (`config.py:36-70`). `.env` is loaded at
runtime and is **gitignored** (`.gitignore:94`); `.env.example` is the
committed template. No secrets are stored in code.

`nvidia_api_key` is optional at import (`config.py:38`) — LLM calls fail at
runtime if the key is missing, which is intentional: fail loudly, not silently.

**Open source secret management:** **HashiCorp Vault** (open source), **SOPS**
(encrypted file-based secrets), **Doppler** (free tier).

**Production fix:**
- Load config strictly from env / a secret manager (AWS Secrets Manager, GCP
  Secret Manager, HashiCorp Vault) — never commit `.env`.
- Make required fields (e.g. `nvidia_api_key` when LLM is used) validated at
  startup.
- Rotate keys; use least-privilege API keys and short-lived tokens where possible.

---

## 7. Database security

**What exists:** SQLAlchemy with SQLite locally and Postgres in
`docker-compose.yml` (`db: postgres:15-alpine`). Every repository read/write is
scoped by `customer_id` at the repository layer — cross-customer data access is
denied by design. Seed data is idempotent (`scripts/seed_data.py`).

**Open source database:** **PostgreSQL** (open source); managed options include
AWS RDS, Google Cloud SQL, Azure Database for PostgreSQL.

**Production fix:** Managed Postgres with TLS-encrypted connections, a
least-privilege DB user, automated backups, and point-in-time recovery. Keep
customer-scoping at the repository layer — it is the last line of defense
against cross-customer data access.

---

## 8. Container & runtime hardening (`Dockerfile`, `docker-compose.yml`, `.dockerignore`)

**What exists:**
- `python:3.12-slim` image, `PIP_NO_CACHE_DIR=1`, dependency layer cached
  separately (`Dockerfile:1-16`).
- App seeds idempotently on startup, then serves on `0.0.0.0:8000`
  (`scripts/entrypoint.sh`).
- App + database healthchecks; `app` waits on `condition: service_healthy`
  (`docker-compose.yml`).
- `.dockerignore` excludes `.git`, `__pycache__`, `.env`, `*.db`, coverage,
  IDE/OS files from the build context — so no secrets or db artifacts enter the
  image.

**Status:** Implemented — non-root user (`supportdesk`), CPU/memory resource
limits, `restart: unless-stopped`.

**Prototype gaps (remaining):**
- No image vulnerability scanning in CI.

Open source scanning options: **Trivy**, **Grype**, **Clair**.

**Production fix:** Scan images (Trivy / Grype — both open source) in CI,
enable Dependabot for dependency updates, and never bake secrets into the
image — pass them at runtime via env / secret manager.

---

## 9. Observability & audit logging (`src/supportdesk/logging.py`)

**What exists:** Structured JSON logging via structlog, with a PII processor
that scrubs emails, phones, cards, and SSNs from **every** log value before it
is written (`logging.py:41-81`). Events are correlated by `conversation_id` /
`customer_id`. The `GET /trace/{id}` endpoint exposes conversation state for
the interview demo (`main.py:201-208`).

**Open source SIEM/observability options:** **Elastic Stack** (Elasticsearch,
Logstash, Kibana), **Grafana Loki + Grafana**, **SigNoz**, **VictoriaMetrics**,
**OpenTelemetry** (collector).

**Production fix:** Forward logs to a SIEM. Alert on rate-limit trips, tool-gate
denials, interrupt / approval events, and failed auth. Keep trace IDs end-to-end
so any ticket can be traced from customer message to final reply.

---

## 10. CI/CD gates (`.github/workflows/ci.yml`)

**What exists:** CI runs, on every push/PR to `main`:

1. **lint-and-types:** `ruff check`, `ruff format --check`, `mypy src`
   (`pyproject.toml` line-length 100, strict mypy).
2. **test:** unit + integration against SQLite with a fake LLM, coverage gate
   `fail_under = 85` (`pyproject.toml:69`).
3. **Eval regression gate:** runs the labeled ticket corpus through a
   deterministic fake LLM and fails CI if routing accuracy drops more than 5
   points vs. the committed baseline (routing 74%, tool-selection ~41%).

**Status:** Dependabot added (`.github/dependabot.yml`).

Open source scanning options: **Trivy**, **Grype**, **Clair**.

**Production fix:** Keep these gates. Add image scanning (Trivy / Grype) in CI,
run the live-LLM smoke suite against the NVIDIA Build API on a cadence (not
every commit), and add LLM-as-judge reply-quality scoring.

---

## Deferred items (intentional)

**Authentication & authorization (`X-Customer-Id` header) and secrets
(secret-manager integration) are intentionally NOT implemented in this round.**
The project deliberately keeps authN as a header-based placeholder
(`X-Customer-Id`, authoritative but not cryptographically verified) and keeps
secrets as environment variables loaded at runtime (`.env` is gitignored, no
secrets in code).

Rationale: these are infrastructure / architectural decisions rather than
contained code changes:

- **AuthN/authZ:** requires an OIDC/OAuth2 provider choice, JWT validation,
  key rotation, and role mapping — a decision about the identity stack, not a
  code tweak.
- **Secrets:** requires a secret-manager choice (AWS Secrets Manager, GCP
  Secret Manager, HashiCorp Vault) and a rotation strategy.

A startup validation (`main.py`) fails loudly in production when
`NVIDIA_API_KEY` is missing (`app_env == production`), and `.env` is excluded
from the Docker build context via `.dockerignore`. When you choose an auth
provider and secret manager, swap the header-based customer resolution and
env-based config accordingly.

---

## Production readiness checklist

| Control | Status | Production action |
|---------|--------|-------------------|
| Rate limiting | Implemented — Redis + in-memory fallback | REDIS_URL optional; degrades to in-memory |
| Tool gate | Deterministic, allowlisted + audit log | Append-only GateAuditEntry per decision |
| Human approval | `interrupt()` + `/approve` | Postgres checkpointer, idempotent `/approve`, TTL |
| Prompt injection | Hardened — NFKC normalization | Log detection counts; consider LLM gateway |
| Authentication | Deferred — see Deferred items | OIDC/OAuth2 + JWT when provider chosen |
| Secrets | Deferred — see Deferred items | Secret manager when provider chosen |
| Database | SQLite / Postgres, customer-scoped | Managed Postgres + TLS, least-privilege user, backups |
| Container | Non-root user + resource limits | Image scanning, restart policy |
| Observability | Structured JSON + PII redaction | SIEM integration, alerts, trace IDs |
| CI/CD | Lint / types / test / eval gate + Dependabot | Image scanning (Trivy/Grype) |

---

## At 100x scale

This is a portfolio project designed to be explained in an interview. The parts
that are genuinely production-grade in design: safety (tool allowlists, customer
scoping, refund approval, PII redaction, prompt-injection defense, no secrets in
code), observability (structured logs, `/trace`, committed eval baseline with a
CI regression gate), correctness (85% coverage gate, mypy strict, ruff clean,
deterministic fake-LLM tests), and deployability (one-command seed, `docker
compose up`, GitHub Actions CI).

The parts that remain prototype-grade (and listed in `docs/08`):
in-memory checkpointer, SQL `ILIKE` RAG, no auth, monolith, no rate limiting,
hand-rolled retry/fallback. The suggested roadmap, in priority order:

1. Postgres checkpointer — durable, shared conversation state.
2. AuthN/authZ — don't trust the client-supplied `customer_id`.
3. Vector-store RAG — semantic article retrieval with citations.
4. Rate limiting + abuse protection — protect against LLM cost abuse.
5. Live-LLM eval cadence — smoke suite against the NVIDIA API more often.
6. Frontend + dashboard — customer chat and human approval queue.
7. Circuit breaker + tracing — resilient LLM calls and distributed tracing.

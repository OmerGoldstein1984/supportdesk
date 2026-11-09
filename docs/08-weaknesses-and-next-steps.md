# SupportDesk — weaknesses and next steps

An honest, interview-ready assessment of where the system is today and what
would need to change to run it at scale. Acknowledging limitations is part of
the design — it shows you understand where this prototype ends and production
begins.

## Known limitations

### 1. RAG is SQL keyword search, not a vector store
The Technical agent searches KB articles with SQL `ILIKE` on title and content.
There is no embedding model, no vector index, and no semantic reranking.
Outdated/conflicting articles are returned and flagged, but the system does not
semantically rank the best match.
**Fix at 100x:** add a vector store (pgvector, Pinecone, Milvus, etc.) with an
embedding model and citation-aware retrieval.

### 2. In-memory checkpointer
Conversation state lives in LangGraph's `InMemorySaver`, keyed by
`conversation_id` (`thread_id`). It works for a single instance but does not
survive a restart and cannot be shared across multiple API replicas.
**Fix at 100x:** swap to a Postgres-backed checkpointer (LangGraph's
`PostgresSaver`) so state is durable and shared across instances.

### 3. No authentication beyond customer-ID scoping
Customers are identified by a `customer_id` passed with the request. There is
no login, session, JWT, or OAuth layer. In production you would not trust the
client to supply `customer_id`.
**Fix at 100x:** add authN/authZ (OAuth2/OIDC), resolve the real caller, and
enforce ownership at the API gateway before it reaches the graph.

### 4. Hand-rolled ReAct loop rather than a prebuilt agent constructor
Each specialist runs an explicit tool-calling loop instead of
`create_tool_calling_agent` / `AgentExecutor`. This gives us full control over
the tool gate and interrupt, but it is more code to maintain and is not the
"default" LangGraph path.
**Fix at 100x:** re-evaluate against the latest LangGraph prebuilt agents once
they stabilize; keep the explicit loop only if the control it gives is still
needed.

### 5. Hand-rolled LLM retry/fallback
`ChatNVIDIA` has no built-in retry/fallback, so we wrap it with tenacity retry
plus a single fallback model. It works but is not a circuit breaker, and there
is no per-model budget or latency tracking.
**Fix at 100x:** use a battle-tested client with circuit breaking, per-model
latency/budget tracking, and distributed tracing.

### 6. No real frontend
There is a minimal approval endpoint (`POST /approve`) and a trace endpoint
(`GET /trace/{id}`) for the demo/interview, but no customer-facing chat UI or
agent dashboard.
**Fix at 100x:** add a small chat frontend and an admin dashboard for human
approval queues and conversation review.

### 7. Evals use a deterministic fake LLM
The committed baseline (routing 74%, tool-selection ~41%) is measured with a
keyword-driven fake LLM, so it measures decision logic rather than the quality
of a particular foundation model. A live-LLM smoke suite runs against the NVIDIA
Build API on demand and nightly, not on every commit.
**Fix at 100x:** run the live-LLM smoke suite more frequently and add
LLM-as-judge scoring on reply quality.

### 8. Single monolith
Everything runs in one FastAPI process. At high traffic you cannot scale the
router independently of the specialists, and a slow LLM call blocks the worker.
**Fix at 100x:** split into per-agent services behind a gateway, with async
task queues (e.g., Celery/RQ or LangGraph's persistent checkpointer + message
queue) for long-running tool calls.

### 9. No rate limiting or abuse protection
There is no per-customer rate limit, no CAPTCHA, and no abuse detection. A
malicious user could spam the LLM and run up cost.
**Fix at 100x:** add rate limiting per customer/API key and anomaly detection.

## What "production-grade" means here

This is a portfolio project designed to be explained in an interview, not a
service you should deploy to real customers today. The parts that are genuinely
production-grade in design:

- **Safety:** tool allowlists, customer scoping, refund approval, PII redaction,
  prompt-injection defense, no secrets in code.
- **Observability:** structured JSON logs (PII-redacted), `/trace` endpoint,
  committed eval baseline with a CI regression gate.
- **Correctness:** 85% coverage gate, mypy strict, ruff clean, deterministic
  fake-LLM tests in CI.
- **Deployability:** one-command seed, `docker compose up`, GitHub Actions CI.

The parts that are **prototype-grade** (and listed above): in-memory
checkpointer, SQL `ILIKE` RAG, no auth, monolith, no rate limiting, hand-rolled
retry/fallback.

## Suggested roadmap (in priority order)

1. **Postgres checkpointer** — durable, shared conversation state (unlocks
   multi-instance deploys).
2. **AuthN/authZ** — don't trust the client-supplied `customer_id`.
3. **Vector-store RAG** — semantic article retrieval with citations.
4. **Rate limiting + abuse protection** — protect against LLM cost abuse.
5. **Live-LLM eval cadence** — run the smoke suite against the NVIDIA API more
   often; add LLM-as-judge reply-quality scoring.
6. **Frontend + dashboard** — customer chat and human approval queue.
7. **Circuit breaker + tracing** — resilient LLM calls and distributed tracing.

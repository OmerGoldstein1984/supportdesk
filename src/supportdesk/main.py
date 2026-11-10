"""SupportDesk FastAPI application.

Endpoints:
  POST /chat        - send a message, get a reply (or an approval request)
  POST /approve     - resume a paused human-in-the-loop refund approval
  GET  /trace/{id}  - inspect conversation state (for the interview demo)

WHAT: FastAPI web app exposing three HTTP endpoints. The chat endpoint is the
main entry point — it runs the supervisor graph with fake LLM in tests, real
LLM in production. The approve endpoint resumes a paused human-in-the-loop
refund approval. The trace endpoint inspects conversation state.

WHY: The REST API is the user-facing entry point. /chat runs the supervisor
graph (Router → specialist → Critic → reply), /approve resumes a paused
human-in-the-loop refund approval, /trace inspects conversation state for the
interview demo.

INPUTS: HTTP requests with JSON bodies.
OUTPUTS: JSON responses (ChatResponse, ApproveResponse).

FAILURE MODES:
- Missing X-Customer-Id header → 422 (header is required)
- LLM failure → propagates as HTTP error
- Graph interrupt → returns 200 with status="awaiting_approval" and interrupt
  value

# BUSINESS: /chat is the main customer-facing endpoint; /approve is the
#   human-in-the-loop gate for refunds above threshold
# INTERVIEW: "Why is customer_id from the header, not the body?" Answer: The
#   body's customer_id is not trusted — a client could spoof it to read another
#   customer's data. The header is authoritative.
# INTERVIEW: "What happens if the graph is interrupted?" Answer: /chat returns
#   200 with status="awaiting_approval" and the interrupt value; /approve
#   resumes with the human's decision.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any, Awaitable

from fastapi import Depends, FastAPI, Header, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .database import init_db
from .graph import ApprovalDecision, get_graph, resume, run
from .logging import configure_logging, get_logger

RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "30"))
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))


def _build_redis_client() -> Any:
    """Best-effort Redis client for distributed rate limiting.

    Returns ``None`` when ``REDIS_URL`` is unset, the ``redis`` package is
    missing, or Redis is unreachable — the middleware then falls back to an
    in-memory fixed window (single replica / local dev).
    """
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        return None
    try:
        import redis as redis_lib  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        client = redis_lib.from_url(redis_url)
        client.ping()
        return client
    except Exception:
        return None


configure_logging(settings.log_level)
logger = get_logger("supportdesk")

app = FastAPI(title="SupportDesk", version="0.1.0")


def get_current_customer_id(x_customer_id: int = Header(alias="X-Customer-Id")) -> int:
    """Resolve the caller's identity from a server-trusted header.

    The request body's ``customer_id`` is *not* trusted: a client can spoof it to
    read another customer's invoices, tickets, and refunds. ``X-Customer-Id`` is
    the authoritative caller identity (a stand-in for a signed session token / JWT
    in production) and is required on the chat endpoint. The graph is then scoped
    to this customer, so the repository layer never returns another customer's data.
    """
    return x_customer_id


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiter keyed by X-Customer-Id.

    Uses a Redis sliding-window counter when ``REDIS_URL`` is configured and
    reachable (shared across replicas), and falls back to an in-memory fixed
    window otherwise (single replica / local dev).

    Protects the LLM-heavy /chat endpoint from abuse: every chat triggers
    router + specialist + critic LLM calls, so an unbounded client can run up
    cost.
    """

    def __init__(
        self,
        app: Any,
        limit: int = RATE_LIMIT_REQUESTS,
        window_seconds: int = RATE_LIMIT_WINDOW_SECONDS,
    ) -> None:
        super().__init__(app)
        self.limit = limit
        self.window_seconds = window_seconds
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._redis = _build_redis_client()

    def _redis_count(self, customer_id: str, now: float) -> int:
        """Add this request to the Redis sliding window and return its size."""
        key = f"ratelimit:{customer_id}"
        pipeline = self._redis.pipeline()
        pipeline.zadd(key, {str(now): now})
        pipeline.zremrangebyscore(key, 0, now - self.window_seconds)
        pipeline.zcard(key)
        pipeline.expire(key, self.window_seconds)
        results = pipeline.execute()
        return int(results[2])

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path != "/chat":
            return await call_next(request)
        customer_id = request.headers.get("x-customer-id", "anonymous")
        now = time.time()

        if self._redis is not None:
            count = self._redis_count(customer_id, now)
            if count > self.limit:
                return Response(
                    "Rate limit exceeded. Try again later.",
                    status_code=429,
                    headers={"Retry-After": str(self.window_seconds)},
                )
            return await call_next(request)

        cutoff = now - self.window_seconds
        window = self._windows[customer_id]
        self._windows[customer_id] = [t for t in window if t > cutoff]
        if len(self._windows[customer_id]) >= self.limit:
            return Response(
                "Rate limit exceeded. Try again later.",
                status_code=429,
                headers={"Retry-After": str(self.window_seconds)},
            )
        self._windows[customer_id].append(now)
        return await call_next(request)


app.add_middleware(RateLimitMiddleware)


from pydantic import BaseModel  # noqa: E402


class ChatRequest(BaseModel):
    conversation_id: str
    customer_id: int | None = None
    message: str


class ApproveRequest(BaseModel):
    conversation_id: str
    approve: bool
    note: str | None = None


class ChatResponse(BaseModel):
    status: str  # "complete" | "awaiting_approval"
    conversation_id: str
    final_reply: str | None = None
    intent: str | None = None
    interrupt: dict[str, Any] | None = None


class ApproveResponse(BaseModel):
    status: str
    conversation_id: str
    final_reply: str | None = None


# Idempotency store: conversation_id -> ApproveResponse dump (in-memory; production
# persists via Postgres checkpointer).
approval_decisions: dict[str, dict] = {}


def _validate_settings() -> None:
    """Fail loudly in production if required config is missing instead of failing mid-request."""
    if settings.app_env == "production" and not settings.nvidia_api_key:
        raise RuntimeError(
            "NVIDIA_API_KEY is required in production. Copy .env.example to .env "
            "and set it before starting the API."
        )


@app.on_event("startup")
def _startup() -> None:
    _validate_settings()
    init_db()
    logger.info("supportdesk_started", database_url=settings.database_url)


@app.post("/chat", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    current_customer_id: int = Depends(get_current_customer_id),
) -> ChatResponse:
    result = run(req.conversation_id, current_customer_id, req.message)
    snapshot = get_graph().get_state({"configurable": {"thread_id": req.conversation_id}})
    if snapshot.next:
        interrupt_value = snapshot.interrupts[0].value if snapshot.interrupts else {}
        logger.info(
            "chat_awaiting_approval",
            conversation_id=req.conversation_id,
            interrupt=interrupt_value,
        )
        return ChatResponse(
            status="awaiting_approval",
            conversation_id=req.conversation_id,
            interrupt=interrupt_value,
        )
    logger.info(
        "chat_complete",
        conversation_id=req.conversation_id,
        intent=result.get("intent"),
        final_reply=(result.get("final_reply") or "")[:120],
    )
    return ChatResponse(
        status="complete",
        conversation_id=req.conversation_id,
        final_reply=result.get("final_reply"),
        intent=result.get("intent"),
    )


@app.post("/approve", response_model=ApproveResponse)
def approve(req: ApproveRequest) -> ApproveResponse:
    # Idempotent: a conversation can only be approved/rejected once. Re-calling
    # /approve for the same conversation returns the cached decision instead of
    # re-resuming the graph (which would error once the graph has completed).
    existing = approval_decisions.get(req.conversation_id)
    if existing is not None:
        return ApproveResponse(**existing)
    decision = ApprovalDecision(approve=req.approve, note=req.note)
    result = resume(req.conversation_id, decision)
    response = ApproveResponse(
        status="complete",
        conversation_id=req.conversation_id,
        final_reply=result.get("final_reply"),
    )
    approval_decisions[req.conversation_id] = response.model_dump()
    logger.info(
        "approval_resumed",
        conversation_id=req.conversation_id,
        approve=req.approve,
        final_reply=(result.get("final_reply") or "")[:120],
    )
    return response


@app.get("/trace/{conversation_id}")
def trace(conversation_id: str) -> dict[str, Any]:
    snapshot = get_graph().get_state({"configurable": {"thread_id": conversation_id}})
    return {
        "conversation_id": conversation_id,
        "next": list(snapshot.next) if snapshot.next else [],
        "values": {k: v for k, v in (snapshot.values or {}).items() if k not in ("message",)},
    }

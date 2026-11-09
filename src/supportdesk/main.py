"""SupportDesk FastAPI application.

Endpoints:
  POST /chat        - send a message, get a reply (or an approval request)
  POST /approve     - resume a paused human-in-the-loop refund approval
  GET  /trace/{id}  - inspect conversation state (for the interview demo)
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from .config import settings
from .database import init_db
from .graph import ApprovalDecision, get_graph, resume, run
from .logging import configure_logging, get_logger

configure_logging(settings.log_level)
logger = get_logger("supportdesk")

app = FastAPI(title="SupportDesk", version="0.1.0")

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


@app.on_event("startup")
def _startup() -> None:
    init_db()
    logger.info("supportdesk_started", database_url=settings.database_url)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    result = run(req.conversation_id, req.customer_id, req.message)
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
    decision = ApprovalDecision(approve=req.approve, note=req.note)
    result = resume(req.conversation_id, decision)
    logger.info(
        "approval_resumed",
        conversation_id=req.conversation_id,
        approve=req.approve,
        final_reply=(result.get("final_reply") or "")[:120],
    )
    return ApproveResponse(
        status="complete",
        conversation_id=req.conversation_id,
        final_reply=result.get("final_reply"),
    )


@app.get("/trace/{conversation_id}")
def trace(conversation_id: str) -> dict[str, Any]:
    snapshot = get_graph().get_state({"configurable": {"thread_id": conversation_id}})
    return {
        "conversation_id": conversation_id,
        "next": list(snapshot.next) if snapshot.next else [],
        "values": {k: v for k, v in (snapshot.values or {}).items() if k not in ("message",)},
    }

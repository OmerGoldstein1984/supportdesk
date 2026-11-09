"""Supervisor graph: Router -> specialist -> Critic -> reply, with checkpointed
state and human-in-the-loop refund approval.

The graph is compiled once with an InMemorySaver checkpointer. Each conversation
is a thread identified by ``conversation_id`` (thread_id), so state and memory
persist across turns and across interrupt/resume cycles.

Flow::

    router --(low confidence / escalation)--> escalation --> END
      \
       --> specialist --(needs approval)--> human_approval (interrupt) --> critic
                                              \
                                               --> critic --(approve)--> reply --> END
                                               --(revise xN)--> specialist
                                               --(reject / over limit)--> escalation --> END
"""

from __future__ import annotations

import json
from typing import Any, Optional, TypedDict, cast

from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel

from .agents import SpecialistResult, critique, make_specialist, route_message
from .config import settings
from .database import session_scope
from .tools import tools_for
from .tools.base import APPROVAL_REQUIRED_PREFIX, ToolContext

__all__ = ["AgentState", "ApprovalDecision", "graph", "run", "resume", "get_graph"]


class ApprovalDecision(BaseModel):
    approve: bool
    note: str | None = None


class AgentState(TypedDict, total=False):  # noqa: UP036
    conversation_id: str
    customer_id: Optional[int]
    message: str
    intent: Optional[str]
    urgency: Optional[str]
    confidence: Optional[float]
    specialist: Optional[str]
    draft_reply: Optional[str]
    citations: list[str]
    critic_decision: Optional[str]
    critic_reason: Optional[str]
    revision_count: int
    needs_approval: bool
    approval_payload: Optional[dict[str, Any]]
    approved: bool
    final_reply: Optional[str]
    escalation: bool
    case_summary: Optional[str]
    error: Optional[str]


def _parse_approval(signal: str) -> dict[str, Any]:
    # "APPROVAL_REQUIRED:issue_refund|{"invoice_id": 3, "amount": 50.0}|reason"
    head = signal[len(APPROVAL_REQUIRED_PREFIX) :]
    parts = head.split("|", 2)
    payload = {}
    if len(parts) >= 2:
        try:
            payload = json.loads(parts[1])
        except Exception:
            payload = {}
    if len(parts) == 3:
        payload["reason"] = parts[2]
    return payload


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def router_node(state: AgentState) -> AgentState:
    message = state.get("message", "")
    try:
        result, clean = route_message(message)
    except Exception:  # defensive: never let the router crash the graph
        from .agents.router import RouterOutput

        result = RouterOutput(
            intent="escalation",
            urgency="high",
            confidence=0.0,
            reasoning="router error",
        )
        clean = message
    specialist = (
        result.intent
        if result.intent
        in {
            "billing",
            "technical",
            "account",
            "escalation",
        }
        else "escalation"
    )
    return {
        "intent": result.intent,
        "urgency": result.urgency,
        "confidence": result.confidence,
        "specialist": specialist,
        "message": clean,
    }


def specialist_node(state: AgentState) -> AgentState:
    customer_id = state.get("customer_id")
    conversation_id = state.get("conversation_id", "default")
    specialist = state.get("specialist") or "escalation"
    message = state.get("message", "")
    context = ToolContext(session_scope, customer_id or 0, conversation_id)
    specialist_fn = make_specialist(specialist, context)
    result: SpecialistResult = specialist_fn(message)

    update: AgentState = {
        "draft_reply": result.draft,
        "revision_count": state.get("revision_count", 0),
        "needs_approval": False,
    }
    if result.approval_signal:
        update["needs_approval"] = True
        update["approval_payload"] = _parse_approval(result.approval_signal)
    return update


def human_approval_node(state: AgentState) -> AgentState:
    payload = state.get("approval_payload") or {}
    decision = interrupt(
        {
            "question": "Approve this refund?",
            "invoice_id": payload.get("invoice_id"),
            "amount": payload.get("amount"),
            "reason": payload.get("reason", "refund above auto-approve threshold"),
        }
    )
    # LangGraph 0.2.x interrupt() returns the raw resume value (a dict here).
    if isinstance(decision, dict):
        approve = bool(decision.get("approve"))
        note = decision.get("note") or ""
    else:
        approve = bool(decision)
        note = ""
    if approve:
        return {
            "approved": True,
            "needs_approval": False,
            "draft_reply": (
                f"Refund of ${payload.get('amount')} for invoice #{payload.get('invoice_id')} "
                f"approved and processed.{(f' Note: {note}' if note else '')}"
            ),
        }
    return {
        "approved": False,
        "needs_approval": False,
        "escalation": True,
        "case_summary": f"Refund rejected by human: {note or 'not approved'}",
        "draft_reply": f"Refund rejected: {note or 'not approved'}",
    }


def critic_node(state: AgentState) -> AgentState:
    draft = state.get("draft_reply") or ""
    message = state.get("message") or ""
    result = critique(draft, message)
    count = state.get("revision_count", 0)
    update: AgentState = {
        "critic_decision": result.decision,
        "critic_reason": result.reason,
    }
    if result.decision == "revise":
        update["revision_count"] = count + 1
        update["draft_reply"] = result.suggested_fix or draft
    return update


def reply_node(state: AgentState) -> AgentState:
    if state.get("escalation"):
        return {
            "final_reply": state.get("case_summary")
            or state.get("draft_reply")
            or "Escalated to a human agent.",
        }
    return {"final_reply": state.get("draft_reply") or ""}


def escalation_node(state: AgentState) -> AgentState:
    customer_id = state.get("customer_id")
    conversation_id = state.get("conversation_id", "default")
    context = ToolContext(session_scope, customer_id or 0, conversation_id)
    summary = state.get("case_summary") or state.get("message") or "Escalated case."
    try:
        escalation_tools = tools_for("escalation")(context)
        ticket = escalation_tools["create_ticket"].invoke(
            {"subject": "Escalated support case", "body": summary}
        )
        notify = escalation_tools["notify_human_agent"].invoke({"message": summary})
        final = f"I've escalated this to a human agent. {ticket} {notify}"
    except Exception:
        final = "I've escalated this to a human agent. They'll follow up with you shortly."
    return {
        "escalation": True,
        "case_summary": summary,
        "final_reply": final,
    }


# ---------------------------------------------------------------------------
# Conditional edges
# ---------------------------------------------------------------------------


def route_after_router(state: AgentState) -> str:
    if (state.get("confidence") or 0) < settings.router_confidence_threshold:
        return "escalation"
    if state.get("intent") == "escalation":
        return "escalation"
    return "specialist"


def route_after_specialist(state: AgentState) -> str:
    if state.get("needs_approval"):
        return "human_approval"
    return "critic"


def route_after_critic(state: AgentState) -> str:
    decision = state.get("critic_decision")
    count = state.get("revision_count", 0)
    if decision == "approve":
        return "reply"
    if decision == "revise" and count < settings.max_revisions:
        return "specialist"
    return "escalation"


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

_builder = StateGraph(AgentState)
_builder.add_node("router", router_node)
_builder.add_node("specialist", specialist_node)
_builder.add_node("human_approval", human_approval_node)
_builder.add_node("critic", critic_node)
_builder.add_node("reply", reply_node)
_builder.add_node("escalation", escalation_node)

_builder.add_edge(START, "router")
_builder.add_conditional_edges("router", route_after_router)
_builder.add_conditional_edges("specialist", route_after_specialist)
_builder.add_edge("human_approval", "critic")
_builder.add_conditional_edges("critic", route_after_critic)
_builder.add_edge("reply", END)
_builder.add_edge("escalation", END)

_checkpointer = InMemorySaver()
graph = _builder.compile(checkpointer=_checkpointer)


def get_graph() -> Any:
    return graph


def run(conversation_id: str, customer_id: Optional[int], message: str) -> AgentState:
    config: RunnableConfig = {"configurable": {"thread_id": conversation_id}}
    initial: AgentState = {
        "conversation_id": conversation_id,
        "customer_id": customer_id,
        "message": message,
        "revision_count": 0,
        "needs_approval": False,
        "approved": False,
        "escalation": False,
    }
    return cast(AgentState, graph.invoke(initial, config=config))


def resume(conversation_id: str, decision: ApprovalDecision) -> AgentState:
    config: RunnableConfig = {"configurable": {"thread_id": conversation_id}}
    return cast(AgentState, graph.invoke(Command(resume=decision.model_dump()), config=config))

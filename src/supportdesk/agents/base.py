"""Agent runners.

Router and Critic use LangChain structured output (Pydantic v2) — no tools.
Specialists run a small, explicit ReAct tool-calling loop over their allowlisted
LangChain tools; every tool call passes through the plain-code tool gate. This
keeps tool execution fully controllable (allowlist, risk policy, human-in-the-loop
interrupt) and easy to explain in an interview.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence, cast

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from ..llm import llm
from ..security import InjectionBlocked, sanitize_tool_output, sanitize_user_input
from ..tools.base import APPROVAL_REQUIRED_PREFIX, ToolContext
from .critic import CriticOutput
from .router import RouterOutput


@dataclass
class SpecialistResult:
    draft: str
    approval_signal: str | None  # "APPROVAL_REQUIRED:<tool>:<reason>" or None


def run_specialist(
    agent: str,
    tools: Sequence[BaseTool],
    system_prompt: str,
    message: str,
    context: ToolContext,
    max_tool_steps: int = 5,
) -> SpecialistResult:
    """Manual ReAct loop bound to one specialist's allowlisted tools.

    The LLM picks tools; we execute them through the tool gate. Returns the
    draft reply plus any approval signal (e.g. a refund over the threshold).
    """
    bound = llm.primary.bind_tools(list(tools))
    messages = [SystemMessage(system_prompt), HumanMessage(message)]
    approval_signal: str | None = None

    for _ in range(max_tool_steps):
        response: Any = bound.invoke(messages)
        messages.append(response)
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            return SpecialistResult(
                draft=str(response.content or ""), approval_signal=approval_signal
            )

        for call in tool_calls:
            name = call["name"]
            args = dict(call["args"] or {})
            tool = next((t for t in tools if t.name == name), None)
            if tool is None:
                result = f"BLOCKED: unknown tool {name}"
            else:
                try:
                    raw = tool.invoke(args)
                    result = sanitize_tool_output(str(raw))
                except InjectionBlocked:
                    result = "BLOCKED: tool output contained a prompt-injection pattern"
            if isinstance(result, str) and result.startswith(APPROVAL_REQUIRED_PREFIX):
                approval_signal = result
            messages.append(ToolMessage(result, tool_call_id=call["id"]))

    return SpecialistResult(draft=str(messages[-1].content or ""), approval_signal=approval_signal)


def route_message(message: str) -> tuple[RouterOutput, str]:
    """Router: classify intent, urgency, confidence via structured output."""
    from .router import router_chain

    try:
        clean = sanitize_user_input(message)
    except InjectionBlocked as exc:
        return (
            RouterOutput(
                intent="escalation",
                urgency="high",
                confidence=0.0,
                reasoning=f"blocked: {exc}",
            ),
            message,
        )
    result = router_chain.invoke(
        {
            "message": clean,
            "specialists": "billing, technical, account, escalation",
        }
    )
    return result, clean


def critique(draft: str, message: str, policy_notes: str = "") -> CriticOutput:
    """Critic: approve / revise / reject a draft reply for policy, PII, hallucination."""
    from .critic import critic_chain

    result = critic_chain.invoke(
        {
            "draft": draft,
            "message": message,
            "policy_notes": policy_notes,
        }
    )
    return cast(CriticOutput, result)

"""Agent runners.

WHAT: The ReAct execution engine and shared agent utilities. Contains:
- SpecialistResult: dataclass holding draft reply + optional approval_signal
- run_specialist(): manual ReAct loop (Reason → Act → Observe) bound to one
  specialist's allowlisted tools, max 5 tool steps
- route_message(): router entry point — sanitizes input, invokes router_chain
- critique(): thin wrapper around critic_chain

WHY: Keeps tool execution fully controllable (allowlist, risk policy,
human-in-the-loop interrupt) and easy to explain in an interview. The manual
ReAct loop gives full control over the tool gate rather than using LangGraph's
prebuilt AgentExecutor.

AGENTS IN THIS MODULE:
- Router: classifies intent/urgency/confidence via structured output — no tools
- Critic: checks drafts for policy/PII/hallucination — no tools
- Specialists: run ReAct loop over allowlisted tools — tools only

Router and Critic have empty tool allowlists (they never call tools).

FAILURE MODES:
- LLM never stops calling tools — hard stop at max_tool_steps=5, returns last
  content (possibly blank/incoherent)
- tool.invoke raises non-InjectionBlocked exception — propagates and crashes
  the specialist/graph (unlike router_node which catches broadly)
- Unknown tool in tool_calls → "BLOCKED: unknown tool {name}"
- Tool output contains injection → "BLOCKED: tool output contained a prompt-injection pattern"
- Tool output starts with APPROVAL_REQUIRED_PREFIX → captured as approval_signal
  (human-in-the-loop for refunds above threshold)

# GAP: approval_signal is set from the *last* tool call that produced one — if
#   multiple tools fire in one step and more than one emits approval, only the
#   last wins; earlier ones silently dropped.
# BUSINESS: Human-in-the-loop for refunds above threshold is a compliance control;
#   business can tune refund_auto_approve_threshold without code changes.
# INTERVIEW: "What happens if the specialist's tool call raises an unexpected
#   exception?" Answer: It propagates out of specialist_node and fails the graph
#   invocation (unlike router_node, which catches broadly).
# INTERVIEW: "How is the revise loop bounded?" Answer: route_after_critic checks
#   count < max_revisions; over limit → escalation.
# INTERVIEW: "How would you test this without a real LLM?" Answer: Mock
#   llm.structured to return fixed RouterOutput/CriticOutput; mock tools_for to
#   return stub tools; assert graph transitions.
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

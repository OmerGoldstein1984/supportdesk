"""Shared base for all SupportDesk LangChain tools.

WHAT: ToolContext dataclass (session_factory, customer_id, conversation_id) and
execute() — the universal wrapper every tool runs through. Every call passes
tool_gate.validate() before any business logic — returns result string or a
BLOCKED:/APPROVAL_REQUIRED: marker that the agent layer interprets.

WHY: Single choke point where all tool execution is authorized. Every LangChain
tool funnels through execute(), so the tool gate is the single place where
allowlist, schema validation, and risk policy are enforced.

WHY: Defense in depth — the tool gate is middleware that every tool call must
pass. It keeps tool execution fully controllable and easy to explain in an
interview.

INPUTS: ToolContext, agent name, tool name, args dict, fn callable.
OUTPUTS: result string, or "BLOCKED:"/"APPROVAL_REQUIRED:" marker string.

FAILURE MODES:
- tool not allowlisted → "BLOCKED: {tool_name} is not allowlisted for the {agent} agent"
- args fail schema validation → "BLOCKED: schema validation failed..."
- fn raises exception → propagates uncaught out of execute()
- requires_approval → returns APPROVAL_REQUIRED marker, graph pauses for human

# GAP: customer_id=None default in validate() weakens scoping if caller omits it
# BUSINESS: Separation of duties via allowlists is a SOC2/ISO 27001-style control:
#   billing clerks can't reprovision SIMs, technical staff can't refund invoices
# INTERVIEW: "Why is the gate a class with state (validation_failures) instead of
#   a pure function?" Answer: so we can count repeated validation failures per
#   conversation and trip a circuit.
# INTERVIEW: "Why does execute() return a marker string instead of raising?"
#   Answer: So the agent layer can interpret the result — BLOCKED means the tool
#   didn't run, APPROVAL_REQUIRED means the graph pauses for human approval.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from ..repositories import Repositories
from ..tool_gate import tool_gate

APPROVAL_REQUIRED_PREFIX = "APPROVAL_REQUIRED:"


@dataclass
class ToolContext:
    session_factory: Callable[..., Any]  # e.g. supportdesk.database.session_scope
    customer_id: int
    conversation_id: str


def execute(
    context: ToolContext,
    agent: str,
    tool_name: str,
    args: dict[str, Any],
    fn: Callable[..., str],
) -> str:
    """Run ``fn`` through the tool gate.

    Returns the tool's result string, or a ``BLOCKED:`` / ``APPROVAL_REQUIRED:``
    marker string that the agent layer interprets.
    """
    verdict = tool_gate.validate(
        agent, tool_name, args, context.customer_id, context.conversation_id
    )
    if not verdict.allowed:
        return f"BLOCKED: {verdict.reason}"
    if verdict.requires_approval:
        return (
            f"{APPROVAL_REQUIRED_PREFIX}{tool_name}|"
            f"{json.dumps(verdict.validated_args)}|{verdict.reason}"
        )
    with context.session_factory() as session:
        repos = Repositories(session)
        return fn(context, repos, verdict.validated_args)

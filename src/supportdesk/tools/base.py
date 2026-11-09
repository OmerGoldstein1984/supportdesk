"""Shared base for all SupportDesk LangChain tools.

Every tool is produced by a factory that binds a :class:`ToolContext` (current
customer, conversation, session factory). Tool execution always passes through
the plain-code :class:`~supportdesk.tool_gate.ToolGate`, which enforces the
per-agent allowlist, Pydantic v2 schema validation, customer scoping, and the
refund risk policy.
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

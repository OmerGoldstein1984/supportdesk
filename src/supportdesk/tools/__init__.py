"""Tool factories for each specialist agent."""

from typing import Any, Callable

from .account import make_account_tools
from .base import ToolContext
from .billing import make_billing_tools
from .escalation import make_escalation_tools
from .technical import make_technical_tools

AGENT_TOOLS: dict[str, Callable[[ToolContext], dict[str, Any]]] = {
    "billing": make_billing_tools,
    "technical": make_technical_tools,
    "account": make_account_tools,
    "escalation": make_escalation_tools,
}


def tools_for(agent: str) -> Callable[[ToolContext], dict[str, Any]]:
    return AGENT_TOOLS[agent]

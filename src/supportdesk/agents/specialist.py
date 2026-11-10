"""Specialist agent system prompts and factory.

WHAT: Factory that builds per-domain specialist functions (billing/technical/account/
escalation). Each specialist gets its own system prompt and an allowlisted tool set
via tools_for(agent). Returns a callable (message) -> SpecialistResult.

WHY: Each specialist is bound to only its own domain tools — a billing agent can
never call technical tools. This per-agent allowlist is the core authorization
mechanism enforced by the tool gate.

INPUTS: agent name, ToolContext (session, customer_id, conversation_id).
OUTPUTS: Callable that takes a message string and returns a SpecialistResult.

FAILURE MODES:
- tools_for(agent) could raise if agent name is unknown — guarded upstream by
  graph.py which narrows intent to {billing, technical, account, escalation}
- tools_for(agent)(context) could raise — propagates to specialist_node and
  crashes the graph (no try/except in specialist_node, unlike router_node)

# GAP: New intent added to RouterOutput without a corresponding prompt here would
#   crash at specialist creation time.
# BUSINESS: Separation of duties via allowlists is a SOC2/ISO 27001-style control:
#   billing clerks can't reprovision SIMs, technical staff can't refund invoices.
# INTERVIEW: "Why does each specialist get its own system prompt?" Answer: domain
#   specialization — each agent should only know about its domain tools and policies.
"""

from typing import Callable

from ..agents.base import SpecialistResult
from ..tools import tools_for
from ..tools.base import ToolContext


def system_prompt_for(agent: str) -> str:
    prompts = {
        "billing": (
            "You are the billing specialist. You help customers with invoices, "
            "refunds, and plan changes. Only use your billing tools. Never invent "
            "amounts or invoice numbers. If a refund exceeds the auto-approve "
            "limit, tell the customer it needs human approval."
        ),
        "technical": (
            "You are the technical specialist. You answer how-to and error "
            "questions using the knowledge base, check service status, and file "
            "bug tickets. Cite the article titles you rely on. Flag outdated "
            "articles when you use them."
        ),
        "account": (
            "You are the account specialist. You help customers look up their own "
            "account and send password resets. You only ever touch the current "
            "customer's data."
        ),
        "escalation": (
            "You are the escalation specialist. You create support tickets and "
            "notify human agents. Use this when the customer is angry, the issue "
            "is unclear, a refund needs approval, or the customer must be handed "
            "to a human. Include a clear case summary."
        ),
    }
    return prompts[agent]


def make_specialist(agent: str, context: ToolContext) -> Callable[[str], SpecialistResult]:
    """Return a function ``(message) -> SpecialistResult`` for the given specialist."""
    from ..agents.base import run_specialist

    def specialist(message: str) -> SpecialistResult:
        tool_factory = tools_for(agent)
        tool_dict = tool_factory(context)
        return run_specialist(
            agent=agent,
            tools=list(tool_dict.values()),
            system_prompt=system_prompt_for(agent),
            message=message,
            context=context,
        )

    return specialist

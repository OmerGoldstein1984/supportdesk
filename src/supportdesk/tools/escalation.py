"""Escalation tools: create_ticket, notify_human_agent.

WHAT: Factory producing the two escalation-agent tools. create_ticket files a
support ticket with specialist="escalation". notify_human_agent returns a
notification string but does not actually page a human (stubbed for demo).

WHY: Escalation is the safety valve — every escape hatch in the graph (low
confidence, critic rejection, refund above threshold) routes here. The escalation
agent creates tickets and notifies human agents.

INPUTS: ToolContext.
OUTPUTS: dict of {tool_name: LangChain tool}.

AGENT TOOLS:
- create_ticket: creates a support ticket, scoped to current customer
- notify_human_agent: returns notification string (no actual notification sent)

FAILURE MODES:
- create_ticket: none beyond repository errors
- notify_human_agent: customer not found → "Cannot notify: account not found."

# BUSINESS: Escalation is the safety valve — every escape hatch in the graph
#   eventually leads here with a case summary for the human agent.
# INTERVIEW: "Why does notify_human_agent not actually page a human?" Answer:
#   Stubbed for demo; in production would page/pager duty.
# INTERVIEW: "Why does create_ticket set specialist='escalation'?" Answer: So
#   the ticket is tagged with which specialist team should handle it.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from ..repositories import Repositories
from ..schemas import CreateTicketArgs, NotifyHumanArgs
from .base import ToolContext, execute


def make_escalation_tools(context: ToolContext) -> dict[str, Any]:
    @tool(args_schema=CreateTicketArgs)
    def create_ticket(subject: str, body: str) -> str:
        """Create a support ticket for the current customer."""

        def _run(ctx: ToolContext, repos: Repositories, args: dict[str, Any]) -> str:
            ticket = repos.tickets.create(
                ctx.customer_id, args["subject"], args["body"], specialist="escalation"
            )
            return f"Escalation ticket #{ticket.id} created: {ticket.subject}."

        return execute(
            context, "escalation", "create_ticket", {"subject": subject, "body": body}, _run
        )

    @tool(args_schema=NotifyHumanArgs)
    def notify_human_agent(message: str) -> str:
        """Notify a human agent with a case summary."""

        def _run(ctx: ToolContext, repos: Repositories, args: dict[str, Any]) -> str:
            customer = repos.customers.get(ctx.customer_id)
            if customer is None:
                return "Cannot notify: account not found."
            return (
                f"Human agent notified for customer {customer.id} "
                f"({customer.name}): {args['message']}"
            )

        return execute(context, "escalation", "notify_human_agent", {"message": message}, _run)

    return {"create_ticket": create_ticket, "notify_human_agent": notify_human_agent}

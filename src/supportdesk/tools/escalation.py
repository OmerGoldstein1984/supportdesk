"""Escalation tools: create_ticket, notify_human_agent."""

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

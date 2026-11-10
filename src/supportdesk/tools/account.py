"""Account tools: lookup_user, send_password_reset.

WHAT: Factory producing the two account-agent tools. Both are self-service — the
customer looks up their own account or requests a password reset to their own
email.

WHY: Account tools are scoped to the current customer only. send_password_reset
returns a confirmation string but does not actually send an email (stubbed for
demo).

INPUTS: ToolContext.
OUTPUTS: dict of {tool_name: LangChain tool}.

AGENT TOOLS:
- lookup_user: read-only account lookup, scoped to current customer
- send_password_reset: returns confirmation string (no email actually sent)

FAILURE MODES:
- lookup_user: customer not found → "Account not found."
- send_password_reset: customer not found → "Cannot send reset: account not found."

# BUSINESS: Account data is customer-scoped — a customer can only look up their
#   own account, enforced by repos.customers.get customer scoping.
# INTERVIEW: "Why does send_password_reset not actually send an email?" Answer:
#   Stubbed for demo; in production would call an email gateway.
# INTERVIEW: "Why does lookup_user take no args?" Answer: It uses ctx.customer_id
#   from the authenticated session — no customer_id arg needed from the user.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from ..repositories import Repositories
from ..schemas import LookupUserArgs, SendPasswordResetArgs
from .base import ToolContext, execute


def make_account_tools(context: ToolContext) -> dict[str, Any]:
    @tool(args_schema=LookupUserArgs)
    def lookup_user() -> str:
        """Look up the current customer's own account details."""

        def _run(ctx: ToolContext, repos: Repositories, args: dict[str, Any]) -> str:
            customer = repos.customers.get(ctx.customer_id)
            if customer is None:
                return "Account not found."
            return (
                f"Account: {customer.name} ({customer.email}), "
                f"state={customer.state.value}, phone={customer.phone or 'N/A'}"
            )

        return execute(context, "account", "lookup_user", {}, _run)

    @tool(args_schema=SendPasswordResetArgs)
    def send_password_reset() -> str:
        """Send a password-reset link to the current customer's own email."""

        def _run(ctx: ToolContext, repos: Repositories, args: dict[str, Any]) -> str:
            customer = repos.customers.get(ctx.customer_id)
            if customer is None:
                return "Cannot send reset: account not found."
            return f"Password-reset link sent to {customer.email}."

        return execute(context, "account", "send_password_reset", {}, _run)

    return {"lookup_user": lookup_user, "send_password_reset": send_password_reset}

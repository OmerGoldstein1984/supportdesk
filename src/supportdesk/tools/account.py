"""Account tools: lookup_user, send_password_reset."""

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

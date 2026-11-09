"""Billing tools: get_invoice, issue_refund, change_plan.

The billing agent is allowlisted for exactly these three tools.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from ..repositories import Repositories
from ..schemas import ChangePlanArgs, GetInvoiceArgs, IssueRefundArgs
from .base import ToolContext, execute


def _invoice_text(inv: Any) -> str:
    if inv is None:
        return "Invoice not found or not accessible by your account."
    return (
        f"Invoice #{inv.id}: ${inv.amount:.2f}, status={inv.status.value}, "
        f"due={inv.due_date.date() if inv.due_date else 'N/A'}"
    )


def make_billing_tools(context: ToolContext) -> dict[str, Any]:
    @tool(args_schema=GetInvoiceArgs)
    def get_invoice(invoice_id: int) -> str:
        """Look up one of the current customer's invoices by id."""

        def _run(ctx: ToolContext, repos: Repositories, args: dict[str, Any]) -> str:
            inv = repos.invoices.get(ctx.customer_id, args["invoice_id"])
            return _invoice_text(inv)

        return execute(context, "billing", "get_invoice", {"invoice_id": invoice_id}, _run)

    @tool(args_schema=IssueRefundArgs)
    def issue_refund(invoice_id: int, amount: float) -> str:
        """Issue a refund for an invoice. Above the auto-approve threshold this
        returns an APPROVAL_REQUIRED marker so a human can approve/reject."""

        def _run(ctx: ToolContext, repos: Repositories, args: dict[str, Any]) -> str:
            inv = repos.invoices.get(ctx.customer_id, args["invoice_id"])
            if inv is None:
                return "Cannot refund: invoice not found or not accessible by your account."
            return f"Refund of ${args['amount']:.2f} for invoice #{inv.id} approved and processed."

        return execute(
            context,
            "billing",
            "issue_refund",
            {"invoice_id": invoice_id, "amount": amount},
            _run,
        )

    @tool(args_schema=ChangePlanArgs)
    def change_plan(plan_name: str) -> str:
        """Switch the current customer to a different plan."""

        def _run(ctx: ToolContext, repos: Repositories, args: dict[str, Any]) -> str:
            plan = repos.plans.by_name(args["plan_name"])
            if plan is None:
                return f"Plan '{args['plan_name']}' not found."
            repos.subscriptions.change_plan(ctx.customer_id, plan)
            return f"Plan changed to {plan.name} (${plan.price_monthly:.2f}/month)."

        return execute(context, "billing", "change_plan", {"plan_name": plan_name}, _run)

    return {"get_invoice": get_invoice, "issue_refund": issue_refund, "change_plan": change_plan}

"""Billing tools: get_invoice, issue_refund, change_plan.

WHAT: Factory producing the three billing-agent tools. Each tool is a LangChain
@tool with a Pydantic v2 args schema; every call passes through execute() which
runs the tool gate.

WHY: The billing agent is allowlisted for exactly these three tools — it can
never call a technical or account tool. This is separation of duties, a SOC2/
ISO 27001-style control.

WHY: Invoices, refunds, and plan changes are customer data. The repository layer
scopes every read/write by customer_id — a customer can never read another
customer's invoices.

INPUTS: ToolContext (session_factory, customer_id, conversation_id).
OUTPUTS: dict of {tool_name: LangChain tool}.

AGENT TOOLS:
- get_invoice: read-only invoice lookup, scoped to current customer
- issue_refund: refund an invoice; above threshold returns APPROVAL_REQUIRED
- change_plan: switch customer to a different plan; mutates subscription

FAILURE MODES:
- issue_refund: above refund_auto_approve_threshold ($100) → APPROVAL_REQUIRED
  marker → graph pauses for human approval
- change_plan: plan not found → "Plan '{name}' not found."
- get_invoice: not found/other customer → "Invoice not found or not accessible"

# GAP: issue_refund returns "approved and processed" but does NOT actually
#   persist a refund — stubbed for demo (see tools/base.py analysis)
# BUSINESS: Refunds above auto-approve threshold ($100) require human approval —
#   compliance control, business tunes the threshold without code changes
# INTERVIEW: "Why does issue_refund not actually refund?" Answer: It's stubbed
#   for the demo; in production it would call a payment gateway with idempotency
#   keys to prevent double-refunds.
# INTERVIEW: "Why > instead of >= for the refund threshold?" Answer: amount
#   exactly at threshold auto-approves — boundary bug for testing.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from ..repositories import Repositories
from ..schemas import ChangePlanArgs, GetInvoiceArgs, IssueRefundArgs
from .base import ToolContext, execute


def _invoice_text(inv: Any) -> str:
    """Format an invoice for display to the customer.

    WHAT: Formats invoice id, amount, status, due date into a readable string.
    Handles None gracefully.

    WHY: Consistent invoice display across the billing agent; guards against
    None invoice (not found or not accessible).

    INPUTS: inv (Invoice or None).
    OUTPUTS: formatted string.

    # BUSINESS: Invoice amounts and statuses are customer data — only shown to
    #   the owning customer (enforced by repos.invoices.get customer scoping).
    """
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

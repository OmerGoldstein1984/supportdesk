"""Pydantic v2 typed argument schemas for every LangChain tool.

WHAT: Typed Pydantic models for every tool's arguments. The tool gate validates
incoming arguments against the matching schema before any repository or LLM call.

WHY: Input validation at the system boundary — every tool call is validated
against its Pydantic schema before any repository or LLM call. This is defense
in depth: even if the LLM sends malformed arguments, they are rejected before
touching the database.

INPUTS: tool name + args dict.
OUTPUTS: validated Pydantic model instance.

FAILURE MODES:
- Pydantic ValidationError — must be caught by tool gate and turned into
  user-friendly error
- float for monetary amounts (IssueRefundArgs.amount) — floating-point rounding
  edge cases on financial data

# GAP: no customer_id field on tool schemas — scoping happens in repositories,
#   not validated at schema boundary
# GAP: no money type (Decimal, not float)
# GAP: no upper bound on text fields — huge body could DoS
# BUSINESS: Refund auto-approve threshold configured separately in config.py —
#   schema doesn't enforce it
# INTERVIEW: "Where does customer_id come from if it's not in the schemas?"
#   Answer: X-Customer-Id header (see main.py config.py)
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GetInvoiceArgs(BaseModel):
    invoice_id: int = Field(gt=0)


class IssueRefundArgs(BaseModel):
    invoice_id: int = Field(gt=0)
    amount: float = Field(gt=0, description="Refund amount in the invoice currency")


class ChangePlanArgs(BaseModel):
    plan_name: str = Field(min_length=1, description="Name of the plan to switch to")


class SearchKBArgs(BaseModel):
    query: str = Field(min_length=1, description="Knowledge-base search query")


class GetServiceStatusArgs(BaseModel):
    pass


class CreateBugTicketArgs(BaseModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)


class LookupUserArgs(BaseModel):
    pass


class SendPasswordResetArgs(BaseModel):
    pass


class CreateTicketArgs(BaseModel):
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)


class NotifyHumanArgs(BaseModel):
    message: str = Field(min_length=1)

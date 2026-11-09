"""Pydantic v2 typed argument schemas for every LangChain tool.

Each tool receives a validated Pydantic model; the tool gate validates incoming
arguments against the matching schema before any repository or LLM call.
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

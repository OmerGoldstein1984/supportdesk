"""Router agent: classifies intent, urgency, confidence (structured output, no tools)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..llm import llm


class RouterOutput(BaseModel):
    intent: str = Field(description="One of: billing, technical, account, escalation, other")
    urgency: str = Field(description="One of: low, medium, high, critical")
    confidence: float = Field(ge=0.0, le=1.0, description="Router confidence in the classification")
    reasoning: str = Field(description="Short justification")


router_chain = llm.structured(RouterOutput)

ROUTER_PROMPT = (
    "You are the router for a customer-support system. Classify the customer's "
    "message into one specialist: billing (invoices/refunds/plans), technical "
    "(errors/how-to/service status/bugs), account (login/password reset/profile), "
    "or escalation (angry/complex/unclear/other). Also estimate urgency and your "
    "confidence (0-1). Respond only with the structured fields."
)

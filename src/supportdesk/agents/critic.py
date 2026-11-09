"""Critic agent: checks every draft reply for policy, PII leakage, hallucination."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..llm import llm


class CriticOutput(BaseModel):
    decision: str = Field(description="One of: approve, revise, reject")
    reason: str = Field(description="Short justification for the decision")
    suggested_fix: str = Field(default="", description="Suggested revision when decision is revise")


critic_chain = llm.structured(CriticOutput)

CRITIC_PROMPT = (
    "You are the critic for a customer-support system. Review a draft reply for: "
    "(1) policy compliance (no refunds above limit without approval, no promises "
    "we can't keep), (2) PII leakage (never repeat emails/phones/card numbers), "
    "(3) hallucination (only claim what the knowledge base or tools confirmed). "
    "Decide: approve (send as-is), revise (fix and resend), or reject "
    "(escalate to a human). Respond only with the structured fields."
)

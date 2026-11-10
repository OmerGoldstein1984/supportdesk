"""Critic agent: checks every draft reply for policy, PII leakage, hallucination.

WHAT: Reviews every draft reply for three concerns: (1) policy compliance — no
refunds above limit without approval, no promises we can't keep; (2) PII leakage —
never repeat emails/phones/card numbers; (3) hallucination — only claim what the
knowledge base or tools confirmed. Decides approve / revise / reject.

WHY: The Critic is the safety net that makes the system interview-defensible.
Every customer-facing reply must pass this policy check before it's sent.

INPUTS: draft (str), message (str), policy_notes (str, optional).
OUTPUTS: CriticOutput (decision, reason, suggested_fix).

FAILURE MODES:
- LLM returns decision not in {approve, revise, reject} — Pydantic accepts as
  string; route_after_critic maps anything not "approve"/"revise" to escalation
- LLM call fails — no exception handling here; critic_node crashes the graph

# BUSINESS: The Critic prevents policy violations (e.g. promising refunds above
#   $100 without approval) from ever reaching the customer — direct regulatory
#   and reputation risk.
# INTERVIEW: "What's the difference between reject and escalation?" Answer: Critic
#   returns "reject", but route_after_critic only branches on "approve"/"revise";
#   anything else (including reject) goes to escalation.
# INTERVIEW: "How is the revise loop bounded?" Answer: route_after_critic checks
#   count < settings.max_revisions; over limit → escalation.
"""

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

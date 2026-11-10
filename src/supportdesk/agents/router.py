"""Router agent: classifies intent, urgency, confidence (structured output, no tools).

WHAT: Classifies the customer's message into one of five intents (billing, technical,
account, escalation, other), plus urgency (low/medium/high/critical) and confidence
(0-1). Uses LangChain structured output: the LLM must return JSON matching the
RouterOutput schema rather than free text. Router has no tools — pure classification.

WHY: The router is the triage stage of the supervisor graph. Its decision determines
which specialist handles the customer's message. A wrong classification wastes the
customer's time; low confidence routes to escalation as a safe default.

INPUTS: message (str), specialists (list of available specialist names).
OUTPUTS: RouterOutput (intent, urgency, confidence, reasoning).

FAILURE MODES:
- LLM returns intent not in allowed set (e.g., typo) — graph.py maps unknown intents
  to escalation (contained failure)
- Garbage confidence/urgency values flow downstream — Pydantic type-checking constrains
  the format but not semantic correctness
- LLM failure — caught by router_node's defensive try/except, which falls back to
  escalation with confidence 0.0

# GAP: Intent confidence thresholds are tuned in config.py (router_confidence_threshold).
  QA must test boundary values.
# BUSINESS: Low-confidence messages escalate to human — avoids confidently wrong answers
  at the cost of agent time.
# INTERVIEW: "Why does the router have no tools?" Answer: It only classifies intent;
  tool use happens in the specialist stage.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..llm import llm


class RouterOutput(BaseModel):
    """Router classification output.

    WHAT: Pydantic model with intent, urgency, confidence, reasoning fields.
    LangChain structured output constrains the LLM to return JSON matching this
    schema rather than free text.

    WHY: Structured output makes the router's decision machine-readable and
    validates intent/urgency/confidence ranges at parse time.

    FIELDS:
        intent - one of billing/technical/account/escalation/other
        urgency - one of low/medium/high/critical
        confidence - float 0.0-1.0
        reasoning - short justification

    FAILURE MODES:
        - LLM returns intent not in allowed set — Pydantic accepts as string;
          graph.py maps unknown intents to escalation
        - Garbage confidence/urgency — Pydantic type-checks format but not
          semantic correctness

    # INTERVIEW: "Can the router return an invalid intent?" Answer: Pydantic
    #   validates types but not enum membership; graph.py handles unknown intents
    #   by routing to escalation.
    """

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

"""Plain-code tool gate (LangChain middleware).

The gate enforces, for every tool call:

1. **Per-agent allowlist** — a billing agent can never call a technical tool,
   and vice versa.
2. **Schema validation** — arguments must match the tool's Pydantic v2 schema.
3. **Permission / customer scoping** — a customer can only touch their own
   data (enforced by the repository layer; the gate passes customer_id through).
4. **Risk policy** — refunds above ``refund_auto_approve_threshold`` are flagged
   ``requires_approval`` (human-in-the-loop), not silently executed.

The gate is deterministic and contains no LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from .config import settings
from .schemas import (
    ChangePlanArgs,
    CreateBugTicketArgs,
    CreateTicketArgs,
    GetInvoiceArgs,
    GetServiceStatusArgs,
    IssueRefundArgs,
    LookupUserArgs,
    NotifyHumanArgs,
    SearchKBArgs,
    SendPasswordResetArgs,
)

__all__ = ["GateVerdict", "ToolGate", "ValidationFailed", "RiskPolicyViolation"]

# Agent -> set of tool names it is allowed to call.
ALLOWLISTS: dict[str, set[str]] = {
    "router": set(),
    "billing": {"get_invoice", "issue_refund", "change_plan"},
    "technical": {"search_knowledge_base", "get_service_status", "create_bug_ticket"},
    "account": {"lookup_user", "send_password_reset"},
    "escalation": {"create_ticket", "notify_human_agent"},
    "critic": set(),
}

# Tool name -> Pydantic v2 args schema.
SCHEMAS: dict[str, type[BaseModel]] = {
    "get_invoice": GetInvoiceArgs,
    "issue_refund": IssueRefundArgs,
    "change_plan": ChangePlanArgs,
    "search_knowledge_base": SearchKBArgs,
    "get_service_status": GetServiceStatusArgs,
    "create_bug_ticket": CreateBugTicketArgs,
    "lookup_user": LookupUserArgs,
    "send_password_reset": SendPasswordResetArgs,
    "create_ticket": CreateTicketArgs,
    "notify_human_agent": NotifyHumanArgs,
}


class ValidationFailed(Exception):
    """Raised when a tool call fails allowlist or schema validation."""


class RiskPolicyViolation(Exception):
    """Raised when a tool call violates the risk policy and must be blocked."""


@dataclass
class GateVerdict:
    allowed: bool
    requires_approval: bool = False
    reason: str = ""
    validated_args: dict[str, Any] | None = None


@dataclass
class GateAuditEntry:
    agent: str
    tool_name: str
    customer_id: int | None
    conversation_id: str
    allowed: bool
    requires_approval: bool
    reason: str


class ToolGate:
    def __init__(self) -> None:
        # validation failure count per conversation id -> int
        self.validation_failures: dict[str, int] = {}
        # Append-only audit of every gate decision. No edit/delete methods are
        # provided here; production should ship these entries to a WORM/SIEM
        # store so they cannot be altered after the fact.
        self.audit_log: list[GateAuditEntry] = []

    def validate(
        self,
        agent: str,
        tool_name: str,
        args: dict[str, Any],
        customer_id: int | None = None,
        conversation_id: str = "default",
    ) -> GateVerdict:
        """Run the full gate: allowlist, schema, permission, risk policy."""
        allowed_tools = ALLOWLISTS.get(agent, set())

        # 1. Allowlist
        if tool_name not in allowed_tools:
            self._record_failure(conversation_id)
            verdict = GateVerdict(
                allowed=False,
                reason=f"{tool_name} is not allowlisted for the {agent} agent",
            )
            self._record_audit(agent, tool_name, customer_id, conversation_id, verdict)
            return verdict

        # 2. Schema validation
        schema = SCHEMAS.get(tool_name)
        if schema is not None:
            try:
                validated = schema.model_validate(args).model_dump()
            except ValidationError as exc:
                self._record_failure(conversation_id)
                verdict = GateVerdict(
                    allowed=False,
                    reason=f"schema validation failed for {tool_name}: {exc}",
                )
                self._record_audit(agent, tool_name, customer_id, conversation_id, verdict)
                return verdict
        else:
            validated = dict(args)

        # 3. Permission / customer scoping is enforced by repositories using
        #    customer_id; we just thread it through.
        # 4. Risk policy
        verdict = self._risk_policy(tool_name, validated)
        if not verdict.allowed:
            self._record_failure(conversation_id)
            self._record_audit(agent, tool_name, customer_id, conversation_id, verdict)
            return verdict
        verdict.validated_args = validated
        self._record_audit(agent, tool_name, customer_id, conversation_id, verdict)
        return verdict

    def _risk_policy(self, tool_name: str, args: dict[str, Any]) -> GateVerdict:
        if tool_name == "issue_refund":
            amount = float(args.get("amount", 0))
            if amount > settings.refund_auto_approve_threshold:
                return GateVerdict(
                    allowed=True,
                    requires_approval=True,
                    reason=(
                        f"refund amount {amount} exceeds auto-approve threshold "
                        f"{settings.refund_auto_approve_threshold}"
                    ),
                )
        return GateVerdict(allowed=True)

    def _record_failure(self, conversation_id: str) -> None:
        self.validation_failures[conversation_id] = (
            self.validation_failures.get(conversation_id, 0) + 1
        )

    def _record_audit(
        self,
        agent: str,
        tool_name: str,
        customer_id: int | None,
        conversation_id: str,
        verdict: GateVerdict,
    ) -> None:
        self.audit_log.append(
            GateAuditEntry(
                agent=agent,
                tool_name=tool_name,
                customer_id=customer_id,
                conversation_id=conversation_id,
                allowed=verdict.allowed,
                requires_approval=verdict.requires_approval,
                reason=verdict.reason,
            )
        )

    def failure_count(self, conversation_id: str = "default") -> int:
        return self.validation_failures.get(conversation_id, 0)

    def has_too_many_failures(self, conversation_id: str = "default") -> bool:
        return self.failure_count(conversation_id) >= settings.max_tool_validation_failures

    def reset_failures(self, conversation_id: str = "default") -> None:
        self.validation_failures.pop(conversation_id, None)


# Module-level gate instance used by all tools (plain-code middleware).
tool_gate = ToolGate()

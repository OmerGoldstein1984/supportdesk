"""Eval harness: runs the labeled ticket corpus through a deterministic fake
LLM and reports routing accuracy and tool-selection accuracy.

The harness is intentionally deterministic (no network, no NVIDIA API key) so
it is stable in CI. It installs a keyword-driven fake router, critic and
specialist LLM, instruments the tool gate to capture which tools are invoked,
and compares the results against the labels in ``data/labeled_tickets.json``.

Run::

    python -m supportdesk.evals.cli run [--sample] [--baseline]

Without ``--baseline`` the report is compared against the committed baseline
(``data/eval_baseline.json``) and the command fails if routing or tool-selection
accuracy drops below it (the CI eval gate).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, cast

from supportdesk import llm as llm_mod
from supportdesk import models
from supportdesk.agents import critic as critic_mod
from supportdesk.agents import router as router_mod
from supportdesk.agents.critic import CriticOutput
from supportdesk.agents.router import RouterOutput
from supportdesk.database import init_db, session_scope
from supportdesk.graph import run
from supportdesk.scripts.seed_data import main as seed_main

__all__ = ["run_eval", "write_report", "REPORT_PATH"]

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")
DATA_DIR = os.path.abspath(DATA_DIR)
REPORT_PATH = os.path.join(DATA_DIR, "eval_report.json")
BASELINE_PATH = os.path.join(DATA_DIR, "eval_baseline.json")

# Keyword-driven fake LLM so evals are fully deterministic.

_ROUTING_KEYWORDS = {
    "billing": [
        "refund",
        "invoice",
        "plan",
        "charge",
        "billing",
        "overcharged",
        "twice",
        "paid",
        "subscription",
    ],
    "account": ["password", "login", "account", "email", "locked", "unlock", "reset", "verify"],
    "technical": [
        "status",
        "api",
        "bug",
        "error",
        "crash",
        "how to",
        "knowledge",
        "article",
        "error 500",
        "export",
        "login page",
    ],
}


def _route(message: str) -> dict[str, Any]:
    m = message.lower()
    for specialist, kws in _ROUTING_KEYWORDS.items():
        if any(k in m for k in kws):
            return {
                "intent": specialist,
                "urgency": "medium",
                "confidence": 0.95,
                "reasoning": "keyword-eval",
            }
    return {
        "intent": "escalation",
        "urgency": "high",
        "confidence": 0.9,
        "reasoning": "keyword-eval",
    }


def _pick_tool(specialist: str, message: str) -> str | None:
    m = message.lower()
    if specialist == "billing":
        if "refund" in m:
            return "issue_refund"
        if "invoice" in m:
            return "get_invoice"
        if "plan" in m:
            return "change_plan"
        return "get_invoice"
    if specialist == "technical":
        if "status" in m or "api" in m or "down" in m:
            return "get_service_status"
        if "bug" in m or "crash" in m or "error" in m:
            return "create_bug_ticket"
        return "search_knowledge_base"
    if specialist == "account":
        if "password" in m or "reset" in m:
            return "send_password_reset"
        return "lookup_user"
    if specialist == "escalation":
        return "create_ticket"
    return None


def _tool_args(specialist: str, message: str) -> dict[str, Any]:
    m = message.lower()
    if specialist == "billing":
        return {"invoice_id": 50, "amount": 49.0}
    if specialist == "technical":
        if specialist == "technical" and ("bug" in m or "crash" in m):
            return {"title": "eval bug", "description": "eval description"}
        return {"query": message}
    if specialist == "account":
        return {}
    if specialist == "escalation":
        return {"subject": "eval case", "body": message}
    return {}


@dataclass
class CallCapture:
    calls: list[tuple[str, str, str]] = field(default_factory=list)  # (conv, agent, tool)

    def record(self, conv: str, agent: str, tool: str) -> None:
        self.calls.append((conv, agent, tool))


@dataclass
class EvalCase:
    ticket_id: int
    customer_id: int
    subject: str
    body: str
    expected_specialist: str
    expected_tool: str
    predicted_specialist: str | None = None
    predicted_tool: str | None = None
    routing_ok: bool = False
    tool_ok: bool = False
    final_reply: str = ""


class FakeResp:
    """Minimal fake LLM response mirroring tests.conftest.FakeResp (kept local so
    the eval harness does not depend on the test package)."""

    def __init__(self, content: Any = None, tool_calls: list[Any] | None = None):
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeRouter:
    def invoke(self, input: Any) -> RouterOutput:
        message = str(input.get("message", "")) if isinstance(input, dict) else str(input)
        return RouterOutput(**_route(message))


class _FakeCritic:
    def invoke(self, input: Any) -> CriticOutput:
        return CriticOutput(decision="approve", reason="eval", suggested_fix="")


class _FakeSpecialistLLM:
    def __init__(self, capture: CallCapture, conv: str) -> None:
        self.capture = capture
        self.conv = conv

    def bind_tools(self, tools: Any) -> "_FakeSpecialistLLM":
        return self

    def invoke(self, input: Any) -> Any:
        from tests.conftest import FakeResp

        text = " ".join((getattr(m, "content", "") or "") for m in input)
        specialist = None
        # infer specialist from the routing already stored on the input is not
        # available here; infer from message keywords instead.
        for s, kws in _ROUTING_KEYWORDS.items():
            if any(k in text.lower() for k in kws):
                specialist = s
                break
        specialist = specialist or "escalation"
        tool = _pick_tool(specialist, text)
        if tool:
            self.capture.record(self.conv, specialist, tool)
            return FakeResp(
                tool_calls=[{"name": tool, "args": _tool_args(specialist, text), "id": "t1"}]
            )
        return FakeResp("Draft reply based on the knowledge base.", tool_calls=[])


def _install_fakes(capture: CallCapture, conv: str) -> None:
    llm_mod.llm.primary = cast(Any, _FakeSpecialistLLM(capture, conv))
    llm_mod.llm.fallback = cast(Any, _FakeSpecialistLLM(capture, conv))
    router_mod.router_chain = _FakeRouter()
    critic_mod.critic_chain = _FakeCritic()


def _ensure_seed() -> None:
    init_db()
    with session_scope() as session:
        if session.query(models.Customer).count() == 0:
            seed_main([])


def _load_tickets() -> list[dict[str, Any]]:
    path = os.path.join(DATA_DIR, "labeled_tickets.json")
    with open(path) as f:
        return cast(list[dict[str, Any]], json.load(f))


def run_eval() -> list[EvalCase]:
    """Run the full labeled corpus and return per-case results."""
    _ensure_seed()
    tickets = _load_tickets()
    cases: list[EvalCase] = []
    for t in tickets:
        conv = f"eval_{t['ticket_id']}"
        capture = CallCapture()
        _install_fakes(capture, conv)
        body = t["body"]
        state = run(conv, t["customer_id"], body)
        calls_for_conv = [c for c in capture.calls if c[0] == conv]
        predicted_tool = calls_for_conv[0][2] if calls_for_conv else None
        case = EvalCase(
            ticket_id=t["ticket_id"],
            customer_id=t["customer_id"],
            subject=t["subject"],
            body=body,
            expected_specialist=t["expected_specialist"],
            expected_tool=t["expected_tool"],
            predicted_specialist=state.get("specialist"),
            predicted_tool=predicted_tool,
            routing_ok=state.get("specialist") == t["expected_specialist"],
            tool_ok=predicted_tool == t["expected_tool"],
            final_reply=state.get("final_reply") or "",
        )
        cases.append(case)
    return cases


def write_report(cases: list[EvalCase] | None = None) -> dict[str, Any]:
    """Compute metrics, write ``data/eval_report.json`` and return the metrics."""
    if cases is None:
        cases = run_eval()
    total = len(cases)
    routing_ok = sum(1 for c in cases if c.routing_ok)
    tool_ok = sum(1 for c in cases if c.tool_ok)
    metrics = {
        "total_cases": total,
        "routing_accuracy": round(routing_ok / total, 4) if total else 0.0,
        "tool_selection_accuracy": round(tool_ok / total, 4) if total else 0.0,
        "routing_correct": routing_ok,
        "tool_correct": tool_ok,
        "cases": [
            {
                "ticket_id": c.ticket_id,
                "customer_id": c.customer_id,
                "subject": c.subject,
                "expected_specialist": c.expected_specialist,
                "predicted_specialist": c.predicted_specialist,
                "routing_ok": c.routing_ok,
                "expected_tool": c.expected_tool,
                "predicted_tool": c.predicted_tool,
                "tool_ok": c.tool_ok,
            }
            for c in cases
        ],
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        json.dump(metrics, f, indent=2)
    return metrics


def load_baseline() -> dict[str, Any] | None:
    if not os.path.exists(BASELINE_PATH):
        return None
    with open(BASELINE_PATH) as f:
        return cast(dict[str, Any] | None, json.load(f))

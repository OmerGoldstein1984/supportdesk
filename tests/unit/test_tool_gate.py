"""Unit tests for the plain-code tool gate (allowlist, schema, risk policy)."""

import pytest

from supportdesk.tool_gate import ALLOWLISTS, tool_gate

pytestmark = pytest.mark.unit


def test_allowlist_blocks_cross_agent_tool():
    verdict = tool_gate.validate("billing", "search_knowledge_base", {"query": "x"}, customer_id=1)
    assert verdict.allowed is False
    assert "not allowlisted" in verdict.reason


def test_router_and_critic_have_empty_allowlist():
    assert ALLOWLISTS["router"] == set()
    assert ALLOWLISTS["critic"] == set()


def test_schema_validation_rejects_bad_args():
    verdict = tool_gate.validate(
        "billing", "issue_refund", {"invoice_id": -5, "amount": 10}, customer_id=1
    )
    assert verdict.allowed is False
    assert "schema validation" in verdict.reason


def test_schema_validation_accepts_good_args():
    verdict = tool_gate.validate("billing", "get_invoice", {"invoice_id": 7}, customer_id=1)
    assert verdict.allowed is True
    assert verdict.validated_args == {"invoice_id": 7}


def test_refund_over_threshold_requires_approval():
    verdict = tool_gate.validate(
        "billing", "issue_refund", {"invoice_id": 50, "amount": 250.0}, customer_id=1
    )
    assert verdict.allowed is True
    assert verdict.requires_approval is True
    assert "exceeds" in verdict.reason


def test_refund_under_threshold_auto_approves():
    verdict = tool_gate.validate(
        "billing", "issue_refund", {"invoice_id": 50, "amount": 49.0}, customer_id=1
    )
    assert verdict.allowed is True
    assert verdict.requires_approval is False


def test_validation_failures_trigger_limit():
    tool_gate.reset_failures("conv")
    for _ in range(2):
        tool_gate.validate(
            "billing",
            "issue_refund",
            {"invoice_id": -1, "amount": 1},
            customer_id=1,
            conversation_id="conv",
        )
    assert tool_gate.has_too_many_failures("conv") is True
    tool_gate.reset_failures("conv")
    assert tool_gate.has_too_many_failures("conv") is False

"""Unit tests for the LangChain tools (billing, technical, account)."""

import pytest

from supportdesk.database import session_scope
from supportdesk.tools import tools_for
from supportdesk.tools.base import ToolContext


@pytest.fixture
def ctx(seeded_db):
    return ToolContext(session_scope, 1, "tool-test")


def test_billing_get_invoice(ctx):
    tools = tools_for("billing")(ctx)
    out = tools["get_invoice"].invoke({"invoice_id": 50})
    assert "Invoice #50" in out


def test_billing_get_invoice_missing(ctx):
    tools = tools_for("billing")(ctx)
    out = tools["get_invoice"].invoke({"invoice_id": 99999})
    assert "not found" in out.lower()


def test_billing_issue_refund_under_threshold(ctx):
    tools = tools_for("billing")(ctx)
    out = tools["issue_refund"].invoke({"invoice_id": 50, "amount": 49.0})
    assert "approved and processed" in out


def test_billing_change_plan(ctx):
    tools = tools_for("billing")(ctx)
    out = tools["change_plan"].invoke({"plan_name": "Premium"})
    assert "Premium" in out


def test_technical_service_status(ctx):
    tools = tools_for("technical")(ctx)
    out = tools["get_service_status"].invoke({})
    assert "Service status:" in out


def test_technical_search_kb(ctx):
    tools = tools_for("technical")(ctx)
    out = tools["search_knowledge_base"].invoke({"query": "password"})
    assert isinstance(out, str)


def test_account_lookup_and_reset(ctx):
    tools = tools_for("account")(ctx)
    out = tools["lookup_user"].invoke({})
    assert "Test User" in out
    out = tools["send_password_reset"].invoke({})
    assert "Test User" in out or "reset" in out.lower()


def test_escalation_create_ticket(ctx):
    tools = tools_for("escalation")(ctx)
    out = tools["create_ticket"].invoke({"subject": "x", "body": "y"})
    assert "ticket" in out.lower()


pytestmark = pytest.mark.unit

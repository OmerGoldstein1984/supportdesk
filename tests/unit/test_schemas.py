"""Unit tests for Pydantic v2 tool-argument schemas."""

import pytest
from pydantic import ValidationError

from supportdesk.schemas import (
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

pytestmark = pytest.mark.unit


def test_get_invoice():
    assert GetInvoiceArgs(invoice_id=3).invoice_id == 3
    try:
        GetInvoiceArgs(invoice_id=0)
        raise AssertionError("should fail")
    except ValidationError:
        pass


def test_issue_refund():
    assert IssueRefundArgs(invoice_id=1, amount=10.0).amount == 10.0
    try:
        IssueRefundArgs(invoice_id=1, amount=0)
        raise AssertionError("should fail")
    except ValidationError:
        pass


def test_change_plan():
    assert ChangePlanArgs(plan_name="Premium").plan_name == "Premium"
    try:
        ChangePlanArgs(plan_name="")
        raise AssertionError("should fail")
    except ValidationError:
        pass


def test_search_kb():
    assert SearchKBArgs(query="refund").query == "refund"


def test_no_arg_schemas():
    GetServiceStatusArgs()
    LookupUserArgs()
    SendPasswordResetArgs()


def test_create_ticket():
    assert CreateTicketArgs(subject="x", body="y").subject == "x"
    assert NotifyHumanArgs(message="hi").message == "hi"
    assert CreateBugTicketArgs(title="t", description="d").title == "t"

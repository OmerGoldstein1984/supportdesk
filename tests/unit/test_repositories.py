"""Unit tests for the repository layer (customer-scoped data access)."""

from datetime import datetime, timedelta

import pytest

from supportdesk import models
from supportdesk.repositories import Repositories

pytestmark = pytest.mark.unit


@pytest.fixture
def repos(db_session):
    return Repositories(db_session)


def test_customer_crud(repos):
    c = repos.customers.create("Ada Lovelace", "ada@example.com", "+1-555-000-0001")
    assert c.id is not None
    got = repos.customers.get(c.id)
    assert got.name == "Ada Lovelace"
    assert got.state == models.AccountState.ACTIVE
    by_email = repos.customers.get_by_email("ada@example.com")
    assert by_email.id == c.id


def test_invoice_scoped_by_customer(repos, seeded_db):
    c = repos.customers.create("Bob", "bob@example.com")
    inv = repos.invoices.get(c.id, 999)
    assert inv is None  # not this customer's / doesn't exist
    # cross-customer: invoice 50 belongs to customer 1, not c
    inv50 = repos.invoices.get(c.id, 50)
    assert inv50 is None


def test_invoice_overdue_and_mark_paid(repos):
    # customer 1 has invoice 50 (paid) and 120 (paid in seed); create an overdue one
    c = repos.customers.create("Overdue User", "overdue@example.com")
    inv = models.Invoice(
        customer_id=c.id,
        amount=100.00,
        status=models.InvoiceStatus.OVERDUE,
        due_date=datetime.utcnow() - timedelta(days=5),
    )
    repos.session.add(inv)
    repos.session.flush()
    overdue = repos.invoices.overdue_for_customer(c.id)
    assert any(i.id == inv.id for i in overdue)
    repos.invoices.mark_paid(inv)
    assert inv.status == models.InvoiceStatus.PAID


def test_plan_and_subscription(repos):
    p = models.Plan(name="Premium Test", price_monthly=99.00, features="x")
    repos.session.add(p)
    repos.session.flush()
    found = repos.plans.by_name("Premium Test")
    assert found is not None
    assert float(found.price_monthly) == 99.0
    c = repos.customers.create("Plan User", "plan@example.com")
    sub = repos.subscriptions.change_plan(c.id, found)
    assert sub.plan_id == found.id
    cur = repos.subscriptions.current_for_customer(c.id)
    assert cur.plan_id == found.id


def test_payment_failures(repos):
    c = repos.customers.create("Fail User", "fail@example.com")
    repos.payment_failures.recent_for_customer(c.id)  # empty ok
    pf = models.PaymentFailure(
        customer_id=c.id, amount=10.00, reason="card_expired", failed_at=datetime.utcnow()
    )
    repos.session.add(pf)
    repos.session.flush()
    recent = repos.payment_failures.recent_for_customer(c.id)
    assert len(recent) == 1


def test_ticket_crud(repos):
    c = repos.customers.create("Ticket User", "ticket@example.com")
    t = repos.tickets.create(c.id, "subject", "body", specialist="billing")
    assert t.id is not None
    got = repos.tickets.get(c.id, t.id)
    assert got.subject == "subject"
    assert repos.tickets.get(99999, t.id) is None  # wrong customer
    listed = repos.tickets.list_for_customer(c.id)
    assert len(listed) == 1


def test_article_search(repos):
    repos.articles.list_all()  # exercises the list path
    results = repos.articles.search("password")
    assert isinstance(results, list)


def test_incident_status(repos):
    assert repos.incidents.get_status() in {
        models.IncidentStatus.HEALTHY,
        models.IncidentStatus.DEGRADED,
        models.IncidentStatus.OUTAGE,
    }
    active = repos.incidents.active_incidents()
    assert isinstance(active, list)

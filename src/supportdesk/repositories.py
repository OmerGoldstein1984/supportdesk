"""Repository layer.

All customer-facing reads/writes are scoped by ``customer_id``. A repository
method that takes ``customer_id`` will never return a row owned by a different
customer, which is how we enforce "a customer cannot access another customer's
data" at the data layer (not just in the LLM).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from . import models


class CustomerRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, customer_id: int) -> Optional[models.Customer]:
        return self.session.get(models.Customer, customer_id)

    def get_by_email(self, email: str) -> Optional[models.Customer]:
        return self.session.query(models.Customer).filter(models.Customer.email == email).first()

    def create(self, name: str, email: str, phone: str | None = None) -> models.Customer:
        customer = models.Customer(name=name, email=email, phone=phone)
        self.session.add(customer)
        self.session.flush()
        return customer


class InvoiceRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, customer_id: int, invoice_id: int) -> Optional[models.Invoice]:
        return (
            self.session.query(models.Invoice)
            .filter(models.Invoice.id == invoice_id, models.Invoice.customer_id == customer_id)
            .first()
        )

    def list_for_customer(self, customer_id: int, limit: int = 10) -> list[models.Invoice]:
        return (
            self.session.query(models.Invoice)
            .filter(models.Invoice.customer_id == customer_id)
            .order_by(models.Invoice.id.desc())
            .limit(limit)
            .all()
        )

    def overdue_for_customer(self, customer_id: int) -> list[models.Invoice]:
        return (
            self.session.query(models.Invoice)
            .filter(
                models.Invoice.customer_id == customer_id,
                models.Invoice.status == models.InvoiceStatus.OVERDUE,
            )
            .all()
        )

    def mark_paid(self, invoice: models.Invoice) -> None:
        invoice.status = models.InvoiceStatus.PAID
        invoice.paid_at = datetime.now(timezone.utc)
        self.session.add(invoice)


class PlanRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[models.Plan]:
        return self.session.query(models.Plan).all()

    def get(self, plan_id: int) -> Optional[models.Plan]:
        return self.session.get(models.Plan, plan_id)

    def by_name(self, name: str) -> Optional[models.Plan]:
        return self.session.query(models.Plan).filter(models.Plan.name.ilike(f"%{name}%")).first()


class SubscriptionRepository:
    def __init__(self, session: Session):
        self.session = session

    def current_for_customer(self, customer_id: int) -> Optional[models.Subscription]:
        return (
            self.session.query(models.Subscription)
            .filter(models.Subscription.customer_id == customer_id)
            .order_by(models.Subscription.id.desc())
            .first()
        )

    def change_plan(self, customer_id: int, plan: models.Plan) -> models.Subscription:
        sub = self.current_for_customer(customer_id)
        if sub is None:
            sub = models.Subscription(customer_id=customer_id, plan_id=plan.id)
            self.session.add(sub)
        else:
            sub.plan_id = plan.id
            sub.status = "active"
            sub.end_date = None
        self.session.add(sub)
        self.session.flush()
        return sub


class PaymentFailureRepository:
    def __init__(self, session: Session):
        self.session = session

    def recent_for_customer(self, customer_id: int, days: int = 30) -> list[models.PaymentFailure]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return (
            self.session.query(models.PaymentFailure)
            .filter(
                models.PaymentFailure.customer_id == customer_id,
                models.PaymentFailure.failed_at >= cutoff,
            )
            .all()
        )


class TicketRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, customer_id: int, ticket_id: int) -> Optional[models.Ticket]:
        return (
            self.session.query(models.Ticket)
            .filter(models.Ticket.id == ticket_id, models.Ticket.customer_id == customer_id)
            .first()
        )

    def create(
        self,
        customer_id: int,
        subject: str,
        body: str,
        specialist: str | None = None,
    ) -> models.Ticket:
        ticket = models.Ticket(
            customer_id=customer_id,
            subject=subject,
            body=body,
            specialist=specialist,
        )
        self.session.add(ticket)
        self.session.flush()
        return ticket

    def list_for_customer(self, customer_id: int, limit: int = 10) -> list[models.Ticket]:
        return (
            self.session.query(models.Ticket)
            .filter(models.Ticket.customer_id == customer_id)
            .order_by(models.Ticket.id.desc())
            .limit(limit)
            .all()
        )


class ArticleRepository:
    def __init__(self, session: Session):
        self.session = session

    def search(self, query: str, limit: int = 5) -> list[models.Article]:
        """Simple keyword search over title/content (replaced by RAG in prod).

        Outdated articles are still returned (flagged) so the system can be
        tested against conflicting/outdated knowledge.
        """
        like = f"%{query}%"
        return (
            self.session.query(models.Article)
            .filter((models.Article.title.ilike(like)) | (models.Article.content.ilike(like)))
            .limit(limit)
            .all()
        )

    def list_all(self) -> list[models.Article]:
        return self.session.query(models.Article).all()


class ServiceIncidentRepository:
    def __init__(self, session: Session):
        self.session = session

    def active_incidents(self) -> list[models.ServiceIncident]:
        return (
            self.session.query(models.ServiceIncident)
            .filter(models.ServiceIncident.status != models.IncidentStatus.HEALTHY)
            .all()
        )

    def get_status(self) -> models.IncidentStatus:
        incidents = self.active_incidents()
        if any(i.status == models.IncidentStatus.OUTAGE for i in incidents):
            return models.IncidentStatus.OUTAGE
        if any(i.status == models.IncidentStatus.DEGRADED for i in incidents):
            return models.IncidentStatus.DEGRADED
        return models.IncidentStatus.HEALTHY


class Repositories:
    """Aggregate holding every repository for a single session."""

    def __init__(self, session: Session):
        self.session = session
        self.customers = CustomerRepository(session)
        self.invoices = InvoiceRepository(session)
        self.plans = PlanRepository(session)
        self.subscriptions = SubscriptionRepository(session)
        self.payment_failures = PaymentFailureRepository(session)
        self.tickets = TicketRepository(session)
        self.articles = ArticleRepository(session)
        self.incidents = ServiceIncidentRepository(session)

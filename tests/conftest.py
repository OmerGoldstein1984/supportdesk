"""Pytest configuration and shared fixtures.

Tests run against a throwaway SQLite database (``test.db``) and use a fake LLM
so nothing touches the network or the NVIDIA Build API.
"""

from __future__ import annotations

from typing import Any, Iterator, cast

import pytest  # noqa: E402
from sqlalchemy import StaticPool, create_engine, delete
from sqlalchemy.orm import Session, sessionmaker

from supportdesk import llm as llm_mod  # noqa: E402
from supportdesk import models  # noqa: E402
from supportdesk.agents import critic as critic_mod  # noqa: E402
from supportdesk.agents import router as router_mod  # noqa: E402
from supportdesk.agents.critic import CriticOutput  # noqa: E402
from supportdesk.agents.router import RouterOutput  # noqa: E402
from supportdesk.database import init_db, session_scope  # noqa: E402


class FakeResp:
    def __init__(self, content: Any = None, tool_calls: list[Any] | None = None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakePrimary:
    def __init__(self, responses: list[FakeResp] | None = None):
        self.responses = list(responses or [])
        self.calls = 0

    def bind_tools(self, tools: Any) -> FakePrimary:
        return self

    def invoke(self, input: Any) -> FakeResp:
        self.calls += 1
        if self.responses:
            return self.responses.pop(0)
        return FakeResp("default reply", tool_calls=[])


class FakeStructured:
    def __init__(self, output: Any):
        self.output = output

    def invoke(self, input: Any) -> Any:
        return self.output


# All domain models, used to tear down test data between tests.
_MODELS = (
    models.Ticket,
    models.PaymentFailure,
    models.Invoice,
    models.Subscription,
    models.Article,
    models.ServiceIncident,
    models.Customer,
    models.Plan,
)


def _clear_tables(session: Session) -> None:
    for model in _MODELS:
        session.execute(delete(cast(Any, model.__table__)))


@pytest.fixture(scope="session", autouse=True)
def _db_schema() -> Iterator[None]:
    """Create the schema once per session on a hermetic in-memory SQLite DB.

    The default ``test.db`` is a shared file that persisted rows between runs
    (stale customer/invoice ids caused flaky primary-key conflicts on re-runs).
    We bind the module engine/session to a fresh ``sqlite:///:memory:`` database
    (StaticPool so every connection shares the same in-memory DB) so each test
    session starts empty and nothing is written to disk.
    """
    import supportdesk.database as database

    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    database._engine = test_engine
    database.SessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    init_db()
    yield


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A SQLAlchemy session backed by the hermetic in-memory test DB, cleaned
    after each test so tests never leak state into one another."""
    with session_scope() as session:
        yield session
    with session_scope() as session:
        _clear_tables(session)


@pytest.fixture
def seeded_db(db_session: Session) -> Session:
    db_session.execute(
        delete(cast(Any, models.Invoice.__table__)).where(models.Invoice.customer_id == 1)
    )
    db_session.execute(delete(cast(Any, models.Customer.__table__)).where(models.Customer.id == 1))
    customer = models.Customer(id=1, name="Test User", email="t@example.com", state="active")
    db_session.add(customer)
    db_session.add(models.Invoice(id=50, customer_id=1, amount=49.00, status="paid"))
    db_session.add(models.Invoice(id=120, customer_id=1, amount=250.00, status="paid"))
    db_session.commit()
    return db_session


@pytest.fixture
def install_fake_llm(monkeypatch: Any) -> Any:
    """Install a configurable fake LLM; returns the FakePrimary for the specialist."""

    def _install(
        router_output: Any = None,
        critic_output: Any = None,
        specialist_responses: list[FakeResp] | None = None,
    ) -> FakePrimary:
        primary = FakePrimary(specialist_responses or [])
        monkeypatch.setattr(llm_mod.llm, "primary", primary)
        monkeypatch.setattr(llm_mod.llm, "fallback", FakePrimary())
        monkeypatch.setattr(
            router_mod,
            "router_chain",
            FakeStructured(
                router_output
                or RouterOutput(
                    intent="billing",
                    urgency="medium",
                    confidence=0.9,
                    reasoning="x",
                )
            ),
        )
        monkeypatch.setattr(
            critic_mod,
            "critic_chain",
            FakeStructured(
                critic_output
                or CriticOutput(
                    decision="approve",
                    reason="ok",
                    suggested_fix="",
                )
            ),
        )
        return primary

    return _install

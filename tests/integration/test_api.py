"""Integration tests for the FastAPI API (TestClient, fake LLM)."""

import pytest
from fastapi.testclient import TestClient

from supportdesk.main import RATE_LIMIT_REQUESTS, app

pytestmark = pytest.mark.integration


def _install(monkeypatch, responses=None):
    import supportdesk.agents.critic as critic_mod
    import supportdesk.agents.router as router_mod
    import supportdesk.llm as llm_mod
    from supportdesk.agents.critic import CriticOutput
    from supportdesk.agents.router import RouterOutput
    from tests.conftest import FakePrimary, FakeResp, FakeStructured

    primary = FakePrimary(responses or [FakeResp("hello", tool_calls=[])])
    monkeypatch.setattr(llm_mod.llm, "primary", primary)
    monkeypatch.setattr(llm_mod.llm, "fallback", FakePrimary())
    monkeypatch.setattr(
        router_mod,
        "router_chain",
        FakeStructured(
            RouterOutput(intent="billing", urgency="medium", confidence=0.9, reasoning="x")
        ),
    )
    monkeypatch.setattr(
        critic_mod,
        "critic_chain",
        FakeStructured(CriticOutput(decision="approve", reason="ok", suggested_fix="")),
    )
    return primary


def test_chat_complete(monkeypatch, seeded_db):
    _install(monkeypatch)
    client = TestClient(app)
    r = client.post(
        "/chat",
        json={"conversation_id": "c1", "customer_id": 1, "message": "hi"},
        headers={"X-Customer-Id": "1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "complete"
    assert body["final_reply"] == "hello"


def test_chat_awaits_approval_then_resume(monkeypatch, seeded_db):
    from tests.conftest import FakeResp

    primary = _install(
        monkeypatch,
        responses=[
            FakeResp(
                tool_calls=[
                    {
                        "name": "issue_refund",
                        "args": {"invoice_id": 120, "amount": 250.0},
                        "id": "tc1",
                    }
                ]
            ),
            FakeResp("pending", tool_calls=[]),
        ],
    )
    client = TestClient(app)
    r = client.post(
        "/chat",
        json={"conversation_id": "c2", "customer_id": 1, "message": "refund $250"},
        headers={"X-Customer-Id": "1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "awaiting_approval"
    assert body["interrupt"]["invoice_id"] == 120
    assert body["interrupt"]["amount"] == 250.0

    r2 = client.post("/approve", json={"conversation_id": "c2", "approve": True, "note": "ok"})
    assert r2.status_code == 200
    assert "approved and processed" in r2.json()["final_reply"]

    # rejection
    primary.responses = [
        FakeResp(
            tool_calls=[
                {"name": "issue_refund", "args": {"invoice_id": 120, "amount": 250.0}, "id": "tc1"}
            ]
        ),
        FakeResp("pending", tool_calls=[]),
    ]
    r3 = client.post(
        "/chat",
        json={"conversation_id": "c3", "customer_id": 1, "message": "refund $250"},
        headers={"X-Customer-Id": "1"},
    )
    assert r3.json()["status"] == "awaiting_approval"
    r4 = client.post("/approve", json={"conversation_id": "c3", "approve": False, "note": "nope"})
    assert "rejected" in r4.json()["final_reply"].lower()


def test_trace_endpoint(monkeypatch, seeded_db):
    _install(monkeypatch)
    client = TestClient(app)
    client.post(
        "/chat",
        json={"conversation_id": "c4", "customer_id": 1, "message": "hi"},
        headers={"X-Customer-Id": "1"},
    )
    r = client.get("/trace/c4")
    assert r.status_code == 200
    assert r.json()["conversation_id"] == "c4"


def test_chat_requires_auth_header(monkeypatch, seeded_db):
    """Security: /chat must require an X-Customer-Id header.

    The body's customer_id is no longer trusted (a client could spoof it to read
    another customer's invoices, tickets, and refunds). A request with no auth
    header is rejected instead of being allowed to impersonate any customer."""
    _install(monkeypatch)
    client = TestClient(app)
    r = client.post(
        "/chat",
        json={"conversation_id": "c_auth", "customer_id": 99, "message": "hi"},
        # deliberately no X-Customer-Id header
    )
    assert r.status_code == 422, "missing auth header must be rejected"


def test_rate_limit_blocks_excess_requests(monkeypatch, seeded_db):
    """Rate limit: beyond the per-minute per-customer limit, /chat returns 429.

    Characterization (before this fix): /chat had NO rate limit, so 35 rapid
    calls all returned 200 (see the now-removed test_chat_has_no_rate_limit_yet).
    Now the first 30 return 200 and calls 31-35 return 429, proving abusive
    clients are throttled instead of running up LLM cost."""
    _install(monkeypatch)
    client = TestClient(app)
    statuses = []
    for i in range(35):
        r = client.post(
            "/chat",
            json={
                "conversation_id": f"c_rl_{i}",
                "customer_id": 999,
                "message": "hi",
            },
            headers={"X-Customer-Id": "999"},
        )
        statuses.append(r.status_code)
    assert statuses.count(200) == RATE_LIMIT_REQUESTS
    assert statuses.count(429) == 35 - RATE_LIMIT_REQUESTS

"""Integration tests for the FastAPI API (TestClient, fake LLM)."""

import pytest
from fastapi.testclient import TestClient

from supportdesk.main import app

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
    r = client.post("/chat", json={"conversation_id": "c1", "customer_id": 1, "message": "hi"})
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
        "/chat", json={"conversation_id": "c2", "customer_id": 1, "message": "refund $250"}
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
        "/chat", json={"conversation_id": "c3", "customer_id": 1, "message": "refund $250"}
    )
    assert r3.json()["status"] == "awaiting_approval"
    r4 = client.post("/approve", json={"conversation_id": "c3", "approve": False, "note": "nope"})
    assert "rejected" in r4.json()["final_reply"].lower()


def test_trace_endpoint(monkeypatch, seeded_db):
    _install(monkeypatch)
    client = TestClient(app)
    client.post("/chat", json={"conversation_id": "c4", "customer_id": 1, "message": "hi"})
    r = client.get("/trace/c4")
    assert r.status_code == 200
    assert r.json()["conversation_id"] == "c4"

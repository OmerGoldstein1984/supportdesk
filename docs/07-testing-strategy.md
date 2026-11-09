# SupportDesk — testing strategy

## The test pyramid

```
        /\
       /  \      E2E   (docker compose up, full HTTP scenarios)
      /    \    -----------------------------
     /      \   Eval   (labeled corpus, routing/tool accuracy, CI gate)
    /--------\  -----------------------------------------
   /          \ Integration  (agents + tools + real DB,
  /            \             FastAPI TestClient, fake LLM)
 /______________\____________________________
/                                            \
Unit  (fast, no network, fake LLM, 85% coverage)
```

### Unit — fast, no network, fake LLM
**Proves:** each building block is correct in isolation.
- Tool schemas (Pydantic v2 args validate/reject correctly)
- Tool-gate allowlist enforcement (billing can't call technical tools)
- Risk policy and refund threshold ($100 auto-approve limit)
- Tool-gate middleware (blocked / approval-required markers)
- Router output parsing (intent, urgency, confidence)
- Confidence fallback logic (below threshold → escalation)
- Critic decision logic (approve / revise / reject)
- PII redaction (emails, phones, cards, SSNs)
- Config loading from environment variables
- **Coverage gate: 85% on core logic** (enforced in CI)

### Integration — agents + tools + real database
**Proves:** the pieces work together with real state.
- Agents + tools + real database (SQLite in CI)
- RAG with a real query path over the seeded KB
- FastAPI endpoints via `TestClient` (`/chat`, `/approve`, `/trace`)
- Human-in-the-loop interrupt and resume with a real checkpointer
- Fallback paths to Escalation (low confidence, failed validations, critic
  rejection)
- Retry and model-fallback behavior (fake/recorded LLM in CI so it's stable)

### E2E — full HTTP scenarios against `docker compose up`
**Proves:** the system runs end-to-end as deployed.
- Standard refund
- Refund over threshold with approval and rejection
- Password reset
- Technical question with cited answer
- Outage-aware reply
- Multi-intent message
- Low-confidence escalation
- Critic rejection then revision
- Prompt injection blocked
- Cross-customer data access denied

**Markers:** `pytest -m "e2e"` (requires a running server).

### Eval — separate from tests
**Proves:** the quality of non-deterministic agent decisions, not just code
correctness.
- Runs the 150+ labeled ticket corpus through a deterministic fake LLM
- Reports **routing accuracy** and **tool-selection accuracy**
- Compared against a **committed baseline**; CI fails if accuracy drops more
  than 5 points (regression gate)
- A small live-LLM smoke suite runs against the NVIDIA Build API on demand and
  nightly, not on every commit

**Markers:** `pytest -m "eval"`

## How to run

```bash
# Unit + integration (CI-stable, fake LLM, SQLite)
pytest -m "unit or integration" -q

# Full suite (includes evals)
pytest -q

# Coverage on core logic (gate: 85%)
pytest -m "unit or integration" --cov=supportdesk --cov-report=term

# Evals on the labeled corpus
pytest -m "eval" -q
```

## Evals vs tests — the difference

| | Tests | Evals |
|---|---|---|
| What they check | Code correctness (did the gate block this call?) | Agent decision quality (did it pick the right specialist?) |
| Determinism | Fully deterministic (fake LLM) | Decision quality over a corpus |
| Fail mode | A test fails (assertion error) | Accuracy drops below baseline |
| Speed | Fast (seconds) | Slower (runs the full corpus) |
| Where | `tests/` | `src/supportdesk/evals/` + `data/eval_baseline.json` |
| CI role | Gate on every commit | Regression gate; can run on demand/nightly with live LLM |

## Markers

- `unit` — fast, no network, fake LLM
- `integration` — agents + tools + real database + FastAPI TestClient
- `e2e` — full HTTP scenarios against a running server
- `eval` — labeled ticket corpus, routing/tool accuracy, LLM-as-judge

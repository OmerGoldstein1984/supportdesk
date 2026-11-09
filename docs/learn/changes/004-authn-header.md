# Change record 004 — Authenticate callers via X-Customer-Id header (fix P0-1)

## PROBLEM
``POST /chat`` accepted ``customer_id`` from the request body and passed it
straight into the graph with no proof the caller *is* that customer:

```python
def chat(req: ChatRequest) -> ChatResponse:
    result = run(req.conversation_id, req.customer_id, req.message)
```

A client could send ``{"customer_id": 42, ...}`` and read customer 42's
invoices, tickets, and refunds. The repository layer scopes reads to the given
customer, but nothing verified the caller's identity — the highest-severity
issue in the repo (documented in docs/08 as limitation #3, "No authentication
beyond customer-ID scoping").

## IMPACT
- **Security / data exposure:** cross-customer data access — a caller can read
  any customer's invoices, refunds, and support tickets. Money, trust, and
  compliance impact.
- **Integrity:** a caller can trigger actions (tickets, refunds) on another
  customer's account.

## ORIGINAL (learn/annotated)
`src/supportdesk/main.py`:
```python
@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    result = run(req.conversation_id, req.customer_id, req.message)
```

## FIX
Add a FastAPI dependency that resolves the caller's identity from a
server-trusted header (``X-Customer-Id``) and use it instead of the body's
``customer_id``:

`src/supportdesk/main.py`:
```python
from fastapi import Depends, FastAPI, Header

app = FastAPI(title="SupportDesk", version="0.1.0")


def get_current_customer_id(x_customer_id: int = Header(alias="X-Customer-Id")) -> int:
    """Resolve the caller's identity from a server-trusted header.

    The request body's customer_id is not trusted ... X-Customer-Id is the
    authoritative caller identity ... and is required on the chat endpoint.
    """
    return x_customer_id


@app.post("/chat", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    current_customer_id: int = Depends(get_current_customer_id),
) -> ChatResponse:
    result = run(req.conversation_id, current_customer_id, req.message)
```

The body's ``customer_id`` field is kept in ``ChatRequest`` for backward
compatibility but is **not** used for authorization — the header is authoritative.
A request without ``X-Customer-Id`` is rejected with 422 (FastAPI, because the
header is required). Updated ``tests/integration/test_api.py`` to send the header
and added ``test_chat_requires_auth_header`` (no header → 422).

## WHY THIS WAY
Three alternatives considered:
1. **Keep trusting body customer_id (status quo)** — rejected: cross-customer
   data access, the P0 finding.
2. **Full OAuth2 / JWT authN** — rejected: gold-plating for this portfolio demo;
   adds a signing key, token issuance, and middleware surface that distracts from
   the core lesson. The header is a deliberate stand-in for a signed session
   token, which I call out in the change record and interview answer.
3. **Required ``X-Customer-Id`` header (chosen)**: minimal, dependency-free, one
   dependency + one-line endpoint change, backward compatible (existing body field
   preserved), and directly teaches "trust a server-controlled source, not the
   client body."

## CONCEPT — authN vs authZ, trusted vs untrusted input
**authN** (authentication) = "who is the caller?" **authZ** (authorization) =
"is the caller allowed to do X?" The bug was missing authN: we never established
who the caller was before scoping data to them. Fix: establish identity from a
server-trusted source (header/session token), then let the existing repository
layer enforce authZ (customer-scoped reads).

Standalone example:
```python
# BAD: trusts the client body (spoofable)
customer_id = request.json["customer_id"]

# GOOD: trust a server-controlled session/header
customer_id = get_current_user(request)   # from signed cookie / JWT / header
```

## HOW I'D EXPLAIN IT IN AN INTERVIEW (3 sentences)
"Our chat endpoint trusted whatever customer_id the client sent in the body, so
a caller could read any customer's invoices and tickets. I added a required
X-Customer-Id header as the authoritative caller identity and routed the graph
through that instead of the body field. In production that header would be a
signed session token or JWT; here it's a deliberate stand-in so the lesson —
establish identity server-side before scoping data — is clear and testable."

## PREDICT FIRST (answer at bottom)
> Before reading the FIX, answer: a client sends
> ``{"customer_id": 1, ...}`` but is actually customer 99. With no
> authentication, what stops them from reading customer 1's invoices? And what
> single change makes the caller's identity trustworthy?

<details>
<summary>Answer</summary>
Nothing stops them — the body customer_id is fully spoofable. The fix is to stop
reading customer_id from the body and resolve the caller from a server-controlled
source (a required header / signed token), then scope the graph to that identity.
</details>

## Verification
- `pytest -m "unit or integration"` → 46 passed (was 45; +1 security test),
  2 deselected.
- `test_chat_requires_auth_header`: /chat with no ``X-Customer-Id`` → 422.
- `ruff check src tests` clean; `ruff format --check` clean; `mypy src` clean.

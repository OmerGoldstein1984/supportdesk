# Change record 005 — Rate-limit the /chat endpoint (fix P1-3)

## PROBLEM
SupportDesk had **no rate limiting**. Every `POST /chat` triggers router +
specialist + critic LLM calls (each a paid NVIDIA Build API call), so a single
malicious client could hammer `/chat` and run up LLM cost or effectively denial
of service. Listed in docs/08 as limitation #9 ("No rate limiting or abuse
protection").

## IMPACT
- **Cost abuse:** unbounded LLM calls = directly billed token usage.
- **Denial of service:** a flood of chat requests can saturate the single app
  instance and delay legitimate customers.
- **No visibility:** there was no mechanism to detect or throttle an abusive
  client.

## ORIGINAL (learn/annotated)
`src/supportdesk/main.py` — the FastAPI app had no middleware and no rate
limiting; `/chat` accepted unlimited requests from any client.

## FIX
Added a fixed-window rate limiter keyed by the authenticated `X-Customer-Id`
header, applied to the LLM-heavy `/chat` endpoint only:

`src/supportdesk/main.py`:
```python
RATE_LIMIT_REQUESTS = 30
RATE_LIMIT_WINDOW_SECONDS = 60


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window rate limiter keyed by X-Customer-Id."""

    def __init__(self, app, limit=..., window_seconds=...) -> None:
        ...
        self._windows: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request, call_next) -> Response:
        if request.url.path != "/chat":
            return await call_next(request)
        customer_id = request.headers.get("x-customer-id", "anonymous")
        now = time.time()
        cutoff = now - self.window_seconds
        window = self._windows[customer_id]
        self._windows[customer_id] = [t for t in window if t > cutoff]
        if len(self._windows[customer_id]) >= self.limit:
            return Response(..., status_code=429,
                            headers={"Retry-After": str(...)})
        self._windows[customer_id].append(now)
        return await call_next(request)


app.add_middleware(RateLimitMiddleware)
```

Non-`/chat` paths (`/approve`, `/trace`) are untouched — they don't call the
LLM. Requests over the limit get `429 Too Many Requests` with a `Retry-After`
header.

## WHY THIS WAY
Three alternatives considered:
1. **No rate limiting (status quo)** — rejected: cost/DoS exposure (the P1
   finding).
2. **Rate limit every endpoint** — rejected: `/approve` and `/trace` don't call
   the LLM, so limiting them adds complexity without protecting the costly path.
3. **Per-endpoint fixed-window middleware on /chat (chosen)**: minimal,
   dependency-free, targets the expensive path, easy to explain and test.
4. **Redis-backed distributed limiter** — rejected for this demo: correct for
   multi-instance production, but adds infrastructure; noted as the v2 upgrade.
   This in-memory per-process limiter is adequate for a single-instance demo.

## CONCEPT — fixed-window rate limiting
A fixed-window counter tracks how many requests a client made in the current
time window; once the limit is reached, further requests are rejected until the
window resets. It's the simplest rate-limiting algorithm (trade-off: bursts at
window edges).

Standalone example:
```python
import time
from collections import defaultdict

windows: dict[str, list[float]] = defaultdict(list)

def allow(customer_id: str, limit: int = 3, window_seconds: int = 60) -> bool:
    now = time.time()
    cutoff = now - window_seconds
    windows[customer_id] = [t for t in windows[customer_id] if t > cutoff]
    if len(windows[customer_id]) >= limit:
        return False
    windows[customer_id].append(now)
    return True
```

## HOW I'D EXPLAIN IT IN AN INTERVIEW (3 sentences)
"Each chat triggers three paid LLM calls, so an unbounded client could run up our
bill or knock the service offline. I added a fixed-window rate limiter keyed by
the authenticated customer ID on the /chat endpoint: after N requests in a
minute, further requests get a 429 with a Retry-After header. It's in-memory and
per-process for this demo; in production I'd swap it for a Redis-backed,
distributed limiter shared across app instances."

## PREDICT FIRST (answer at bottom)
> Before reading the FIX, answer: a client sends 40 `/chat` requests in one
> minute. The limit is 30/minute. What happens to requests 31-40, and what HTTP
> status should they receive?

<details>
<summary>Answer</summary>
Requests 31-40 are rejected with `429 Too Many Requests` (plus a `Retry-After`
header), because the fixed-window counter for that customer's ID has reached 30
within the current 60-second window.
</details>

## Verification
- `pytest -m "unit or integration"` → 47 passed (was 46; +1 rate-limit test),
  2 deselected.
- `test_rate_limit_blocks_excess_requests`: 30 calls return 200, the next 5
  return 429.
- Note: the rate-limit test uses customer_id `999` because the in-memory window
  is shared across the test process and other tests already consume the `1`
  window — a test-isolation caveat worth knowing when the middleware is extended.
- `ruff check src tests` clean; `ruff format --check` clean; `mypy src` clean.

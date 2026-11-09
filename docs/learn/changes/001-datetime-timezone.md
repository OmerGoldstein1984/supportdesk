# Change record 001 — Use timezone-aware datetimes (fix P1-1)

## PROBLEM
`datetime.datetime.utcnow()` is used across the codebase to stamp created/updated/failed
datetimes. `utcnow()` is deprecated since Python 3.12 (and scheduled for removal) and it
returns a **naive** `datetime` (no time zone). Running the test suite emits 38
`DeprecationWarning`s, and a future Python/SQLAlchemy upgrade will crash every write that
stamps a `created_at` / `paid_at` / `failed_at` / `started_at`.

The new characterization test `tests/unit/test_repositories.py::test_mark_paid_sets_timezone_aware_paid_at`
pins the bug: on the original code `invoice.paid_at.tzinfo is None` (naive) and the test
fails with `DeprecationWarning`; after the fix it is timezone-aware and passes.

## IMPACT
- **Correctness:** tests are noisy (38 warnings) and will break on upgrade → CI can turn red
  for reasons unrelated to logic.
- **Trust:** naive datetimes compare incorrectly against aware ones and make "when did this
  happen?" ambiguous across DST / server time zones — a support agent could misquote a refund
  or invoice timestamp to a customer.
- **Upgrade risk:** silent crash on the next Python/SQLAlchemy bump (data-write path).

## ORIGINAL (learn/annotated)
`src/supportdesk/models.py` — 6 column defaults, e.g. line 63:
```python
created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```
`src/supportdesk/repositories.py`:
- line 68: `invoice.paid_at = datetime.utcnow()` (in `mark_paid`)
- line 117: `cutoff = datetime.utcnow() - timedelta(days=days)` (in `recent_for_customer`)
`src/supportdesk/scripts/seed_data.py`:
- line ~357: `return datetime.utcnow() - timedelta(...)` (in `_random_date`)

All imports were `from datetime import datetime` (no `timezone`).

## FIX
Replaced every `datetime.utcnow`/`datetime.utcnow()` with `datetime.now(timezone.utc)`
(timezone-aware) and added `timezone` to the `datetime` imports.

`src/supportdesk/models.py` (all 6 defaults via `replace_all`):
```python
created_at: Mapped[datetime] = mapped_column(
    DateTime, default=lambda: datetime.now(timezone.utc)
)
```
Note: `default=` must receive a **callable** SQLAlchemy invokes at flush time, so we pass a
`lambda` rather than calling `datetime.now(...)` eagerly (which would stamp every row with
import time).

`src/supportdesk/repositories.py`:
```python
invoice.paid_at = datetime.now(timezone.utc)   # was datetime.utcnow()
...
cutoff = datetime.now(timezone.utc) - timedelta(days=days)  # was datetime.utcnow()
```

`src/supportdesk/scripts/seed_data.py`:
```python
return datetime.now(timezone.utc) - timedelta(  # was datetime.utcnow()
```

## WHY THIS WAY
Three alternatives considered:
1. **`datetime.utcnow()` (status quo)** — rejected: deprecated, naive, future crash risk.
2. **`datetime.now(timezone.utc)`** (chosen): timezone-aware, built into stdlib, no new dependency, one-line mechanical change, works with SQLAlchemy's SQLite dialect.
3. **`pendulum` / `arrow` / a dedicated datetime library** — rejected: gold-plating for a one-line stdlib fix; adds a dependency and surface area for the learner to defend.

## CONCEPT — naive vs aware datetimes
Naive datetimes carry no time zone, so two systems can disagree on "now." Production systems
store and compare **timezone-aware** datetimes (UTC at the edge, convert to local only for
display).

Standalone example:
```python
from datetime import datetime, timezone

# BAD: naive (ambiguous)
now_naive = datetime.utcnow()          # 2026-11-09 18:35:10  (tzinfo=None)

# GOOD: aware (unambiguous UTC)
now_aware = datetime.now(timezone.utc)  # 2026-11-09 18:35:10+00:00

assert now_aware.tzinfo is not None    # unambiguous, comparable across systems
```

## HOW I'D EXPLAIN IT IN AN INTERVIEW (3 sentences)
"We were stamping timestamps with `datetime.utcnow()`, which Python deprecated because it
returns a time-zone-naive datetime — two servers in different zones could disagree on when an
invoice was paid. I switched every stamp to `datetime.now(timezone.utc)` so every stored
datetime carries UTC, making comparisons safe and the code ready for the next Python upgrade.
I pinned the behavior with a failing characterization test first so the fix is verifiable and
reversible."

## PREDICT FIRST (answer at bottom)
> Before reading the FIX, answer: `datetime.utcnow()` returns a datetime with no time zone.
> If you compare that naive value against a timezone-aware `datetime.now(timezone.utc)`, what
> does Python do — raise, or silently return a wrong result? And why is that dangerous for a
> refund cutoff like "refunds older than 30 days"?

<details>
<summary>Answer</summary>
Python raises `TypeError: can't compare offset-naive and offset-aware datetimes`. For a refund
cutoff, that means a query like `failed_at >= cutoff` crashes instead of returning rows —
exactly the kind of silent production outage this fix prevents.
</details>

## Verification
- `pytest -m "unit or integration"` → 44 passed (was 43; +1 characterization test), 2 deselected.
- Deprecation warnings dropped from 38 → 6 (remaining are unrelated FastAPI/SQLAlchemy deprecations).
- `ruff check src tests` clean; `ruff format --check` clean; `mypy src` clean.

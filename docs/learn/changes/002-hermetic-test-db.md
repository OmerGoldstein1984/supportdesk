# Change record 002 — Hermetic in-memory test database (fix P1-2)

## PROBLEM
Tests ran against a shared, file-based `test.db` (`DATABASE_URL=sqlite:///./test.db`)
that persisted rows between pytest runs. `seeded_db` hard-codes `customer_id == 1`
and invoice ids `50` / `120`, so if a previous run left those rows, the next run's
`seeded_db` hit primary-key conflicts. Observed after switching branches: **18 errors**
on the first run, then a clean pass once the file DB happened to be empty. This is
classic cross-test state leakage — tests are not hermetic and CI can fail spuriously.

The behavior was pinned by running the suite twice in a row against a pre-existing
`test.db`: the first run errored, the second passed (nondeterministic).

## IMPACT
- **Reliability:** flaky, order-dependent tests; CI can turn red for environment
  reasons unrelated to code changes.
- **Debuggability:** a failing test leaves rows in `test.db` that corrupt the next
  test, masking the real cause.
- **Trust:** QA can't trust a green run unless they manually delete `test.db` first.

## ORIGINAL (learn/annotated)
`tests/conftest.py`:
```python
from sqlalchemy import delete
from sqlalchemy.orm import Session
...
@pytest.fixture(scope="session", autouse=True)
def _db_schema() -> Iterator[None]:
    init_db()   # bound to module _engine -> file-based test.db via settings

@pytest.fixture
def db_session() -> Iterator[Session]:
    """A SQLAlchemy session backed by test.db, cleaned after each test."""
    with session_scope() as session:
        yield session
```
`init_db()` and `session_scope()` used the module-level `_engine`/`SessionLocal` from
`supportdesk.database`, which is created at import time from `settings.database_url`
(file-based `test.db`).

## FIX
`tests/conftest.py` — bind the module engine/session to a fresh
`sqlite:///:memory:` database (with `StaticPool` so every connection shares the same
in-memory DB) for the test session:

```python
from sqlalchemy import StaticPool, create_engine, delete
from sqlalchemy.orm import Session, sessionmaker

@pytest.fixture(scope="session", autouse=True)
def _db_schema() -> Iterator[None]:
    import supportdesk.database as database

    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    database._engine = test_engine
    database.SessionLocal = sessionmaker(
        bind=test_engine, autoflush=False, autocommit=False
    )
    init_db()
    yield
```

Because `_engine`/`SessionLocal` are looked up at call time inside `init_db()` and
`session_scope()`, rebinding them makes every test use the hermetic in-memory DB.
Nothing is written to disk; each pytest process starts from an empty DB.

## WHY THIS WAY
Three alternatives considered:
1. **File-based `test.db` + manual cleanup** (status quo) — rejected: caused the
   flakiness we're fixing.
2. **`sqlite:///:memory:` with default `QueuePool`** — rejected: each connection gets
   a *different* empty in-memory DB, so the schema created in `_db_schema` is invisible
   to `db_session` connections → all tests fail with "no such table."
3. **`sqlite:///:memory:` + `StaticPool`** (chosen): shares one in-memory DB across all
   connections, no file, fresh per process. One import + fixture change, no source
   changes to `supportdesk/`.
4. **`tmp_path` temp file per session** — considered and rejected as an alternative:
   works, but leaves temp files and is slower than in-memory; in-memory is simpler
   and sufficient for a unit/integration suite.

## CONCEPT — hermetic tests
Hermetic tests depend only on their own inputs and leave no observable side effects
outside themselves, so they pass/fail the same way every time regardless of environment
or run order.

Standalone example:
```python
# NOT hermetic: depends on /tmp/notes.txt existing from a previous run
notes = open("/tmp/notes.txt").read()
assert "expected" in notes

# HERMETIC: creates its own input, cleans up after itself
with tempfile.NamedTemporaryFile("w+") as f:
    f.write("expected"); f.flush()
    assert open(f.name).read() == "expected"
```

## HOW I'D EXPLAIN IT IN AN INTERVIEW (3 sentences)
"Our tests shared a file-based `test.db`, so rows left over from one run could collide
with the next run's hard-coded customer and invoice ids — that's why the suite was
flaky and sometimes errored on the first run after a branch switch. I switched the test
fixture to a fresh in-memory SQLite database (`sqlite:///:memory:` with `StaticPool`)
so every pytest process starts from an empty database and nothing is written to disk.
Now the suite is deterministic: it passes the same way every time, no manual cleanup
needed."

## PREDICT FIRST (answer at bottom)
> Before reading the FIX, answer: why can't we just use `sqlite:///:memory:` with
> SQLAlchemy's default connection pool for the test schema? (Hint: `_db_schema` creates
> the schema on one connection, but `db_session` gets a brand-new connection.)

<details>
<summary>Answer</summary>
With the default pool, each connection to `sqlite:///:memory:` opens a *brand-new,
empty* in-memory database. The tables created by `_db_schema` live on connection A;
`db_session` connects via connection B and sees an empty DB with no tables → "no such
table" errors. `StaticPool` forces all connections to share the single in-memory DB,
so the schema is visible everywhere.
</details>

## Verification
- `pytest -m "unit or integration"` → 44 passed, 2 deselected, on two consecutive runs
  (stable; no cross-run state leakage).
- Deprecation warnings unchanged at 6 (unrelated FastAPI/SQLAlchemy deprecations).
- `ruff check src tests` clean; `ruff format --check` clean; `mypy src` clean.

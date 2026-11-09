# Change record 006 — Explicit coverage gate in CI (fix P3-1)

## PROBLEM
CI ran tests with `--cov=supportdesk` but did not pass `--cov-fail-under`, so
the 85% coverage gate (declared only in pyproject `[tool.coverage.report]`) was
implicit rather than explicit in the CI step. A reader of the CI config could not
tell whether the gate was enforced.

## IMPACT
- **Observability / governance:** the coverage threshold isn't visible in CI,
  so coverage could silently erode if the pyproject config were changed.
- **Polish:** CI config should be self-documenting about its gates.

## ORIGINAL (learn/annotated)
`.github/workflows/ci.yml`:
```yaml
      - name: Unit + integration tests (fake LLM, sqlite)
        run: DATABASE_URL=sqlite:///./test.db pytest -m "unit or integration" -q --cov=supportdesk --cov-report=xml --cov-report=term -p no:cacheprovider
```

## FIX
Added `--cov-fail-under=85` to the CI pytest command so the gate is explicit:
```yaml
        run: DATABASE_URL=sqlite:///./test.db pytest -m "unit or integration" -q --cov=supportdesk --cov-fail-under=85 --cov-report=xml --cov-report=term -p no:cacheprovider
```

Current coverage is 93.01% (well above 85%), so the gate passes.

## WHY THIS WAY
Making the gate explicit in CI (in addition to the pyproject config) means the
threshold is visible to anyone reading the pipeline, not hidden in a config file.
No behavior change; it's a clarity/governance improvement.

## Verification
- `pytest --cov=supportdesk` → Total coverage 93.01%, gate reached.
- `ruff check .github` — not a Python file; no lint change needed.

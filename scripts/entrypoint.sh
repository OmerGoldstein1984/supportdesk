#!/bin/sh
# Entrypoint: seed idempotently, then serve.
set -e

echo "[entrypoint] seeding data (idempotent)..."
python -m supportdesk.cli seed || true

echo "[entrypoint] starting uvicorn..."
exec uvicorn supportdesk.main:app --host 0.0.0.0 --port "${PORT:-8000}"

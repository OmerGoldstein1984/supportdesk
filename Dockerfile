FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for psycopg2 (Postgres) build
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies (pyproject.toml first for layer caching; src/ must be
# present for the editable install to resolve `egg_base = src`)
COPY pyproject.toml ./
COPY ./src ./src
COPY ./scripts ./scripts
COPY ./data ./data

RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000

# Seed idempotently on startup, then serve. Seed is safe to re-run (skips existing rows).
ENTRYPOINT ["sh", "/app/scripts/entrypoint.sh"]

"""CLI entrypoint: seed the database or serve the API.

Usage:
    python -m supportdesk.cli seed
    python -m supportdesk.cli serve

WHAT: CLI with two commands: seed (reproducible synthetic test data) and serve
(FastAPI API via uvicorn).

WHY: Single command to get the system running — seed test data, then serve the
API. The seed command is idempotent (re-running skips existing rows).

INPUTS: CLI args (seed|serve).
OUTPUTS: Console output; running API server.

FAILURE MODES:
- Missing command → prints usage and exits with code 1
- Seed fails → database error propagates

# BUSINESS: One command to get the system running — seed data, then serve the
#   API. Good for demo/interview scenarios.
# INTERVIEW: "Why is seed idempotent?" Answer: Re-running skips existing rows,
#   so it's safe to run multiple times.
"""

from __future__ import annotations

import sys


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "help"
    if command == "seed":
        from .scripts.seed_data import main as seed_main

        seed_main(sys.argv[2:])
    elif command == "serve":
        import uvicorn

        uvicorn.run("supportdesk.main:app", host="0.0.0.0", port=8000, reload=True)
    else:
        print("Usage: python -m supportdesk.cli {seed|serve}")
        sys.exit(1)


if __name__ == "__main__":
    main()

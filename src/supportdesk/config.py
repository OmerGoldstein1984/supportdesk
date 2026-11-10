"""Application configuration, loaded from environment variables.

WHAT: Pydantic-settings BaseSettings that loads all config from env vars (.env
file). No secrets stored in code.

WHY: All settings are environment-based — the same image runs dev/staging/prod
with different env values. No secrets in code (copy .env.example to .env and fill
in real values before running).

INPUTS: environment variables (.env file).
OUTPUTS: Settings singleton with all config fields.

FAILURE MODES:
- missing nvidia_api_key → LLM calls fail at runtime (no validation that key is
  present when needed)
- extra="ignore" silently drops mistyped env var names — typo in DATABASE_URL
  won't error, just ignored, leading to confusing "using default SQLite" behavior
- settings instantiated at import — env must be loaded before import; tests
  mutating env need re-instantiation

# GAP: no required-field enforcement (nvidia_api_key optional)
# GAP: no validation of threshold ranges (refund threshold could be negative)
# GAP: app_env and log_level unused in these files
# BUSINESS: Refund auto-approve threshold is a business lever — finance should
#   own it, not code
# INTERVIEW: "How do you rotate NVIDIA API key without redeploying?" Answer:
#   Env var — no code change needed
# INTERVIEW: "How is router_confidence computed and by whom?" Answer: It's a
#   config threshold; the router LLM sets confidence per-message
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM provider: NVIDIA Build API via ChatNVIDIA
    nvidia_api_key: str | None = None
    nvidia_model: str = "meta/llama-3.1-8b-instruct"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"

    # LLM retry / fallback middleware
    llm_max_retries: int = 3
    llm_fallback_model: str = "meta/llama-3.1-8b-instruct"

    # Tool gate / risk policy
    refund_auto_approve_threshold: float = Field(
        100.00, description="Refunds above this amount require human approval"
    )
    max_tool_validation_failures: int = 2
    max_revisions: int = 1
    router_confidence_threshold: float = Field(
        0.70, description="Router confidence below this routes to Escalation"
    )

    # Database (SQLite locally, Postgres in docker-compose)
    database_url: str = "sqlite:///./supportdesk.db"

    # Application
    app_env: str = "development"
    log_level: str = "INFO"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()  # type: ignore[call-arg]  # pydantic BaseSettings defaults are applied at runtime

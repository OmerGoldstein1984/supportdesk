"""Application configuration, loaded from environment variables.

All settings are environment-based. No secrets are stored in code.
Copy ``.env.example`` to ``.env`` and fill in real values before running.
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

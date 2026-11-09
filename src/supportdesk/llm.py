"""LLM provider: NVIDIA Build API via ChatNVIDIA, with retry + model-fallback middleware.

ChatNVIDIA itself has no built-in retry/fallback, so this module wraps it:
- transient failures are retried with exponential backoff (tenacity)
- if all retries fail, the request is retried once against the fallback model
- the router uses structured output (Pydantic) for intent/urgency/confidence
"""

from __future__ import annotations

from typing import Any, TypeVar

from langchain_nvidia_ai_endpoints import ChatNVIDIA
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import settings

__all__ = ["LLM", "llm"]

_T = TypeVar("_T", bound=BaseModel)


def _make_chat(model: str) -> ChatNVIDIA:
    return ChatNVIDIA(
        model=model,
        nvidia_api_key=settings.nvidia_api_key,
        base_url=settings.nvidia_base_url,
        temperature=0.2,
        max_completion_tokens=1000,
    )


class LLM:
    def __init__(self) -> None:
        self.primary = _make_chat(settings.nvidia_model)
        self.fallback = _make_chat(settings.llm_fallback_model)

    @retry(
        stop=stop_after_attempt(max(1, settings.llm_max_retries)),
        wait=wait_exponential(multiplier=0.5, min=1, max=8),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _invoke(self, chat: ChatNVIDIA, input: Any) -> Any:
        return chat.invoke(input)

    def invoke(self, input: Any) -> Any:
        """Invoke primary model with retry; fall back to fallback model on total failure."""
        try:
            return self._invoke(self.primary, input)
        except Exception:  # primary exhausted retries -> try fallback
            return self._invoke(self.fallback, input)

    def structured(self, schema: type[_T]) -> Any:
        """Primary model with Pydantic structured output (used by the Router)."""
        return self.primary.with_structured_output(schema)


# Singleton used by agents. Tests can monkeypatch or replace it.
llm = LLM()

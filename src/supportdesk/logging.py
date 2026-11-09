"""Structured JSON logging with PII redaction.

Logs are emitted as JSON (one event per line) so they can be consumed by
log collectors. A processor scrubs PII (emails, phones, card numbers) from
any value before it reaches the log sink, so sensitive customer data never
lands in plain-text logs.
"""

from __future__ import annotations

import logging
import re
from typing import Any, MutableMapping, cast

import structlog

_PII_PATTERNS = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    (re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[PHONE]"),
    (re.compile(r"\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b"), "[CARD]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
]


def _redact_pii(value: Any) -> Any:
    """Recursively scrub PII from strings found inside log values."""
    if isinstance(value, str):
        redacted = value
        for pattern, replacement in _PII_PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        return redacted
    if isinstance(value, dict):
        return {k: _redact_pii(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_pii(v) for v in value]
    return value


def _pii_processor(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor that redacts PII from every logged value."""
    for key, value in list(event_dict.items()):
        event_dict[key] = _redact_pii(value)
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog to emit JSON with PII redaction."""
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            _pii_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    return cast(structlog.BoundLogger, structlog.get_logger(name))

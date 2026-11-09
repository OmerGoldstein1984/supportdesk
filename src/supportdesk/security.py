"""Prompt-injection defense and PII redaction for user input and tool outputs.

Two concerns, both enforced in plain code (no LLM):

1. Prompt injection: user messages and tool outputs are scanned for
   instruction-hijack patterns ("ignore previous instructions", "you are now",
   "reveal the system prompt", ...). A match raises :class:`InjectionBlocked`.
2. PII: emails, phones, card numbers, SSNs are replaced with safe tokens so
   they never leak into LLM prompts, tool results, or logs.
"""

from __future__ import annotations

import re

__all__ = ["InjectionBlocked", "sanitize_user_input", "sanitize_tool_output", "redact_pii"]

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+previous\s+instructions", re.I),
    re.compile(r"disregard\s+(the|above|prior)", re.I),
    re.compile(r"you\s+are\s+now\s+(a|an)\s+", re.I),
    re.compile(r"system\s*:\s*(.*)", re.I),
    re.compile(r"reveal\s+(the\s+)?(system\s+)?prompt", re.I),
    re.compile(r"jailbreak", re.I),
    re.compile(r"override\s+safety", re.I),
    re.compile(r"pretend\s+to\s+be", re.I),
]


class InjectionBlocked(ValueError):
    """Raised when user input or a tool output contains a prompt-injection attempt."""


def _contains_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


def _redact_pii(text: str) -> str:
    substitutions = [
        (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
        (re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[PHONE]"),
        (re.compile(r"\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b"), "[CARD]"),
        (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    ]
    for pattern, replacement in substitutions:
        text = pattern.sub(replacement, text)
    return text


def sanitize_user_input(message: str) -> str:
    """Sanitize a raw user message before it reaches any LLM or tool.

    Redacts PII and raises :class:`InjectionBlocked` if a prompt-injection
    pattern is detected.
    """
    if not isinstance(message, str):
        return ""
    if _contains_injection(message):
        raise InjectionBlocked("prompt-injection pattern detected in user input")
    return _redact_pii(message)


def sanitize_tool_output(output: str) -> str:
    """Sanitize a tool output before feeding it back to an LLM.

    Redacts PII (tool outputs may contain customer records) and raises
    :class:`InjectionBlocked` if the output itself contains an injection
    attempt (defense-in-depth against a compromised/tool-injection path).
    """
    if not isinstance(output, str):
        output = str(output)
    if _contains_injection(output):
        raise InjectionBlocked("prompt-injection pattern detected in tool output")
    return _redact_pii(output)


def redact_pii(text: str) -> str:
    """Public PII redaction helper (no injection check)."""
    return _redact_pii(text)

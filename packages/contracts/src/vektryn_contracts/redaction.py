"""Shared secret redaction utilities for telemetry and log sanitization."""

import re

REDACTED_VALUE = "[Filtered]"

_AIZA_KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
_AQ_KEY_RE = re.compile(r"AQ\.[0-9A-Za-z._-]{20,}")
_QUERY_API_KEY_RE = re.compile(r"(?i)([?&](?:key|api_key|x-goog-api-key)=)([^&\s'\"]+)")


def redact_secrets(text: str) -> str:
    """Scrub Gemini API keys (legacy AIza... and AI Studio AQ....) and key query params."""
    if not text:
        return text
    redacted = _AIZA_KEY_RE.sub(REDACTED_VALUE, text)
    redacted = _AQ_KEY_RE.sub(REDACTED_VALUE, redacted)
    redacted = _QUERY_API_KEY_RE.sub(rf"\1{REDACTED_VALUE}", redacted)
    return redacted

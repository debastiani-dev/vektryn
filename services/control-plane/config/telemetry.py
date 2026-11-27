import json
import logging
import os
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.core.exceptions import (
    DisallowedHost,
    PermissionDenied,
    SuspiciousOperation,
)
from django.http import Http404
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.types import Event, Hint

from vektryn_contracts.redaction import redact_secrets

logger = logging.getLogger(__name__)
_SENTRY_CONFIGURED = False

REDACTED = "[Filtered]"
_HEALTH_PATHS = frozenset({"/health", "/api/v1/health"})
_DATA_COLLECTION = {
    "user_info": False,
    "cookies": {"mode": "off"},
    "http_bodies": [],
    "gen_ai": {"inputs": False, "outputs": False},
}
_IGNORED_CLIENT_STATUS_CODES = frozenset({400, 401, 403, 404, 405, 429})
_IGNORED_LOGGERS = frozenset({"django.security.DisallowedHost"})
_IGNORED_EXCEPTIONS = (Http404, PermissionDenied, DisallowedHost, SuspiciousOperation)
_SENSITIVE_HEADERS = frozenset(
    {
        "cookie",
        "set-cookie",
        "authorization",
        "proxy-authorization",
        "x-csrftoken",
        "x-ingest-api-key",
        "x-goog-api-key",
    }
)
_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "token",
        "api_key",
        "key",
        "secret",
        "password",
        "access_token",
        "stream_token",
    }
)
_SENSITIVE_BODY_KEYS = frozenset(
    {
        "password",
        "current_password",
        "new_password",
        "confirm_password",
        "raw_text",
        "resume_text",
        "raw_html",
        "stream_token",
        "secret_key",
        "api_key",
        "gemini_api_key",
        "gemini_api_key_encrypted",
        "byok_encryption_key",
        "x-goog-api-key",
        "csrfmiddlewaretoken",
        "csrftoken",
        "authorization",
        "cookie",
        "set-cookie",
        "x-csrftoken",
        "x-ingest-api-key",
        "proxy-authorization",
    }
)


def _parse_sample_rate(raw: str | None, default: float = 0.0) -> float:
    if raw is None or not raw.strip():
        return default
    try:
        parsed = float(raw.strip())
    except ValueError:
        return default
    return max(0.0, min(1.0, parsed))


def _is_sensitive_key(key: str) -> bool:
    lowered = key.strip().lower()
    if lowered in _SENSITIVE_BODY_KEYS:
        return True
    return "password" in lowered or "passwd" in lowered


def _scrub_query_string(raw_query: str) -> str:
    if not raw_query:
        return raw_query
    pairs = parse_qsl(raw_query, keep_blank_values=True)
    if not pairs:
        return raw_query
    scrubbed = [
        (k, REDACTED if k.strip().lower() in _SENSITIVE_QUERY_KEYS else v)
        for k, v in pairs
    ]
    return urlencode(scrubbed)


def _scrub_url(raw_url: str) -> str:
    if not raw_url or "?" not in raw_url:
        return raw_url
    parts = urlsplit(raw_url)
    scrubbed_query = _scrub_query_string(parts.query)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, scrubbed_query, parts.fragment)
    )


def _is_health_request(event: Event) -> bool:
    request = event.get("request")
    if not isinstance(request, dict):
        return False
    raw_url = request.get("url")
    if not isinstance(raw_url, str) or not raw_url:
        return False
    path = urlsplit(raw_url).path.rstrip("/") or "/"
    return path in _HEALTH_PATHS


def _extract_response_status(event: Event) -> int | None:
    contexts = event.get("contexts")
    if isinstance(contexts, dict):
        response_ctx = contexts.get("response")
        if isinstance(response_ctx, dict) and isinstance(
            response_ctx.get("status_code"), int
        ):
            return response_ctx["status_code"]
    tags = event.get("tags")
    if isinstance(tags, dict):
        raw_status = tags.get("status_code")
        if isinstance(raw_status, int):
            return raw_status
        if isinstance(raw_status, str) and raw_status.isdigit():
            return int(raw_status)
    return None


def _is_expected_client_error(event: Event, hint: Hint) -> bool:
    if event.get("logger") in _IGNORED_LOGGERS:
        return True

    exc_info = hint.get("exc_info")
    if isinstance(exc_info, tuple) and len(exc_info) >= 2:
        exc = exc_info[1]
        if isinstance(exc, _IGNORED_EXCEPTIONS):
            return True
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int) and 400 <= status_code < 500:
            return True

    status = _extract_response_status(event)
    return status in _IGNORED_CLIENT_STATUS_CODES


def _scrub_string(value: str, *, depth: int) -> str:
    stripped = value.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return redact_secrets(_scrub_url(value))
    try:
        parsed = json.loads(stripped)
    except ValueError:
        return redact_secrets(_scrub_url(value))
    if isinstance(parsed, dict):
        return json.dumps(_scrub_value(parsed, depth=depth + 1))
    return redact_secrets(_scrub_url(value))


def _scrub_dict(mapping: dict[Any, Any], *, depth: int) -> dict[Any, Any]:
    scrubbed: dict[Any, Any] = {}
    for key, item in mapping.items():
        if isinstance(key, str) and _is_sensitive_key(key):
            scrubbed[key] = REDACTED
        else:
            scrubbed[key] = _scrub_value(item, depth=depth + 1)
    return scrubbed


def _scrub_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 6:
        return value
    if isinstance(value, dict):
        return _scrub_dict(value, depth=depth)
    if isinstance(value, list):
        return [_scrub_value(item, depth=depth + 1) for item in value]
    if isinstance(value, str):
        return _scrub_string(value, depth=depth)
    return value


def _scrub_headers(headers: Any) -> Any:
    if isinstance(headers, dict):
        return {
            k: (REDACTED if k.strip().lower() in _SENSITIVE_HEADERS else v)
            for k, v in headers.items()
        }
    if isinstance(headers, list):
        scrubbed_list = []
        for entry in headers:
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                key = str(entry[0])
                val = (
                    REDACTED if key.strip().lower() in _SENSITIVE_HEADERS else entry[1]
                )
                scrubbed_list.append([entry[0], val])
            else:
                scrubbed_list.append(entry)
        return scrubbed_list
    return headers


def _scrub_request(request: dict[str, Any]) -> None:
    if "headers" in request:
        request["headers"] = _scrub_headers(request["headers"])
    request.pop("cookies", None)
    if isinstance(request.get("url"), str):
        request["url"] = _scrub_url(request["url"])
    if isinstance(request.get("query_string"), str):
        request["query_string"] = _scrub_query_string(request["query_string"])
    elif isinstance(request.get("query_string"), dict):
        request["query_string"] = {
            k: (REDACTED if k.strip().lower() in _SENSITIVE_QUERY_KEYS else v)
            for k, v in request["query_string"].items()
        }
    if "data" in request:
        request["data"] = _scrub_value(request["data"])


def _scrub_breadcrumbs(event: Event) -> None:
    breadcrumbs = event.get("breadcrumbs")
    values = breadcrumbs.get("values") if isinstance(breadcrumbs, dict) else breadcrumbs
    if not isinstance(values, list):
        return
    for crumb in values:
        if not isinstance(crumb, dict):
            continue
        if isinstance(crumb.get("message"), str):
            crumb["message"] = _scrub_string(crumb["message"], depth=0)
        data = crumb.get("data")
        if isinstance(data, dict):
            if isinstance(data.get("url"), str):
                data["url"] = redact_secrets(_scrub_url(data["url"]))
            if isinstance(data.get("query_string"), str):
                data["query_string"] = redact_secrets(
                    _scrub_query_string(data["query_string"])
                )
            crumb["data"] = _scrub_value(data)


def _scrub_exception_values(event: Event) -> None:
    exception = event.get("exception")
    values = exception.get("values") if isinstance(exception, dict) else None
    if not isinstance(values, list):
        return
    for entry in values:
        if isinstance(entry, dict) and isinstance(entry.get("value"), str):
            entry["value"] = _scrub_string(entry["value"], depth=0)


def _scrub_logentry(event: Event) -> None:
    logentry = event.get("logentry")
    if not isinstance(logentry, dict):
        return
    for key in ("message", "formatted"):
        if isinstance(logentry.get(key), str):
            logentry[key] = _scrub_string(logentry[key], depth=0)
    if "params" in logentry:
        logentry["params"] = _scrub_value(logentry["params"])


def _scrub_event_payload(event: Event) -> Event:
    request = event.get("request")
    if isinstance(request, dict):
        _scrub_request(request)

    if isinstance(event.get("message"), str):
        event["message"] = _scrub_string(event["message"], depth=0)

    if isinstance(event.get("extra"), dict):
        event["extra"] = _scrub_value(event["extra"])

    if isinstance(event.get("contexts"), dict):
        event["contexts"] = _scrub_value(event["contexts"])

    user = event.get("user")
    if isinstance(user, dict):
        user.pop("email", None)
        user.pop("ip_address", None)

    _scrub_exception_values(event)
    _scrub_logentry(event)
    _scrub_breadcrumbs(event)
    return event


def before_send(event: Event, hint: Hint) -> Event | None:
    if _is_health_request(event) or _is_expected_client_error(event, hint):
        return None
    return _scrub_event_payload(event)


def _is_health_span(span: Event) -> bool:
    if _is_health_request(span):
        return True
    data = span.get("data")
    if isinstance(data, dict):
        raw_url = data.get("url.full") or data.get("url") or data.get("http.target")
        if isinstance(raw_url, str) and raw_url:
            path = urlsplit(raw_url).path.rstrip("/") or "/"
            return path in _HEALTH_PATHS
    return False


def before_send_span(span: Event, _hint: Hint) -> Event | None:
    if _is_health_span(span):
        return None
    return _scrub_event_payload(span)


def configure_sentry(service_name: str | None = None) -> bool:
    global _SENTRY_CONFIGURED
    if _SENTRY_CONFIGURED:
        return True

    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    resolved_service = (
        service_name or os.getenv("SENTRY_SERVICE_NAME", "control-plane")
    ).strip() or "control-plane"
    environment = os.getenv("SENTRY_ENVIRONMENT", "production").strip() or "production"
    release = os.getenv("SENTRY_RELEASE", "").strip() or None
    traces_sample_rate = _parse_sample_rate(
        os.getenv("SENTRY_TRACES_SAMPLE_RATE"),
        default=0.0,
    )

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        integrations=[DjangoIntegration()],
        traces_sample_rate=traces_sample_rate,
        profile_session_sample_rate=0.0,
        data_collection=_DATA_COLLECTION,
        before_send=before_send,
        before_send_span=before_send_span,
    )
    sentry_sdk.set_tag("service", resolved_service)
    sentry_sdk.set_tag("environment", environment)
    _SENTRY_CONFIGURED = True
    logger.info(
        "Sentry error tracking enabled for %s (env=%s, release=%s)",
        resolved_service,
        environment,
        release or "unset",
    )
    return True


def flush_sentry(timeout: float = 5.0) -> None:
    if _SENTRY_CONFIGURED:
        sentry_sdk.flush(timeout=timeout)

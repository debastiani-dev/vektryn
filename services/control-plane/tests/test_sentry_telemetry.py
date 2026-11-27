from io import StringIO
import json
from unittest.mock import MagicMock, patch

from django.core.exceptions import DisallowedHost, PermissionDenied
from django.core.management import call_command
from django.http import Http404
import pytest
from rest_framework.exceptions import Throttled, ValidationError

from config import telemetry as cp_telemetry


def test_configure_sentry_free_plan_defaults_and_release(monkeypatch):
    monkeypatch.setattr(cp_telemetry, "_SENTRY_CONFIGURED", False)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.ingest.sentry.io/10")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "production")
    monkeypatch.setenv("SENTRY_RELEASE", "abc1234deadbeef")
    monkeypatch.setenv("SENTRY_SERVICE_NAME", "vektryn-migrate")
    monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)

    with (
        patch.object(cp_telemetry.sentry_sdk, "init") as mock_init,
        patch.object(cp_telemetry.sentry_sdk, "set_tag") as mock_tag,
    ):
        assert cp_telemetry.configure_sentry() is True

    kwargs = mock_init.call_args.kwargs
    assert kwargs["dsn"] == "https://public@example.ingest.sentry.io/10"
    assert kwargs["environment"] == "production"
    assert kwargs["release"] == "abc1234deadbeef"
    assert kwargs["data_collection"] == {
        "user_info": False,
        "cookies": {"mode": "off"},
        "http_bodies": [],
        "gen_ai": {"inputs": False, "outputs": False},
    }
    assert kwargs["traces_sample_rate"] == pytest.approx(0.0)
    assert kwargs["profile_session_sample_rate"] == pytest.approx(0.0)
    assert kwargs["before_send"] is cp_telemetry.before_send
    assert kwargs["before_send_span"] is cp_telemetry.before_send_span
    mock_tag.assert_any_call("service", "vektryn-migrate")
    mock_tag.assert_any_call("environment", "production")


def test_configure_sentry_accepts_real_sentry_sdk_v3_init(monkeypatch):
    monkeypatch.setattr(cp_telemetry, "_SENTRY_CONFIGURED", False)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.ingest.sentry.io/11")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "production")
    monkeypatch.setenv("SENTRY_RELEASE", "sha-real-init")
    try:
        assert cp_telemetry.configure_sentry("control-plane") is True
        client = cp_telemetry.sentry_sdk.get_client()
        assert client.is_active() is True
        assert client.options["traces_sample_rate"] == pytest.approx(0.0)
        assert client.options["profile_session_sample_rate"] == pytest.approx(0.0)
        assert client.options["data_collection"]["user_info"] is False
        assert client.options["data_collection"]["cookies"] == {"mode": "off"}
        assert client.options["data_collection"]["http_bodies"] == []
        assert "google_genai" not in client.integrations
    finally:
        cp_telemetry.sentry_sdk.init(dsn="")
        monkeypatch.setattr(cp_telemetry, "_SENTRY_CONFIGURED", False)


def test_before_send_scrubs_headers_tokens_passwords_and_resume_text():
    event = {
        "request": {
            "url": "https://vektryn.debastiani.dev/stream/alerts?token=secret-hmac&page=2",
            "query_string": "token=secret-hmac&page=2",
            "cookies": {"sessionid": "raw-cookie"},
            "headers": {
                "Cookie": "sessionid=abc",
                "Authorization": "Bearer secret",
                "X-CSRFToken": "csrf123",
                "X-Ingest-API-Key": "ingest-key",
                "Content-Type": "application/json",
            },
            "data": json.dumps(
                {
                    "username": "rafa",
                    "current_password": "old",
                    "new_password": "new",
                    "confirm_password": "new",
                    "raw_text": "Confidential CV text",
                }
            ),
        },
        "extra": {
            "resume_text": "Full resume content",
            "safe_count": 3,
        },
        "user": {
            "id": "1",
            "username": "rafa",
            "email": "rafa@example.com",
            "ip_address": "1.2.3.4",
        },
        "breadcrumbs": {
            "values": [
                {
                    "category": "http",
                    "data": {
                        "url": "https://vektryn.debastiani.dev/stream/alerts?token=hmac-999&keep=1",
                    },
                }
            ]
        },
    }

    scrubbed = cp_telemetry.before_send(event, {})
    assert scrubbed is not None

    req = scrubbed["request"]
    assert "cookies" not in req
    assert req["headers"]["Cookie"] == "[Filtered]"
    assert req["headers"]["Authorization"] == "[Filtered]"
    assert req["headers"]["X-CSRFToken"] == "[Filtered]"
    assert req["headers"]["X-Ingest-API-Key"] == "[Filtered]"
    assert req["headers"]["Content-Type"] == "application/json"
    assert "secret-hmac" not in req["url"]
    assert "page=2" in req["url"]
    assert "secret-hmac" not in req["query_string"]

    parsed_body = json.loads(req["data"])
    assert parsed_body["username"] == "rafa"
    assert parsed_body["current_password"] == "[Filtered]"
    assert parsed_body["new_password"] == "[Filtered]"
    assert parsed_body["confirm_password"] == "[Filtered]"
    assert parsed_body["raw_text"] == "[Filtered]"

    assert scrubbed["extra"]["resume_text"] == "[Filtered]"
    assert scrubbed["extra"]["safe_count"] == 3
    assert scrubbed["user"] == {"id": "1", "username": "rafa"}

    crumb_url = scrubbed["breadcrumbs"]["values"][0]["data"]["url"]
    assert "hmac-999" not in crumb_url
    assert "keep=1" in crumb_url


@pytest.mark.parametrize(
    ("event", "hint"),
    [
        ({"request": {"url": "https://vektryn.debastiani.dev/health/"}}, {}),
        ({"request": {"url": "https://vektryn.debastiani.dev/api/v1/health/"}}, {}),
        ({"logger": "django.security.DisallowedHost"}, {}),
        ({}, {"exc_info": (Http404, Http404("missing"), None)}),
        ({}, {"exc_info": (PermissionDenied, PermissionDenied("forbidden"), None)}),
        ({}, {"exc_info": (DisallowedHost, DisallowedHost("bad host"), None)}),
        ({}, {"exc_info": (ValidationError, ValidationError("bad input"), None)}),
        ({}, {"exc_info": (Throttled, Throttled(wait=60), None)}),
        ({"contexts": {"response": {"status_code": 401}}}, {}),
        ({"tags": {"status_code": "429"}}, {}),
    ],
)
def test_before_send_drops_health_checks_and_expected_4xx(event, hint):
    assert cp_telemetry.before_send(event, hint) is None


def test_before_send_preserves_5xx_and_unhandled_exceptions():
    exc = RuntimeError("database connection lost")
    event = {
        "request": {"url": "https://vektryn.debastiani.dev/api/v1/matches/"},
        "contexts": {"response": {"status_code": 500}},
    }
    result = cp_telemetry.before_send(event, {"exc_info": (RuntimeError, exc, None)})
    assert result is not None
    assert (
        cp_telemetry.before_send_span(
            {"request": {"url": "https://vektryn.debastiani.dev/api/v1/health/"}},
            {},
        )
        is None
    )


def test_verify_sentry_management_command_handles_unset_and_configured_dsn(monkeypatch):
    monkeypatch.setattr(cp_telemetry, "_SENTRY_CONFIGURED", False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    out = StringIO()
    call_command("verify_sentry", stdout=out)
    assert "SENTRY_DSN is not configured" in out.getvalue()

    monkeypatch.setenv("SENTRY_DSN", "https://public@example.ingest.sentry.io/99")
    fake_scope = MagicMock()
    scope_cm = MagicMock()
    scope_cm.__enter__.return_value = fake_scope

    out_configured = StringIO()
    with (
        patch.object(cp_telemetry.sentry_sdk, "init"),
        patch.object(cp_telemetry.sentry_sdk, "set_tag"),
        patch.object(cp_telemetry.sentry_sdk, "new_scope", return_value=scope_cm),
        patch.object(
            cp_telemetry.sentry_sdk,
            "capture_message",
            return_value="evt-control-plane-1",
        ) as mock_capture,
        patch.object(cp_telemetry.sentry_sdk, "flush") as mock_flush,
    ):
        call_command(
            "verify_sentry", "--service", "control-plane", stdout=out_configured
        )

    mock_capture.assert_called_once()
    fake_scope.set_tag.assert_any_call("service", "control-plane")
    fake_scope.set_tag.assert_any_call("verification", "true")
    mock_flush.assert_called_once_with(timeout=5.0)
    assert "evt-control-plane-1" in out_configured.getvalue()

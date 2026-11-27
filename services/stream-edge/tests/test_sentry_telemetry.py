import asyncio
from unittest.mock import MagicMock, patch

from fastapi.exceptions import RequestValidationError
import pytest
from starlette.exceptions import HTTPException as StarletteHTTPException

from stream_edge import telemetry as edge_telemetry
from stream_edge.collectors import run as collectors_run
from stream_edge.workers import lifecycle as lifecycle_worker
from stream_edge.workers import rollup as rollup_worker


def test_configure_sentry_free_plan_defaults_and_fastapi_flag(monkeypatch):
    monkeypatch.setattr(edge_telemetry, "_SENTRY_CONFIGURED", False)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.ingest.sentry.io/20")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "production")
    monkeypatch.setenv("SENTRY_RELEASE", "deadbeef1234")
    monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)

    with (
        patch.object(edge_telemetry.sentry_sdk, "init") as mock_init,
        patch.object(edge_telemetry.sentry_sdk, "set_tag") as mock_tag,
    ):
        assert edge_telemetry.configure_sentry("enrichment-worker") is True

    kwargs = mock_init.call_args.kwargs
    assert kwargs["data_collection"] == {
        "user_info": False,
        "cookies": {"mode": "off"},
        "http_bodies": [],
        "gen_ai": {"inputs": False, "outputs": False},
    }
    assert kwargs["traces_sample_rate"] == pytest.approx(0.0)
    assert kwargs["profile_session_sample_rate"] == pytest.approx(0.0)
    assert kwargs["release"] == "deadbeef1234"
    assert kwargs["integrations"] == []
    assert kwargs["before_send_span"] is edge_telemetry.before_send_span
    mock_tag.assert_any_call("service", "enrichment-worker")
    mock_tag.assert_any_call("environment", "production")

    monkeypatch.setattr(edge_telemetry, "_SENTRY_CONFIGURED", False)
    with (
        patch.object(edge_telemetry.sentry_sdk, "init") as mock_init_api,
        patch.object(edge_telemetry.sentry_sdk, "set_tag"),
    ):
        assert (
            edge_telemetry.configure_sentry("stream-edge", include_fastapi=True) is True
        )
    assert len(mock_init_api.call_args.kwargs["integrations"]) == 1


def test_stream_edge_configure_sentry_accepts_real_sentry_sdk_v3_init(monkeypatch):
    monkeypatch.setattr(edge_telemetry, "_SENTRY_CONFIGURED", False)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.ingest.sentry.io/21")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "production")
    monkeypatch.setenv("SENTRY_RELEASE", "sha-edge-init")
    try:
        assert (
            edge_telemetry.configure_sentry("stream-edge", include_fastapi=True) is True
        )
        client = edge_telemetry.sentry_sdk.get_client()
        assert client.is_active() is True
        assert client.options["traces_sample_rate"] == pytest.approx(0.0)
        assert client.options["profile_session_sample_rate"] == pytest.approx(0.0)
        assert client.options["data_collection"]["user_info"] is False
        assert client.options["data_collection"]["cookies"] == {"mode": "off"}
        assert "google_genai" not in client.integrations
    finally:
        edge_telemetry.sentry_sdk.init(dsn="")
        monkeypatch.setattr(edge_telemetry, "_SENTRY_CONFIGURED", False)


def test_stream_edge_before_send_scrubs_hmac_token_headers_and_payload():
    event = {
        "request": {
            "url": "https://vektryn.debastiani.dev/stream/alerts?token=hmac-secret-value&user=1",
            "query_string": "token=hmac-secret-value&user=1",
            "cookies": {"sessionid": "xyz"},
            "headers": {
                "Cookie": "sessionid=xyz",
                "Authorization": "Bearer secret",
                "X-CSRFToken": "csrf-tok",
                "X-Ingest-API-Key": "ingest-secret",
            },
            "data": {
                "confirm_password": "secret",
                "raw_text": "Private resume text",
                "source": "greenhouse",
            },
        },
        "breadcrumbs": {
            "values": [
                {
                    "data": {
                        "url": "https://vektryn.debastiani.dev/stream/alerts?token=hmac-breadcrumb"
                    }
                }
            ]
        },
    }

    scrubbed = edge_telemetry.before_send(event, {})
    assert scrubbed is not None
    req = scrubbed["request"]
    assert "cookies" not in req
    assert "hmac-secret-value" not in req["url"]
    assert "user=1" in req["url"]
    assert "hmac-secret-value" not in req["query_string"]
    assert req["headers"]["Cookie"] == "[Filtered]"
    assert req["headers"]["Authorization"] == "[Filtered]"
    assert req["headers"]["X-CSRFToken"] == "[Filtered]"
    assert req["headers"]["X-Ingest-API-Key"] == "[Filtered]"
    assert req["data"]["confirm_password"] == "[Filtered]"
    assert req["data"]["raw_text"] == "[Filtered]"
    assert req["data"]["source"] == "greenhouse"
    assert "hmac-breadcrumb" not in scrubbed["breadcrumbs"]["values"][0]["data"]["url"]


@pytest.mark.parametrize(
    ("event", "hint"),
    [
        ({"request": {"url": "https://stream-edge.run.app/health"}}, {}),
        (
            {},
            {
                "exc_info": (
                    StarletteHTTPException,
                    StarletteHTTPException(status_code=403, detail="denied"),
                    None,
                )
            },
        ),
        (
            {},
            {
                "exc_info": (
                    RequestValidationError,
                    RequestValidationError([]),
                    None,
                )
            },
        ),
        (
            {},
            {
                "exc_info": (
                    asyncio.CancelledError,
                    asyncio.CancelledError(),
                    None,
                )
            },
        ),
        ({"contexts": {"response": {"status_code": 429}}}, {}),
    ],
)
def test_stream_edge_before_send_drops_health_4xx_and_cancelled(event, hint):
    assert edge_telemetry.before_send(event, hint) is None


def test_stream_edge_before_send_keeps_5xx_and_worker_errors():
    exc = StarletteHTTPException(status_code=503, detail="broker unavailable")
    assert (
        edge_telemetry.before_send(
            {"request": {"url": "https://stream-edge.run.app/ingest/jobs"}},
            {"exc_info": (StarletteHTTPException, exc, None)},
        )
        is not None
    )
    assert (
        edge_telemetry.before_send_span(
            {"request": {"url": "https://stream-edge.run.app/health"}},
            {},
        )
        is None
    )


def test_capture_worker_exception_sets_isolated_tags_and_is_noop_when_unconfigured(
    monkeypatch,
):
    monkeypatch.setattr(edge_telemetry, "_SENTRY_CONFIGURED", False)
    with patch.object(edge_telemetry.sentry_sdk, "capture_exception") as mock_cap:
        assert (
            edge_telemetry.capture_worker_exception(
                RuntimeError("boom"), worker="enrichment-worker", topic="jobs.raw"
            )
            is None
        )
        mock_cap.assert_not_called()

    monkeypatch.setattr(edge_telemetry, "_SENTRY_CONFIGURED", True)
    fake_scope = MagicMock()
    scope_cm = MagicMock()
    scope_cm.__enter__.return_value = fake_scope
    err = ValueError("gemini timeout")

    with (
        patch.object(edge_telemetry.sentry_sdk, "new_scope", return_value=scope_cm),
        patch.object(
            edge_telemetry.sentry_sdk,
            "capture_exception",
            return_value="evt-worker-1",
        ) as mock_cap,
    ):
        event_id = edge_telemetry.capture_worker_exception(
            err,
            worker="matcher-worker",
            topic="jobs.enriched",
            extra={"raw_text": "secret resume", "batch": 5},
        )

    assert event_id == "evt-worker-1"
    fake_scope.set_tag.assert_any_call("worker", "matcher-worker")
    fake_scope.set_tag.assert_any_call("topic", "jobs.enriched")
    fake_scope.set_tag.assert_any_call("error_type", "ValueError")
    fake_scope.set_extra.assert_any_call("raw_text", "[Filtered]")
    fake_scope.set_extra.assert_any_call("batch", 5)
    mock_cap.assert_called_once_with(err)


def test_short_lived_jobs_initialize_capture_and_flush_sentry(monkeypatch):
    monkeypatch.setattr(
        collectors_run,
        "_parse_args",
        lambda: MagicMock(
            boards_per_ats=1,
            max_total=1,
            resume_id=None,
            min_skills=2,
            refresh_discovery=False,
        ),
    )

    with (
        patch.object(collectors_run, "configure_sentry") as mock_cfg,
        patch.object(
            collectors_run, "run_collection", side_effect=RuntimeError("collect boom")
        ),
        patch.object(collectors_run, "capture_worker_exception") as mock_cap,
        patch.object(collectors_run, "flush_sentry") as mock_flush,
    ):
        with pytest.raises(RuntimeError, match="collect boom"):
            collectors_run.main()
    mock_cfg.assert_called_once_with("vektryn-collect")
    mock_cap.assert_called_once()
    mock_flush.assert_called_once_with(timeout=5.0)

    with (
        patch.object(rollup_worker, "configure_sentry") as mock_cfg_r,
        patch.object(
            rollup_worker, "run_daily_rollup", side_effect=RuntimeError("rollup boom")
        ),
        patch.object(rollup_worker, "capture_worker_exception") as mock_cap_r,
        patch.object(rollup_worker, "flush_sentry") as mock_flush_r,
    ):
        with pytest.raises(RuntimeError, match="rollup boom"):
            rollup_worker.main()
    mock_cfg_r.assert_called_once_with("vektryn-rollup")
    mock_cap_r.assert_called_once()
    mock_flush_r.assert_called_once_with(timeout=5.0)

    with (
        patch.object(lifecycle_worker, "configure_sentry") as mock_cfg_l,
        patch.object(
            lifecycle_worker,
            "run_lifecycle_check",
            side_effect=RuntimeError("lifecycle boom"),
        ),
        patch.object(lifecycle_worker, "capture_worker_exception") as mock_cap_l,
        patch.object(lifecycle_worker, "flush_sentry") as mock_flush_l,
    ):
        with pytest.raises(RuntimeError, match="lifecycle boom"):
            lifecycle_worker.main()
    mock_cfg_l.assert_called_once_with("vektryn-lifecycle")
    mock_cap_l.assert_called_once()
    mock_flush_l.assert_called_once_with(timeout=5.0)


def test_stream_edge_verify_cli_handles_unset_and_configured_dsn(monkeypatch, capsys):
    monkeypatch.setattr(edge_telemetry, "_SENTRY_CONFIGURED", False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert edge_telemetry.main(["--verify", "--service", "enrichment-worker"]) == 0
    assert "SENTRY_DSN is not configured" in capsys.readouterr().out

    monkeypatch.setenv("SENTRY_DSN", "https://public@example.ingest.sentry.io/42")
    fake_scope = MagicMock()
    scope_cm = MagicMock()
    scope_cm.__enter__.return_value = fake_scope

    with (
        patch.object(edge_telemetry.sentry_sdk, "init"),
        patch.object(edge_telemetry.sentry_sdk, "set_tag"),
        patch.object(edge_telemetry.sentry_sdk, "new_scope", return_value=scope_cm),
        patch.object(
            edge_telemetry.sentry_sdk,
            "capture_message",
            return_value="evt-edge-cli-1",
        ),
        patch.object(edge_telemetry.sentry_sdk, "flush") as mock_flush,
    ):
        assert edge_telemetry.main(["--verify", "--service", "enrichment-worker"]) == 0

    mock_flush.assert_called_once_with(timeout=5.0)
    assert "evt-edge-cli-1" in capsys.readouterr().out

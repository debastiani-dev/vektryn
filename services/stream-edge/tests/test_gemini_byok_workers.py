"""Tests for Feature Spec #18 in stream-edge (BYOK matcher, enrichment cap, telemetry)."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from cryptography.fernet import Fernet
from google.genai import errors as genai_errors
from google.genai import types
import pytest

from stream_edge.clients.gemini import (
    ExtractedJobMetadata,
    GeminiStreamClient,
    UserGeminiScoringManager,
    UserScoringPausedError,
)
from stream_edge.config import settings
from stream_edge.telemetry import before_send
from stream_edge.workers.enrichment import process_raw_message
from stream_edge.workers.matcher import (
    _rescore_resume_sync,
    _upsert_job_and_score_sync,
    _validate_byok_encryption_key_once,
)
from vektryn_contracts import (
    ATSSource,
    EMBEDDING_DIMENSIONS,
    GeminiErrorAction,
    JobEnrichedEvent,
    JobRawEvent,
    JobRescoreEvent,
    NotificationKind,
    encrypt_api_key,
)


def test_enrichment_client_uses_thinking_config_without_temperature():
    seen: list[tuple[str, types.GenerateContentConfig]] = []

    def _generate_side_effect(*, model, contents, config):
        seen.append((model, config))
        if model == "gemini-3.5-flash-lite":
            raise genai_errors.APIError(
                429,
                {
                    "error": {
                        "code": 429,
                        "status": "RESOURCE_EXHAUSTED",
                        "message": "Quota",
                    }
                },
                None,
            )
        return SimpleNamespace(text=ExtractedJobMetadata().model_dump_json())

    fake_sdk = MagicMock()
    fake_sdk.models.generate_content.side_effect = _generate_side_effect
    client = GeminiStreamClient.__new__(GeminiStreamClient)
    client._client = fake_sdk

    with patch("stream_edge.clients.gemini.time.sleep"):
        raw_json, used_model = client._generate_structured_sync(
            prompt="Extract metadata",
            schema=ExtractedJobMetadata,
        )

    assert used_model == "gemini-3.8-flash"
    assert json.loads(raw_json)["seniority"] == "unknown"
    assert seen[0][0] == "gemini-3.5-flash-lite"
    assert seen[0][1].thinking_config.thinking_level == types.ThinkingLevel.MINIMAL
    assert seen[0][1].temperature is None
    assert seen[-1][0] == "gemini-3.8-flash"
    assert seen[-1][1].thinking_config.thinking_level == types.ThinkingLevel.LOW
    assert seen[-1][1].temperature is None


def test_extracted_job_metadata_coerces_empty_and_null_salary_strings():
    raw_empty = json.dumps(
        {
            "seniority": "senior",
            "contract_type": "b2b_contractor",
            "work_mode": "remote",
            "language": "en",
            "region_eligibility": ["worldwide"],
            "salary_min": "",
            "salary_max": "  ",
            "salary_currency": None,
            "salary_period": "",
            "tech_stack": ["python"],
        }
    )
    parsed = ExtractedJobMetadata.model_validate_json(raw_empty)
    assert parsed.salary_min is None
    assert parsed.salary_max is None
    assert parsed.salary_currency == ""
    assert parsed.salary_period is None

    raw_formatted = json.dumps(
        {
            "salary_min": "120,000",
            "salary_max": "N/A",
            "salary_currency": "USD",
            "salary_period": "ANNUAL",
        }
    )
    parsed_formatted = ExtractedJobMetadata.model_validate_json(raw_formatted)
    assert str(parsed_formatted.salary_min) == "120000"
    assert parsed_formatted.salary_max is None
    assert parsed_formatted.salary_period == "annual"


async def test_enrichment_daily_cap_skips_automated_releases_lock_and_exempts_manual(
    monkeypatch,
):
    monkeypatch.setattr(settings, "enrichment_daily_cap", 250)

    auto_event = JobRawEvent(
        ats_source=ATSSource.GREENHOUSE,
        external_id="gh-over-cap",
        content_hash="a" * 64,
        title="Backend Engineer",
        company_name="Acme",
        apply_url="https://example.com/jobs/1",
        raw_html_gcs_uri="gs://bucket/1.html",
        description_clean="Python",
    )
    fake_redis = MagicMock()
    fake_redis.acquire_content_hash = AsyncMock(return_value=True)
    fake_redis.try_consume_enrichment_daily_quota = AsyncMock(return_value=(False, 250))
    fake_redis.release_content_hash = AsyncMock()
    fake_gemini = MagicMock()
    fake_gemini.extract_job_metadata = AsyncMock()
    fake_producer = MagicMock()
    fake_producer.publish = AsyncMock()

    with patch(
        "stream_edge.workers.enrichment.persist_pipeline_error_notifications"
    ) as mock_notify:
        await process_raw_message(
            raw_bytes=auto_event.model_dump_json().encode("utf-8"),
            gemini=fake_gemini,
            redis_client=fake_redis,
            producer=fake_producer,
        )

    fake_redis.release_content_hash.assert_awaited_once_with(auto_event.content_hash)
    fake_gemini.extract_job_metadata.assert_not_awaited()
    fake_producer.publish.assert_not_awaited()
    mock_notify.assert_called_once()
    assert mock_notify.call_args.kwargs["error_type"] == "EnrichmentDailyCapReached"

    # Manual imports bypass daily cap completely
    manual_event = JobRawEvent(
        ats_source=ATSSource.MANUAL,
        external_id="manual-exempt-1",
        content_hash="b" * 64,
        title="Staff Python Engineer",
        company_name="Beta",
        apply_url="https://example.com/jobs/manual",
        raw_html_gcs_uri="gs://bucket/manual.html",
        description_clean="Python Kafka",
    )
    fake_redis_manual = MagicMock()
    fake_redis_manual.acquire_content_hash = AsyncMock(return_value=True)
    fake_redis_manual.try_consume_enrichment_daily_quota = AsyncMock()
    fake_gemini_manual = MagicMock()
    fake_gemini_manual.extract_job_metadata = AsyncMock(
        return_value=ExtractedJobMetadata(tech_stack=["python"])
    )
    fake_gemini_manual.embed_job_text = AsyncMock(
        return_value=[0.01] * EMBEDDING_DIMENSIONS
    )
    fake_producer_manual = MagicMock()
    fake_producer_manual.publish = AsyncMock()

    await process_raw_message(
        raw_bytes=manual_event.model_dump_json().encode("utf-8"),
        gemini=fake_gemini_manual,
        redis_client=fake_redis_manual,
        producer=fake_producer_manual,
    )
    fake_redis_manual.try_consume_enrichment_daily_quota.assert_not_awaited()
    fake_producer_manual.publish.assert_awaited_once()


def test_user_scoring_manager_lru_prepayment_depleted_and_invalid_key():
    manager = UserGeminiScoringManager(max_cached_clients=2)
    with patch("stream_edge.clients.gemini.genai.Client") as mock_cls:
        mock_cls.side_effect = [MagicMock(id=1), MagicMock(id=2), MagicMock(id=3)]
        manager._get_client(1, "AQ.key-one-12345678901234567890")
        manager._get_client(2, "AQ.key-two-12345678901234567890")
        manager._get_client(3, "AQ.key-three-123456789012345678")
    assert len(manager._clients) == 2

    # HTTP 429 "prepayment credits are depleted" classifies as PAYMENT_REQUIRED -> ai_quota_exhausted + short-circuit
    depleted_client = MagicMock()
    depleted_client.models.generate_content.side_effect = genai_errors.APIError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "Prepayment credits are depleted.",
            }
        },
        None,
    )
    with (
        patch.object(manager, "_get_redis", return_value=None),
        patch.object(manager, "_get_client", return_value=depleted_client),
        patch(
            "stream_edge.clients.gemini.persist_user_ai_notification"
        ) as mock_user_notif,
    ):
        with pytest.raises(UserScoringPausedError) as exc_info:
            manager.evaluate_resume_fit_sync(
                user_id=7,
                api_key="AQ.depleted-key-1234567890123456",
                preferred_model="auto",
                allow_model_fallback=True,
                resume_text="Python",
                resume_skills=["python"],
                job_title="Backend",
                company_name="Acme",
                job_description="Python",
                job_stack=["python"],
            )
    assert exc_info.value.action is GeminiErrorAction.PAYMENT_REQUIRED
    assert depleted_client.models.generate_content.call_count == 1
    mock_user_notif.assert_called_once()
    assert (
        mock_user_notif.call_args.kwargs["kind"] is NotificationKind.AI_QUOTA_EXHAUSTED
    )


def test_matcher_skips_keyless_stage2_and_skips_keyless_rescore_silently():
    job_uuid = uuid4()
    resume_uuid = uuid4()
    event = JobEnrichedEvent(
        ats_source=ATSSource.GREENHOUSE,
        external_id="gh-keyless",
        content_hash="c" * 64,
        title="Backend Engineer",
        company_name="Acme",
        apply_url="https://example.com/jobs/keyless",
        raw_html_gcs_uri="gs://bucket/keyless.html",
        description_clean="Python",
        embedding=[0.01] * EMBEDDING_DIMENSIONS,
    )
    fake_cursor = MagicMock()
    fake_cursor.__enter__.return_value = fake_cursor
    fake_cursor.fetchone.side_effect = [None, None, (job_uuid,), (uuid4(), None)]
    fake_cursor.fetchall.return_value = [
        (
            resume_uuid,
            99,
            "Primary",
            "Python Engineer",
            "h" * 64,
            ["python"],
            [],
            [],
            [],
            70,
            0.91,
            "",  # No BYOK key
            "auto",
            True,
        )
    ]
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.cursor.return_value = fake_cursor
    fake_manager = MagicMock()
    fake_producer = MagicMock()

    with (
        patch("stream_edge.workers.matcher.psycopg.connect", return_value=fake_conn),
        patch("stream_edge.workers.matcher.register_vector"),
        patch("stream_edge.workers.matcher.persist_user_ai_notification") as mock_notif,
    ):
        _upsert_job_and_score_sync(
            enriched=event,
            scoring_manager=fake_manager,
            producer=fake_producer,
            byok_encryption_key=Fernet.generate_key().decode("utf-8"),
        )

    fake_manager.evaluate_resume_fit_sync.assert_not_called()
    mock_notif.assert_not_called()
    fake_conn.commit.assert_called_once()

    # Keyless jobs.rescore returns 0 immediately without touching existing MatchScore rows
    rescore_cursor = MagicMock()
    rescore_cursor.__enter__.return_value = rescore_cursor
    rescore_cursor.fetchall.return_value = [
        (
            resume_uuid,
            99,
            "Python Engineer",
            "h" * 64,
            ["python"],
            [],
            [],
            [],
            70,
            [0.01] * EMBEDDING_DIMENSIONS,
            "Primary",
            "",  # No BYOK key
            "auto",
            True,
        )
    ]
    rescore_conn = MagicMock()
    rescore_conn.__enter__.return_value = rescore_conn
    rescore_conn.cursor.return_value = rescore_cursor

    with (
        patch("stream_edge.workers.matcher.psycopg.connect", return_value=rescore_conn),
        patch("stream_edge.workers.matcher.register_vector"),
    ):
        processed = _rescore_resume_sync(
            event=JobRescoreEvent(
                resume_profile_uuid=resume_uuid,
                user_id=99,
                max_jobs=10,
                force=True,
            ),
            scoring_manager=fake_manager,
            producer=fake_producer,
            byok_encryption_key=Fernet.generate_key().decode("utf-8"),
        )

    assert processed == 0
    rescore_conn.commit.assert_not_called()


def test_matcher_rescore_breaks_early_on_pause_without_dlq_or_null_overwrite():
    fernet_key = Fernet.generate_key().decode("utf-8")
    encrypted = encrypt_api_key("AQ.Ab8RN6-PausedRescoreKey1234567", fernet_key)
    resume_uuid = uuid4()

    fake_cursor = MagicMock()
    fake_cursor.__enter__.return_value = fake_cursor
    fake_cursor.fetchall.side_effect = [
        [
            (
                resume_uuid,
                55,
                "Python Engineer",
                "h" * 64,
                ["python"],
                [],
                [],
                [],
                70,
                [0.01] * EMBEDDING_DIMENSIONS,
                "Primary",
                encrypted,
                "auto",
                True,
            )
        ],
        [
            (
                uuid4(),
                "Job 1",
                "Acme",
                "https://example.com/1",
                "Python",
                "senior",
                "pj",
                ["worldwide"],
                ["python"],
                0.9,
                "greenhouse",
            ),
            (
                uuid4(),
                "Job 2",
                "Beta",
                "https://example.com/2",
                "Python",
                "senior",
                "pj",
                ["worldwide"],
                ["python"],
                0.88,
                "greenhouse",
            ),
        ],
    ]
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.cursor.return_value = fake_cursor

    fake_manager = MagicMock()
    fake_manager.get_pause_state.return_value = None
    fake_manager.evaluate_resume_fit_sync.side_effect = UserScoringPausedError(
        GeminiErrorAction.INVALID_KEY, "invalid"
    )
    fake_producer = MagicMock()

    with (
        patch("stream_edge.workers.matcher.psycopg.connect", return_value=fake_conn),
        patch("stream_edge.workers.matcher.register_vector"),
    ):
        processed = _rescore_resume_sync(
            event=JobRescoreEvent(
                resume_profile_uuid=resume_uuid,
                user_id=55,
                max_jobs=10,
                force=True,
            ),
            scoring_manager=fake_manager,
            producer=fake_producer,
            byok_encryption_key=fernet_key,
        )

    assert processed == 0
    assert fake_manager.evaluate_resume_fit_sync.call_count == 1
    fake_conn.commit.assert_not_called()


def test_matcher_missing_byok_encryption_key_fails_safe(monkeypatch):
    monkeypatch.setattr(settings, "byok_encryption_key", "")
    with patch("stream_edge.workers.matcher.capture_worker_error_message") as mock_err:
        assert _validate_byok_encryption_key_once() == ""
    mock_err.assert_called_once()


def test_stream_edge_telemetry_scrubs_aiza_and_aq_keys():
    aiza = "AIzaSyD1234567890abcdefghijklmnop"
    aq = "AQ.Ab8RN6L_sample.token-1234567890abcdef"
    event = {
        "message": f"Worker error with {aq}",
        "request": {
            "headers": {"X-Goog-Api-Key": aq},
            "data": {"gemini_api_key": aiza},
        },
        "exception": {"values": [{"value": f"APIError for key {aq} / {aiza}"}]},
        "logentry": {"message": f"Key={aq}", "params": [aiza]},
        "breadcrumbs": {"values": [{"message": f"Called with {aq}"}]},
    }
    scrubbed = before_send(event, {})
    assert scrubbed is not None
    serialized = str(scrubbed)
    assert aiza not in serialized
    assert aq not in serialized
    assert scrubbed["request"]["headers"]["X-Goog-Api-Key"] == "[Filtered]"


def test_scoring_manager_disables_sdk_retries_and_falls_back_immediately_on_504(
    monkeypatch,
):
    monkeypatch.setattr(settings, "redis_url", "")
    manager = UserGeminiScoringManager()
    assert manager.REQUEST_TIMEOUT_MS == 45_000

    seen_models: list[str] = []
    seen_http_options = []

    def _side_effect(*, model, contents, config):
        seen_models.append(model)
        if model == "gemini-4-carbon":
            raise genai_errors.ServerError(
                504,
                {
                    "error": {
                        "code": 504,
                        "status": "DEADLINE_EXCEEDED",
                        "message": "Deadline expired before operation could complete.",
                    }
                },
                None,
            )
        return SimpleNamespace(
            text=(
                '{"fit_score": 81, "matched_skills": ["python"], '
                '"missing_keywords": [], "talking_points": ["point"], '
                '"gap_summary": "Solid fit.", "fit_highlights": ["Python"], '
                '"watchout_note": ""}'
            )
        )

    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = _side_effect

    def _capture_client(*, api_key, http_options):
        seen_http_options.append(http_options)
        return fake_client

    with patch("stream_edge.clients.gemini.genai.Client", side_effect=_capture_client):
        evaluation, used_model = manager.evaluate_resume_fit_sync(
            user_id=99,
            api_key="AQ.Ab8RN6-Scoring504Key1234567890",
            preferred_model="gemini-4-carbon",
            allow_model_fallback=True,
            resume_text="Senior Python engineer",
            resume_skills=["python"],
            job_title="Staff Python Engineer",
            company_name="Acme",
            job_description="Build distributed services",
            job_stack=["python"],
        )

    assert used_model == "gemini-4-neon"
    assert evaluation.fit_score == 81
    assert seen_models == ["gemini-4-carbon", "gemini-4-neon"]
    assert len(seen_http_options) == 1
    assert seen_http_options[0].timeout == 45_000
    assert seen_http_options[0].retry_options is not None
    assert seen_http_options[0].retry_options.attempts == 1

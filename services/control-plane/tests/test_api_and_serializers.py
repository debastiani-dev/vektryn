from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
import json
from pathlib import Path
import socket
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse
from uuid import uuid4

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
import httpx
import pytest
from rest_framework.test import APIClient, APIRequestFactory

from apps.analytics.models.analytics import CollectorRunLog, StackTrendDaily
from apps.analytics.services import collector_trigger, system_status
from apps.base.models.user_profile import get_or_create_user_profile
from apps.jobs.models.jobs import JobPosting
from apps.jobs.services import hybrid_search, manual_import
from apps.jobs.services.manual_import import (
    MAX_SNAPSHOT_HTML_BYTES,
    ManualImportFetchError,
    ManualImportRateLimitError,
    ManualImportValidationError,
    extract_job_from_html,
    fetch_public_job_page,
    validate_public_http_url,
)
from apps.matching.models.matching import MatchScore
from apps.matching.serializers.matching import MatchScoreSerializer
from apps.resumes.models.resumes import ResumeProfile
from apps.resumes.serializers.resumes import ResumeProfileSerializer
from apps.resumes.services import rescore_publisher
from vektryn_contracts import encrypt_api_key
from apps.resumes.services.rescore_publisher import (
    RescoreBrokerError,
    RescoreCooldownError,
)
from apps.resumes.services.resume_service import ResumeService
from apps.tracker.serializers.leads import ApplicationLeadSerializer
from apps.tracker.services.leads import create_lead, update_lead
from config import telemetry as cp_telemetry
from config.settings import ControlPlaneSettings, _build_database_config
from vektryn_contracts import (
    EMBEDDING_DIMENSIONS,
    JobRescoreEvent,
    verify_stream_token,
)
from vektryn_contracts.enums import (
    ATSSource,
    ContractType,
    LeadPriority,
    LeadStatus,
    RegionEligibility,
    SeniorityLevel,
    TechCategory,
)

User = get_user_model()


def test_settings_supports_secret_key_and_database_url(monkeypatch):
    fake_pw = uuid4().hex
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    monkeypatch.setenv("SECRET_KEY", "alias-secret-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        f"postgresql://clouduser:{fake_pw}@10.0.0.5:5433/vektryn_prod",
    )

    cfg = ControlPlaneSettings(_env_file=None)
    assert cfg.django_secret_key == "alias-secret-key"

    db_cfg = _build_database_config(cfg)
    assert db_cfg["NAME"] == "vektryn_prod"
    assert db_cfg["USER"] == "clouduser"
    assert db_cfg["PASSWORD"] == fake_pw
    assert db_cfg["HOST"] == "10.0.0.5"
    assert db_cfg["PORT"] == 5433


@pytest.mark.django_db
def test_resume_serializer_handles_json_dict_multi_value_fields():
    user = User.objects.create_user(username="alice", password="pw")
    request = APIRequestFactory().post("/api/v1/resumes/", format="json")
    request.user = user

    serializer = ResumeProfileSerializer(
        data={
            "label": "Senior Backend",
            "raw_text": "Python Django PostgreSQL Kafka",
            "target_seniority": ["senior", "staff"],
            "target_contract_types": "pj,b2b_contractor",
            "target_regions": ["brazil", "latam"],
            "min_alert_score": 75,
        },
        context={"request": request},
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["target_seniority"] == [
        SeniorityLevel.SENIOR,
        SeniorityLevel.STAFF,
    ]
    assert serializer.validated_data["target_contract_types"] == [
        ContractType.PJ,
        ContractType.B2B_CONTRACTOR,
    ]
    assert serializer.validated_data["target_regions"] == [
        RegionEligibility.BRAZIL,
        RegionEligibility.LATAM,
    ]


@pytest.mark.django_db
def test_application_lead_serializer_blocks_cross_user_resume_profile():
    owner = User.objects.create_user(username="owner", password="pw")
    attacker = User.objects.create_user(username="attacker", password="pw")

    owner_resume = ResumeProfile.objects.create(
        user=owner,
        label="Owner Resume",
        raw_text="Python Django",
        content_hash="a" * 64,
    )
    job = JobPosting.objects.create(
        ats_source=ATSSource.GREENHOUSE,
        external_id="gh-101",
        content_hash="b" * 64,
        title="Senior Python Engineer",
        company_name="Acme",
        apply_url="https://example.com/jobs/101",
        raw_html_gcs_uri="file:///tmp/101.html",
        description_clean="Build Python backends.",
    )

    request = APIRequestFactory().post("/api/v1/leads/", format="json")
    request.user = attacker

    serializer = ApplicationLeadSerializer(
        data={
            "job_posting": str(job.uuid),
            "resume_profile": str(owner_resume.uuid),
            "status": LeadStatus.SAVED,
        },
        context={"request": request},
    )
    assert not serializer.is_valid()
    assert "resume_profile" in serializer.errors


@pytest.mark.django_db
def test_lead_service_updates_applied_at_and_last_activity_at():
    user = User.objects.create_user(username="bob", password="pw")
    job = JobPosting.objects.create(
        ats_source=ATSSource.ASHBY,
        external_id="ash-202",
        content_hash="c" * 64,
        title="Staff Backend Engineer",
        company_name="Beta",
        apply_url="https://example.com/jobs/202",
        raw_html_gcs_uri="file:///tmp/202.html",
        description_clean="Distributed systems.",
    )

    lead = create_lead(
        user=user,
        validated_data={"job_posting": job, "status": LeadStatus.SAVED},
    )
    assert lead.applied_at is None
    initial_activity = lead.last_activity_at
    assert initial_activity is not None

    update_lead(lead, validated_data={"priority": LeadPriority.HIGH})
    assert lead.last_activity_at == initial_activity

    update_lead(lead, validated_data={"status": LeadStatus.APPLIED})
    assert lead.applied_at is not None
    assert lead.last_activity_at is not None
    assert lead.last_activity_at >= initial_activity


@pytest.mark.django_db
def test_match_score_serializer_exposes_resume_profile_uuid_and_staleness():
    user = User.objects.create_user(username="carol", password="pw")
    resume = ResumeProfile.objects.create(
        user=user,
        label="Primary Resume",
        raw_text="Python FastAPI",
        content_hash="d" * 64,
    )
    job = JobPosting.objects.create(
        ats_source=ATSSource.LEVER,
        external_id="lev-303",
        content_hash="e" * 64,
        title="Backend Engineer",
        company_name="Gamma",
        apply_url="https://example.com/jobs/303",
        raw_html_gcs_uri="file:///tmp/303.html",
        description_clean="FastAPI microservices.",
    )
    match = MatchScore.objects.create(
        job_posting=job,
        resume_profile=resume,
        cosine_similarity=0.84,
        fit_score=88,
        matched_skills=["python", "fastapi"],
        missing_keywords=["kafka"],
        talking_points=["Highlight FastAPI experience."],
        gap_summary="Strong backend match.",
        resume_content_hash="f" * 64,
        scoring_model="gemini-4-hydrogen",
    )

    data = MatchScoreSerializer(match).data
    assert data["resume_profile_uuid"] == str(resume.uuid)
    assert data["resume_profile_label"] == "Primary Resume"
    assert data["is_stale"] is True


@pytest.mark.django_db
def test_health_and_authenticated_leads_endpoints():
    client = APIClient()
    health_resp = client.get("/api/v1/health/")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "ok"

    unauth_resp = client.get("/api/v1/leads/")
    assert unauth_resp.status_code in (401, 403)

    user = User.objects.create_user(username="dave", password="pw")
    client.force_authenticate(user=user)
    auth_resp = client.get("/api/v1/leads/")
    assert auth_resp.status_code == 200
    assert auth_resp.json()["results"] == []


@pytest.mark.django_db
def test_auth_me_endpoint_issues_verifiable_stream_token():
    client = APIClient()
    unauth = client.get("/api/v1/auth/me/")
    assert unauth.status_code in (401, 403)

    user = User.objects.create_user(
        username="eve", email="eve@example.com", password="pw"
    )
    client.force_authenticate(user=user)
    resp = client.get("/api/v1/auth/me/")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["id"] == str(user.id)
    assert payload["username"] == "eve"
    assert verify_stream_token(
        payload["stream_token"], settings.STREAM_AUTH_SECRET
    ) == str(user.id)


@pytest.mark.django_db
def test_resume_service_persists_uploaded_file_uri(tmp_path, settings):
    settings.STORAGE_BACKEND = "local"
    settings.LOCAL_STORAGE_DIR = tmp_path
    settings.GEMINI_API_KEY = ""

    user = User.objects.create_user(username="frank", password="pw")
    uploaded = BytesIO(b"Senior Python Engineer with Django, FastAPI, and Kafka.")
    uploaded.name = "frank_resume.txt"

    service = ResumeService(user=user)
    profile = service.create_profile(
        validated_data={"label": "Uploaded Resume"},
        uploaded_file=uploaded,
    )

    assert profile.source_file_gcs_uri.startswith("file://")
    saved_path = Path(urlparse(profile.source_file_gcs_uri).path)
    assert saved_path.exists()
    assert (
        saved_path.read_bytes()
        == b"Senior Python Engineer with Django, FastAPI, and Kafka."
    )


@pytest.mark.django_db
def test_auth_csrf_login_and_logout_flow():
    User.objects.create_user(
        username="grace", email="grace@example.com", password="secret-password"
    )
    client = APIClient()

    csrf_resp = client.get("/api/v1/auth/csrf/")
    assert csrf_resp.status_code == 200

    bad_login = client.post(
        "/api/v1/auth/login/",
        {"username": "grace", "password": "wrong"},
        format="json",
    )
    assert bad_login.status_code == 401

    good_login = client.post(
        "/api/v1/auth/login/",
        {"username": "grace", "password": "secret-password"},
        format="json",
    )
    assert good_login.status_code == 200
    assert good_login.json()["username"] == "grace"
    assert good_login.json()["stream_token"]

    me_resp = client.get("/api/v1/auth/me/")
    assert me_resp.status_code == 200

    logout_resp = client.post("/api/v1/auth/logout/")
    assert logout_resp.status_code == 204

    me_after_logout = client.get("/api/v1/auth/me/")
    assert me_after_logout.status_code in (401, 403)


def test_database_url_sslmode_and_proxy_settings(monkeypatch):
    fake_pw = uuid4().hex
    monkeypatch.setenv(
        "DATABASE_URL",
        f"postgresql://neonuser:{fake_pw}@ep-demo.neon.tech:5432/vektryn?sslmode=require",
    )
    cfg = ControlPlaneSettings(_env_file=None)
    db_cfg = _build_database_config(cfg)
    assert db_cfg["OPTIONS"] == {"sslmode": "require"}
    assert settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
    assert settings.USE_X_FORWARDED_HOST is True


def test_control_plane_sentry_gated_by_dsn(monkeypatch):
    monkeypatch.setattr(cp_telemetry, "_SENTRY_CONFIGURED", False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    with patch.object(cp_telemetry.sentry_sdk, "init") as mock_init:
        assert cp_telemetry.configure_sentry() is False
        mock_init.assert_not_called()

        monkeypatch.setenv("SENTRY_DSN", "https://public@example.ingest.sentry.io/1")
        with patch.object(cp_telemetry.sentry_sdk, "set_tag") as mock_tag:
            assert cp_telemetry.configure_sentry("control-plane") is True
            mock_init.assert_called_once()
            mock_tag.assert_any_call("service", "control-plane")
            mock_tag.assert_any_call("environment", "production")


@pytest.mark.django_db
def test_matches_endpoint_returns_global_summary_totals_across_pages():
    user = User.objects.create_user(username="heidi", password="pw")
    other = User.objects.create_user(username="ivan", password="pw")

    resume = ResumeProfile.objects.create(
        user=user,
        label="Primary Backend",
        raw_text="Python Django Kafka",
        content_hash="1" * 64,
    )
    other_resume = ResumeProfile.objects.create(
        user=other,
        label="Other Resume",
        raw_text="Go Rust",
        content_hash="2" * 64,
    )

    # Create 27 matches for user (> PAGE_SIZE=25) so pagination splits across 2 pages:
    # 10 strong (fit_score=85), 8 alert-only (fit_score=75), 6 below threshold (fit_score=50),
    # and 3 unevaluated (fit_score=None).
    scores = [85] * 10 + [75] * 8 + [50] * 6 + [None] * 3
    for idx, score in enumerate(scores):
        job = JobPosting.objects.create(
            ats_source=ATSSource.GREENHOUSE,
            external_id=f"gh-page-{idx}",
            content_hash=f"{idx:064x}",
            title=f"Engineer {idx}",
            company_name="Acme",
            apply_url=f"https://example.com/jobs/{idx}",
            raw_html_gcs_uri=f"file:///tmp/{idx}.html",
            description_clean="Backend role.",
        )
        MatchScore.objects.create(
            job_posting=job,
            resume_profile=resume,
            cosine_similarity=0.80,
            fit_score=score,
            resume_content_hash=resume.content_hash,
        )

    # Add an inactive job with a high score for the same user; excluded by default
    inactive_job = JobPosting.objects.create(
        ats_source=ATSSource.GREENHOUSE,
        external_id="gh-inactive-1",
        content_hash="e" * 64,
        title="Closed Role",
        company_name="Acme",
        apply_url="https://example.com/jobs/closed",
        raw_html_gcs_uri="file:///tmp/closed.html",
        description_clean="Closed role.",
        is_active=False,
    )
    MatchScore.objects.create(
        job_posting=inactive_job,
        resume_profile=resume,
        cosine_similarity=0.92,
        fit_score=92,
        resume_content_hash=resume.content_hash,
    )

    # Add a high-scoring match for another user to verify IDOR isolation in summary counts
    other_job = JobPosting.objects.create(
        ats_source=ATSSource.ASHBY,
        external_id="ash-other-1",
        content_hash="f" * 64,
        title="Other Role",
        company_name="OtherCo",
        apply_url="https://example.com/jobs/other",
        raw_html_gcs_uri="file:///tmp/other.html",
        description_clean="Other role.",
    )
    MatchScore.objects.create(
        job_posting=other_job,
        resume_profile=other_resume,
        cosine_similarity=0.95,
        fit_score=95,
        resume_content_hash=other_resume.content_hash,
    )

    client = APIClient()
    client.force_authenticate(user=user)

    page1 = client.get("/api/v1/matches/?page=1")
    assert page1.status_code == 200
    body1 = page1.json()
    assert body1["count"] == 27
    assert len(body1["results"]) == 25
    assert body1["summary"] == {
        "ai_scored_count": 24,
        "strong_fit_count": 10,
        "alert_threshold_count": 18,
    }

    # Page 2 has only 2 rows, yet summary must still report totals across all 27 active matches
    page2 = client.get("/api/v1/matches/?page=2")
    assert page2.status_code == 200
    body2 = page2.json()
    assert len(body2["results"]) == 2
    assert body2["summary"] == {
        "ai_scored_count": 24,
        "strong_fit_count": 10,
        "alert_threshold_count": 18,
    }

    # Explicit include_inactive=true surfaces closed roles in count and summary
    with_inactive = client.get("/api/v1/matches/?include_inactive=true")
    assert with_inactive.status_code == 200
    with_inactive_body = with_inactive.json()
    assert with_inactive_body["count"] == 28
    assert with_inactive_body["summary"] == {
        "ai_scored_count": 25,
        "strong_fit_count": 11,
        "alert_threshold_count": 19,
    }

    # Filters apply consistently to both count and summary
    filtered = client.get("/api/v1/matches/?min_fit_score=80")
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["count"] == 10
    assert filtered_body["summary"] == {
        "ai_scored_count": 10,
        "strong_fit_count": 10,
        "alert_threshold_count": 10,
    }

    # alert_threshold_count dynamically tracks each resume's configured min_alert_score
    resume.min_alert_score = 85
    resume.save(update_fields=["min_alert_score", "modified_at"])
    custom_threshold = client.get("/api/v1/matches/?page=1")
    assert custom_threshold.status_code == 200
    custom_body = custom_threshold.json()
    assert custom_body["results"][0]["resume_min_alert_score"] == 85
    assert custom_body["summary"] == {
        "ai_scored_count": 24,
        "strong_fit_count": 10,
        "alert_threshold_count": 10,
    }


def test_rescore_publisher_raises_on_delivery_error_or_flush_timeout(settings):
    settings.KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
    event = JobRescoreEvent(resume_profile_uuid=uuid4(), user_id=7)

    # Case 1: flush() returns remaining > 0 (timeout)
    timeout_producer = MagicMock()
    timeout_producer.flush.return_value = 1
    with patch.object(
        rescore_publisher, "_get_producer", return_value=timeout_producer
    ):
        with pytest.raises(RescoreBrokerError, match="flush timeout"):
            rescore_publisher.publish_rescore_event(event, require_broker=True)

    # Case 2: on_delivery callback reports broker error even though flush() returns 0
    error_producer = MagicMock()

    def _produce_with_error(*_args, **kwargs):
        kwargs["on_delivery"]("BrokerNotAvailable", None)

    error_producer.produce.side_effect = _produce_with_error
    error_producer.flush.return_value = 0
    with patch.object(rescore_publisher, "_get_producer", return_value=error_producer):
        with pytest.raises(RescoreBrokerError, match="BrokerNotAvailable"):
            rescore_publisher.publish_rescore_event(event, require_broker=True)

    # Case 3: clean delivery succeeds
    ok_producer = MagicMock()

    def _produce_ok(*_args, **kwargs):
        kwargs["on_delivery"](None, MagicMock())

    ok_producer.produce.side_effect = _produce_ok
    ok_producer.flush.return_value = 0
    with patch.object(rescore_publisher, "_get_producer", return_value=ok_producer):
        assert (
            rescore_publisher.publish_rescore_event(event, require_broker=True) is True
        )


@pytest.mark.django_db
def test_resume_service_auto_rescore_triggers(django_capture_on_commit_callbacks):
    user = User.objects.create_user(username="judy", password="pw")
    service = ResumeService(user=user)
    fake_embedding = [0.02] * EMBEDDING_DIMENSIONS

    published: list[JobRescoreEvent] = []

    def _record(event: JobRescoreEvent, **_kwargs):
        published.append(event)
        return True

    with (
        patch.object(
            ResumeService,
            "generate_embedding_and_skills",
            return_value=(fake_embedding, ["python", "django"]),
        ),
        patch(
            "apps.resumes.services.resume_service.publish_rescore_event",
            side_effect=_record,
        ),
    ):
        # 1. Creating an active embedded profile enqueues force=False rescore
        with django_capture_on_commit_callbacks(execute=True):
            profile = service.create_profile(
                validated_data={
                    "label": "Backend",
                    "raw_text": "Python Django",
                    "is_active": True,
                }
            )
        assert len(published) == 1
        assert published[-1].resume_profile_uuid == profile.uuid
        assert published[-1].force is False

        # 2. Label-only edit must NOT trigger rescoring
        with django_capture_on_commit_callbacks(execute=True):
            service.update_profile(
                instance=profile, validated_data={"label": "Senior Backend"}
            )
        assert len(published) == 1

        # 3. Targeting filter change triggers force=True rescore
        with django_capture_on_commit_callbacks(execute=True):
            service.update_profile(
                instance=profile,
                validated_data={"target_regions": [RegionEligibility.BRAZIL]},
            )
        assert len(published) == 2
        assert published[-1].force is True

        # 4. Content edit triggers force=False rescore (new hash makes existing rows stale)
        with django_capture_on_commit_callbacks(execute=True):
            service.update_profile(
                instance=profile,
                validated_data={"raw_text": "Python Django FastAPI Kafka"},
            )
        assert len(published) == 3
        assert published[-1].force is False

        # 5. Pausing must NOT trigger rescoring; reactivating triggers force=False
        with django_capture_on_commit_callbacks(execute=True):
            service.update_profile(
                instance=profile, validated_data={"is_active": False}
            )
        assert len(published) == 3

        with django_capture_on_commit_callbacks(execute=True):
            service.update_profile(instance=profile, validated_data={"is_active": True})
        assert len(published) == 4
        assert published[-1].force is False


@pytest.mark.django_db
def test_resume_rescore_endpoint_validation_cooldown_broker_error_and_idor():
    owner = User.objects.create_user(username="karl", password="pw")
    other = User.objects.create_user(username="liam", password="pw")
    fake_embedding = [0.03] * EMBEDDING_DIMENSIONS

    active_resume = ResumeProfile.objects.create(
        user=owner,
        label="Active Embedded",
        raw_text="Python Django",
        content_hash="1" * 64,
        embedding=fake_embedding,
        is_active=True,
    )
    paused_resume = ResumeProfile.objects.create(
        user=owner,
        label="Paused Embedded",
        raw_text="Python Django",
        content_hash="2" * 64,
        embedding=fake_embedding,
        is_active=False,
    )
    unembedded_resume = ResumeProfile.objects.create(
        user=owner,
        label="Active Unembedded",
        raw_text="Python Django",
        content_hash="3" * 64,
        embedding=None,
        is_active=True,
    )

    client = APIClient()
    client.force_authenticate(user=owner)

    # Guard 1: paused profile -> 400
    paused_resp = client.post(f"/api/v1/resumes/{paused_resume.uuid}/rescore/", {})
    assert paused_resp.status_code == 400

    # Guard 2: unembedded profile -> 400
    unembedded_resp = client.post(
        f"/api/v1/resumes/{unembedded_resume.uuid}/rescore/", {}
    )
    assert unembedded_resp.status_code == 400

    # Guard 2b: keyless user on embedded active profile -> 400
    keyless_resp = client.post(f"/api/v1/resumes/{active_resume.uuid}/rescore/", {})
    assert keyless_resp.status_code == 400

    # Configure a BYOK key for owner so remaining rescore guards can be exercised
    owner_profile = get_or_create_user_profile(owner)
    owner_profile.gemini_api_key_encrypted = "fernet-token-placeholder"
    owner_profile.gemini_api_key_last4 = "1234"
    owner_profile.save(
        update_fields=["gemini_api_key_encrypted", "gemini_api_key_last4"]
    )

    # Guard 2b: keyless user on embedded active profile -> 400
    keyless_resp = client.post(f"/api/v1/resumes/{active_resume.uuid}/rescore/", {})
    assert keyless_resp.status_code == 400

    # Configure a BYOK key for owner so remaining rescore guards can be exercised
    owner_profile = get_or_create_user_profile(owner)
    owner_profile.gemini_api_key_encrypted = "fernet-token-placeholder"
    owner_profile.gemini_api_key_last4 = "1234"
    owner_profile.save(
        update_fields=["gemini_api_key_encrypted", "gemini_api_key_last4"]
    )

    # Guard 3: Redis cooldown active -> 429 + Retry-After
    with patch(
        "apps.resumes.services.resume_service.acquire_rescore_cooldown",
        side_effect=RescoreCooldownError(retry_after=30),
    ):
        throttled = client.post(f"/api/v1/resumes/{active_resume.uuid}/rescore/", {})
    assert throttled.status_code == 429
    assert throttled["Retry-After"] == "30"

    # Guard 4: Broker failure -> 503 and releases cooldown
    with (
        patch(
            "apps.resumes.services.resume_service.acquire_rescore_cooldown",
            return_value=True,
        ),
        patch(
            "apps.resumes.services.resume_service.publish_rescore_event",
            side_effect=RescoreBrokerError("broker down"),
        ),
        patch(
            "apps.resumes.services.resume_service.release_rescore_cooldown"
        ) as mock_release,
    ):
        failed = client.post(f"/api/v1/resumes/{active_resume.uuid}/rescore/", {})
    assert failed.status_code == 503
    mock_release.assert_called_once_with(active_resume.uuid)

    # Happy path: 202 Accepted
    with (
        patch(
            "apps.resumes.services.resume_service.acquire_rescore_cooldown",
            return_value=True,
        ),
        patch(
            "apps.resumes.services.resume_service.publish_rescore_event",
            return_value=True,
        ) as mock_pub,
    ):
        ok = client.post(
            f"/api/v1/resumes/{active_resume.uuid}/rescore/",
            {"max_jobs": 25, "force": True},
            format="json",
        )
    assert ok.status_code == 202
    body = ok.json()
    assert body["status"] == "queued"
    assert body["resume_profile_uuid"] == str(active_resume.uuid)
    assert body["max_jobs"] == 25
    assert body["force"] is True
    mock_pub.assert_called_once()

    # IDOR check: another user gets 404
    client.force_authenticate(user=other)
    idor_resp = client.post(f"/api/v1/resumes/{active_resume.uuid}/rescore/", {})
    assert idor_resp.status_code == 404


def test_manual_import_ssrf_redirects_ipv6_and_sni():
    blocked_urls = [
        "http://127.0.0.1/admin",
        "http://localhost/health",
        "http://[::1]/secret",
        "http://[::ffff:127.0.0.1]/secret",
        "http://10.8.0.10/postgres",
        "http://169.254.169.254/computeMetadata/v1/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://192.168.1.50/internal",
        "file:///etc/passwd",
        "ftp://example.com/job.txt",
        "https://example.com:5432/job",
        "https://user:pass@example.com/job",
    ]
    for bad_url in blocked_urls:
        with pytest.raises(ManualImportValidationError):
            validate_public_http_url(bad_url)

    # IPv6 literal bracketing + str sni_hostname
    with patch(
        "apps.jobs.services.manual_import.socket.getaddrinfo",
        return_value=[
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                6,
                "",
                ("2606:2800:220:1:248:1893:25c8:1946", 443, 0, 0),
            )
        ],
    ):
        ipv6_target = validate_public_http_url("https://careers.acme.com/jobs/1")
    assert ipv6_target.pinned_url == (
        "https://[2606:2800:220:1:248:1893:25c8:1946]/jobs/1"
    )
    assert ipv6_target.host_header == "careers.acme.com"
    assert isinstance(ipv6_target.ascii_host, str)
    assert ipv6_target.ascii_host == "careers.acme.com"

    # Relative Location redirect resolves against logical_url (not pinned IP) & preserves Host/SNI
    captured_requests: list[httpx.Request] = []

    def _redirect_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/jobs/final"})
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            text="<html><body><h1>Senior Python Engineer</h1></body></html>",
        )

    with (
        patch(
            "apps.jobs.services.manual_import.socket.getaddrinfo",
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
            ],
        ),
        httpx.Client(
            transport=httpx.MockTransport(_redirect_handler), follow_redirects=False
        ) as mock_client,
    ):
        body, final_url = fetch_public_job_page(
            "https://careers.acme.com/start", client=mock_client
        )

    assert final_url == "https://careers.acme.com/jobs/final"
    assert "Senior Python Engineer" in body
    assert len(captured_requests) == 2
    assert str(captured_requests[0].url) == "https://93.184.216.34/start"
    assert str(captured_requests[1].url) == "https://93.184.216.34/jobs/final"
    assert captured_requests[1].headers["host"] == "careers.acme.com"
    assert captured_requests[1].extensions.get("sni_hostname") == "careers.acme.com"

    # Redirect pivoting to cloud metadata IP must be rejected with ManualImportValidationError
    def _ssrf_redirect_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Location": "http://169.254.169.254/computeMetadata/v1/"},
        )

    with (
        patch(
            "apps.jobs.services.manual_import.socket.getaddrinfo",
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
            ],
        ),
        httpx.Client(
            transport=httpx.MockTransport(_ssrf_redirect_handler),
            follow_redirects=False,
        ) as mock_client,
    ):
        with pytest.raises(ManualImportValidationError):
            fetch_public_job_page("https://evil.example/job", client=mock_client)


def test_manual_import_html_json_ld_extraction_and_snapshot_cap():
    bloat = "A" * (MAX_SNAPSHOT_HTML_BYTES + 20_000)
    html_doc = f"""
    <html>
      <head>
        <title>Fallback Title</title>
        <style>.hero {{ color: red; }}</style>
        <script type="application/ld+json">
          {{
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "Staff Backend Engineer",
            "hiringOrganization": {{"@type": "Organization", "name": "CloudNova"}},
            "jobLocationType": "TELECOMMUTE",
            "jobLocation": {{"@type": "Place", "address": {{"addressCountry": "Brazil"}}}},
            "datePosted": "2026-11-20T12:00:00Z",
            "description": "<p>Build distributed Python, Django, PostgreSQL, and Kafka services at scale across LATAM teams.</p>"
          }}
        </script>
        <script>alert("xss");</script>
      </head>
      <body><main>{bloat}</main></body>
    </html>
    """
    extracted = extract_job_from_html(html_doc, "https://cloudnova.example/careers/42")
    assert extracted.title == "Staff Backend Engineer"
    assert extracted.company_name == "CloudNova"
    assert extracted.location_raw == "Remote · Brazil"
    assert "PostgreSQL" in extracted.description_clean
    assert extracted.posted_at is not None
    assert "<script" not in extracted.raw_html_snapshot.lower()
    assert "<style" not in extracted.raw_html_snapshot.lower()
    assert len(extracted.raw_html_snapshot.encode("utf-8")) <= MAX_SNAPSHOT_HTML_BYTES

    with pytest.raises(ManualImportFetchError):
        extract_job_from_html(
            "<html><body><p>Sign in to view this job</p></body></html>",
            "https://linkedin.example/jobs/1",
        )

    # Hosted ATS URLs (e.g. job-boards.greenhouse.io/canonical/...) resolve company from title or path slug
    gh_html = """
    <html>
      <head>
        <meta property="og:site_name" content="Job Boards" />
        <title>Job Application for Software Developer (Backend SaaS) at Canonical</title>
      </head>
      <body>
        <main>
          <h1>Software Developer (Backend SaaS)</h1>
          <p>Build scalable Python, Django, PostgreSQL, and Ubuntu fleet services with distributed remote teams.</p>
        </main>
      </body>
    </html>
    """
    gh_extracted = extract_job_from_html(
        gh_html, "https://job-boards.greenhouse.io/canonical/jobs/4647417?gh_src=abc"
    )
    assert gh_extracted.company_name == "Canonical"

    slug_html = """
    <html>
      <head><title>Senior Backend Engineer</title></head>
      <body><main><p>Build Python, Django, Kafka, and PostgreSQL cloud services for global engineering teams.</p></main></body>
    </html>
    """
    slug_extracted = extract_job_from_html(
        slug_html, "https://jobs.lever.co/stripe-payments/12345"
    )
    assert slug_extracted.company_name == "Stripe Payments"

    # Generalized LinkedIn URL canonicalization (currentJobId -> /jobs/view/<id>/) and company extraction
    assert (
        manual_import.normalize_import_url(
            "https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4493044423&trk=abc"
        )
        == "https://www.linkedin.com/jobs/view/4493044423/"
    )
    assert (
        manual_import.normalize_import_url(
            "https://br.linkedin.com/jobs/search/?currentJobId=987654321"
        )
        == "https://www.linkedin.com/jobs/view/987654321/"
    )

    li_pt_html = """
    <html>
      <head>
        <meta property="og:site_name" content="LinkedIn" />
        <title>Acme Labs está contratando Desenvolvedor Fullstack em Brasil | LinkedIn</title>
      </head>
      <body><main><p>Desenvolvimento backend Python, Django, PostgreSQL e serviços distribuídos em nuvem.</p></main></body>
    </html>
    """
    li_pt = extract_job_from_html(
        li_pt_html,
        "https://br.linkedin.com/jobs/view/desenvolvedor-fullstack-at-acme-labs-4493044423",
    )
    assert li_pt.company_name == "Acme Labs"

    li_slug_only = extract_job_from_html(
        "<html><head><title>Software Engineer | LinkedIn</title></head>"
        "<body><main><p>Build Python, Kafka, and distributed PostgreSQL systems with global engineering teams.</p></main></body></html>",
        "https://de.linkedin.com/jobs/view/software-engineer-at-mercado-livre-123456789",
    )
    assert li_slug_only.company_name == "Mercado Livre"

    # LinkedIn authwall redirect raises ManualImportFetchError (422) instead of importing login text
    def _authwall_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/jobs/view/"):
            return httpx.Response(
                302, headers={"Location": "https://www.linkedin.com/authwall?trk=gf"}
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            text="<html><body><main>Join LinkedIn to continue viewing jobs and profiles across our network today.</main></body></html>",
        )

    with (
        patch(
            "apps.jobs.services.manual_import.socket.getaddrinfo",
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
            ],
        ),
        httpx.Client(
            transport=httpx.MockTransport(_authwall_handler), follow_redirects=False
        ) as mock_client,
    ):
        with pytest.raises(ManualImportFetchError, match="sign-in wall"):
            fetch_public_job_page(
                "https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4493044423",
                client=mock_client,
            )


@pytest.mark.django_db
def test_manual_import_endpoint_url_email_dedup_reactivate_and_guards(settings):
    settings.STREAM_EDGE_URL = "http://stream-edge:8001"
    settings.INGEST_API_KEY = "edge-ingest-secret"

    user = User.objects.create_user(username="importer", password="pw")
    client = APIClient()

    # Unauthenticated request rejected
    unauth = client.post(
        "/api/v1/jobs/import/", {"url": "https://acme.example/jobs/1"}, format="json"
    )
    assert unauth.status_code == 403

    client.force_authenticate(user=user)

    # SSRF private IP rejected with 400
    ssrf_resp = client.post(
        "/api/v1/jobs/import/",
        {"url": "http://10.8.0.10:5432/internal"},
        format="json",
    )
    assert ssrf_resp.status_code == 400

    # Blocked/unparseable external page returns 422
    with patch(
        "apps.jobs.services.manual_import.fetch_public_job_page",
        side_effect=ManualImportFetchError("HTTP 999 blocked"),
    ):
        blocked_resp = client.post(
            "/api/v1/jobs/import/",
            {"url": "https://linkedin.example/jobs/view/123"},
            format="json",
        )
    assert blocked_resp.status_code == 422

    # Rate limit returns 429 + Retry-After
    with patch(
        "apps.jobs.services.manual_import.enforce_import_rate_limit",
        side_effect=ManualImportRateLimitError(retry_after=120),
    ):
        rl_resp = client.post(
            "/api/v1/jobs/import/",
            {"url": "https://acme.example/jobs/1"},
            format="json",
        )
    assert rl_resp.status_code == 429
    assert rl_resp["Retry-After"] == "120"

    # Manual Entry with plain email normalizes to mailto:, synthesizes HTML, forwards with API key
    forwarded_calls: list[dict] = []

    def _fake_forward(self, **kwargs):
        forwarded_calls.append(kwargs)
        return {"event_id": str(uuid4()), "content_hash": "a" * 64}

    description_text = (
        "Seeking a Senior Python & Django backend engineer to design event-driven "
        "Kafka pipelines, pgvector semantic search, and Cloud Run services."
    )
    with patch.object(
        manual_import.ManualJobImportService,
        "_forward_to_stream_edge",
        autospec=True,
        side_effect=_fake_forward,
    ):
        email_resp = client.post(
            "/api/v1/jobs/import/",
            {
                "title": "Senior Python Engineer",
                "company_name": "ReferralCorp",
                "apply_url": "Hiring@ReferralCorp.COM",
                "location_raw": "Remote - Brazil",
                "description": description_text,
            },
            format="json",
        )

    assert email_resp.status_code == 202
    email_body = email_resp.json()
    assert email_body["status"] == "queued"
    assert email_body["ats_source"] == "manual"
    assert email_body["apply_url"] == "mailto:Hiring@referralcorp.com"
    assert email_body["external_id"].startswith("manual-")
    assert len(forwarded_calls) == 1
    assert forwarded_calls[0]["apply_url"] == "mailto:Hiring@referralcorp.com"
    assert "<article" in forwarded_calls[0]["raw_html"]

    # Persist the manual mailto job and verify serializers, external_id filters, dedup, and reactivation
    manual_job = JobPosting.objects.create(
        ats_source=ATSSource.MANUAL,
        external_id=email_body["external_id"],
        content_hash=manual_import.compute_job_content_hash(
            ATSSource.MANUAL,
            "Senior Python Engineer",
            "ReferralCorp",
            description_text,
        ),
        title="Senior Python Engineer",
        company_name="ReferralCorp",
        apply_url="mailto:Hiring@referralcorp.com",
        raw_html_gcs_uri="gs://vektryn-snapshots/raw_html/manual/test.html",
        location_raw="Remote - Brazil",
        description_clean=description_text,
    )
    resume = ResumeProfile.objects.create(
        user=user,
        label="Backend",
        raw_text="Python Django Kafka",
        content_hash="9" * 64,
        embedding=[0.01] * EMBEDDING_DIMENSIONS,
    )
    MatchScore.objects.create(
        job_posting=manual_job,
        resume_profile=resume,
        cosine_similarity=0.88,
        fit_score=90,
        resume_content_hash=resume.content_hash,
    )
    lead = create_lead(user=user, validated_data={"job_posting": manual_job})
    assert (
        ApplicationLeadSerializer(lead).data["apply_url"]
        == "mailto:Hiring@referralcorp.com"
    )

    # O(1) external_id filters on /api/v1/jobs/ and /api/v1/matches/
    jobs_lookup = client.get(
        f"/api/v1/jobs/?ats_source=manual&external_id={manual_job.external_id}"
    )
    assert jobs_lookup.status_code == 200
    assert jobs_lookup.json()["count"] == 1
    assert (
        jobs_lookup.json()["results"][0]["apply_url"]
        == "mailto:Hiring@referralcorp.com"
    )

    matches_lookup = client.get(
        f"/api/v1/matches/?external_id={manual_job.external_id}"
    )
    assert matches_lookup.status_code == 200
    assert matches_lookup.json()["count"] == 1
    assert (
        matches_lookup.json()["results"][0]["job_posting"]["apply_url"]
        == "mailto:Hiring@referralcorp.com"
    )

    # Re-importing identical active manual job returns 200 already_exists without forwarding
    dup_resp = client.post(
        "/api/v1/jobs/import/",
        {
            "title": "Senior Python Engineer",
            "company_name": "ReferralCorp",
            "apply_url": "mailto:Hiring@referralcorp.com",
            "description": description_text,
        },
        format="json",
    )
    assert dup_resp.status_code == 200
    assert dup_resp.json()["status"] == "already_exists"
    assert dup_resp.json()["job_posting_uuid"] == str(manual_job.uuid)

    # Soft-deleting + closing the job and re-importing reactivates directly via all_objects
    manual_job.is_active = False
    manual_job.is_deleted = True
    manual_job.save(update_fields=["is_active", "is_deleted"])

    with patch(
        "apps.jobs.services.manual_import.publish_rescore_event", return_value=True
    ):
        reactivate_resp = client.post(
            "/api/v1/jobs/import/",
            {
                "title": "Senior Python Engineer",
                "company_name": "ReferralCorp",
                "apply_url": "Hiring@ReferralCorp.COM",
                "description": description_text,
            },
            format="json",
        )
    assert reactivate_resp.status_code == 200
    assert reactivate_resp.json()["status"] == "reactivated"
    manual_job.refresh_from_db()
    assert manual_job.is_active is True
    assert manual_job.is_deleted is False
    assert manual_job.closed_at is None


@pytest.mark.django_db
def test_matches_ordering_puts_null_fit_scores_and_null_posted_at_last():
    user = User.objects.create_user(username="radar-order-user", password="pw")
    resume = ResumeProfile.objects.create(
        user=user,
        label="Backend",
        raw_text="Python Django PostgreSQL",
        content_hash=uuid4().hex,
        extracted_skills=["python", "django"],
    )
    now = datetime.now(UTC)

    def _make_job(ext_id: str, posted_at: datetime | None) -> JobPosting:
        return JobPosting.objects.create(
            ats_source=ATSSource.GREENHOUSE.value,
            external_id=ext_id,
            title=f"Role {ext_id}",
            company_name="Acme",
            apply_url=f"https://acme.example/jobs/{ext_id}",
            description_clean="Python backend role",
            content_hash=uuid4().hex,
            posted_at=posted_at,
            is_active=True,
        )

    job_unscored_high_vec = _make_job("unscored-hi", now - timedelta(days=1))
    job_scored_mid = _make_job("scored-mid", now - timedelta(days=5))
    job_scored_top = _make_job("scored-top", None)
    job_unscored_low_vec = _make_job("unscored-lo", now)

    m_unscored_hi = MatchScore.objects.create(
        job_posting=job_unscored_high_vec,
        resume_profile=resume,
        cosine_similarity=0.95,
        fit_score=None,
    )
    m_scored_mid = MatchScore.objects.create(
        job_posting=job_scored_mid,
        resume_profile=resume,
        cosine_similarity=0.72,
        fit_score=78,
    )
    m_scored_top = MatchScore.objects.create(
        job_posting=job_scored_top,
        resume_profile=resume,
        cosine_similarity=0.81,
        fit_score=91,
    )
    m_unscored_lo = MatchScore.objects.create(
        job_posting=job_unscored_low_vec,
        resume_profile=resume,
        cosine_similarity=0.65,
        fit_score=None,
    )

    # Space out created_at deterministically to verify -created_at ordering
    for offset, match_obj in enumerate(
        [m_unscored_hi, m_scored_mid, m_scored_top, m_unscored_lo]
    ):
        MatchScore.objects.filter(pk=match_obj.pk).update(
            created_at=now + timedelta(seconds=offset * 10)
        )

    client = APIClient()
    client.force_authenticate(user=user)
    matches_url = "/api/v1/matches/"

    # Default ordering: AI-scored DESC first, then unscored ordered by cosine_similarity DESC
    default_resp = client.get(matches_url)
    assert default_resp.status_code == 200
    assert [
        r["job_posting"]["external_id"] for r in default_resp.json()["results"]
    ] == [
        "scored-top",
        "scored-mid",
        "unscored-hi",
        "unscored-lo",
    ]

    # Posted Date ordering: newest posted_at first, NULL posted_at strictly last
    posted_resp = client.get(
        f"{matches_url}?ordering=-job_posting__posted_at,-created_at"
    )
    assert posted_resp.status_code == 200
    assert [r["job_posting"]["external_id"] for r in posted_resp.json()["results"]] == [
        "unscored-lo",
        "unscored-hi",
        "scored-mid",
        "scored-top",
    ]

    # Newest Added ordering: most recently created match first
    newest_resp = client.get(f"{matches_url}?ordering=-created_at")
    assert newest_resp.status_code == 200
    assert [r["job_posting"]["external_id"] for r in newest_resp.json()["results"]] == [
        "unscored-lo",
        "scored-top",
        "scored-mid",
        "unscored-hi",
    ]

    # Vector Similarity ordering: highest cosine_similarity first
    vector_resp = client.get(
        f"{matches_url}?ordering=-cosine_similarity,-fit_score,-created_at"
    )
    assert vector_resp.status_code == 200
    assert [r["job_posting"]["external_id"] for r in vector_resp.json()["results"]] == [
        "unscored-hi",
        "scored-top",
        "scored-mid",
        "unscored-lo",
    ]


def _unit_vec(
    axis: int, weight: float = 1.0, secondary: tuple[int, float] | None = None
) -> list[float]:
    vec = [0.0] * EMBEDDING_DIMENSIONS
    vec[axis] = weight
    if secondary is not None:
        vec[secondary[0]] = secondary[1]
    return vec


@pytest.mark.django_db
def test_jobposting_search_vector_trigger_and_negation_exclusion():
    user = User.objects.create_user(username="fts-trigger-user", password="pw")
    orm_job = JobPosting.objects.create(
        ats_source=ATSSource.GREENHOUSE.value,
        external_id="fts-orm-1",
        title="Senior Python Backend Engineer",
        company_name="Vektryn Labs",
        apply_url="https://vektryn.example/jobs/1",
        description_clean="Build distributed systems with DRF, KRaft, pgvector, and PJ contract.",
        tech_stack=["python", "drf", "kraft", "pgvector"],
        is_active=True,
        content_hash=uuid4().hex,
    )
    orm_job.refresh_from_db()
    assert orm_job.search_vector is not None

    # Simulate stream-edge matcher-worker raw psycopg INSERT bypassing Django ORM
    now = datetime.now(UTC)
    raw_uuid = uuid4()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO jobs_jobposting (
                uuid, created_at, modified_at, is_deleted,
                ats_source, external_id, content_hash,
                title, company_name, apply_url, raw_html_gcs_uri,
                location_raw, description_clean,
                seniority, contract_type, region_eligibility,
                salary_currency, tech_stack, is_active
            ) VALUES (
                %s, %s, %s, FALSE,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s::jsonb, TRUE
            )
            """,
            [
                raw_uuid,
                now,
                now,
                ATSSource.GREENHOUSE.value,
                "fts-raw-intern",
                uuid4().hex,
                "Python Backend Intern",
                "StartupCo",
                "https://startup.example/jobs/intern",
                "",
                "Remote",
                "Entry-level Python and DRF internship role.",
                SeniorityLevel.INTERN.value,
                ContractType.CLT.value,
                [RegionEligibility.BRAZIL.value],
                "",
                json.dumps(["python", "drf"]),
            ],
        )

    raw_job = JobPosting.objects.get(uuid=raw_uuid)
    assert raw_job.search_vector is not None

    client = APIClient()
    client.force_authenticate(user=user)
    jobs_url = "/api/v1/jobs/"

    with patch(
        "apps.jobs.services.hybrid_search.embed_search_query", return_value=None
    ):
        resp_tokens = client.get(f"{jobs_url}?search=KRaft pgvector")
        assert resp_tokens.status_code == 200
        assert resp_tokens.json()["search_mode"] == "keyword"
        assert [r["external_id"] for r in resp_tokens.json()["results"]] == [
            "fts-orm-1"
        ]

        # Single english config prevents negation bypass (-interns excludes singular "intern")
        resp_excl = client.get(f"{jobs_url}?search=python -interns")
        assert resp_excl.status_code == 200
        assert [r["external_id"] for r in resp_excl.json()["results"]] == ["fts-orm-1"]


@pytest.mark.django_db
def test_hybrid_search_rrf_on_jobs_and_matches_with_filters_and_ordering(settings):
    settings.HYBRID_SEARCH_MIN_SIMILARITY = 0.60
    user = User.objects.create_user(username="rrf-user", password="pw")
    resume = ResumeProfile.objects.create(
        user=user,
        label="Backend",
        raw_text="Python Django DRF Kafka",
        content_hash=uuid4().hex,
        extracted_skills=["python", "django", "drf"],
    )

    query_vec = _unit_vec(0, 1.0)
    both_vec = _unit_vec(0, 1.0)  # cosine = 1.0
    semantic_only_vec = _unit_vec(0, 0.95, (1, 0.31225))  # cosine ~= 0.95
    orthogonal_vec = _unit_vec(2, 1.0)  # cosine = 0.0

    job_both = JobPosting.objects.create(
        ats_source=ATSSource.GREENHOUSE.value,
        external_id="rrf-both",
        title="Senior DRF Backend Engineer",
        company_name="AlphaCorp",
        apply_url="https://alpha.example/jobs/both",
        description_clean="Build DRF APIs and PostgreSQL services.",
        seniority=SeniorityLevel.SENIOR.value,
        contract_type=ContractType.PJ.value,
        region_eligibility=[RegionEligibility.BRAZIL.value],
        tech_stack=["python", "drf"],
        embedding=both_vec,
        is_active=True,
        content_hash=uuid4().hex,
    )
    job_kw = JobPosting.objects.create(
        ats_source=ATSSource.LEVER.value,
        external_id="rrf-keyword",
        title="DRF API Maintainer",
        company_name="BetaCorp",
        apply_url="https://beta.example/jobs/kw",
        description_clean="Maintain legacy DRF endpoints.",
        seniority=SeniorityLevel.MID.value,
        contract_type=ContractType.CLT.value,
        region_eligibility=[RegionEligibility.LATAM.value],
        tech_stack=["python", "drf"],
        embedding=orthogonal_vec,
        is_active=True,
        content_hash=uuid4().hex,
    )
    job_sem = JobPosting.objects.create(
        ats_source=ATSSource.GREENHOUSE.value,
        external_id="rrf-semantic",
        title="Distributed Platform Architect",
        company_name="GammaCorp",
        apply_url="https://gamma.example/jobs/sem",
        description_clean="Design scalable REST microservices in Python.",
        seniority=SeniorityLevel.SENIOR.value,
        contract_type=ContractType.PJ.value,
        region_eligibility=[RegionEligibility.BRAZIL.value],
        tech_stack=["python", "kafka"],
        embedding=semantic_only_vec,
        is_active=True,
        content_hash=uuid4().hex,
    )
    job_unrelated = JobPosting.objects.create(
        ats_source=ATSSource.GREENHOUSE.value,
        external_id="rrf-unrelated",
        title="iOS Swift Designer",
        company_name="DeltaCorp",
        apply_url="https://delta.example/jobs/ios",
        description_clean="Craft mobile SwiftUI interfaces.",
        seniority=SeniorityLevel.SENIOR.value,
        contract_type=ContractType.PJ.value,
        region_eligibility=[RegionEligibility.BRAZIL.value],
        tech_stack=["swift"],
        embedding=orthogonal_vec,
        is_active=True,
        content_hash=uuid4().hex,
    )

    now = datetime.now(UTC)
    m_both = MatchScore.objects.create(
        job_posting=job_both,
        resume_profile=resume,
        cosine_similarity=0.82,
        fit_score=75,
    )
    m_kw = MatchScore.objects.create(
        job_posting=job_kw,
        resume_profile=resume,
        cosine_similarity=0.70,
        fit_score=92,
    )
    m_sem = MatchScore.objects.create(
        job_posting=job_sem,
        resume_profile=resume,
        cosine_similarity=0.88,
        fit_score=85,
    )
    m_unrelated = MatchScore.objects.create(
        job_posting=job_unrelated,
        resume_profile=resume,
        cosine_similarity=0.40,
        fit_score=30,
    )
    for idx, match_obj in enumerate([m_both, m_kw, m_sem, m_unrelated]):
        MatchScore.objects.filter(pk=match_obj.pk).update(
            created_at=now + timedelta(seconds=idx * 10)
        )

    client = APIClient()
    client.force_authenticate(user=user)
    jobs_url = "/api/v1/jobs/"
    matches_url = "/api/v1/matches/"

    with patch(
        "apps.jobs.services.hybrid_search.embed_search_query", return_value=query_vec
    ):
        # /api/v1/jobs/: RRF boosts job matching BOTH keyword and semantic to #1; excludes unrelated
        jobs_resp = client.get(f"{jobs_url}?search=DRF")
        assert jobs_resp.status_code == 200
        jobs_data = jobs_resp.json()
        assert jobs_data["search_mode"] == "hybrid"
        job_ids = [r["external_id"] for r in jobs_data["results"]]
        assert job_ids[0] == "rrf-both"
        assert set(job_ids) == {"rrf-both", "rrf-keyword", "rrf-semantic"}

        # Composed structured filters on /api/v1/jobs/
        filtered_jobs_resp = client.get(
            f"{jobs_url}?search=DRF&seniority=senior&contract_type=pj&region=brazil&tech=python"
        )
        assert filtered_jobs_resp.status_code == 200
        assert [r["external_id"] for r in filtered_jobs_resp.json()["results"]] == [
            "rrf-both",
            "rrf-semantic",
        ]

        # /api/v1/matches/: default search orders by -rrf_score (rrf-both beats higher fit_score rrf-keyword)
        matches_resp = client.get(f"{matches_url}?search=DRF")
        assert matches_resp.status_code == 200
        matches_data = matches_resp.json()
        assert matches_data["search_mode"] == "hybrid"
        match_ids = [r["job_posting"]["external_id"] for r in matches_data["results"]]
        assert match_ids[0] == "rrf-both"
        assert set(match_ids) == {"rrf-both", "rrf-keyword", "rrf-semantic"}
        assert matches_data["summary"] == {
            "ai_scored_count": 3,
            "strong_fit_count": 2,
            "alert_threshold_count": 3,
        }

        # Explicit ?ordering=-created_at overrides RRF order while keeping hybrid filter
        ordered_resp = client.get(f"{matches_url}?search=DRF&ordering=-created_at")
        assert ordered_resp.status_code == 200
        assert [
            r["job_posting"]["external_id"] for r in ordered_resp.json()["results"]
        ] == ["rrf-semantic", "rrf-keyword", "rrf-both"]

        # Structured filters + min_fit_score compose cleanly on /api/v1/matches/
        scoped_resp = client.get(
            f"{matches_url}?search=DRF&seniority=senior&min_fit_score=80&ats_source=greenhouse"
        )
        assert scoped_resp.status_code == 200
        assert [
            r["job_posting"]["external_id"] for r in scoped_resp.json()["results"]
        ] == ["rrf-semantic"]

    # Gibberish query with orthogonal vector returns 0 results
    with patch(
        "apps.jobs.services.hybrid_search.embed_search_query",
        return_value=_unit_vec(5, 1.0),
    ):
        gibberish_resp = client.get(f"{matches_url}?search=zzzznonexistenttoken")
        assert gibberish_resp.status_code == 200
        assert gibberish_resp.json()["count"] == 0
        assert gibberish_resp.json()["results"] == []


@pytest.mark.django_db
def test_hybrid_search_embedding_cache_short_query_and_fallback(settings):
    fernet_key = Fernet.generate_key().decode("utf-8")
    settings.BYOK_ENCRYPTION_KEY = fernet_key
    settings.REDIS_URL = ""
    user = User.objects.create_user(username="hybrid_byok", password="pw")
    profile = get_or_create_user_profile(user)
    profile.gemini_api_key_encrypted = encrypt_api_key(
        "AQ.Ab8RN6-ValidHybridTestKey12345678", fernet_key
    )
    profile.gemini_api_key_last4 = "5678"
    profile.save(update_fields=["gemini_api_key_encrypted", "gemini_api_key_last4"])

    # Single-character query skips Gemini completely
    with patch("apps.base.services.byok.genai.Client") as mock_client_cls:
        assert hybrid_search.embed_search_query("a", user=user) is None
        mock_client_cls.assert_not_called()

    # Redis cache stores per-user embedding with 5-minute (300s) TTL and avoids repeat Gemini calls
    fake_store: dict[str, str] = {}
    fake_redis = MagicMock()
    fake_redis.get.side_effect = lambda key: fake_store.get(key)

    def _fake_set(key: str, val: str, ex: int | None = None) -> None:
        assert ex == hybrid_search.EMBEDDING_CACHE_TTL_SECONDS
        assert key.startswith(f"vektryn:search_embed:v2:{user.pk}:")
        fake_store[key] = val

    fake_redis.set.side_effect = _fake_set

    expected_vec = _unit_vec(3, 1.0)
    mock_embed_obj = MagicMock()
    mock_embed_obj.values = expected_vec
    mock_embed_res = MagicMock()
    mock_embed_res.embeddings = [mock_embed_obj]
    mock_client = MagicMock()
    mock_client.models.embed_content.return_value = mock_embed_res

    with (
        patch(
            "apps.jobs.services.hybrid_search._get_redis_client",
            return_value=fake_redis,
        ),
        patch("apps.base.services.byok.genai.Client", return_value=mock_client),
    ):
        first = hybrid_search.embed_search_query("Distributed   Python", user=user)
        second = hybrid_search.embed_search_query("distributed python", user=user)

    assert first == expected_vec
    assert second == expected_vec
    assert mock_client.models.embed_content.call_count == 1

    # Upstream Gemini error degrades cleanly to None (keyword fallback) without raising
    mock_client.models.embed_content.side_effect = RuntimeError("timeout")
    with (
        patch("apps.jobs.services.hybrid_search._get_redis_client", return_value=None),
        patch("apps.base.services.byok.genai.Client", return_value=mock_client),
    ):
        assert hybrid_search.embed_search_query("kafka streams", user=user) is None


@pytest.mark.django_db
def test_system_status_telemetry_multi_resume_backlog_and_dlq_offset_invalid(settings):
    settings.KAFKA_BOOTSTRAP_SERVERS = "kafka:9092"
    user = User.objects.create_user(username="obs-user", password="pw", is_staff=False)
    staff_user = User.objects.create_user(
        username="obs-staff", password="pw", is_staff=True
    )

    client = APIClient()
    client.force_authenticate(user=user)
    me_non_staff = client.get("/api/v1/auth/me/")
    assert me_non_staff.status_code == 200
    assert me_non_staff.json()["is_staff"] is False

    client.force_authenticate(user=staff_user)
    me_staff = client.get("/api/v1/auth/me/")
    assert me_staff.status_code == 200
    assert me_staff.json()["is_staff"] is True

    # Two active embedded resumes for staff_user to test distinct Exists() counting
    vec = _unit_vec(0, 1.0)
    r1 = ResumeProfile.objects.create(
        user=staff_user,
        label="Backend 1",
        raw_text="Python Django",
        content_hash=uuid4().hex,
        embedding=vec,
        is_active=True,
    )
    r2 = ResumeProfile.objects.create(
        user=staff_user,
        label="Backend 2",
        raw_text="Python Kafka",
        content_hash=uuid4().hex,
        embedding=vec,
        is_active=True,
    )

    now = datetime.now(UTC)
    j_scored = JobPosting.objects.create(
        ats_source=ATSSource.GREENHOUSE.value,
        external_id="obs-scored",
        title="Senior Python",
        company_name="Acme",
        apply_url="https://acme.example/1",
        description_clean="Python backend",
        embedding=vec,
        is_active=True,
        content_hash=uuid4().hex,
    )
    j_old_unmatched = JobPosting.objects.create(
        ats_source=ATSSource.LEVER.value,
        external_id="obs-old-unmatched",
        title="Older Role",
        company_name="Beta",
        apply_url="https://beta.example/2",
        description_clean="Older job outside 2h lag window",
        embedding=vec,
        is_active=True,
        content_hash=uuid4().hex,
    )
    JobPosting.objects.filter(pk=j_old_unmatched.pk).update(
        created_at=now - timedelta(hours=6)
    )

    # Both resumes score the SAME job -> distinct ai_scored_count must be 1 (never 2 > active_count)
    MatchScore.objects.create(
        job_posting=j_scored,
        resume_profile=r1,
        cosine_similarity=0.85,
        fit_score=88,
    )
    MatchScore.objects.create(
        job_posting=j_scored,
        resume_profile=r2,
        cosine_similarity=0.83,
        fit_score=84,
    )

    older_ts = now - timedelta(hours=5)
    latest_ts = now - timedelta(minutes=10)
    CollectorRunLog.objects.create(
        source=ATSSource.GREENHOUSE.value,
        fetched_count=50,
        ingested_count=10,
        deduped_count=40,
        error_count=1,
        duration_ms=2000,
        ran_at=older_ts,
    )
    CollectorRunLog.objects.create(
        source=ATSSource.GREENHOUSE.value,
        fetched_count=40,
        ingested_count=8,
        deduped_count=32,
        error_count=0,
        duration_ms=1500,
        ran_at=latest_ts,
    )
    CollectorRunLog.objects.create(
        source=ATSSource.REMOTIVE.value,
        fetched_count=20,
        ingested_count=4,
        deduped_count=16,
        error_count=0,
        duration_ms=900,
        ran_at=latest_ts,
    )
    StackTrendDaily.objects.create(
        bucket_date=now.date(),
        tag="python",
        mention_count=12,
        unique_companies_count=10,
    )

    # Case 1: Kafka offsets_for_times returns -1 (OFFSET_INVALID) -> 0 recent failures, healthy overall
    fake_topic = MagicMock(error=None, partitions={0: MagicMock()})
    fake_meta = MagicMock(topics={"jobs.dlq": fake_topic})
    fake_consumer = MagicMock()
    fake_consumer.list_topics.return_value = fake_meta
    fake_consumer.get_watermark_offsets.return_value = (0, 5)
    fake_consumer.offsets_for_times.return_value = [MagicMock(offset=-1)]

    status_url = "/api/v1/system/status/"
    with (
        patch.object(system_status, "_get_redis_client", return_value=None),
        patch.object(collector_trigger, "_get_redis_client", return_value=None),
        patch.object(system_status, "Consumer", return_value=fake_consumer),
    ):
        resp = client.get(status_url)

    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_status"] == "healthy"
    assert body["dlq"] == {"status": "healthy", "recent_24h_count": 0, "total_count": 5}
    fake_consumer.close.assert_called_once()
    assert body["latest_run_totals"] == {
        "fetched_count": 60,
        "ingested_count": 12,
        "deduped_count": 48,
        "error_count": 0,
        "duration_ms": 1500,
    }
    assert len(body["sources"]) == 2
    assert body["jobs"]["active_count"] == 2
    assert body["jobs"]["ai_scored_count"] == 1
    assert body["jobs"]["unscored_active_count"] == 1
    assert body["jobs"]["pending_match_count"] == 1
    assert body["jobs"]["recent_unmatched_count"] == 0
    assert body["rollup"]["latest_bucket_date"] == now.date().isoformat()
    assert body["collect_trigger"]["can_trigger"] is True

    # Case 2: Zero active resumes for regular user -> pending_match_count == 0
    # and recent DLQ messages (offset=3, high=5 -> 2 recent) flips status to degraded
    fake_consumer.close.reset_mock()
    fake_consumer.offsets_for_times.return_value = [MagicMock(offset=3)]
    client.force_authenticate(user=user)
    with (
        patch.object(system_status, "_get_redis_client", return_value=None),
        patch.object(collector_trigger, "_get_redis_client", return_value=None),
        patch.object(system_status, "Consumer", return_value=fake_consumer),
    ):
        degraded_resp = client.get(status_url)

    assert degraded_resp.status_code == 200
    degraded = degraded_resp.json()
    assert degraded["overall_status"] == "degraded"
    assert degraded["dlq"] == {
        "status": "warning",
        "recent_24h_count": 2,
        "total_count": 5,
    }
    assert degraded["jobs"]["pending_match_count"] == 0
    assert degraded["collect_trigger"]["can_trigger"] is False
    fake_consumer.close.assert_called_once()


@pytest.mark.django_db
def test_system_collect_trigger_staff_gate_atomic_cooldown_and_rollback(settings):
    settings.GCP_PROJECT_ID = "vektryn-prod"
    settings.GCP_REGION = "us-central1"
    settings.COLLECTOR_JOB_NAME = "vektryn-collect"

    regular_user = User.objects.create_user(
        username="non-staff-collect", password="pw", is_staff=False
    )
    staff_user = User.objects.create_user(
        username="staff-collect", password="pw", is_staff=True
    )
    collect_url = "/api/v1/system/collect/"

    client = APIClient()
    client.force_authenticate(user=regular_user)
    forbidden = client.post(collect_url)
    assert forbidden.status_code == 403

    client.force_authenticate(user=staff_user)
    lock_state: dict[str, str] = {}
    fake_redis = MagicMock()

    def _fake_set(key: str, val: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in lock_state:
            return False
        lock_state[key] = val
        return True

    fake_redis.set.side_effect = _fake_set
    fake_redis.ttl.return_value = 240
    fake_redis.delete.side_effect = lambda key: lock_state.pop(key, None)

    mock_token_resp = MagicMock()
    mock_token_resp.json.return_value = {"access_token": "gcp-oauth-token"}
    mock_token_resp.raise_for_status.return_value = None

    mock_run_resp = MagicMock()
    mock_run_resp.content = b'{"name": "exec-123"}'
    mock_run_resp.json.return_value = {"name": "exec-123"}
    mock_run_resp.raise_for_status.return_value = None

    with (
        patch.object(collector_trigger, "_get_redis_client", return_value=fake_redis),
        patch.object(collector_trigger.httpx, "get", return_value=mock_token_resp),
        patch.object(collector_trigger.httpx, "post", return_value=mock_run_resp),
    ):
        ok_resp = client.post(collect_url)
        assert ok_resp.status_code == 202
        assert ok_resp.json()["execution_id"] == "exec-123"
        assert ok_resp.json()["mode"] == "cloud_run_job"
        assert collector_trigger.COLLECT_RUNNING_KEY in lock_state

        fake_redis.get.side_effect = lambda key: lock_state.get(key)
        is_running, started_at = collector_trigger.get_collect_running_state()
        assert is_running is True
        assert started_at is not None

        # Once a CollectorRunLog lands after started_at, running marker auto-clears
        is_running_after, _ = collector_trigger.get_collect_running_state(
            datetime.now(UTC) + timedelta(seconds=5)
        )
        assert is_running_after is False

        # Second immediate click hits atomic SET NX EX cooldown -> 429 + Retry-After
        cooldown_resp = client.post(collect_url)
        assert cooldown_resp.status_code == 429
        assert cooldown_resp["Retry-After"] == "240"

    # Reset lock and simulate upstream Cloud Run failure -> 503 AND lock released
    lock_state.clear()
    with (
        patch.object(collector_trigger, "_get_redis_client", return_value=fake_redis),
        patch.object(collector_trigger.httpx, "get", return_value=mock_token_resp),
        patch.object(
            collector_trigger.httpx,
            "post",
            side_effect=httpx.ConnectError("run API down"),
        ),
    ):
        err_resp = client.post(collect_url)
    assert err_resp.status_code == 503
    assert collector_trigger.COLLECT_COOLDOWN_KEY not in lock_state


@pytest.mark.django_db
def test_health_endpoints_ok_and_prometheus_metrics_removed():
    client = APIClient()
    health_root = client.get("/health/")
    health_api = client.get("/api/v1/health/")
    assert health_root.status_code == 200
    assert health_root.json() == {"status": "ok", "service": "control-plane"}
    assert health_api.status_code == 200
    assert health_api.json() == {"status": "ok", "service": "control-plane"}

    assert client.get("/metrics").status_code == 404
    assert client.get("/metrics/").status_code == 404


@pytest.mark.django_db
def test_stack_trends_series_returns_complete_multiday_top_tags_beyond_page_size():
    user = User.objects.create_user(username="trends-user", password="secret")
    client = APIClient()
    client.force_authenticate(user=user)

    today = datetime.now(UTC).date()
    days = [today - timedelta(days=2), today - timedelta(days=1), today]

    # Create 30 tags on the latest day (> PAGE_SIZE=25) plus multi-day rows for top tags.
    for idx in range(30):
        tag_name = f"tag-{idx:02d}"
        StackTrendDaily.objects.create(
            bucket_date=days[2],
            tag=tag_name,
            category=(
                TechCategory.LANGUAGE.value if idx < 10 else TechCategory.CLOUD.value
            ),
            mention_count=1 + (idx % 3),
            unique_companies_count=1,
        )

    for rank, (tag_name, counts) in enumerate(
        [
            ("python", [12, 15, 18]),
            ("typescript", [10, 10, 11]),
            ("go", [8, 9, 7]),
            ("rust", [6, 5, 6]),
            ("java", [5, 5, 5]),
        ]
    ):
        for day, count in zip(days, counts, strict=True):
            StackTrendDaily.objects.create(
                bucket_date=day,
                tag=tag_name,
                category=TechCategory.LANGUAGE.value,
                mention_count=count,
                unique_companies_count=max(1, count - 1),
                median_annual_usd=Decimal("150000.00") if rank == 0 else None,
            )

    # Paginated table page 1 only sees 25 rows from the newest day, while /series/ returns all 3 days.
    page_resp = client.get("/api/v1/analytics/trends/")
    assert page_resp.status_code == 200
    page_dates = {row["bucket_date"] for row in page_resp.json()["results"]}
    assert page_dates == {days[2].isoformat()}

    series_resp = client.get("/api/v1/analytics/trends/series/")
    assert series_resp.status_code == 200
    payload = series_resp.json()
    assert payload["dates"] == [d.isoformat() for d in days]
    assert payload["tags"] == ["python", "typescript", "go", "rust", "java"]
    assert len(payload["results"]) == 15

    # Category filter applies identically to /series/
    cloud_resp = client.get("/api/v1/analytics/trends/series/?category=cloud&limit=3")
    assert cloud_resp.status_code == 200
    cloud_payload = cloud_resp.json()
    assert len(cloud_payload["tags"]) == 3
    assert all(
        row["category"] == TechCategory.CLOUD.value for row in cloud_payload["results"]
    )

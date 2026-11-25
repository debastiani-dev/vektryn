from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
import pytest
from rest_framework.test import APIClient, APIRequestFactory

from apps.jobs.models.jobs import JobPosting
from apps.matching.models.matching import MatchScore
from apps.matching.serializers.matching import MatchScoreSerializer
from apps.resumes.models.resumes import ResumeProfile
from apps.resumes.serializers.resumes import ResumeProfileSerializer
from apps.resumes.services import rescore_publisher
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
)

User = get_user_model()


def test_settings_supports_secret_key_and_database_url(monkeypatch):
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    monkeypatch.setenv("SECRET_KEY", "alias-secret-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://clouduser:cloudpass@10.0.0.5:5433/vektryn_prod",
    )

    cfg = ControlPlaneSettings(_env_file=None)
    assert cfg.django_secret_key == "alias-secret-key"

    db_cfg = _build_database_config(cfg)
    assert db_cfg["NAME"] == "vektryn_prod"
    assert db_cfg["USER"] == "clouduser"
    assert db_cfg["PASSWORD"] == "cloudpass"
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
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://neonuser:neonpass@ep-demo.neon.tech:5432/vektryn?sslmode=require",
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
            assert cp_telemetry.configure_sentry("vektryn-control-plane") is True
            mock_init.assert_called_once()
            mock_tag.assert_called_once_with("service", "vektryn-control-plane")


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

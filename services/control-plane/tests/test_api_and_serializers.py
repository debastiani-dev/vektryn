from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
import pytest
from rest_framework.test import APIClient, APIRequestFactory

from apps.jobs.models.jobs import JobPosting
from apps.matching.models.matching import MatchScore
from apps.matching.serializers.matching import MatchScoreSerializer
from apps.resumes.models.resumes import ResumeProfile
from apps.resumes.serializers.resumes import ResumeProfileSerializer
from apps.resumes.services.resume_service import ResumeService
from apps.tracker.serializers.leads import ApplicationLeadSerializer
from apps.tracker.services.leads import create_lead, update_lead
from config.settings import ControlPlaneSettings, _build_database_config
from vektryn_contracts import verify_stream_token
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

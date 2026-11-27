"""Tests for Spec #20 Work Mode classification, API filters, SavedFilter, and ResumeProfile targeting."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
import pytest
from rest_framework.test import APIClient

from apps.jobs.models.jobs import JobPosting
from apps.jobs.models.triage import DismissedJob
from apps.matching.models.matching import MatchScore
from apps.resumes.models.resumes import ResumeProfile
from apps.resumes.services.resume_service import ResumeService
from apps.tracker.models import ApplicationLead
from vektryn_contracts.enums import (
    ATSSource,
    ContractType,
    RegionEligibility,
    SeniorityLevel,
    WorkMode,
)

User = get_user_model()


def _create_job(
    *,
    external_id: str,
    title: str,
    work_mode: WorkMode,
    company_name: str = "Acme Cloud",
    description_clean: str = "Build distributed Python Django backend services.",
) -> JobPosting:
    return JobPosting.objects.create(
        ats_source=ATSSource.GREENHOUSE,
        external_id=external_id,
        content_hash=f"{external_id:0<64}"[:64],
        title=title,
        company_name=company_name,
        apply_url=f"https://example.com/jobs/{external_id}",
        raw_html_gcs_uri=f"gs://bucket/{external_id}.html",
        location_raw="Remote" if work_mode == WorkMode.REMOTE else "Sao Paulo, SP",
        description_clean=description_clean,
        seniority=SeniorityLevel.SENIOR,
        contract_type=ContractType.PJ,
        work_mode=work_mode,
        region_eligibility=[RegionEligibility.BRAZIL],
        tech_stack=["python", "django"],
        is_active=True,
    )


@pytest.mark.django_db
def test_jobs_and_matches_work_mode_filtering_composable_with_search_and_triage():
    user = User.objects.create_user(username="wm_filter_user", password="pw")
    resume = ResumeProfile.objects.create(
        user=user,
        label="Backend",
        raw_text="Senior Python engineer",
        content_hash="a" * 64,
        embedding=[0.1] * 768,
        is_active=True,
    )
    assert resume.target_work_modes == ["remote"]

    remote_job = _create_job(
        external_id="wm-remote-1",
        title="Senior Python Remote Engineer",
        work_mode=WorkMode.REMOTE,
    )
    hybrid_job = _create_job(
        external_id="wm-hybrid-1",
        title="Senior Python Hybrid Engineer",
        work_mode=WorkMode.HYBRID,
    )
    onsite_job = _create_job(
        external_id="wm-onsite-1",
        title="Senior Python Onsite Engineer",
        work_mode=WorkMode.ONSITE,
    )
    unknown_job = _create_job(
        external_id="wm-unknown-1",
        title="Senior Python Engineer",
        work_mode=WorkMode.UNKNOWN,
    )

    for job in (remote_job, hybrid_job, onsite_job, unknown_job):
        MatchScore.objects.create(
            job_posting=job,
            resume_profile=resume,
            cosine_similarity=0.85,
            fit_score=80,
            resume_content_hash=resume.content_hash,
        )

    lead = ApplicationLead.objects.create(
        user=user,
        job_posting=remote_job,
        resume_profile=resume,
    )

    client = APIClient()
    client.force_authenticate(user=user)

    # Single work_mode filter on /api/v1/jobs/
    jobs_remote = client.get("/api/v1/jobs/?work_mode=remote")
    assert jobs_remote.status_code == 200
    assert [r["external_id"] for r in jobs_remote.json()["results"]] == ["wm-remote-1"]
    assert jobs_remote.json()["results"][0]["work_mode"] == "remote"

    # Comma-separated work_mode filter on /api/v1/jobs/
    jobs_multi = client.get("/api/v1/jobs/?work_mode=remote,unknown")
    assert jobs_multi.status_code == 200
    assert {r["external_id"] for r in jobs_multi.json()["results"]} == {
        "wm-remote-1",
        "wm-unknown-1",
    }

    # Single & comma-separated work_mode filter on /api/v1/matches/
    matches_hybrid = client.get("/api/v1/matches/?work_mode=hybrid")
    assert matches_hybrid.status_code == 200
    assert [
        m["job_posting"]["external_id"] for m in matches_hybrid.json()["results"]
    ] == ["wm-hybrid-1"]
    assert matches_hybrid.json()["results"][0]["job_posting"]["work_mode"] == "hybrid"

    matches_multi = client.get("/api/v1/matches/?work_mode=remote,hybrid")
    assert matches_multi.status_code == 200
    assert {
        m["job_posting"]["external_id"] for m in matches_multi.json()["results"]
    } == {"wm-remote-1", "wm-hybrid-1"}

    # Composable with Hybrid RRF search + triage (hide_dismissed + untracked_only)
    DismissedJob.objects.create(user=user, job_posting=hybrid_job)
    composed = client.get(
        "/api/v1/matches/?work_mode=remote,hybrid,unknown&search=Python&hide_dismissed=true&untracked_only=true"
    )
    assert composed.status_code == 200
    # hybrid_job is dismissed, remote_job is tracked by lead -> only unknown_job remains
    assert [m["job_posting"]["external_id"] for m in composed.json()["results"]] == [
        "wm-unknown-1"
    ]

    # /api/v1/leads/ exposes work_mode on leads
    leads_resp = client.get("/api/v1/leads/")
    assert leads_resp.status_code == 200
    lead_payload = next(
        item for item in leads_resp.json()["results"] if item["uuid"] == str(lead.uuid)
    )
    assert lead_payload["work_mode"] == "remote"


@pytest.mark.django_db
def test_saved_filter_allows_work_mode():
    user = User.objects.create_user(username="wm_preset_user", password="pw")
    client = APIClient()
    client.force_authenticate(user=user)

    resp = client.post(
        "/api/v1/jobs/filters/",
        {
            "name": "Remote Backend",
            "query_params": {
                "work_mode": "remote",
                "seniority": "senior",
                "region": "brazil",
            },
        },
        format="json",
    )
    assert resp.status_code == 201
    assert resp.json()["query_params"]["work_mode"] == "remote"


@pytest.mark.django_db
def test_resume_target_work_modes_validation_and_rescore_without_reembedding(
    django_capture_on_commit_callbacks,
):
    user = User.objects.create_user(username="wm_resume_user", password="pw")
    raw_text = "Senior Python Django engineer"
    resume = ResumeProfile.objects.create(
        user=user,
        label="Main CV",
        raw_text=raw_text,
        content_hash=ResumeService.compute_text_hash(raw_text),
        embedding=[0.2] * 768,
        is_active=True,
    )
    assert resume.target_work_modes == ["remote"]

    client = APIClient()
    client.force_authenticate(user=user)

    # Invalid enum value returns 400 Bad Request
    bad = client.patch(
        f"/api/v1/resumes/{resume.uuid}/",
        {"target_work_modes": ["remote", "teleport"]},
        format="json",
    )
    assert bad.status_code == 400
    assert "target_work_modes" in bad.json()

    # Valid update publishes jobs.rescore via on_commit WITHOUT re-embedding raw_text
    with (
        patch(
            "apps.resumes.services.resume_service.ResumeService.generate_embedding_and_skills"
        ) as mock_embed,
        patch(
            "apps.resumes.services.resume_service.publish_rescore_event"
        ) as mock_publish,
        django_capture_on_commit_callbacks(execute=True),
    ):
        updated = client.patch(
            f"/api/v1/resumes/{resume.uuid}/",
            {"target_work_modes": ["remote", "unknown"]},
            format="json",
        )

    assert updated.status_code == 200
    assert updated.json()["target_work_modes"] == ["remote", "unknown"]
    mock_embed.assert_not_called()
    mock_publish.assert_called_once()
    published_event = mock_publish.call_args.args[0]
    assert published_event.resume_profile_uuid == resume.uuid
    assert published_event.force is True

    # Empty list [] is allowed (unrestricted)
    with (
        patch(
            "apps.resumes.services.resume_service.ResumeService.generate_embedding_and_skills"
        ) as mock_embed,
        patch("apps.resumes.services.resume_service.publish_rescore_event"),
        django_capture_on_commit_callbacks(execute=True),
    ):
        cleared = client.patch(
            f"/api/v1/resumes/{resume.uuid}/",
            {"target_work_modes": []},
            format="json",
        )
    assert cleared.status_code == 200
    assert cleared.json()["target_work_modes"] == []
    mock_embed.assert_not_called()

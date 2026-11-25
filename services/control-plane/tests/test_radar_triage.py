from unittest.mock import patch

from django.contrib.auth import get_user_model
import pytest
from rest_framework.test import APIClient

from apps.jobs.models import DismissedJob, JobPosting, MutedCompany
from apps.matching.models import MatchScore
from apps.resumes.models import ResumeProfile
from apps.tracker.models import ApplicationLead
from vektryn_contracts.enums import ATSSource, LeadStatus

User = get_user_model()


def _create_job(
    *,
    external_id: str,
    title: str,
    company_name: str,
    description_clean: str = "Python Django PostgreSQL distributed backend services.",
) -> JobPosting:
    return JobPosting.objects.create(
        ats_source=ATSSource.GREENHOUSE,
        external_id=external_id,
        content_hash=f"{abs(hash((external_id, title, company_name))) % (10**16):064d}",
        title=title,
        company_name=company_name,
        apply_url=f"https://example.com/jobs/{external_id}",
        raw_html_gcs_uri=f"file:///tmp/{external_id}.html",
        description_clean=description_clean,
        tech_stack=["python", "django", "postgresql"],
    )


@pytest.mark.django_db
def test_dismissed_job_and_muted_company_crud_idempotency_and_idor():
    alice = User.objects.create_user(username="alice_triage", password="pw")
    bob = User.objects.create_user(username="bob_triage", password="pw")
    job = _create_job(
        external_id="triage-crud-1",
        title="Staff Python Engineer",
        company_name="Acme Staffing",
    )

    alice_client = APIClient()
    alice_client.force_authenticate(user=alice)
    bob_client = APIClient()
    bob_client.force_authenticate(user=bob)

    # DismissedJob create, idempotent duplicate, soft-delete restore, and re-dismiss
    created = alice_client.post(
        "/api/v1/jobs/dismissed/",
        {"job_posting": str(job.uuid)},
        format="json",
    )
    assert created.status_code == 201
    dismissed_uuid = created.json()["uuid"]
    assert created.json()["job_title"] == "Staff Python Engineer"
    assert created.json()["company_name"] == "Acme Staffing"

    dup = alice_client.post(
        "/api/v1/jobs/dismissed/",
        {"job_posting": str(job.uuid)},
        format="json",
    )
    assert dup.status_code == 200
    assert dup.json()["uuid"] == dismissed_uuid

    # Verify savepoint recovery when a concurrent race raises IntegrityError on INSERT
    with patch(
        "apps.jobs.views.triage.DismissedJobViewSet.get_queryset",
        side_effect=[
            DismissedJob.objects.none(),
            DismissedJob.objects.select_related("job_posting").filter(user=alice),
        ],
    ):
        raced = alice_client.post(
            "/api/v1/jobs/dismissed/",
            {"job_posting": str(job.uuid)},
            format="json",
        )
    assert raced.status_code == 200
    assert raced.json()["uuid"] == dismissed_uuid

    # Cross-user IDOR isolation
    assert (
        bob_client.get(f"/api/v1/jobs/dismissed/{dismissed_uuid}/").status_code == 404
    )
    assert (
        bob_client.delete(f"/api/v1/jobs/dismissed/{dismissed_uuid}/").status_code
        == 404
    )
    assert bob_client.get("/api/v1/jobs/dismissed/").json()["count"] == 0

    # Restore (soft-delete) and re-dismiss cleanly
    restored = alice_client.delete(f"/api/v1/jobs/dismissed/{dismissed_uuid}/")
    assert restored.status_code == 204
    assert alice_client.get("/api/v1/jobs/dismissed/").json()["count"] == 0

    re_dismissed = alice_client.post(
        "/api/v1/jobs/dismissed/",
        {"job_posting": str(job.uuid)},
        format="json",
    )
    assert re_dismissed.status_code == 201
    assert re_dismissed.json()["uuid"] != dismissed_uuid

    # MutedCompany blank validation, normalization, idempotency, savepoint race, and IDOR
    blank = alice_client.post(
        "/api/v1/jobs/muted-companies/",
        {"company_name": "   \t\n  "},
        format="json",
    )
    assert blank.status_code == 400

    muted = alice_client.post(
        "/api/v1/jobs/muted-companies/",
        {"company_name": "  Acme   Staffing \t"},
        format="json",
    )
    assert muted.status_code == 201
    muted_uuid = muted.json()["uuid"]
    assert muted.json()["company_name_display"] == "Acme Staffing"
    assert muted.json()["company_name_normalized"] == "acme staffing"

    muted_dup = alice_client.post(
        "/api/v1/jobs/muted-companies/",
        {"company_name": "ACME staffing"},
        format="json",
    )
    assert muted_dup.status_code == 200
    assert muted_dup.json()["uuid"] == muted_uuid

    with patch(
        "apps.jobs.views.triage.MutedCompanyViewSet.get_queryset",
        side_effect=[
            MutedCompany.objects.none(),
            MutedCompany.objects.filter(user=alice),
        ],
    ):
        muted_race = alice_client.post(
            "/api/v1/jobs/muted-companies/",
            {"company_name": "acme staffing"},
            format="json",
        )
    assert muted_race.status_code == 200
    assert muted_race.json()["uuid"] == muted_uuid

    assert (
        bob_client.delete(f"/api/v1/jobs/muted-companies/{muted_uuid}/").status_code
        == 404
    )
    assert (
        alice_client.delete(f"/api/v1/jobs/muted-companies/{muted_uuid}/").status_code
        == 204
    )
    assert alice_client.get("/api/v1/jobs/muted-companies/").json()["count"] == 0


@pytest.mark.django_db
def test_triage_filters_compose_with_matches_jobs_rrf_search_and_user_isolation():
    alice = User.objects.create_user(username="alice_filter", password="pw")
    bob = User.objects.create_user(username="bob_filter", password="pw")

    alice_resume = ResumeProfile.objects.create(
        user=alice,
        label="Alice Backend",
        raw_text="Python Django PostgreSQL",
        content_hash="a" * 64,
        min_alert_score=70,
    )
    bob_resume = ResumeProfile.objects.create(
        user=bob,
        label="Bob Backend",
        raw_text="Python Django PostgreSQL",
        content_hash="b" * 64,
        min_alert_score=70,
    )

    job_visible = _create_job(
        external_id="triage-vis-1",
        title="Senior Python Platform Engineer",
        company_name="CleanCo",
        description_clean="Build Python Django PostgreSQL platform APIs.",
    )
    job_dismissed = _create_job(
        external_id="triage-dis-1",
        title="Senior Python API Engineer",
        company_name="OtherCo",
        description_clean="Build Python Django PostgreSQL APIs.",
    )
    # Messy outer tabs/newlines + repeated internal spaces to verify BTRIM(REGEXP_REPLACE(LOWER(...)))
    job_muted = _create_job(
        external_id="triage-mut-1",
        title="Senior Python Systems Engineer",
        company_name="\tSpam   Agency\n",
        description_clean="Build Python Django PostgreSQL systems.",
    )
    job_tracked = _create_job(
        external_id="triage-trk-1",
        title="Senior Python Data Engineer",
        company_name="GoodCo",
        description_clean="Build Python Django PostgreSQL data services.",
    )

    all_jobs = [job_visible, job_dismissed, job_muted, job_tracked]
    alice_matches = {}
    for idx, job in enumerate(all_jobs):
        alice_matches[job.uuid] = MatchScore.objects.create(
            job_posting=job,
            resume_profile=alice_resume,
            cosine_similarity=0.85,
            fit_score=88 - idx,
            resume_content_hash=alice_resume.content_hash,
        )
        MatchScore.objects.create(
            job_posting=job,
            resume_profile=bob_resume,
            cosine_similarity=0.85,
            fit_score=88 - idx,
            resume_content_hash=bob_resume.content_hash,
        )

    alice_client = APIClient()
    alice_client.force_authenticate(user=alice)
    bob_client = APIClient()
    bob_client.force_authenticate(user=bob)

    # Short-circuit path when user has zero muted companies returns all 4 matches
    initial = alice_client.get("/api/v1/matches/")
    assert initial.status_code == 200
    assert initial.json()["count"] == 4

    # Alice dismisses one role, mutes "Spam Agency", and tracks one lead
    dismissed_res = alice_client.post(
        "/api/v1/jobs/dismissed/",
        {"job_posting": str(job_dismissed.uuid)},
        format="json",
    )
    assert dismissed_res.status_code == 201

    muted_res = alice_client.post(
        "/api/v1/jobs/muted-companies/",
        {"company_name": "Spam Agency"},
        format="json",
    )
    assert muted_res.status_code == 201

    lead = ApplicationLead.objects.create(
        user=alice,
        job_posting=job_tracked,
        resume_profile=alice_resume,
        status=LeadStatus.SAVED,
    )

    # Default /matches/ hides dismissed + messy-whitespace muted company (2 left)
    default_matches = alice_client.get("/api/v1/matches/")
    assert default_matches.status_code == 200
    default_body = default_matches.json()
    assert default_body["count"] == 2
    assert {r["job_posting"]["uuid"] for r in default_body["results"]} == {
        str(job_visible.uuid),
        str(job_tracked.uuid),
    }
    assert default_body["summary"] == {
        "ai_scored_count": 2,
        "strong_fit_count": 2,
        "alert_threshold_count": 2,
    }

    # untracked_only=true excludes tracked lead as well (1 left)
    untracked_matches = alice_client.get("/api/v1/matches/?untracked_only=true")
    assert untracked_matches.status_code == 200
    assert [r["job_posting"]["uuid"] for r in untracked_matches.json()["results"]] == [
        str(job_visible.uuid)
    ]

    # Soft-deleting the ApplicationLead makes the role visible again under untracked_only=true
    lead.delete()
    after_lead_delete = alice_client.get("/api/v1/matches/?untracked_only=true")
    assert after_lead_delete.json()["count"] == 2

    # Explicit overrides surface hidden & muted roles again
    override_matches = alice_client.get(
        "/api/v1/matches/?hide_dismissed=false&hide_muted=false"
    )
    assert override_matches.status_code == 200
    assert override_matches.json()["count"] == 4

    # Detail retrieve() stays unfiltered so deep-links never 404
    assert alice_client.get(f"/api/v1/jobs/{job_dismissed.uuid}/").status_code == 200
    assert (
        alice_client.get(
            f"/api/v1/matches/{alice_matches[job_dismissed.uuid].uuid}/"
        ).status_code
        == 200
    )

    # /jobs/ list AND Hybrid RRF search both respect triage exclusions
    jobs_res = alice_client.get("/api/v1/jobs/?search=python")
    assert jobs_res.status_code == 200
    assert {r["uuid"] for r in jobs_res.json()["results"]} == {
        str(job_visible.uuid),
        str(job_tracked.uuid),
    }

    matches_search = alice_client.get("/api/v1/matches/?search=python")
    assert matches_search.status_code == 200
    assert {r["job_posting"]["uuid"] for r in matches_search.json()["results"]} == {
        str(job_visible.uuid),
        str(job_tracked.uuid),
    }

    # Bob is completely unaffected by Alice's dismissals and mutes
    bob_matches = bob_client.get("/api/v1/matches/")
    assert bob_matches.status_code == 200
    assert bob_matches.json()["count"] == 4

    # Restoring dismissed role and unmuting company surfaces all 4 for Alice again
    alice_client.delete(f"/api/v1/jobs/dismissed/{dismissed_res.json()['uuid']}/")
    alice_client.delete(f"/api/v1/jobs/muted-companies/{muted_res.json()['uuid']}/")
    restored_matches = alice_client.get("/api/v1/matches/")
    assert restored_matches.json()["count"] == 4


@pytest.mark.django_db
def test_saved_filter_allows_triage_boolean_params_and_validates_types():
    user = User.objects.create_user(username="preset_triage_user", password="pw")
    client = APIClient()
    client.force_authenticate(user=user)

    valid = client.post(
        "/api/v1/jobs/filters/",
        {
            "name": "Unapplied 80%+",
            "query_params": {
                "min_score": 80,
                "untracked_only": True,
                "hide_dismissed": True,
                "hide_muted": False,
            },
        },
        format="json",
    )
    assert valid.status_code == 201
    assert valid.json()["query_params"] == {
        "min_score": 80,
        "untracked_only": True,
        "hide_dismissed": True,
        "hide_muted": False,
    }

    invalid_bool = client.post(
        "/api/v1/jobs/filters/",
        {
            "name": "Bad Bool",
            "query_params": {"untracked_only": "yes"},
        },
        format="json",
    )
    assert invalid_bool.status_code == 400
    assert "must be a boolean" in str(invalid_bool.json())

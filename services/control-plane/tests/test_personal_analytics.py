from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.utils import timezone
import pytest
from rest_framework.test import APIClient

from apps.jobs.models.jobs import JobPosting
from apps.matching.models.matching import MatchScore
from apps.resumes.models.resumes import ResumeProfile
from apps.tracker.models.tracker import ApplicationLead
from vektryn_contracts.enums import (
    ATSSource,
    ContractType,
    LeadStatus,
    SeniorityLevel,
)

User = get_user_model()


def _make_job(
    *,
    external_id: str,
    ats_source: ATSSource = ATSSource.GREENHOUSE,
    contract_type: ContractType = ContractType.PJ,
    is_deleted: bool = False,
) -> JobPosting:
    job = JobPosting.objects.create(
        ats_source=ats_source,
        external_id=external_id,
        content_hash=f"hash-{external_id}-{uuid4().hex[:8]}",
        title=f"Engineer {external_id}",
        company_name="Acme Corp",
        apply_url=f"https://example.com/jobs/{external_id}",
        raw_html_gcs_uri=f"gs://bucket/{external_id}.html",
        location_raw="Remote",
        description_clean="Build scalable Python and Kafka platforms.",
        seniority=SeniorityLevel.SENIOR,
        contract_type=contract_type,
        tech_stack=["python", "kafka"],
    )
    if is_deleted:
        job.soft_delete()
    return job


@pytest.mark.django_db
def test_personal_analytics_empty_account_and_validation():
    user = User.objects.create_user(username="empty_analytics", password="pw")
    client = APIClient()
    client.force_authenticate(user=user)

    res = client.get("/api/v1/analytics/personal/")
    assert res.status_code == 200
    body = res.json()
    assert body["window"] == {"days": 30, "label": "30d", "resume_profile_uuid": None}
    assert body["funnel"]["total_leads"] == 0
    assert body["funnel"]["applied_to_offer_pct"] is None
    assert body["funnel"]["median_days_since_applied"] is None
    assert all(stage["count"] == 0 for stage in body["funnel"]["stages"])
    assert all(
        stage["conversion_from_previous_pct"] is None
        for stage in body["funnel"]["stages"]
    )
    assert body["channels"] == {"by_ats_source": [], "by_contract_type": []}
    assert body["skill_gaps"] == {
        "high_fit_match_count": 0,
        "missing_keywords": [],
        "matched_skills": [],
    }

    assert client.get("/api/v1/analytics/personal/?days=7").status_code == 400
    assert (
        client.get("/api/v1/analytics/personal/?resume_profile=not-a-uuid").status_code
        == 400
    )
    assert (
        client.get(f"/api/v1/analytics/personal/?resume_profile={uuid4()}").status_code
        == 404
    )


@pytest.mark.django_db
def test_personal_analytics_user_isolation_funnel_channels_and_median():
    user_a = User.objects.create_user(username="analytics_a", password="pw")
    user_b = User.objects.create_user(username="analytics_b", password="pw")
    resume_a = ResumeProfile.objects.create(
        user=user_a,
        label="Backend A",
        raw_text="Python Django PostgreSQL",
        content_hash="hash-a",
        min_alert_score=75,
    )
    resume_b = ResumeProfile.objects.create(
        user=user_b,
        label="Backend B",
        raw_text="Go Rust",
        content_hash="hash-b",
        min_alert_score=70,
    )

    now = timezone.now()
    j1 = _make_job(
        external_id="pa-1",
        ats_source=ATSSource.GREENHOUSE,
        contract_type=ContractType.PJ,
    )
    j2 = _make_job(
        external_id="pa-2",
        ats_source=ATSSource.GREENHOUSE,
        contract_type=ContractType.PJ,
    )
    j3 = _make_job(
        external_id="pa-3", ats_source=ATSSource.LEVER, contract_type=ContractType.CLT
    )
    j4 = _make_job(
        external_id="pa-4", ats_source=ATSSource.LEVER, contract_type=ContractType.CLT
    )
    j5 = _make_job(
        external_id="pa-5",
        ats_source=ATSSource.GREENHOUSE,
        contract_type=ContractType.PJ,
    )
    j_deleted = _make_job(external_id="pa-del", is_deleted=True)

    # User A leads:
    # 1. discovered (not applied)
    ApplicationLead.objects.create(
        user=user_a,
        job_posting=j1,
        resume_profile=resume_a,
        status=LeadStatus.DISCOVERED,
    )
    # 2. offer (applied 10 days ago)
    ApplicationLead.objects.create(
        user=user_a,
        job_posting=j2,
        resume_profile=resume_a,
        status=LeadStatus.OFFER,
        applied_at=now - timedelta(days=10),
    )
    # 3. screening (applied 4 days ago)
    ApplicationLead.objects.create(
        user=user_a,
        job_posting=j3,
        resume_profile=resume_a,
        status=LeadStatus.SCREENING,
        applied_at=now - timedelta(days=4),
    )
    # 4. rejected AFTER applying (applied 2 days ago) -> MUST count in applied_plus & applied_count
    ApplicationLead.objects.create(
        user=user_a,
        job_posting=j4,
        resume_profile=resume_a,
        status=LeadStatus.REJECTED,
        applied_at=now - timedelta(days=2),
    )
    # 5. withdrawn BEFORE applying (applied_at=None) -> NOT counted in applied
    ApplicationLead.objects.create(
        user=user_a,
        job_posting=j5,
        resume_profile=resume_a,
        status=LeadStatus.WITHDRAWN,
        applied_at=None,
    )
    # Deleted job lead -> excluded from both funnel & median
    ApplicationLead.objects.create(
        user=user_a,
        job_posting=j_deleted,
        resume_profile=resume_a,
        status=LeadStatus.APPLIED,
        applied_at=now - timedelta(days=100),
    )

    # User B lead -> must never leak into User A
    ApplicationLead.objects.create(
        user=user_b,
        job_posting=j1,
        resume_profile=resume_b,
        status=LeadStatus.OFFER,
        applied_at=now - timedelta(days=1),
    )

    client_a = APIClient()
    client_a.force_authenticate(user=user_a)

    # Cross-user resume_profile -> 404
    assert (
        client_a.get(
            f"/api/v1/analytics/personal/?resume_profile={resume_b.uuid}"
        ).status_code
        == 404
    )

    res = client_a.get("/api/v1/analytics/personal/?days=30")
    assert res.status_code == 200
    body = res.json()

    funnel = body["funnel"]
    assert funnel["total_leads"] == 5
    assert funnel["status_counts"]["discovered"] == 1
    assert funnel["status_counts"]["offer"] == 1
    assert funnel["status_counts"]["screening"] == 1
    assert funnel["status_counts"]["rejected"] == 1
    assert funnel["status_counts"]["withdrawn"] == 1

    stage_by_key = {s["key"]: s for s in funnel["stages"]}
    assert stage_by_key["tracked"]["count"] == 5
    assert (
        stage_by_key["applied"]["count"] == 3
    )  # offer + screening + rejected(applied)
    assert stage_by_key["applied"]["conversion_from_previous_pct"] == pytest.approx(
        60.0
    )
    assert stage_by_key["screening"]["count"] == 2  # screening + offer
    assert stage_by_key["screening"]["conversion_from_previous_pct"] == pytest.approx(
        66.7
    )
    assert stage_by_key["interviewing"]["count"] == 1  # offer
    assert stage_by_key["interviewing"][
        "conversion_from_previous_pct"
    ] == pytest.approx(50.0)
    assert stage_by_key["offer"]["count"] == 1
    assert stage_by_key["offer"]["conversion_from_previous_pct"] == pytest.approx(100.0)
    assert funnel["applied_to_offer_pct"] == pytest.approx(33.3)
    # Median of [2, 4, 10] days = 4.0 days
    assert funnel["median_days_since_applied"] == pytest.approx(4.0, abs=0.2)

    # Channel performance reconciles with funnel applied_count
    by_ats = {row["key"]: row for row in body["channels"]["by_ats_source"]}
    assert by_ats["lever"]["total_leads"] == 2
    assert by_ats["lever"]["applied_count"] == 2  # screening + rejected(applied)
    assert by_ats["lever"]["response_count"] == 1
    assert by_ats["lever"]["response_rate_pct"] == pytest.approx(50.0)
    assert by_ats["lever"]["interview_count"] == 0
    assert by_ats["lever"]["interview_rate_pct"] == pytest.approx(0.0)

    assert by_ats["greenhouse"]["total_leads"] == 3
    assert (
        by_ats["greenhouse"]["applied_count"] == 1
    )  # offer only (discovered + withdrawn unapplied excluded)
    assert by_ats["greenhouse"]["response_rate_pct"] == pytest.approx(100.0)
    assert by_ats["greenhouse"]["interview_rate_pct"] == pytest.approx(100.0)
    assert (
        sum(r["applied_count"] for r in by_ats.values())
        == stage_by_key["applied"]["count"]
    )


@pytest.mark.django_db
def test_personal_analytics_skill_gaps_cte_dedup_normalization_and_windows():
    user = User.objects.create_user(username="analytics_skills", password="pw")
    resume_main = ResumeProfile.objects.create(
        user=user,
        label="Main Resume",
        raw_text="Python Django",
        content_hash="hash-main",
        min_alert_score=75,
    )
    resume_alt = ResumeProfile.objects.create(
        user=user,
        label="Alt Resume",
        raw_text="TypeScript React",
        content_hash="hash-alt",
        min_alert_score=70,
    )

    now = timezone.now()
    j1 = _make_job(external_id="sk-1")
    j2 = _make_job(external_id="sk-2")
    j3 = _make_job(external_id="sk-3")
    j4 = _make_job(external_id="sk-4")
    j5 = _make_job(external_id="sk-5")

    # High-fit match 1 (score=90) with duplicate casing/whitespace keywords -> must NOT double-weight AVG!
    MatchScore.objects.create(
        job_posting=j1,
        resume_profile=resume_main,
        cosine_similarity=0.85,
        fit_score=90,
        matched_skills=["Python", "  python\t"],
        missing_keywords=["Kubernetes", "\tkubernetes\n", "React  Native"],
        resume_content_hash="hash-main",
    )
    # High-fit match 2 (score=80, created 60d ago, rescored 2d ago -> modified_at inside 30d window!)
    m_rescored = MatchScore.objects.create(
        job_posting=j2,
        resume_profile=resume_main,
        cosine_similarity=0.82,
        fit_score=80,
        matched_skills=["python", "django"],
        missing_keywords=["kubernetes", "terraform"],
        resume_content_hash="hash-main",
    )
    MatchScore.all_objects.filter(pk=m_rescored.pk).update(
        created_at=now - timedelta(days=60),
        modified_at=now - timedelta(days=2),
    )
    # Below min_alert_score (74 < 75) -> MUST be excluded from high-fit tallies
    MatchScore.objects.create(
        job_posting=j3,
        resume_profile=resume_main,
        cosine_similarity=0.70,
        fit_score=74,
        matched_skills=["python"],
        missing_keywords=["rust"],
        resume_content_hash="hash-main",
    )
    # Unscored Stage-1 match (fit_score=None) -> MUST be excluded
    MatchScore.objects.create(
        job_posting=j4,
        resume_profile=resume_main,
        cosine_similarity=0.65,
        fit_score=None,
        matched_skills=[],
        missing_keywords=["go"],
        resume_content_hash="hash-main",
    )
    # Old match on alt resume (modified 50 days ago -> excluded from 30d, included in 90d/all)
    m_old_alt = MatchScore.objects.create(
        job_posting=j5,
        resume_profile=resume_alt,
        cosine_similarity=0.88,
        fit_score=85,
        matched_skills=["typescript"],
        missing_keywords=["graphql"],
        resume_content_hash="hash-alt",
    )
    MatchScore.all_objects.filter(pk=m_old_alt.pk).update(
        created_at=now - timedelta(days=50),
        modified_at=now - timedelta(days=50),
    )

    client = APIClient()
    client.force_authenticate(user=user)

    # 30-day window includes m1 + rescored m2 (both >= 75), excludes m_old_alt (50d) and low-fit m3 (74)
    res_30 = client.get("/api/v1/analytics/personal/?days=30")
    assert res_30.status_code == 200
    gaps_30 = res_30.json()["skill_gaps"]
    assert gaps_30["high_fit_match_count"] == 2
    missing_30 = {item["skill"]: item for item in gaps_30["missing_keywords"]}
    # Exact unweighted AVG of [90, 80] = 85.0 (NOT (90 + 90 + 80)/3 = 86.7!)
    assert missing_30["kubernetes"]["skill"] == "kubernetes"
    assert missing_30["kubernetes"]["match_count"] == 2
    assert missing_30["kubernetes"]["pct_of_high_fit"] == pytest.approx(100.0)
    assert missing_30["kubernetes"]["avg_fit_score"] == pytest.approx(85.0)
    assert "react native" in missing_30  # Multi-space collapsed cleanly
    assert "rust" not in missing_30
    assert "graphql" not in missing_30

    # 90-day window includes m_old_alt -> 3 high-fit matches and graphql surfaces
    res_90 = client.get("/api/v1/analytics/personal/?days=90")
    assert res_90.status_code == 200
    gaps_90 = res_90.json()["skill_gaps"]
    assert gaps_90["high_fit_match_count"] == 3
    assert any(item["skill"] == "graphql" for item in gaps_90["missing_keywords"])

    # Scoped to resume_alt across all time -> only m_old_alt
    res_alt = client.get(
        f"/api/v1/analytics/personal/?days=all&resume_profile={resume_alt.uuid}"
    )
    assert res_alt.status_code == 200
    gaps_alt = res_alt.json()["skill_gaps"]
    assert gaps_alt["high_fit_match_count"] == 1
    assert gaps_alt["missing_keywords"][0]["skill"] == "graphql"
    assert gaps_alt["matched_skills"][0]["skill"] == "typescript"

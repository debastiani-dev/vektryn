from datetime import timedelta
from io import StringIO
import ipaddress
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.utils import timezone
import pytest
from rest_framework.test import APIClient

from apps.jobs.models.jobs import JobPosting, JobPostingSource
from apps.jobs.models.saved_filter import SavedFilter
from apps.jobs.models.triage import DismissedJob
from apps.jobs.services.manual_import import ManualJobImportService
from apps.matching.models.artifacts import MatchArtifact, MatchArtifactKind
from apps.matching.models.matching import MatchScore
from apps.resumes.models.resumes import ResumeProfile
from apps.tracker.models import ApplicationLead
from vektryn_contracts import (
    ATSSource,
    LeadStatus,
    compute_description_fingerprint,
    compute_job_content_hash,
    normalize_company_for_dedup,
    normalize_title_for_dedup,
)

User = get_user_model()

LONG_DESC = (
    "We are hiring a Senior Backend Python Engineer to architect distributed "
    "event-driven services with Django, PostgreSQL, pgvector, Redis, and Apache Kafka. "
    "You will collaborate with product teams, own production SLAs, and mentor engineers."
)


def _unit_vec(index: int, weight: float = 1.0) -> list[float]:
    vec = [0.0] * 768
    vec[index] = weight
    return vec


def _make_job(
    *,
    ats_source: str = ATSSource.REMOTIVE.value,
    external_id: str = "ext-1",
    title: str = "Senior Backend Python Engineer",
    company_name: str = "Acme Corp.",
    apply_url: str = "https://remotive.com/jobs/ext-1",
    description: str = LONG_DESC,
    seniority: str = "senior",
    work_mode: str = "remote",
    language: str = "en",
    region_eligibility: list[str] | None = None,
    embedding: list[float] | None = None,
    is_active: bool = True,
    repost_count: int = 0,
    last_reposted_at=None,
    salary_min=None,
    salary_max=None,
    salary_currency: str = "",
    salary_period: str | None = None,
    tech_stack: list[str] | None = None,
    with_source: bool = True,
) -> JobPosting:
    content_hash = compute_job_content_hash(
        ats_source=ats_source,
        title=title,
        company_name=company_name,
        description_clean=description,
    )
    fp, _ = compute_description_fingerprint(description)
    job = JobPosting.objects.create(
        ats_source=ats_source,
        external_id=external_id,
        content_hash=content_hash,
        title=title,
        company_name=company_name,
        apply_url=apply_url,
        raw_html_gcs_uri=f"gs://test/{external_id}.html",
        description_clean=description,
        seniority=seniority,
        work_mode=work_mode,
        language=language,
        region_eligibility=region_eligibility or ["worldwide"],
        embedding=embedding,
        is_active=is_active,
        repost_count=repost_count,
        last_reposted_at=last_reposted_at,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=salary_currency,
        salary_period=salary_period,
        tech_stack=tech_stack or ["python"],
        company_name_normalized=normalize_company_for_dedup(company_name),
        title_normalized=normalize_title_for_dedup(title),
        description_fingerprint=fp,
    )
    if with_source:
        JobPostingSource.objects.create(
            job_posting=job,
            ats_source=ats_source,
            external_id=external_id,
            apply_url=apply_url,
            raw_html_gcs_uri=job.raw_html_gcs_uri,
            is_primary=True,
            is_active=is_active,
        )
    return job


@pytest.mark.django_db
def test_job_posting_source_db_constraints() -> None:
    job = _make_job(ats_source="greenhouse", external_id="gh-101")

    # uq_job_source_ats_ext blocks duplicate active (ats_source, external_id)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            JobPostingSource.objects.create(
                job_posting=job,
                ats_source="greenhouse",
                external_id="gh-101",
                apply_url="https://boards.greenhouse.io/acme/jobs/101",
                is_primary=False,
                is_active=True,
            )

    # uq_job_source_single_primary blocks two active primaries on same job
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            JobPostingSource.objects.create(
                job_posting=job,
                ats_source="remotive",
                external_id="rem-101",
                apply_url="https://remotive.com/jobs/101",
                is_primary=True,
                is_active=True,
            )


@pytest.mark.django_db
def test_jobs_matches_and_leads_api_fields_filters_and_zero_n_plus_one(
    django_assert_num_queries,
) -> None:
    user = User.objects.create_user(username="dedup_api_user", password="Password123!")
    resume = ResumeProfile.objects.create(
        user=user,
        label="Backend EN",
        raw_text="Senior Python Engineer",
        content_hash="r" * 64,
        extracted_skills=["python", "django"],
        language="en",
        is_active=True,
        embedding=_unit_vec(0),
    )

    now = timezone.now()
    # Create 1 multi-source canonical job first (originally remotive, upgraded to greenhouse)
    job_1 = _make_job(
        ats_source="remotive",
        external_id="rem-1",
        apply_url="https://boards.greenhouse.io/acme/jobs/1",
        repost_count=2,
        last_reposted_at=now,
        with_source=False,
    )
    JobPostingSource.objects.create(
        job_posting=job_1,
        ats_source="remotive",
        external_id="rem-1",
        apply_url="https://remotive.com/jobs/rem-1",
        is_primary=False,
        is_active=True,
    )
    JobPostingSource.objects.create(
        job_posting=job_1,
        ats_source="greenhouse",
        external_id="gh-1",
        apply_url="https://boards.greenhouse.io/acme/jobs/1",
        is_primary=True,
        is_active=True,
    )
    MatchScore.objects.create(
        job_posting=job_1,
        resume_profile=resume,
        cosine_similarity=0.92,
        fit_score=88,
        resume_content_hash=resume.content_hash,
        is_routed_winner=True,
    )
    ApplicationLead.objects.create(
        user=user,
        job_posting=job_1,
        resume_profile=resume,
        status=LeadStatus.SAVED.value,
    )

    client = APIClient()
    client.force_authenticate(user=user)

    # Check payload fields on /api/v1/jobs/, /api/v1/jobs/{uuid}/, /api/v1/matches/, /api/v1/leads/
    jobs_res = client.get("/api/v1/jobs/")
    assert jobs_res.status_code == 200
    item = jobs_res.data["results"][0]
    assert item["primary_source"] == "greenhouse"
    assert item["sources_count"] == 2
    assert item["observed_sources"] == ["greenhouse", "remotive"]
    assert item["repost_count"] == 2
    assert item["last_reposted_at"] is not None

    detail_res = client.get(f"/api/v1/jobs/{job_1.uuid}/")
    assert detail_res.status_code == 200
    assert len(detail_res.data["sources"]) == 2
    assert detail_res.data["sources"][0]["ats_source"] == "greenhouse"
    assert detail_res.data["sources"][0]["is_primary"] is True

    # ?ats_source=greenhouse finds job originally ingested via remotive without duplicating rows
    filtered_jobs = client.get("/api/v1/jobs/?ats_source=greenhouse")
    assert filtered_jobs.status_code == 200
    assert filtered_jobs.data["count"] == 1
    assert filtered_jobs.data["results"][0]["uuid"] == str(job_1.uuid)

    filtered_matches = client.get("/api/v1/matches/?ats_source=greenhouse")
    assert filtered_matches.status_code == 200
    assert filtered_matches.data["count"] == 1
    assert filtered_matches.data["summary"]["ai_scored_count"] == 1

    # ?hide_reposts=true excludes job_1 (repost_count=2)
    assert client.get("/api/v1/jobs/?hide_reposts=true").data["count"] == 0
    assert client.get("/api/v1/matches/?hide_reposts=true").data["count"] == 0

    # SavedFilter accepts hide_reposts boolean and rejects non-bool
    preset_res = client.post(
        "/api/v1/jobs/filters/",
        data={"name": "Fresh Roles Only", "query_params": {"hide_reposts": True}},
        format="json",
    )
    assert preset_res.status_code == 201
    assert preset_res.data["query_params"]["hide_reposts"] is True
    assert SavedFilter.objects.filter(user=user, name="Fresh Roles Only").exists()

    bad_preset = client.post(
        "/api/v1/jobs/filters/",
        data={"name": "Bad Repost", "query_params": {"hide_reposts": "yes"}},
        format="json",
    )
    assert bad_preset.status_code == 400

    # Leads expose repost_count, last_reposted_at, primary_source
    leads_res = client.get("/api/v1/leads/")
    assert leads_res.status_code == 200
    lead_item = leads_res.data["results"][0]
    assert lead_item["primary_source"] == "greenhouse"
    assert lead_item["repost_count"] == 2
    assert lead_item["last_reposted_at"] is not None

    # Measure baseline query count for 1 job, then add 4 more multi-source jobs -> exact same query count (0 N+1)
    with django_assert_num_queries(5):
        assert client.get("/api/v1/jobs/").status_code == 200
    with django_assert_num_queries(6):
        assert client.get("/api/v1/matches/").status_code == 200
    with django_assert_num_queries(4):
        assert client.get("/api/v1/leads/").status_code == 200

    for idx in range(2, 6):
        extra = _make_job(
            ats_source="remotive",
            external_id=f"rem-{idx}",
            title=f"Backend Engineer {idx}",
            company_name=f"Company {idx}",
            description=f"{LONG_DESC} Role number {idx} details.",
            repost_count=0,
        )
        JobPostingSource.objects.create(
            job_posting=extra,
            ats_source="ashby",
            external_id=f"ash-{idx}",
            apply_url=f"https://jobs.ashbyhq.com/company{idx}/{idx}",
            is_primary=False,
            is_active=True,
        )
        MatchScore.objects.create(
            job_posting=extra,
            resume_profile=resume,
            cosine_similarity=0.85,
            fit_score=80,
            resume_content_hash=resume.content_hash,
            is_routed_winner=True,
        )
        ApplicationLead.objects.create(
            user=user,
            job_posting=extra,
            resume_profile=resume,
            status=LeadStatus.APPLIED.value,
        )

    # Exact same query counts with 5 multi-source jobs proves zero N+1!
    with django_assert_num_queries(5):
        res_jobs = client.get("/api/v1/jobs/")
        assert res_jobs.data["count"] == 5
    with django_assert_num_queries(6):
        res_matches = client.get("/api/v1/matches/")
        assert res_matches.data["count"] == 5
    with django_assert_num_queries(4):
        res_leads = client.get("/api/v1/leads/")
        assert res_leads.data["count"] == 5


@pytest.mark.django_db
def test_manual_import_sync_dedup_option_a_and_soft_delete_guard() -> None:
    user = User.objects.create_user(
        username="manual_dedup_user", password="Password123!"
    )
    ResumeProfile.objects.create(
        user=user,
        label="Backend EN",
        raw_text="Senior Python Engineer",
        content_hash="m" * 64,
        extracted_skills=["python"],
        language="en",
        is_active=True,
        embedding=_unit_vec(1),
    )

    canonical = _make_job(
        ats_source="greenhouse",
        external_id="gh-canonical-1",
        company_name="Stripe, Inc.",
        apply_url="https://boards.greenhouse.io/stripe/jobs/1",
        embedding=_unit_vec(1),
    )

    service = ManualJobImportService(user=user)
    with (
        patch("apps.jobs.services.manual_import.enforce_import_rate_limit"),
        patch(
            "apps.jobs.services.manual_import._resolve_and_validate_ips",
            return_value=[ipaddress.ip_address("93.184.216.34")],
        ),
    ):
        with patch(
            "apps.jobs.services.manual_import.publish_enriched_event",
            return_value=True,
        ) as mock_publish_enriched:
            result = service.import_job(
                {
                    "title": "Senior Backend Python Engineer (Remote)",
                    "company_name": "Stripe Corp.",
                    "apply_url": "https://careers.stripe.com/custom-link",
                    "description": LONG_DESC,
                }
            )

        assert result.status == "already_exists"
        assert result.merged_into_existing is True
        assert result.job_posting_uuid == canonical.uuid
        # Greenhouse remains primary; manual source attached as secondary
        sources = list(JobPostingSource.objects.filter(job_posting=canonical))
        assert len(sources) == 2
        manual_src = next(s for s in sources if s.ats_source == ATSSource.MANUAL.value)
        assert manual_src.is_primary is False
        # Option A published JobEnrichedEvent reusing canonical embedding for unscored submitter
        assert mock_publish_enriched.call_count == 1
        published_event = mock_publish_enriched.call_args.args[0]
        assert published_event.submitted_by_user_id == user.pk
        assert published_event.ats_source == ATSSource.MANUAL

        # Guard: canonical with embedding=None falls back to normal jobs.raw forward
        no_embed = _make_job(
            ats_source="greenhouse",
            external_id="gh-no-embed",
            company_name="Vercel Inc.",
            description=f"{LONG_DESC} Built on Next.js edge network.",
            embedding=None,
        )
        with patch.object(
            service,
            "_forward_to_stream_edge",
            return_value={"content_hash": "x" * 64, "event_id": "evt-1"},
        ) as mock_forward:
            res_no_embed = service.import_job(
                {
                    "title": "Senior Backend Python Engineer",
                    "company_name": "Vercel",
                    "apply_url": "https://vercel.com/jobs/custom",
                    "description": no_embed.description_clean,
                }
            )
        assert res_no_embed.status == "queued"
        assert res_no_embed.merged_into_existing is False
        assert mock_forward.call_count == 1

        # Soft-deleted merged duplicate content_hash must NOT be resurrected
        soft_dup = _make_job(
            ats_source="manual",
            external_id="manual-old-dup",
            company_name="Stripe",
            description=f"{LONG_DESC} Unique manual copy.",
            with_source=False,
        )
        soft_dup.is_deleted = True
        soft_dup.is_active = False
        soft_dup.save(update_fields=["is_deleted", "is_active"])
        JobPostingSource.objects.create(
            job_posting=canonical,
            ats_source="manual",
            external_id="manual-old-dup",
            apply_url="https://stripe.com/repointed",
            is_primary=False,
            is_active=True,
        )
        with patch(
            "apps.jobs.services.manual_import.publish_enriched_event",
            return_value=True,
        ):
            res_repointed = service.import_job(
                {
                    "title": soft_dup.title,
                    "company_name": soft_dup.company_name,
                    "apply_url": "https://stripe.com/repointed",
                    "description": soft_dup.description_clean,
                }
            )
        soft_dup.refresh_from_db()
        assert soft_dup.is_deleted is True
        assert res_repointed.job_posting_uuid == canonical.uuid
        assert res_repointed.merged_into_existing is True


@pytest.mark.django_db
def test_backfill_job_sources_idempotent_and_merge_duplicates_conflict_resolution() -> (
    None
):
    user = User.objects.create_user(username="backfill_user", password="Password123!")
    resume_1 = ResumeProfile.objects.create(
        user=user,
        label="Backend EN 1",
        raw_text="Python Kafka",
        content_hash="1" * 64,
        language="en",
        is_active=True,
        embedding=_unit_vec(0),
    )
    resume_2 = ResumeProfile.objects.create(
        user=user,
        label="Backend EN 2",
        raw_text="Python Django",
        content_hash="2" * 64,
        language="en",
        is_active=True,
        embedding=_unit_vec(0),
    )

    shared_vec = _unit_vec(5)
    # Job A (Direct ATS winner) & Job B (Aggregator duplicate) — created without sources/normalized keys
    job_a = _make_job(
        ats_source="greenhouse",
        external_id="gh-merge-a",
        title="Senior Backend Python Engineer (Remote)",
        company_name="Datadog, Inc.",
        apply_url="https://boards.greenhouse.io/datadog/jobs/a",
        description=LONG_DESC,
        embedding=shared_vec,
        salary_min=None,
        tech_stack=["python"],
        with_source=False,
    )
    job_b = _make_job(
        ats_source="remotive",
        external_id="rem-merge-b",
        title="Senior Backend Python Engineer - Worldwide",
        company_name="Datadog Corp.",
        apply_url="https://remotive.com/jobs/b",
        description=f"{LONG_DESC} Extra aggregator footer.",
        embedding=shared_vec,
        salary_min=140000,
        salary_max=180000,
        salary_currency="USD",
        salary_period="annual",
        tech_stack=["kafka"],
        with_source=False,
    )
    # Job C (Different seniority Staff -> MUST NOT merge)
    job_c = _make_job(
        ats_source="remotive",
        external_id="rem-staff-c",
        title="Staff Backend Python Engineer",
        company_name="Datadog Corp.",
        apply_url="https://remotive.com/jobs/c",
        description=f"{LONG_DESC} Staff role.",
        seniority="staff",
        embedding=shared_vec,
        with_source=False,
    )
    # Job D (Different language pt -> MUST NOT merge)
    job_d = _make_job(
        ats_source="gupy",
        external_id="gupy-pt-d",
        title="Senior Backend Python Engineer",
        company_name="Datadog Corp.",
        apply_url="https://datadog.gupy.io/jobs/d",
        description=f"{LONG_DESC} Vaga PT.",
        language="pt",
        embedding=shared_vec,
        with_source=False,
    )

    # Clear normalized keys to verify Pass 1 backfill populates them
    JobPosting.objects.update(
        company_name_normalized="",
        title_normalized="",
        description_fingerprint="",
    )

    # Create tricky child-record conflicts between A and B:
    # 1. Soft-deleted MatchScore on (A, resume_1) + active MatchScore on (B, resume_1) with artifact!
    ms_a_deleted = MatchScore.objects.create(
        job_posting=job_a,
        resume_profile=resume_1,
        cosine_similarity=0.80,
        fit_score=70,
        resume_content_hash=resume_1.content_hash,
        is_routed_winner=False,
    )
    ms_a_deleted.is_deleted = True
    ms_a_deleted.save(update_fields=["is_deleted"])

    ms_b_active = MatchScore.objects.create(
        job_posting=job_b,
        resume_profile=resume_1,
        cosine_similarity=0.95,
        fit_score=91,
        resume_content_hash=resume_1.content_hash,
        is_routed_winner=True,
        alert_sent_at=timezone.now() - timedelta(days=1),
    )
    artifact_b = MatchArtifact.objects.create(
        user=user,
        match_score=ms_b_active,
        kind=MatchArtifactKind.COVER_LETTER,
        resume_content_hash=resume_1.content_hash,
        content_markdown="Tailored letter for Datadog",
    )
    # Active MatchScore on (A, resume_2) with lower fit_score -> winner re-election must keep strictly 1 winner
    ms_a_r2 = MatchScore.objects.create(
        job_posting=job_a,
        resume_profile=resume_2,
        cosine_similarity=0.88,
        fit_score=82,
        resume_content_hash=resume_2.content_hash,
        is_routed_winner=True,
    )

    # 2. ApplicationLead conflict: A is SAVED with note A, B is INTERVIEWING with note B -> INTERVIEWING + combined notes win
    lead_a = ApplicationLead.objects.create(
        user=user,
        job_posting=job_a,
        status=LeadStatus.SAVED.value,
        notes="Initial save note",
    )
    lead_b = ApplicationLead.objects.create(
        user=user,
        job_posting=job_b,
        status=LeadStatus.INTERVIEWING.value,
        notes="Recruiter screen passed",
    )

    # 3. DismissedJob on B -> repointed onto A
    dismissed_b = DismissedJob.objects.create(user=user, job_posting=job_b)

    # Dry-run Pass 1 writes nothing
    out_dry = StringIO()
    call_command("backfill_job_sources", "--dry-run", stdout=out_dry)
    assert JobPostingSource.objects.count() == 0

    # Real Pass 1 + --merge-duplicates
    out_apply = StringIO()
    call_command(
        "backfill_job_sources",
        "--batch-size=2",
        "--merge-duplicates",
        stdout=out_apply,
    )
    assert "merged_duplicates=1" in out_apply.getvalue()

    job_a.refresh_from_db()
    job_b = JobPosting.all_objects.get(pk=job_b.pk)
    job_c.refresh_from_db()
    job_d.refresh_from_db()

    # B merged into A; C (different seniority) and D (different language) untouched
    assert job_a.is_deleted is False
    assert job_b.is_deleted is True
    assert job_b.is_active is False
    assert job_c.is_deleted is False
    assert job_d.is_deleted is False

    # Sources moved cleanly onto A with greenhouse primary
    a_sources = list(JobPostingSource.objects.filter(job_posting=job_a))
    assert len(a_sources) == 2
    primaries = [s for s in a_sources if s.is_primary]
    assert len(primaries) == 1
    assert primaries[0].ats_source == "greenhouse"

    # Non-destructive metadata backfill
    assert job_a.salary_min == 140000
    assert set(job_a.tech_stack) == {"python", "kafka"}

    # MatchScore & MatchArtifact conflict reconciled + strictly 1 routed winner for user on A
    ms_a_r1 = MatchScore.objects.get(job_posting=job_a, resume_profile=resume_1)
    assert ms_a_r1.fit_score == 91
    assert ms_a_r1.alert_sent_at is not None
    artifact_b.refresh_from_db()
    assert artifact_b.match_score_id == ms_a_r1.uuid
    winners = list(
        MatchScore.objects.filter(
            job_posting=job_a,
            resume_profile__user=user,
            is_routed_winner=True,
        )
    )
    assert len(winners) == 1
    assert winners[0].uuid == ms_a_r1.uuid
    ms_a_r2.refresh_from_db()
    assert ms_a_r2.is_routed_winner is False

    # ApplicationLead merged cleanly
    lead_a.refresh_from_db()
    assert lead_a.status == LeadStatus.INTERVIEWING.value
    assert "Initial save note" in lead_a.notes
    assert "Recruiter screen passed" in lead_a.notes
    assert ApplicationLead.all_objects.get(pk=lead_b.pk).is_deleted is True

    # DismissedJob repointed onto A
    dismissed_b.refresh_from_db()
    assert dismissed_b.job_posting_id == job_a.uuid

    # Re-running is 100% idempotent
    out_rerun = StringIO()
    call_command("backfill_job_sources", "--merge-duplicates", stdout=out_rerun)
    assert "updated_jobs=0 created_sources=0" in out_rerun.getvalue()
    assert "merged_duplicates=0" in out_rerun.getvalue()

"""Integration tests for Spec #21: Multi-Resume & Multilingual Auto-Matching."""

from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
import pytest
from rest_framework.test import APIClient

from apps.base.models.user_profile import UserProfile
from apps.jobs.models.jobs import JobPosting
from apps.matching.models.artifacts import MatchArtifactKind
from apps.matching.models.matching import MatchScore
from apps.matching.services.copilot import (
    build_copilot_prompt,
    resolve_copilot_output_language,
)
from apps.resumes.models.resumes import ResumeProfile
from apps.resumes.services.resume_service import ResumeService
from vektryn_contracts import (
    EMBEDDING_DIMENSIONS,
    UNKNOWN_LANGUAGE,
    ATSSource,
    WorkMode,
)

User = get_user_model()

EN_RESUME_TEXT = (
    "Senior Backend Software Engineer with 8 years of experience designing scalable "
    "distributed systems in Python, Django, PostgreSQL, Redis, and Apache Kafka."
)
PT_RESUME_TEXT = (
    "Engenheiro de Software Backend Senior com 8 anos de experiencia desenvolvendo "
    "sistemas distribuidos escalaveis com Python, Django, PostgreSQL e mensageria."
)
DE_JOB_DESC = (
    "Wir suchen einen erfahrenen Backend-Entwickler fuer unsere skalierbaren "
    "Microservices mit Python, Django, PostgreSQL und moderner Cloud-Infrastruktur."
)


def _make_job(
    *,
    external_id: str,
    title: str = "Senior Python Engineer",
    language: str = "en",
    description_clean: str = EN_RESUME_TEXT,
    work_mode: str = WorkMode.REMOTE.value,
) -> JobPosting:
    return JobPosting.objects.create(
        ats_source=ATSSource.GREENHOUSE.value,
        external_id=external_id,
        content_hash=f"{external_id:0<64}"[:64],
        title=title,
        company_name="Acme Corp",
        apply_url=f"https://acme.example/jobs/{external_id}",
        raw_html_gcs_uri=f"gs://bucket/{external_id}.html",
        location_raw="Remote",
        description_clean=description_clean,
        work_mode=work_mode,
        language=language,
        tech_stack=["python", "django"],
        embedding=[0.01] * EMBEDDING_DIMENSIONS,
        is_active=True,
    )


@pytest.mark.django_db
def test_resumes_multi_active_cap_language_validation_autodetect_and_rescore_without_reembed(
    settings, django_capture_on_commit_callbacks
):
    settings.MAX_ACTIVE_RESUMES_PER_USER = 2
    user = User.objects.create_user(username="multi_user", password="Password!2026")
    UserProfile.objects.create(
        user=user,
        gemini_api_key_encrypted="dummy-encrypted",
        gemini_api_key_last4="1234",
    )
    client = APIClient()
    client.force_authenticate(user=user)

    with (
        patch(
            "apps.resumes.services.resume_service.ResumeService.generate_embedding_and_skills",
            return_value=([0.05] * EMBEDDING_DIMENSIONS, ["python", "django"]),
        ) as mock_embed,
        patch(
            "apps.resumes.services.resume_service.publish_rescore_event"
        ) as mock_publish,
    ):
        # 1. Invalid language returns 400
        bad_res = client.post(
            "/api/v1/resumes/",
            {"label": "Bad Lang", "raw_text": EN_RESUME_TEXT, "language": "other"},
            format="json",
        )
        assert bad_res.status_code == 400
        assert "language" in bad_res.data

        # 2. Auto-detect Portuguese when language omitted
        with django_capture_on_commit_callbacks(execute=True):
            pt_res = client.post(
                "/api/v1/resumes/",
                {"label": "Backend PT-BR", "raw_text": PT_RESUME_TEXT},
                format="json",
            )
        assert pt_res.status_code == 201
        assert pt_res.data["language"] == "pt"
        assert pt_res.data["strict_language_match"] is False
        assert pt_res.data["is_active"] is True

        # 3. BCP-47 normalizes ("en-US" -> "en") and sibling stays active
        with django_capture_on_commit_callbacks(execute=True):
            en_res = client.post(
                "/api/v1/resumes/",
                {
                    "label": "Backend EN",
                    "raw_text": EN_RESUME_TEXT,
                    "language": "en-US",
                    "strict_language_match": True,
                },
                format="json",
            )
        assert en_res.status_code == 201
        assert en_res.data["language"] == "en"
        assert en_res.data["strict_language_match"] is True
        assert ResumeProfile.objects.filter(user=user, is_active=True).count() == 2

        # 4. 3rd active profile exceeds MAX_ACTIVE_RESUMES_PER_USER=2 -> 400
        cap_res = client.post(
            "/api/v1/resumes/",
            {"label": "Backend DE", "raw_text": DE_JOB_DESC, "language": "de"},
            format="json",
        )
        assert cap_res.status_code == 400
        assert "is_active" in cap_res.data

        # Inactive 3rd profile is allowed
        paused_res = client.post(
            "/api/v1/resumes/",
            {
                "label": "Backend DE Paused",
                "raw_text": DE_JOB_DESC,
                "language": "de",
                "is_active": False,
            },
            format="json",
        )
        assert paused_res.status_code == 201
        paused_uuid = paused_res.data["uuid"]

        # Activating paused 3rd profile while 2 are active -> 400
        activate_cap_res = client.patch(
            f"/api/v1/resumes/{paused_uuid}/",
            {"is_active": True},
            format="json",
        )
        assert activate_cap_res.status_code == 400
        assert "is_active" in activate_cap_res.data

        # 5. Editing language / strict_language_match publishes jobs.rescore WITHOUT re-embedding
        embed_calls_before = mock_embed.call_count
        mock_publish.reset_mock()
        with django_capture_on_commit_callbacks(execute=True):
            patch_res = client.patch(
                f"/api/v1/resumes/{pt_res.data['uuid']}/",
                {"strict_language_match": True},
                format="json",
            )
        assert patch_res.status_code == 200
        assert patch_res.data["strict_language_match"] is True
        assert mock_embed.call_count == embed_calls_before
        mock_publish.assert_called_once()
        published_event = mock_publish.call_args.args[0]
        assert published_event.force is True


@pytest.mark.django_db
def test_resume_pause_and_soft_delete_reconcile_winners_and_schedule_rescore(
    django_capture_on_commit_callbacks,
):
    user = User.objects.create_user(username="reconcile_user", password="Password!2026")
    UserProfile.objects.create(
        user=user,
        gemini_api_key_encrypted="dummy-enc",
        gemini_api_key_last4="9999",
    )
    client = APIClient()
    client.force_authenticate(user=user)

    pt_profile = ResumeProfile.objects.create(
        user=user,
        label="PT Track",
        raw_text=PT_RESUME_TEXT,
        content_hash=ResumeService.compute_text_hash(PT_RESUME_TEXT),
        language="pt",
        embedding=[0.02] * EMBEDDING_DIMENSIONS,
        is_active=True,
    )
    en_profile = ResumeProfile.objects.create(
        user=user,
        label="EN Track",
        raw_text=EN_RESUME_TEXT,
        content_hash=ResumeService.compute_text_hash(EN_RESUME_TEXT),
        language="en",
        embedding=[0.02] * EMBEDDING_DIMENSIONS,
        is_active=True,
    )
    job = _make_job(external_id="reconcile-job-1", language="pt")
    pt_match = MatchScore.objects.create(
        job_posting=job,
        resume_profile=pt_profile,
        cosine_similarity=0.88,
        fit_score=91,
        resume_content_hash=pt_profile.content_hash,
        is_routed_winner=True,
    )
    en_match = MatchScore.objects.create(
        job_posting=job,
        resume_profile=en_profile,
        cosine_similarity=0.81,
        fit_score=84,
        resume_content_hash=en_profile.content_hash,
        is_routed_winner=False,
    )

    with (
        patch(
            "apps.resumes.services.resume_service.publish_rescore_event"
        ) as mock_publish,
        django_capture_on_commit_callbacks(execute=True),
    ):
        pause_res = client.patch(
            f"/api/v1/resumes/{pt_profile.uuid}/",
            {"is_active": False},
            format="json",
        )
    assert pause_res.status_code == 200
    pt_match.refresh_from_db()
    en_match.refresh_from_db()
    assert pt_match.is_routed_winner is False
    assert en_match.is_routed_winner is True
    mock_publish.assert_called_once()
    assert mock_publish.call_args.args[0].resume_profile_uuid == en_profile.uuid

    # Soft-deleting remaining active profile marks is_active=False and demotes its winner
    del_res = client.delete(f"/api/v1/resumes/{en_profile.uuid}/")
    assert del_res.status_code == 204
    en_profile_db = ResumeProfile.all_objects.get(pk=en_profile.pk)
    assert en_profile_db.is_deleted is True
    assert en_profile_db.is_active is False
    en_match.refresh_from_db()
    assert en_match.is_routed_winner is False


@pytest.mark.django_db
def test_matches_default_winner_scoping_drilldown_language_filter_analytics_leads_and_copilot():
    user = User.objects.create_user(username="radar_multi", password="Password!2026")
    other_user = User.objects.create_user(
        username="other_multi", password="Password!2026"
    )
    client = APIClient()
    client.force_authenticate(user=user)

    en_profile = ResumeProfile.objects.create(
        user=user,
        label="Backend EN",
        raw_text=EN_RESUME_TEXT,
        content_hash="a" * 64,
        language="en",
        min_alert_score=70,
        embedding=[0.02] * EMBEDDING_DIMENSIONS,
        is_active=True,
    )
    pt_profile = ResumeProfile.objects.create(
        user=user,
        label="Backend PT-BR",
        raw_text=PT_RESUME_TEXT,
        content_hash="b" * 64,
        language="pt",
        min_alert_score=70,
        embedding=[0.02] * EMBEDDING_DIMENSIONS,
        is_active=True,
    )
    other_profile = ResumeProfile.objects.create(
        user=other_user,
        label="Other EN",
        raw_text=EN_RESUME_TEXT,
        content_hash="c" * 64,
        language="en",
        is_active=True,
    )

    en_job = _make_job(
        external_id="multi-en-1",
        title="Senior Python Backend",
        language="en",
    )
    pt_job = _make_job(
        external_id="multi-pt-1",
        title="Engenheiro Python Senior",
        language="pt",
        description_clean=PT_RESUME_TEXT,
    )

    # For en_job, BOTH profiles have MatchScore rows, but only en_profile is routed winner
    MatchScore.objects.create(
        job_posting=en_job,
        resume_profile=en_profile,
        cosine_similarity=0.90,
        fit_score=88,
        matched_skills=["python", "django"],
        missing_keywords=["kubernetes"],
        resume_content_hash=en_profile.content_hash,
        is_routed_winner=True,
    )
    MatchScore.objects.create(
        job_posting=en_job,
        resume_profile=pt_profile,
        cosine_similarity=0.82,
        fit_score=75,
        matched_skills=["python"],
        missing_keywords=["kubernetes"],
        resume_content_hash=pt_profile.content_hash,
        is_routed_winner=False,
    )
    pt_winner = MatchScore.objects.create(
        job_posting=pt_job,
        resume_profile=pt_profile,
        cosine_similarity=0.89,
        fit_score=92,
        matched_skills=["python"],
        missing_keywords=["kafka"],
        resume_content_hash=pt_profile.content_hash,
        is_routed_winner=True,
    )

    # 1. Default GET /api/v1/matches/ returns strictly 2 deduplicated winners (not 3!)
    default_res = client.get("/api/v1/matches/")
    assert default_res.status_code == 200
    assert default_res.data["count"] == 2
    assert default_res.data["summary"]["ai_scored_count"] == 2
    assert default_res.data["summary"]["strong_fit_count"] == 2
    assert default_res.data["results"][0]["resume_profile_summary"]["label"] in {
        "Backend EN",
        "Backend PT-BR",
    }
    assert default_res.data["results"][0]["is_routed_winner"] is True

    # 2. Single-profile drill-down includes non-winner historical rows + IDOR 404
    drill_res = client.get(f"/api/v1/matches/?resume_profile={pt_profile.uuid}")
    assert drill_res.status_code == 200
    assert drill_res.data["count"] == 2  # Both pt_job (winner) and en_job (non-winner)

    idor_res = client.get(f"/api/v1/matches/?resume_profile={other_profile.uuid}")
    assert idor_res.status_code == 404

    # 3. Composable ?language= filtering on /api/v1/jobs/ and /api/v1/matches/ + 400 on invalid
    lang_matches = client.get("/api/v1/matches/?language=pt")
    assert lang_matches.status_code == 200
    assert lang_matches.data["count"] == 1
    assert lang_matches.data["results"][0]["job_posting"]["language"] == "pt"

    lang_jobs = client.get("/api/v1/jobs/?language=en,pt")
    assert lang_jobs.status_code == 200
    assert lang_jobs.data["count"] == 2

    assert client.get("/api/v1/matches/?language=other").status_code == 400
    assert client.get("/api/v1/jobs/?language=invalid").status_code == 400

    # 4. SavedFilter persists valid language & rejects invalid language
    sf_ok = client.post(
        "/api/v1/jobs/filters/",
        {"name": "PT Roles", "query_params": {"language": "pt-BR"}},
        format="json",
    )
    assert sf_ok.status_code == 201
    assert sf_ok.data["query_params"]["language"] == "pt"

    sf_bad = client.post(
        "/api/v1/jobs/filters/",
        {"name": "Bad Lang", "query_params": {"language": "other"}},
        format="json",
    )
    assert sf_bad.status_code == 400

    # 5. Personal Analytics avoids double-counting en_job when unfiltered
    analytics_res = client.get("/api/v1/analytics/personal/?days=all")
    assert analytics_res.status_code == 200
    assert analytics_res.data["skill_gaps"]["high_fit_match_count"] == 2
    k8s_item = next(
        item
        for item in analytics_res.data["skill_gaps"]["missing_keywords"]
        if item["skill"] == "kubernetes"
    )
    assert k8s_item["match_count"] == 1

    # 6. POST /api/v1/leads/ without resume_profile auto-attaches winning resume_profile
    lead_res = client.post(
        "/api/v1/leads/",
        {"job_posting": str(pt_job.uuid)},
        format="json",
    )
    assert lead_res.status_code == 201
    assert str(lead_res.data["resume_profile"]) == str(pt_profile.uuid)
    assert lead_res.data["resume_profile_summary"] == {
        "uuid": str(pt_profile.uuid),
        "label": "Backend PT-BR",
        "language": "pt",
    }
    assert lead_res.data["language"] == "pt"

    # PATCH /api/v1/leads/{uuid}/ allows switching linked resume_profile
    switch_res = client.patch(
        f"/api/v1/leads/{lead_res.data['uuid']}/",
        {"resume_profile": str(en_profile.uuid)},
        format="json",
    )
    assert switch_res.status_code == 200
    assert switch_res.data["resume_profile_summary"]["label"] == "Backend EN"

    # 7. Copilot dynamically aligns output language to job.language -> resume.language fallback
    assert resolve_copilot_output_language(pt_winner) == "pt"
    prompt_pt = build_copilot_prompt(
        match_score=pt_winner,
        kind=MatchArtifactKind.COVER_LETTER,
    )
    assert "Target Output Language (ISO 639-1): pt" in prompt_pt
    assert "Language (ISO 639-1): pt" in prompt_pt

    unknown_job = _make_job(external_id="multi-unk-1", language=UNKNOWN_LANGUAGE)
    unk_match = MatchScore.objects.create(
        job_posting=unknown_job,
        resume_profile=pt_profile,
        cosine_similarity=0.80,
        fit_score=80,
        resume_content_hash=pt_profile.content_hash,
        is_routed_winner=True,
    )
    assert resolve_copilot_output_language(unk_match) == "pt"


@pytest.mark.django_db
def test_backfill_languages_command_is_idempotent_and_respects_dry_run():
    user = User.objects.create_user(username="backfill_user", password="Password!2026")
    job_de = _make_job(
        external_id="bf-de-1",
        title="Backend Entwickler",
        language=UNKNOWN_LANGUAGE,
        description_clean=DE_JOB_DESC,
    )
    job_short = _make_job(
        external_id="bf-short-1",
        title="Dev",
        language=UNKNOWN_LANGUAGE,
        description_clean="Short text",
    )
    resume_pt = ResumeProfile.objects.create(
        user=user,
        label="Backfill PT",
        raw_text=PT_RESUME_TEXT,
        content_hash="f" * 64,
        language=UNKNOWN_LANGUAGE,
    )

    out_dry = StringIO()
    call_command("backfill_languages", "--dry-run", stdout=out_dry)
    assert "[DRY-RUN] JobPosting: scanned=2 updated=1" in out_dry.getvalue()
    assert "[DRY-RUN] ResumeProfile: scanned=1 updated=1" in out_dry.getvalue()
    job_de.refresh_from_db()
    resume_pt.refresh_from_db()
    assert job_de.language == UNKNOWN_LANGUAGE
    assert resume_pt.language == UNKNOWN_LANGUAGE

    out_apply = StringIO()
    call_command("backfill_languages", "--batch-size=1", stdout=out_apply)
    assert "[APPLIED] JobPosting: scanned=2 updated=1" in out_apply.getvalue()
    assert "[APPLIED] ResumeProfile: scanned=1 updated=1" in out_apply.getvalue()
    job_de.refresh_from_db()
    job_short.refresh_from_db()
    resume_pt.refresh_from_db()
    assert job_de.language == "de"
    assert job_short.language == UNKNOWN_LANGUAGE
    assert resume_pt.language == "pt"

    # Re-running is idempotent (0 further updates)
    out_rerun = StringIO()
    call_command("backfill_languages", stdout=out_rerun)
    assert "updated=0" in out_rerun.getvalue()

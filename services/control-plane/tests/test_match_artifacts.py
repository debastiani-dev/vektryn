from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone
from google.genai import errors as genai_errors
import pytest
from rest_framework.test import APIClient

from apps.base.models.user_profile import get_or_create_user_profile
from apps.jobs.models.jobs import JobPosting
from apps.jobs.models.triage import DismissedJob
from apps.matching.models.artifacts import MatchArtifact, MatchArtifactKind
from apps.matching.models.matching import MatchScore
from apps.matching.services.copilot import (
    CopilotRateLimitError,
    build_copilot_prompt,
    enforce_copilot_rate_limit,
    get_or_generate_match_artifact,
)
from apps.resumes.models.resumes import ResumeProfile
from vektryn_contracts import encrypt_api_key
from vektryn_contracts.enums import ATSSource, ContractType, SeniorityLevel

User = get_user_model()


def _create_match_fixture(
    *,
    username: str,
    email: str,
    external_id: str,
    content_hash: str = "hash-v1",
    fit_score: int | None = 88,
    is_active: bool = True,
) -> tuple[object, ResumeProfile, JobPosting, MatchScore]:
    user = User.objects.create_user(
        username=username,
        email=email,
        password="test-password-123",
    )
    resume = ResumeProfile.objects.create(
        user=user,
        label="Staff Backend",
        raw_text="Senior Python engineer with 8 years building Django, PostgreSQL, and Kafka pipelines.",
        content_hash=content_hash,
        extracted_skills=["python", "django", "postgresql", "kafka"],
    )
    job = JobPosting.objects.create(
        ats_source=ATSSource.GREENHOUSE,
        external_id=external_id,
        content_hash=f"job-hash-{external_id}",
        title="Staff Backend Engineer",
        company_name="Acme Cloud",
        apply_url=f"https://boards.greenhouse.io/acme/jobs/{external_id}",
        raw_html_gcs_uri=f"gs://bucket/{external_id}.html",
        location_raw="Remote - Americas",
        description_clean="Build resilient Python and Kafka streaming services for cloud telemetry.",
        seniority=SeniorityLevel.STAFF,
        contract_type=ContractType.PJ,
        tech_stack=["python", "kafka", "terraform"],
        is_active=is_active,
    )
    match = MatchScore.objects.create(
        job_posting=job,
        resume_profile=resume,
        cosine_similarity=0.87,
        fit_score=fit_score,
        matched_skills=["python", "kafka"] if fit_score is not None else [],
        missing_keywords=["terraform"] if fit_score is not None else [],
        talking_points=(
            ["Highlight Kafka partitioning throughput wins."]
            if fit_score is not None
            else []
        ),
        gap_summary=(
            "Strong backend match with minor IaC gap." if fit_score is not None else ""
        ),
        fit_highlights=(
            ["Deep Python & Kafka production alignment."]
            if fit_score is not None
            else []
        ),
        watchout_note=(
            "Terraform not explicitly listed on resume."
            if fit_score is not None
            else ""
        ),
        resume_content_hash=content_hash,
        scoring_model="gemini-4-hydrogen" if fit_score is not None else "",
    )
    return user, resume, job, match


@pytest.mark.django_db
def test_list_artifacts_empty_stale_and_idor_scoping():
    user_a, resume_a, job_a, match_a = _create_match_fixture(
        username="copilot_a",
        email="copilot_a@example.com",
        external_id="gh-copilot-1",
    )
    user_b, _, _, _ = _create_match_fixture(
        username="copilot_b",
        email="copilot_b@example.com",
        external_id="gh-copilot-2",
    )

    client_a = APIClient()
    client_a.force_authenticate(user=user_a)
    client_b = APIClient()
    client_b.force_authenticate(user=user_b)

    url = f"/api/v1/matches/{match_a.uuid}/artifacts/"
    empty_res = client_a.get(url)
    assert empty_res.status_code == 200
    assert empty_res.data == {"results": []}

    artifact = MatchArtifact.objects.create(
        user=user_a,
        match_score=match_a,
        kind=MatchArtifactKind.TAILORED_BULLETS,
        resume_content_hash=resume_a.content_hash,
        content_markdown="## Tailored Resume Bullets\n- Built Kafka pipelines.",
        model_name="gemini-4-hydrogen",
    )

    # Works even if the role was dismissed or archived by the owner
    DismissedJob.objects.create(user=user_a, job_posting=job_a)
    job_a.is_active = False
    job_a.save(update_fields=["is_active"])

    list_res = client_a.get(url)
    assert list_res.status_code == 200
    assert len(list_res.data["results"]) == 1
    assert list_res.data["results"][0]["uuid"] == str(artifact.uuid)
    assert list_res.data["results"][0]["is_stale"] is False

    # Updating ResumeProfile.content_hash flips is_stale to True
    resume_a.content_hash = "hash-v2"
    resume_a.save(update_fields=["content_hash"])

    stale_res = client_a.get(url)
    assert stale_res.status_code == 200
    assert stale_res.data["results"][0]["is_stale"] is True

    # Cross-user GET and POST must return 404
    assert client_b.get(url).status_code == 404
    assert (
        client_b.post(
            url,
            {"kind": MatchArtifactKind.TAILORED_BULLETS},
            format="json",
        ).status_code
        == 404
    )


@pytest.mark.django_db
def test_generate_cache_hit_regenerate_and_custom_guidance(settings):
    settings.REDIS_URL = ""
    user, _, _, match = _create_match_fixture(
        username="copilot_gen",
        email="copilot_gen@example.com",
        external_id="gh-copilot-3",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    url = f"/api/v1/matches/{match.uuid}/artifacts/"

    with (
        patch(
            "apps.matching.services.copilot.invoke_copilot_gemini",
            return_value=("## Cover Letter\nInitial draft.", "gemini-4-hydrogen"),
        ) as mock_gemini,
        patch(
            "apps.matching.services.copilot.enforce_copilot_rate_limit"
        ) as mock_rate_limit,
    ):
        # 1. Cache miss -> invokes Gemini and returns 201 Created
        res1 = client.post(
            url,
            {"kind": MatchArtifactKind.COVER_LETTER},
            format="json",
        )
        assert res1.status_code == 201
        assert res1.data["cached"] is False
        assert res1.data["is_stale"] is False
        assert res1.data["content_markdown"] == "## Cover Letter\nInitial draft."
        assert res1.data["model_name"] == "gemini-4-hydrogen"
        assert mock_gemini.call_count == 1
        assert mock_rate_limit.call_count == 1
        artifact_uuid = res1.data["uuid"]

        # 2. Repeat default request -> PostgreSQL cache hit (200), 0 Gemini & 0 rate-limit calls
        res2 = client.post(
            url,
            {"kind": MatchArtifactKind.COVER_LETTER},
            format="json",
        )
        assert res2.status_code == 200
        assert res2.data["cached"] is True
        assert res2.data["uuid"] == artifact_uuid
        assert mock_gemini.call_count == 1
        assert mock_rate_limit.call_count == 1

        # 3. regenerate=True -> invokes Gemini and updates existing row in place
        mock_gemini.return_value = (
            "## Cover Letter\nRegenerated draft.",
            "gemini-4-hydrogen",
        )
        res3 = client.post(
            url,
            {"kind": MatchArtifactKind.COVER_LETTER, "regenerate": True},
            format="json",
        )
        assert res3.status_code == 200
        assert res3.data["cached"] is False
        assert res3.data["uuid"] == artifact_uuid
        assert res3.data["content_markdown"] == "## Cover Letter\nRegenerated draft."
        assert mock_gemini.call_count == 2
        assert mock_rate_limit.call_count == 2

        # 4. Custom tone/guidance bypasses cache even with regenerate=False
        mock_gemini.return_value = (
            "## Cover Letter\nExecutive Kafka focus.",
            "gemini-4-hydrogen",
        )
        res4 = client.post(
            url,
            {
                "kind": MatchArtifactKind.COVER_LETTER,
                "tone": "executive",
                "guidance": "Highlight Kafka reliability metrics",
            },
            format="json",
        )
        assert res4.status_code == 200
        assert res4.data["cached"] is False
        assert res4.data["uuid"] == artifact_uuid
        assert mock_gemini.call_count == 3
        prompt_sent = mock_gemini.call_args.kwargs["prompt"]
        assert "Tone Preference (executive)" in prompt_sent
        assert "Highlight Kafka reliability metrics" in prompt_sent
        assert MatchArtifact.objects.filter(match_score=match).count() == 1


@pytest.mark.django_db
def test_resume_hash_change_soft_deletes_stale_and_updates_modified_at(settings):
    settings.REDIS_URL = ""
    user, resume, _, match = _create_match_fixture(
        username="copilot_hash",
        email="copilot_hash@example.com",
        external_id="gh-copilot-4",
        content_hash="hash-v1",
    )
    old_time = timezone.now() - timedelta(hours=2)
    stale_row = MatchArtifact.objects.create(
        user=user,
        match_score=match,
        kind=MatchArtifactKind.RECRUITER_OUTREACH,
        resume_content_hash="hash-v1",
        content_markdown="Old outreach draft.",
        model_name="gemini-4-hydrogen",
    )
    MatchArtifact.all_objects.filter(pk=stale_row.pk).update(modified_at=old_time)

    # Candidate edits their resume -> new content_hash
    resume.content_hash = "hash-v2"
    resume.save(update_fields=["content_hash"])

    client = APIClient()
    client.force_authenticate(user=user)
    url = f"/api/v1/matches/{match.uuid}/artifacts/"

    with patch(
        "apps.matching.services.copilot.invoke_copilot_gemini",
        return_value=("## LinkedIn / Short DM\nFresh outreach.", "gemini-4-hydrogen"),
    ) as mock_gemini:
        res = client.post(
            url,
            {"kind": MatchArtifactKind.RECRUITER_OUTREACH},
            format="json",
        )

    assert res.status_code == 201
    assert res.data["cached"] is False
    assert res.data["is_stale"] is False
    assert res.data["resume_content_hash"] == "hash-v2"
    assert mock_gemini.call_count == 1

    # Superseded stale row was soft-deleted and had modified_at updated explicitly
    stale_refreshed = MatchArtifact.all_objects.get(pk=stale_row.pk)
    assert stale_refreshed.is_deleted is True
    assert stale_refreshed.modified_at > old_time

    # GET returns only the single active fresh artifact
    list_res = client.get(url)
    assert list_res.status_code == 200
    assert len(list_res.data["results"]) == 1
    assert list_res.data["results"][0]["resume_content_hash"] == "hash-v2"


@pytest.mark.django_db
def test_unscored_stage1_match_prompt_handles_none_fit_score_cleanly():
    _, _, _, match = _create_match_fixture(
        username="copilot_unscored",
        email="copilot_unscored@example.com",
        external_id="gh-copilot-5",
        fit_score=None,
    )
    prompt = build_copilot_prompt(
        match_score=match,
        kind=MatchArtifactKind.INTERVIEW_QUESTIONS,
    )
    assert "None%" not in prompt
    assert "Not AI-scored yet (Stage 1 vector match only)" in prompt
    assert "Tech Stack: python, kafka, terraform" in prompt

    ask_prompt = build_copilot_prompt(
        match_score=match,
        kind=MatchArtifactKind.QUESTIONS_TO_ASK,
    )
    assert "## Questions to Ask the Interviewer" in ask_prompt
    assert "What to listen for" in ask_prompt


@pytest.mark.django_db
def test_rate_limit_429_and_redis_ttl_recovery(settings):
    settings.REDIS_URL = "redis://localhost:6379/0"
    settings.COPILOT_RATE_LIMIT_MAX_REQUESTS = 2
    settings.COPILOT_RATE_LIMIT_WINDOW_SECONDS = 120

    # Unit test TTL < 0 recovery in enforce_copilot_rate_limit
    fake_redis = MagicMock()
    fake_redis.incr.return_value = 3
    fake_redis.ttl.return_value = -1

    with patch(
        "apps.matching.services.copilot.redis.Redis.from_url", return_value=fake_redis
    ):
        with pytest.raises(CopilotRateLimitError) as exc_info:
            enforce_copilot_rate_limit(42)
    assert exc_info.value.retry_after_seconds == 120
    fake_redis.expire.assert_called_once_with("vektryn:copilot:rl:42", 120)

    # End-to-end API 429 response + Retry-After header
    user, _, _, match = _create_match_fixture(
        username="copilot_rl",
        email="copilot_rl@example.com",
        external_id="gh-copilot-6",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    url = f"/api/v1/matches/{match.uuid}/artifacts/"

    with patch(
        "apps.matching.services.copilot.enforce_copilot_rate_limit",
        side_effect=CopilotRateLimitError(retry_after_seconds=47),
    ):
        res = client.post(
            url,
            {"kind": MatchArtifactKind.TAILORED_BULLETS},
            format="json",
        )
    assert res.status_code == 429
    assert res["Retry-After"] == "47"
    assert res.data["retry_after_seconds"] == 47


@pytest.mark.django_db
def test_unavailable_503_and_fallback_model_and_validation(settings):
    settings.REDIS_URL = ""
    fernet_key = Fernet.generate_key().decode("utf-8")
    settings.BYOK_ENCRYPTION_KEY = fernet_key

    user, _, _, match = _create_match_fixture(
        username="copilot_503",
        email="copilot_503@example.com",
        external_id="gh-copilot-7",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    url = f"/api/v1/matches/{match.uuid}/artifacts/"

    # Missing user BYOK key -> 400 byok_missing
    res_missing = client.post(
        url,
        {"kind": MatchArtifactKind.TAILORED_BULLETS},
        format="json",
    )
    assert res_missing.status_code == 400
    assert res_missing.data["code"] == "byok_missing"

    # Validation errors -> 400
    assert client.post(url, {"kind": "unknown_kind"}, format="json").status_code == 400
    assert (
        client.post(
            url,
            {"kind": MatchArtifactKind.COVER_LETTER, "tone": "pirate"},
            format="json",
        ).status_code
        == 400
    )
    assert (
        client.post(
            url,
            {"kind": MatchArtifactKind.COVER_LETTER, "guidance": "x" * 301},
            format="json",
        ).status_code
        == 400
    )

    # Configure user's BYOK key; primary transient 503 cascades cleanly to gemini-3.8-flash
    profile = get_or_create_user_profile(user)
    profile.gemini_api_key_encrypted = encrypt_api_key(
        "AQ.Ab8RN6-ValidCopilotTestKey123456", fernet_key
    )
    profile.gemini_api_key_last4 = "3456"
    profile.save(update_fields=["gemini_api_key_encrypted", "gemini_api_key_last4"])

    fake_client = MagicMock()
    calls: list[str] = []

    def _side_effect(*, model, contents, config):
        calls.append(model)
        if model == "gemini-4-hydrogen":
            raise genai_errors.APIError(
                503,
                {"error": {"message": "Overloaded", "status": "UNAVAILABLE"}},
                None,
            )
        return SimpleNamespace(text="## Tailored Resume Bullets\n- Fallback bullet.")

    fake_client.models.generate_content.side_effect = _side_effect

    with (
        patch("apps.base.services.byok.time.sleep"),
        patch(
            "apps.base.services.byok.genai.Client",
            return_value=fake_client,
        ),
    ):
        res_fb = client.post(
            url,
            {"kind": MatchArtifactKind.TAILORED_BULLETS},
            format="json",
        )

    assert res_fb.status_code == 201
    assert res_fb.data["model_name"] == "gemini-3.8-flash"
    assert calls == [
        "gemini-4-hydrogen",
        "gemini-4-hydrogen",
        "gemini-3.8-flash",
    ]


@pytest.mark.django_db
def test_persist_artifact_handles_concurrent_integrity_error_savepoint(settings):
    settings.REDIS_URL = ""
    user, resume, _, match = _create_match_fixture(
        username="copilot_race",
        email="copilot_race@example.com",
        external_id="gh-copilot-8",
    )
    existing = MatchArtifact.objects.create(
        user=user,
        match_score=match,
        kind=MatchArtifactKind.TAILORED_BULLETS,
        resume_content_hash=resume.content_hash,
        content_markdown="Original concurrent draft.",
        model_name="gemini-4-hydrogen",
    )

    # Simulate a race where the initial lookup missed the row, then create() hits IntegrityError
    original_filter = MatchArtifact.objects.filter

    def _race_filter(*args, **kwargs):
        qs = original_filter(*args, **kwargs)
        if "resume_content_hash" in kwargs:
            empty = MagicMock()
            empty.first.return_value = None
            return empty
        return qs

    with (
        patch(
            "apps.matching.services.copilot.invoke_copilot_gemini",
            return_value=("Updated after race.", "gemini-4-hydrogen"),
        ),
        patch.object(MatchArtifact.objects, "filter", side_effect=_race_filter),
        patch.object(
            MatchArtifact.objects,
            "create",
            side_effect=IntegrityError("duplicate key"),
        ),
    ):
        result = get_or_generate_match_artifact(
            user=user,
            match_score=match,
            kind=MatchArtifactKind.TAILORED_BULLETS,
            regenerate=True,
        )

    assert result.cached is False
    assert result.created is False
    assert result.artifact.pk == existing.pk
    existing.refresh_from_db()
    assert existing.content_markdown == "Updated after race."

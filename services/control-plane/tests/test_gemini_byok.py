"""End-to-end tests for Feature Spec #18 BYOK Gemini migration in control-plane."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from google.genai import errors as genai_errors
from google.genai import types
import pytest
from rest_framework.test import APIClient

from apps.base.models.notification import Notification
from apps.base.models.user_profile import UserProfile, get_or_create_user_profile
from apps.jobs.models.jobs import JobPosting
from apps.jobs.services import hybrid_search
from apps.matching.models.artifacts import MatchArtifactKind
from apps.matching.models.matching import MatchScore
from apps.resumes.models.resumes import ResumeProfile
from config.telemetry import before_send
from vektryn_contracts import (
    EMBEDDING_DIMENSIONS,
    NotificationKind,
    all_user_gemini_state_keys,
    decrypt_api_key,
    encrypt_api_key,
)
from vektryn_contracts.enums import ATSSource, ContractType, SeniorityLevel

User = get_user_model()


def _set_user_key(user, plaintext_key: str, fernet_key: str) -> UserProfile:
    profile = get_or_create_user_profile(user)
    profile.gemini_api_key_encrypted = encrypt_api_key(plaintext_key, fernet_key)
    profile.gemini_api_key_last4 = plaintext_key[-4:]
    profile.save(update_fields=["gemini_api_key_encrypted", "gemini_api_key_last4"])
    return profile


@pytest.mark.django_db
def test_self_profile_byok_save_normalize_remove_and_missing_encryption_key(settings):
    fernet_key = Fernet.generate_key().decode("utf-8")
    settings.BYOK_ENCRYPTION_KEY = ""
    settings.REDIS_URL = ""

    user = User.objects.create_user(username="byok_owner", password="pw")
    client = APIClient()
    client.force_authenticate(user=user)

    # Fail-safe 503 when BYOK_ENCRYPTION_KEY is missing (never stores plaintext)
    res_503 = client.patch(
        "/api/v1/auth/profile/",
        {"gemini_api_key": "AQ.Ab8RN6-ValidUserApiKey1234567890"},
        format="json",
    )
    assert res_503.status_code == 503
    assert res_503.json()["code"] == "byok_unavailable"
    assert (
        not UserProfile.objects.filter(user=user)
        .exclude(gemini_api_key_encrypted="")
        .exists()
    )

    # Enable BYOK_ENCRYPTION_KEY and test whitespace/quote stripping + Redis clear
    settings.BYOK_ENCRYPTION_KEY = fernet_key
    fake_redis = MagicMock()
    with patch("apps.base.services.byok._get_redis_client", return_value=fake_redis):
        res_save = client.patch(
            "/api/v1/auth/profile/",
            {
                "gemini_api_key": '  "AQ.Ab8RN6-ValidUserApiKey1234567890" \n',
                "preferred_gemini_model": "gemini-4-argon",
                "allow_model_fallback": False,
            },
            format="json",
        )
    assert res_save.status_code == 200
    body = res_save.json()
    assert body["has_gemini_api_key"] is True
    assert body["gemini_api_key_last4"] == "7890"
    assert body["preferred_gemini_model"] == "gemini-4-argon"
    assert body["allow_model_fallback"] is False
    assert "gemini_api_key" not in body
    assert "gemini_api_key_encrypted" not in body
    fake_redis.delete.assert_called_once_with(*all_user_gemini_state_keys(user.pk))

    profile = UserProfile.objects.get(user=user)
    assert (
        decrypt_api_key(profile.gemini_api_key_encrypted, fernet_key)
        == "AQ.Ab8RN6-ValidUserApiKey1234567890"
    )

    # Rejects internal whitespace and too-short keys
    assert (
        client.patch(
            "/api/v1/auth/profile/",
            {"gemini_api_key": "AQ.bad key with spaces 1234567890"},
            format="json",
        ).status_code
        == 400
    )
    assert (
        client.patch(
            "/api/v1/auth/profile/",
            {"gemini_api_key": "short"},
            format="json",
        ).status_code
        == 400
    )

    # Removing key via blank string clears encrypted value & last4
    with patch("apps.base.services.byok._get_redis_client", return_value=fake_redis):
        res_clear = client.patch(
            "/api/v1/auth/profile/",
            {"gemini_api_key": ""},
            format="json",
        )
    assert res_clear.status_code == 200
    assert res_clear.json()["has_gemini_api_key"] is False
    assert res_clear.json()["gemini_api_key_last4"] == ""
    profile.refresh_from_db()
    assert profile.gemini_api_key_encrypted == ""


@pytest.mark.django_db
def test_staff_users_endpoint_never_exposes_or_mutates_byok_fields(settings):
    fernet_key = Fernet.generate_key().decode("utf-8")
    settings.BYOK_ENCRYPTION_KEY = fernet_key
    staff = User.objects.create_user(
        username="staff_admin", password="pw", is_staff=True
    )
    target = User.objects.create_user(username="byok_member", password="pw")
    _set_user_key(target, "AQ.Ab8RN6-MemberSecretKey123456789", fernet_key)

    client = APIClient()
    client.force_authenticate(user=staff)

    forbidden = {
        "has_gemini_api_key",
        "gemini_api_key",
        "gemini_api_key_last4",
        "gemini_api_key_encrypted",
        "preferred_gemini_model",
        "allow_model_fallback",
    }

    list_res = client.get(f"/api/v1/users/?search={target.username}")
    assert list_res.status_code == 200
    row = list_res.json()["results"][0]
    assert forbidden.isdisjoint(row.keys())
    assert forbidden.isdisjoint(row["profile"].keys())

    detail_res = client.get(f"/api/v1/users/{target.pk}/")
    assert detail_res.status_code == 200
    assert forbidden.isdisjoint(detail_res.json().keys())
    assert forbidden.isdisjoint(detail_res.json()["profile"].keys())

    # Attempting to overwrite BYOK fields via staff PATCH must be ignored
    patch_res = client.patch(
        f"/api/v1/users/{target.pk}/",
        {
            "profile": {
                "display_name": "Updated Name",
                "gemini_api_key": "",
                "preferred_gemini_model": "gemini-3.5-flash-lite",
            }
        },
        format="json",
    )
    assert patch_res.status_code == 200
    target_profile = UserProfile.objects.get(user=target)
    assert target_profile.display_name == "Updated Name"
    assert target_profile.has_gemini_api_key is True
    assert target_profile.preferred_gemini_model == "auto"


@pytest.mark.django_db
def test_key_save_embeds_bounded_pending_resumes_and_reports_remaining(settings):
    fernet_key = Fernet.generate_key().decode("utf-8")
    settings.BYOK_ENCRYPTION_KEY = fernet_key
    settings.REDIS_URL = ""

    user = User.objects.create_user(username="pending_embed_user", password="pw")
    for idx in range(4):
        ResumeProfile.objects.create(
            user=user,
            label=f"Resume {idx}",
            raw_text=f"Python Django PostgreSQL resume {idx}",
            content_hash=f"{idx}" * 64,
            embedding=None,
            is_active=True,
        )

    fake_embed_res = SimpleNamespace(
        embeddings=[SimpleNamespace(values=[0.01] * EMBEDDING_DIMENSIONS)]
    )
    fake_skill_res = SimpleNamespace(text='{"skills": ["python", "django"]}')
    fake_client = MagicMock()
    fake_client.models.embed_content.return_value = fake_embed_res
    fake_client.models.generate_content.return_value = fake_skill_res

    client = APIClient()
    client.force_authenticate(user=user)
    with (
        patch("apps.base.services.byok.genai.Client", return_value=fake_client),
        patch(
            "apps.resumes.services.resume_service.publish_rescore_event",
            return_value=True,
        ) as mock_publish,
    ):
        res = client.patch(
            "/api/v1/auth/profile/",
            {"gemini_api_key": "AQ.Ab8RN6-PendingEmbedUserKey123456"},
            format="json",
        )

    assert res.status_code == 200
    body = res.json()
    assert body["pending_resumes_embedded"] == 3
    assert body["pending_resumes_remaining"] == 1
    assert body["embedding_warning"]
    assert mock_publish.call_count == 3
    assert ResumeProfile.objects.filter(user=user, embedding__isnull=False).count() == 3


@pytest.mark.django_db
def test_hybrid_search_keyless_never_reads_redis_and_isolates_user_cache(settings):
    fernet_key = Fernet.generate_key().decode("utf-8")
    settings.BYOK_ENCRYPTION_KEY = fernet_key
    settings.REDIS_URL = ""

    keyless_user = User.objects.create_user(username="keyless_search", password="pw")
    staff_keyless = User.objects.create_user(
        username="staff_keyless", password="pw", is_staff=True, is_superuser=True
    )
    fake_redis = MagicMock()

    with patch(
        "apps.jobs.services.hybrid_search._get_redis_client", return_value=fake_redis
    ):
        assert (
            hybrid_search.embed_search_query("python kafka", user=keyless_user) is None
        )
        assert (
            hybrid_search.embed_search_query("python kafka", user=staff_keyless) is None
        )
    fake_redis.get.assert_not_called()


@pytest.mark.django_db
def test_copilot_error_classification_thinking_config_and_notifications(settings):
    fernet_key = Fernet.generate_key().decode("utf-8")
    settings.BYOK_ENCRYPTION_KEY = fernet_key
    settings.REDIS_URL = ""

    user = User.objects.create_user(username="copilot_byok_err", password="pw")
    profile = _set_user_key(user, "AQ.Ab8RN6-CopilotErrorTestKey12345", fernet_key)
    profile.preferred_gemini_model = "gemini-4-carbon"
    profile.allow_model_fallback = True
    profile.save(update_fields=["preferred_gemini_model", "allow_model_fallback"])

    resume = ResumeProfile.objects.create(
        user=user,
        label="Staff",
        raw_text="Python Kafka engineer",
        content_hash="a" * 64,
        extracted_skills=["python", "kafka"],
    )
    job = JobPosting.objects.create(
        ats_source=ATSSource.GREENHOUSE,
        external_id="byok-copilot-job",
        content_hash="b" * 64,
        title="Staff Backend Engineer",
        company_name="Acme",
        apply_url="https://example.com/jobs/1",
        raw_html_gcs_uri="gs://bucket/1.html",
        location_raw="Remote",
        description_clean="Python Kafka distributed systems",
        seniority=SeniorityLevel.STAFF,
        contract_type=ContractType.PJ,
        tech_stack=["python", "kafka"],
        is_active=True,
    )
    match = MatchScore.objects.create(
        job_posting=job,
        resume_profile=resume,
        cosine_similarity=0.85,
        fit_score=90,
        resume_content_hash=resume.content_hash,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    url = f"/api/v1/matches/{match.uuid}/artifacts/"

    # 1. HTTP 400 API_KEY_INVALID -> 403 byok_invalid + ai_key_invalid notification
    bad_key_client = MagicMock()
    bad_key_client.models.generate_content.side_effect = genai_errors.APIError(
        400,
        {
            "error": {
                "code": 400,
                "status": "INVALID_ARGUMENT",
                "message": "API key not valid. Please pass a valid API key.",
                "details": [{"reason": "API_KEY_INVALID"}],
            }
        },
        None,
    )
    with patch("apps.base.services.byok.genai.Client", return_value=bad_key_client):
        res_invalid = client.post(
            url, {"kind": MatchArtifactKind.COVER_LETTER}, format="json"
        )
    assert res_invalid.status_code == 403
    assert res_invalid.json()["code"] == "byok_invalid"
    assert bad_key_client.models.generate_content.call_count == 1
    assert Notification.objects.filter(
        user=user, kind=NotificationKind.AI_KEY_INVALID
    ).exists()

    # 2. HTTP 429 "prepayment credits are depleted" -> short-circuits as PAYMENT_REQUIRED -> 429 + ai_quota_exhausted
    Notification.objects.filter(user=user).delete()
    depleted_client = MagicMock()
    depleted_client.models.generate_content.side_effect = genai_errors.APIError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "Prepayment credits are depleted for this billing account.",
            }
        },
        None,
    )
    with patch("apps.base.services.byok.genai.Client", return_value=depleted_client):
        res_depleted = client.post(
            url, {"kind": MatchArtifactKind.COVER_LETTER}, format="json"
        )
    assert res_depleted.status_code == 429
    assert res_depleted.json()["code"] == "byok_quota_exhausted"
    assert res_depleted.json()["payment_required"] is True
    assert depleted_client.models.generate_content.call_count == 1
    notif = Notification.objects.get(
        user=user, kind=NotificationKind.AI_QUOTA_EXHAUSTED
    )
    assert "credits" in notif.title.lower()

    # 3. Paid-tier 403 cascades down to free model with ThinkingConfig and no temperature/max_output_tokens
    seen_configs: list[tuple[str, types.GenerateContentConfig]] = []

    def _cascade_side_effect(*, model, contents, config):
        seen_configs.append((model, config))
        if model in ("gemini-4-carbon", "gemini-4-neon", "gemini-4-argon"):
            raise genai_errors.APIError(
                403,
                {
                    "error": {
                        "code": 403,
                        "status": "PERMISSION_DENIED",
                        "message": "Model is not available on the free tier.",
                    }
                },
                None,
            )
        return SimpleNamespace(text="## Cover Letter\nGenerated via hydrogen.")

    cascade_client = MagicMock()
    cascade_client.models.generate_content.side_effect = _cascade_side_effect
    with patch("apps.base.services.byok.genai.Client", return_value=cascade_client):
        res_ok = client.post(
            url, {"kind": MatchArtifactKind.COVER_LETTER}, format="json"
        )

    assert res_ok.status_code == 201
    assert res_ok.json()["model_name"] == "gemini-4-hydrogen"
    assert [m for m, _ in seen_configs] == [
        "gemini-4-carbon",
        "gemini-4-neon",
        "gemini-4-argon",
        "gemini-4-hydrogen",
    ]
    for _model, cfg in seen_configs:
        assert cfg.thinking_config is not None
        assert cfg.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM
        assert cfg.temperature is None
        assert cfg.max_output_tokens is None


def test_control_plane_telemetry_scrubs_aiza_and_aq_everywhere():
    aiza = "AIzaSyD1234567890abcdefghijklmnop"
    aq = "AQ.Ab8RN6L_sample.token-1234567890abcdef"
    event = {
        "message": f"Failed request using {aq}",
        "request": {
            "url": f"https://generativelanguage.googleapis.com/v1?key={aiza}",
            "headers": {"X-Goog-Api-Key": aq, "Accept": "application/json"},
            "data": {"gemini_api_key": aq, "display_name": "Rafa"},
        },
        "exception": {
            "values": [{"type": "ClientError", "value": f"Invalid key {aq} and {aiza}"}]
        },
        "logentry": {
            "message": f"Error with {aq}",
            "params": [aiza],
        },
        "breadcrumbs": {
            "values": [
                {
                    "message": f"Called Gemini with {aq}",
                    "data": {"url": f"https://example.com?key={aiza}"},
                }
            ]
        },
    }
    scrubbed = before_send(event, {})
    assert scrubbed is not None
    serialized = str(scrubbed)
    assert aiza not in serialized
    assert aq not in serialized
    assert scrubbed["request"]["headers"]["X-Goog-Api-Key"] == "[Filtered]"
    assert scrubbed["request"]["data"]["gemini_api_key"] == "[Filtered]"
    assert scrubbed["request"]["data"]["display_name"] == "Rafa"


@pytest.mark.django_db
def test_copilot_504_deadline_exceeded_falls_back_immediately_and_disables_sdk_retries(
    settings,
):
    fernet_key = Fernet.generate_key().decode("utf-8")
    settings.BYOK_ENCRYPTION_KEY = fernet_key
    settings.REDIS_URL = ""

    user = User.objects.create_user(username="byok_504", password="pw")
    profile = get_or_create_user_profile(user)
    profile.gemini_api_key_encrypted = encrypt_api_key(
        "AQ.Ab8RN6-ValidCopilot504Key12345678", fernet_key
    )
    profile.gemini_api_key_last4 = "5678"
    profile.preferred_gemini_model = "gemini-4-carbon"
    profile.allow_model_fallback = True
    profile.save(
        update_fields=[
            "gemini_api_key_encrypted",
            "gemini_api_key_last4",
            "preferred_gemini_model",
            "allow_model_fallback",
        ]
    )

    resume = ResumeProfile.objects.create(
        user=user,
        label="Backend CV",
        raw_text="Senior Python engineer",
        content_hash="b" * 64,
        embedding=[0.1] * 768,
        is_active=True,
    )
    job = JobPosting.objects.create(
        ats_source=ATSSource.GREENHOUSE,
        external_id="byok-504-job",
        content_hash="c" * 64,
        title="Staff Python Engineer",
        company_name="Acme",
        apply_url="https://example.com/jobs/byok-504",
        raw_html_gcs_uri="gs://bucket/byok-504.html",
        location_raw="Remote",
        description_clean="Build distributed systems",
        seniority=SeniorityLevel.STAFF,
        contract_type=ContractType.PJ,
        tech_stack=["python"],
        is_active=True,
    )
    match = MatchScore.objects.create(
        job_posting=job,
        resume_profile=resume,
        cosine_similarity=0.84,
        fit_score=82,
        resume_content_hash=resume.content_hash,
    )

    seen_models: list[str] = []
    seen_http_options: list[types.HttpOptions] = []

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
        return SimpleNamespace(text="## Cover Letter\nFallback succeeded.")

    fake_genai_client = MagicMock()
    fake_genai_client.models.generate_content.side_effect = _side_effect

    def _capture_client(*, api_key, http_options):
        seen_http_options.append(http_options)
        return fake_genai_client

    api_client = APIClient()
    api_client.force_authenticate(user=user)
    with patch("apps.base.services.byok.genai.Client", side_effect=_capture_client):
        resp = api_client.post(
            f"/api/v1/matches/{match.uuid}/artifacts/",
            {"kind": MatchArtifactKind.COVER_LETTER},
            format="json",
        )

    assert resp.status_code == 201
    assert resp.json()["model_name"] == "gemini-4-neon"
    assert seen_models == ["gemini-4-carbon", "gemini-4-neon"]
    assert len(seen_http_options) == 2
    for opts in seen_http_options:
        assert opts.retry_options is not None
        assert opts.retry_options.attempts == 1
        assert opts.timeout <= 35000

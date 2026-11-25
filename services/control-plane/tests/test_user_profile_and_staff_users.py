from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.db import transaction
import pytest
from rest_framework.test import APIClient

from apps.base.models.notification import Notification, NotificationKind
from apps.base.models.user_profile import (
    UserProfile,
    get_or_create_user_profile,
)
from apps.base.services.user_management import (
    PrivilegedGuardError,
    update_staff_managed_user,
)
from apps.jobs.models.jobs import JobPosting
from apps.matching.models.artifacts import MatchArtifact, MatchArtifactKind
from apps.matching.models.matching import MatchScore
from apps.resumes.models.resumes import ResumeProfile
from apps.tracker.models.tracker import ApplicationLead
from vektryn_contracts.enums import ATSSource, ContractType, SeniorityLevel

User = get_user_model()


def _make_user_history(
    user, suffix: str
) -> tuple[ResumeProfile, MatchScore, MatchArtifact, ApplicationLead, Notification]:
    resume = ResumeProfile.objects.create(
        user=user,
        label=f"Backend {suffix}",
        raw_text="Senior Python, Django, PostgreSQL, and Kafka engineer.",
        content_hash=f"hash-{suffix}",
        extracted_skills=["python", "django", "kafka"],
    )
    job = JobPosting.objects.create(
        ats_source=ATSSource.GREENHOUSE,
        external_id=f"u13-{suffix}",
        content_hash=f"job-hash-{suffix}",
        title="Staff Backend Engineer",
        company_name="Acme Cloud",
        apply_url=f"https://boards.greenhouse.io/acme/jobs/{suffix}",
        raw_html_gcs_uri=f"gs://bucket/{suffix}.html",
        location_raw="Remote",
        description_clean="Build resilient Python and Kafka systems.",
        seniority=SeniorityLevel.STAFF,
        contract_type=ContractType.PJ,
        tech_stack=["python", "kafka"],
        is_active=True,
    )
    match = MatchScore.objects.create(
        job_posting=job,
        resume_profile=resume,
        cosine_similarity=0.88,
        fit_score=91,
        matched_skills=["python", "kafka"],
        missing_keywords=["terraform"],
        talking_points=["Kafka partitioning wins"],
        gap_summary="Strong backend fit.",
        resume_content_hash=resume.content_hash,
        scoring_model="gemini-4-hydrogen",
    )
    artifact = MatchArtifact.objects.create(
        user=user,
        match_score=match,
        kind=MatchArtifactKind.TAILORED_BULLETS,
        resume_content_hash=resume.content_hash,
        content_markdown="## Tailored Resume Bullets\n- Built Kafka pipelines.",
        model_name="gemini-4-hydrogen",
    )
    lead = ApplicationLead.objects.create(
        user=user,
        job_posting=job,
        resume_profile=resume,
    )
    notif = Notification.objects.create(
        user=user,
        kind=NotificationKind.MATCH_ALERT,
        title="91% Fit: Staff Backend Engineer",
        body="Acme Cloud matched.",
    )
    return resume, match, artifact, lead, notif


@pytest.mark.django_db
def test_auth_me_and_self_profile_validation_and_updates():
    user = User.objects.create_user(
        username="profile_owner",
        email="owner@example.com",
        password="ValidPassword!2026",
    )
    client = APIClient()
    client.force_authenticate(user=user)

    me_res = client.get("/api/v1/auth/me/")
    assert me_res.status_code == 200
    me_body = me_res.json()
    assert me_body["is_superuser"] is False
    assert me_body["profile"] == {
        "display_name": "",
        "timezone": "UTC",
        "preferred_currency": "USD",
        "default_copilot_tone": "balanced",
    }

    get_res = client.get("/api/v1/auth/profile/")
    assert get_res.status_code == 200
    assert get_res.json()["timezone"] == "UTC"

    # Invalid IANA timezone & unsafe URL schemes rejected with 400
    bad_tz = client.patch(
        "/api/v1/auth/profile/",
        {"timezone": "Mars/Olympus_Mons"},
        format="json",
    )
    assert bad_tz.status_code == 400
    assert "timezone" in bad_tz.json()

    for bad_url in (
        "javascript:alert(1)",
        "ftp://example.com/cv",
        "data:text/html,hi",
        "mailto:test@example.com",
    ):
        bad_link = client.patch(
            "/api/v1/auth/profile/",
            {"portfolio_url": bad_url},
            format="json",
        )
        assert bad_link.status_code == 400
        assert "portfolio_url" in bad_link.json()

    # Valid update persists email + profile preferences & links
    patch_res = client.patch(
        "/api/v1/auth/profile/",
        {
            "email": "Rafa@Example.com",
            "display_name": "Rafa Debastiani",
            "timezone": "America/Sao_Paulo",
            "preferred_currency": "BRL",
            "default_copilot_tone": "technical",
            "linkedin_url": "https://linkedin.com/in/rafa",
            "github_url": "https://github.com/debastiani-dev",
            "portfolio_url": "https://debastiani.dev",
        },
        format="json",
    )
    assert patch_res.status_code == 200
    body = patch_res.json()
    assert body["email"] == "rafa@example.com"
    assert body["display_name"] == "Rafa Debastiani"
    assert body["timezone"] == "America/Sao_Paulo"
    assert body["preferred_currency"] == "BRL"
    assert body["default_copilot_tone"] == "technical"
    assert body["linkedin_url"] == "https://linkedin.com/in/rafa"

    # Clearing an optional URL succeeds
    clear_res = client.patch(
        "/api/v1/auth/profile/",
        {"portfolio_url": ""},
        format="json",
    )
    assert clear_res.status_code == 200
    assert clear_res.json()["portfolio_url"] == ""

    # Savepoint-safe lazy provisioning restores soft-deleted profile inside atomic()
    profile = UserProfile.objects.get(user=user)
    profile.soft_delete()
    with transaction.atomic():
        restored = get_or_create_user_profile(user)
    assert restored.is_deleted is False


@pytest.mark.django_db
def test_copilot_profile_grounding_default_tone_and_cache_stability(settings):
    settings.REDIS_URL = ""
    user = User.objects.create_user(
        username="copilot_profile_user",
        email="cp@example.com",
        password="ValidPassword!2026",
    )
    _, match, _, _, _ = _make_user_history(user, "copilot")
    # Remove seeded bullets artifact so cover_letter tests fresh generation + caching
    MatchArtifact.all_objects.filter(user=user).delete()

    client = APIClient()
    client.force_authenticate(user=user)
    client.patch(
        "/api/v1/auth/profile/",
        {
            "display_name": "Rafa Debastiani",
            "default_copilot_tone": "technical",
            "linkedin_url": "https://linkedin.com/in/rafa",
            "github_url": "https://github.com/debastiani-dev",
            "portfolio_url": "https://debastiani.dev",
        },
        format="json",
    )

    captured_prompts: list[str] = []

    def _fake_generate(*, prompt: str, genai_client=None):
        captured_prompts.append(prompt)
        return (
            "## Cover Letter\nGrounded draft for Rafa Debastiani.",
            "gemini-4-hydrogen",
        )

    url = f"/api/v1/matches/{match.uuid}/artifacts/"
    with patch(
        "apps.matching.services.copilot.invoke_copilot_gemini",
        side_effect=_fake_generate,
    ) as mock_gemini:
        # Omitting tone falls back to profile.default_copilot_tone ("technical")
        first = client.post(url, {"kind": "cover_letter"}, format="json")
        assert first.status_code == 201
        assert first.json()["cached"] is False
        assert mock_gemini.call_count == 1
        assert "=== CANDIDATE PROFILE & LINKS ===" in captured_prompts[0]
        assert "Name: Rafa Debastiani" in captured_prompts[0]
        assert "LinkedIn: https://linkedin.com/in/rafa" in captured_prompts[0]
        assert "GitHub: https://github.com/debastiani-dev" in captured_prompts[0]
        assert "Portfolio: https://debastiani.dev" in captured_prompts[0]
        assert "Tone Preference (technical):" in captured_prompts[0]

        # Repeat call with default tone (omitted or explicit "technical") hits cache
        second = client.post(
            url, {"kind": "cover_letter", "tone": "technical"}, format="json"
        )
        assert second.status_code == 200
        assert second.json()["cached"] is True
        assert mock_gemini.call_count == 1

        # Updating UserProfile does NOT invalidate existing cached MatchArtifact rows
        client.patch(
            "/api/v1/auth/profile/",
            {"display_name": "Rafael Debastiani"},
            format="json",
        )
        listed = client.get(url)
        assert listed.status_code == 200
        assert listed.json()["results"][0]["is_stale"] is False

        third = client.post(url, {"kind": "cover_letter"}, format="json")
        assert third.status_code == 200
        assert third.json()["cached"] is True
        assert mock_gemini.call_count == 1

    # Verify read-only lookup when no UserProfile row exists on cache hit
    user_no_prof = User.objects.create_user(
        username="no_profile_cache_user",
        password="ValidPassword!2026",
    )
    _, match_np, _, _, _ = _make_user_history(user_no_prof, "noprof")
    client_np = APIClient()
    client_np.force_authenticate(user=user_no_prof)
    cache_hit = client_np.post(
        f"/api/v1/matches/{match_np.uuid}/artifacts/",
        {"kind": "tailored_bullets"},
        format="json",
    )
    assert cache_hit.status_code == 200
    assert cache_hit.json()["cached"] is True
    assert not UserProfile.all_objects.filter(user=user_no_prof).exists()


@pytest.mark.django_db
def test_self_deactivation_guards_session_purge_and_data_preservation(settings):
    settings.REDIS_URL = ""
    pw = "StrongPass!2026"

    # 1. Last active is_staff=True cannot self-deactivate even if an is_superuser=True, is_staff=False exists
    sole_staff = User.objects.create_user(
        username="sole_staff", password=pw, is_staff=True, is_superuser=False
    )
    non_staff_super = User.objects.create_user(
        username="non_staff_super", password=pw, is_staff=False, is_superuser=True
    )
    staff_client = APIClient()
    staff_client.force_authenticate(user=sole_staff)
    res_last_staff = staff_client.post(
        "/api/v1/auth/deactivate/", {"current_password": pw}, format="json"
    )
    assert res_last_staff.status_code == 400
    sole_staff.refresh_from_db()
    assert sole_staff.is_active is True

    # 2. Last active is_superuser=True cannot self-deactivate even if another is_staff=True exists
    super_client = APIClient()
    super_client.force_authenticate(user=non_staff_super)
    res_last_super = super_client.post(
        "/api/v1/auth/deactivate/", {"current_password": pw}, format="json"
    )
    assert res_last_super.status_code == 400
    non_staff_super.refresh_from_db()
    assert non_staff_super.is_active is True

    # 3. Standard user deactivation checks password, clears all sessions, and preserves history
    regular = User.objects.create_user(username="deact_user", password=pw)
    resume, match, artifact, lead, notif = _make_user_history(regular, "deact")

    client_a = APIClient()
    client_b = APIClient()
    assert (
        client_a.post(
            "/api/v1/auth/login/",
            {"username": "deact_user", "password": pw},
            format="json",
        ).status_code
        == 200
    )
    assert (
        client_b.post(
            "/api/v1/auth/login/",
            {"username": "deact_user", "password": pw},
            format="json",
        ).status_code
        == 200
    )
    sess_b_key = client_b.cookies["sessionid"].value

    # Wrong password rejected
    bad_pw = client_a.post(
        "/api/v1/auth/deactivate/", {"current_password": "wrong"}, format="json"
    )
    assert bad_pw.status_code == 400
    assert "current_password" in bad_pw.json()

    # Valid password deactivates, flushes cookie, purges all sessions, preserves records
    ok_res = client_a.post(
        "/api/v1/auth/deactivate/", {"current_password": pw}, format="json"
    )
    assert ok_res.status_code == 200
    regular.refresh_from_db()
    assert regular.is_active is False
    assert not Session.objects.filter(session_key=sess_b_key).exists()
    assert client_a.get("/api/v1/auth/me/").status_code == 403
    assert client_b.get("/api/v1/auth/me/").status_code == 403
    assert (
        APIClient()
        .post(
            "/api/v1/auth/login/",
            {"username": "deact_user", "password": pw},
            format="json",
        )
        .status_code
        == 401
    )

    assert ResumeProfile.objects.filter(pk=resume.pk).exists()
    assert MatchScore.objects.filter(pk=match.pk).exists()
    assert MatchArtifact.objects.filter(pk=artifact.pk).exists()
    assert ApplicationLead.objects.filter(pk=lead.pk).exists()
    assert Notification.objects.filter(pk=notif.pk).exists()


@pytest.mark.django_db
def test_staff_user_management_crud_filters_and_security_guards(settings):
    settings.REDIS_URL = ""
    pw = "OperatorPass!2026"
    superuser = User.objects.create_superuser(
        username="root_admin", email="root@example.com", password=pw
    )
    staff_a = User.objects.create_user(
        username="staff_a", email="staff_a@example.com", password=pw, is_staff=True
    )
    regular = User.objects.create_user(
        username="regular_user", email="reg@example.com", password=pw
    )

    # Non-staff user receives 403 Forbidden across all methods
    reg_client = APIClient()
    reg_client.force_authenticate(user=regular)
    assert reg_client.get("/api/v1/users/").status_code == 403
    assert (
        reg_client.post(
            "/api/v1/users/",
            {"username": "nope", "password": "SafePassword!2026"},
            format="json",
        ).status_code
        == 403
    )
    assert (
        reg_client.patch(f"/api/v1/users/{regular.id}/", {}, format="json").status_code
        == 403
    )
    assert reg_client.delete(f"/api/v1/users/{regular.id}/").status_code == 403

    super_client = APIClient()
    super_client.force_authenticate(user=superuser)
    staff_client = APIClient()
    staff_client.force_authenticate(user=staff_a)

    # PUT is explicitly excluded (405)
    assert (
        super_client.put(
            f"/api/v1/users/{regular.id}/", {"email": "x@example.com"}, format="json"
        ).status_code
        == 405
    )

    # Non-superuser staff cannot PATCH (even email/profile) or DELETE a superuser (403)
    assert (
        staff_client.patch(
            f"/api/v1/users/{superuser.id}/",
            {"email": "hijack@example.com"},
            format="json",
        ).status_code
        == 403
    )
    assert staff_client.delete(f"/api/v1/users/{superuser.id}/").status_code == 403

    # POST enforces AUTH_PASSWORD_VALIDATORS including UserAttributeSimilarityValidator
    sim_pw = super_client.post(
        "/api/v1/users/",
        {
            "username": "candidate_alpha",
            "email": "candidate_alpha@example.com",
            "password": "candidate_alpha_2026",
        },
        format="json",
    )
    assert sim_pw.status_code == 400
    assert "password" in sim_pw.json()

    # POST rejects is_superuser mutation with explicit 400
    super_create = super_client.post(
        "/api/v1/users/",
        {
            "username": "sneaky_admin",
            "password": "UniquePassword#99",
            "is_superuser": True,
        },
        format="json",
    )
    assert super_create.status_code == 400
    assert "is_superuser" in super_create.json()

    # Valid POST creates user + nested profile
    created = super_client.post(
        "/api/v1/users/",
        {
            "username": "new_member",
            "email": "Member@Example.com",
            "password": "UniquePassword#99",
            "is_staff": False,
            "profile": {
                "display_name": "New Member",
                "timezone": "America/Sao_Paulo",
                "preferred_currency": "BRL",
            },
        },
        format="json",
    )
    assert created.status_code == 201
    new_user_id = created.json()["id"]
    assert created.json()["email"] == "member@example.com"
    assert created.json()["profile"]["display_name"] == "New Member"

    # List search + boolean filters + soft-deleted profile resilience
    soft_prof = get_or_create_user_profile(regular)
    soft_prof.display_name = "Ghost Name"
    soft_prof.save(update_fields=["display_name"])
    soft_prof.soft_delete()

    list_search = super_client.get(
        "/api/v1/users/?search=New+Member&is_staff=false&is_active=true"
    )
    assert list_search.status_code == 200
    assert [u["username"] for u in list_search.json()["results"]] == ["new_member"]

    list_reg = super_client.get("/api/v1/users/?search=regular_user")
    assert list_reg.status_code == 200
    assert list_reg.json()["results"][0]["profile"]["display_name"] == ""
    assert super_client.get("/api/v1/users/?is_active=maybe").status_code == 400

    # Self-deactivation, self-demotion, and is_superuser PATCH rejected with 400
    assert (
        super_client.patch(
            f"/api/v1/users/{superuser.id}/", {"is_active": False}, format="json"
        ).status_code
        == 400
    )
    assert (
        super_client.patch(
            f"/api/v1/users/{superuser.id}/", {"is_staff": False}, format="json"
        ).status_code
        == 400
    )
    assert super_client.delete(f"/api/v1/users/{superuser.id}/").status_code == 400
    assert (
        super_client.patch(
            f"/api/v1/users/{new_user_id}/", {"is_superuser": True}, format="json"
        ).status_code
        == 400
    )

    # Last active is_staff=True guard even when an is_superuser=True, is_staff=False exists
    superuser.is_staff = False
    superuser.save(update_fields=["is_staff"])
    # Now staff_a is the ONLY active is_staff=True user; create another superuser who is staff to test demotion
    helper_super = User.objects.create_superuser(
        username="helper_super", email="h@example.com", password=pw
    )
    helper_client = APIClient()
    helper_client.force_authenticate(user=helper_super)
    # Demote staff_a first (allowed because helper_super has is_staff=True)
    assert (
        helper_client.patch(
            f"/api/v1/users/{staff_a.id}/", {"is_staff": False}, format="json"
        ).status_code
        == 200
    )
    # Restore staff_a as sole staff after demoting helper_super? Instead test staff_a demoting helper_super when staff_a isn't staff;
    # Verify superuser (is_superuser=True, is_staff=False) cannot count as active is_staff=True!
    # Make staff_a active staff again, then have a 3rd staff try to demote the last active staff when only 1 staff exists:
    helper_super.is_staff = False
    helper_super.save(update_fields=["is_staff"])
    staff_a.is_staff = True
    staff_a.save(update_fields=["is_staff"])
    # Now ONLY staff_a has is_active=True, is_staff=True (superuser & helper_super have is_staff=False)
    with pytest.raises(PrivilegedGuardError):
        update_staff_managed_user(target_user=staff_a, is_staff=False)
    staff_a.refresh_from_db()
    assert staff_a.is_staff is True

    member_user = User.objects.get(pk=new_user_id)
    resume, _, _, lead, _ = _make_user_history(member_user, "staffdel")
    member_sess_client = APIClient()
    assert (
        member_sess_client.post(
            "/api/v1/auth/login/",
            {"username": "new_member", "password": "UniquePassword#99"},
            format="json",
        ).status_code
        == 200
    )
    member_session_key = member_sess_client.cookies["sessionid"].value

    del_res = staff_client.delete(f"/api/v1/users/{new_user_id}/")
    assert del_res.status_code == 200
    assert del_res.json()["is_active"] is False
    assert not Session.objects.filter(session_key=member_session_key).exists()
    assert member_sess_client.get("/api/v1/auth/me/").status_code == 403
    assert ResumeProfile.objects.filter(pk=resume.pk).exists()
    assert ApplicationLead.objects.filter(pk=lead.pk).exists()

    # Reactivate cleanly via PATCH
    react_res = staff_client.patch(
        f"/api/v1/users/{new_user_id}/", {"is_active": True}, format="json"
    )
    assert react_res.status_code == 200
    assert react_res.json()["is_active"] is True

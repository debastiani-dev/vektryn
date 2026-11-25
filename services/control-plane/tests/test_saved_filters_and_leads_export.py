import csv
from datetime import UTC, datetime, timedelta
from io import StringIO

from django.contrib.auth import get_user_model
import pytest
from rest_framework.test import APIClient

from apps.base.models.notification import Notification
from apps.jobs.models import JobPosting, SavedFilter
from apps.tracker.models import ApplicationLead
from vektryn_contracts.enums import (
    ATSSource,
    LeadPriority,
    LeadStatus,
    NotificationKind,
)

User = get_user_model()


def _create_job(
    external_id: str, title: str = "Senior Python Engineer", company: str = "Acme"
) -> JobPosting:
    return JobPosting.objects.create(
        ats_source=ATSSource.GREENHOUSE,
        external_id=external_id,
        content_hash=f"{external_id:0<64}"[:64],
        title=title,
        company_name=company,
        apply_url=f"https://example.com/jobs/{external_id}",
        raw_html_gcs_uri=f"gs://bucket/{external_id}.html",
        description_clean="Build Python and Django backend systems.",
    )


@pytest.mark.django_db
def test_saved_filter_crud_idor_uniqueness_and_router_order() -> None:
    alice = User.objects.create_user(username="alice-filters", password="secret")
    bob = User.objects.create_user(username="bob-filters", password="secret")
    job = _create_job("gh-filter-route-1")

    client = APIClient()
    client.force_authenticate(user=alice)

    # Create valid preset
    create_res = client.post(
        "/api/v1/jobs/filters/",
        {
            "name": "  BR Senior Python PJ  ",
            "query_params": {
                "search": "python django",
                "seniority": "senior",
                "contract_type": "pj",
                "region": "brazil",
                "min_score": 80,
            },
        },
        format="json",
    )
    assert create_res.status_code == 201
    assert create_res.data["name"] == "BR Senior Python PJ"
    preset_uuid = create_res.data["uuid"]

    # Duplicate active name rejected with 400 (not 500)
    dup_res = client.post(
        "/api/v1/jobs/filters/",
        {"name": "BR Senior Python PJ", "query_params": {"min_score": 70}},
        format="json",
    )
    assert dup_res.status_code == 400

    # Unsupported query_params key rejected with 400
    bad_key_res = client.post(
        "/api/v1/jobs/filters/",
        {"name": "Invalid", "query_params": {"evil_key": "x"}},
        format="json",
    )
    assert bad_key_res.status_code == 400

    # PATCHing query_params without renaming excludes self.instance.pk and succeeds
    patch_res = client.patch(
        f"/api/v1/jobs/filters/{preset_uuid}/",
        {"name": "BR Senior Python PJ", "query_params": {"min_score": 85}},
        format="json",
    )
    assert patch_res.status_code == 200
    assert patch_res.data["query_params"] == {"min_score": 85}

    # JobPosting detail route still resolves alongside /api/v1/jobs/filters/
    job_res = client.get(f"/api/v1/jobs/{job.uuid}/")
    assert job_res.status_code == 200
    assert job_res.data["uuid"] == str(job.uuid)

    # IDOR isolation: Bob cannot see, update, or delete Alice's preset
    bob_client = APIClient()
    bob_client.force_authenticate(user=bob)
    assert bob_client.get("/api/v1/jobs/filters/").data["count"] == 0
    assert bob_client.get(f"/api/v1/jobs/filters/{preset_uuid}/").status_code == 404
    assert bob_client.delete(f"/api/v1/jobs/filters/{preset_uuid}/").status_code == 404

    # Soft-deleting Alice's preset allows re-creating the same name
    assert client.delete(f"/api/v1/jobs/filters/{preset_uuid}/").status_code == 204
    assert SavedFilter.all_objects.filter(uuid=preset_uuid, is_deleted=True).exists()
    recreate_res = client.post(
        "/api/v1/jobs/filters/",
        {"name": "BR Senior Python PJ", "query_params": {"min_score": 70}},
        format="json",
    )
    assert recreate_res.status_code == 201


@pytest.mark.django_db
def test_lead_next_action_at_unset_sentinel_and_reschedule_resets_watermark() -> None:
    alice = User.objects.create_user(username="alice-leads", password="secret")
    job = _create_job("gh-lead-reminder-1")
    due = datetime(2026, 11, 20, 14, 0, tzinfo=UTC)
    notified = datetime(2026, 11, 21, 3, 0, tzinfo=UTC)

    lead = ApplicationLead.objects.create(
        user=alice,
        job_posting=job,
        status=LeadStatus.APPLIED,
        priority=LeadPriority.MEDIUM,
        next_action_at=due,
        followup_notified_at=notified,
    )

    client = APIClient()
    client.force_authenticate(user=alice)

    # Partial PATCH omitting next_action_at (Kanban move) preserves both next_action_at and watermark
    move_res = client.patch(
        f"/api/v1/leads/{lead.uuid}/",
        {"status": LeadStatus.INTERVIEWING},
        format="json",
    )
    assert move_res.status_code == 200
    lead.refresh_from_db()
    assert lead.status == LeadStatus.INTERVIEWING
    assert lead.next_action_at == due
    assert lead.followup_notified_at == notified

    # Rescheduling next_action_at resets followup_notified_at to None
    new_due = due + timedelta(days=5)
    resched_res = client.patch(
        f"/api/v1/leads/{lead.uuid}/",
        {"next_action_at": new_due.isoformat()},
        format="json",
    )
    assert resched_res.status_code == 200
    lead.refresh_from_db()
    assert lead.next_action_at == new_due
    assert lead.followup_notified_at is None

    # Explicitly clearing next_action_at sets it to None
    lead.followup_notified_at = notified
    lead.save(update_fields=["followup_notified_at"])
    clear_res = client.patch(
        f"/api/v1/leads/{lead.uuid}/",
        {"next_action_at": None},
        format="json",
    )
    assert clear_res.status_code == 200
    lead.refresh_from_db()
    assert lead.next_action_at is None
    assert lead.followup_notified_at is None


@pytest.mark.django_db
def test_leads_export_csv_json_auth_guard_and_formula_sanitization() -> None:
    alice = User.objects.create_user(username="alice-export", password="secret")
    bob = User.objects.create_user(username="bob-export", password="secret")
    job_evil = _create_job(
        "gh-export-1",
        title='=HYPERLINK("https://evil.test","Click")',
        company="+Acme Corp",
    )
    job_other = _create_job("gh-export-2", title="Staff Engineer", company="Beta")

    due = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
    ApplicationLead.objects.create(
        user=alice,
        job_posting=job_evil,
        status=LeadStatus.APPLIED,
        priority=LeadPriority.HIGH,
        next_action_at=due,
        notes="@recruiter follow up\n-salary check",
    )
    ApplicationLead.objects.create(
        user=alice,
        job_posting=job_other,
        status=LeadStatus.SAVED,
        priority=LeadPriority.LOW,
    )
    ApplicationLead.objects.create(
        user=bob,
        job_posting=job_other,
        status=LeadStatus.APPLIED,
        priority=LeadPriority.HIGH,
        notes="Bob private notes",
    )

    # Unauthenticated ?format=csv returns 403 cleanly (no 500 crash in CSVExportRenderer)
    anon = APIClient()
    unauth_res = anon.get("/api/v1/leads/export/?format=csv")
    assert unauth_res.status_code == 403

    client = APIClient()
    client.force_authenticate(user=alice)

    # CSV export respects status filter, isolates user, and neutralizes formula prefixes
    csv_res = client.get("/api/v1/leads/export/?format=csv&status=applied")
    assert csv_res.status_code == 200
    assert csv_res["Content-Type"].startswith("text/csv")
    assert 'attachment; filename="vektryn-leads-' in csv_res["Content-Disposition"]
    assert csv_res["Content-Disposition"].endswith('.csv"')

    parsed_rows = list(csv.DictReader(StringIO(csv_res.content.decode("utf-8"))))
    assert len(parsed_rows) == 1
    row = parsed_rows[0]
    assert row["job_title"].startswith("'=")
    assert row["company_name"] == "'+Acme Corp"
    assert row["notes"].startswith("'@recruiter")
    assert row["next_action_at"] == due.isoformat()

    # JSON export includes both of Alice's leads and excludes Bob's
    json_res = client.get("/api/v1/leads/export/?format=json")
    assert json_res.status_code == 200
    assert json_res["Content-Disposition"].endswith('.json"')
    assert len(json_res.data) == 2
    assert all(item["notes"] != "Bob private notes" for item in json_res.data)


@pytest.mark.django_db
def test_overdue_followup_emits_notification_immediately_and_deduplicates() -> None:
    alice = User.objects.create_user(username="alice-due-now", password="secret")
    job_due = _create_job("gh-due-now-1", title="Staff Engineer", company="Alpha")
    job_rejected = _create_job("gh-due-now-2", title="Old Role", company="Omega")

    past = datetime.now(UTC) - timedelta(minutes=5)
    future = datetime.now(UTC) + timedelta(hours=4)

    due_lead = ApplicationLead.objects.create(
        user=alice,
        job_posting=job_due,
        status=LeadStatus.INTERVIEWING,
        next_action_at=past,
    )
    ApplicationLead.objects.create(
        user=alice,
        job_posting=job_rejected,
        status=LeadStatus.REJECTED,
        next_action_at=past,
    )

    client = APIClient()
    client.force_authenticate(user=alice)

    # First fetch claims the overdue active lead and emits lead_followup_due immediately
    first = client.get("/api/v1/notifications/")
    assert first.status_code == 200
    assert first.data["count"] == 1
    assert first.data["unread_count"] == 1
    assert first.data["results"][0]["kind"] == NotificationKind.LEAD_FOLLOWUP_DUE

    # Second fetch does NOT create a duplicate notification
    second = client.get("/api/v1/notifications/")
    assert second.status_code == 200
    assert second.data["count"] == 1

    # Rescheduling to a future time resets watermark, then moving past re-triggers cleanly
    assert (
        client.patch(
            f"/api/v1/leads/{due_lead.uuid}/",
            {"next_action_at": future.isoformat()},
            format="json",
        ).status_code
        == 200
    )
    assert client.get("/api/v1/notifications/").data["count"] == 1

    earlier_past = datetime.now(UTC) - timedelta(minutes=1)
    assert (
        client.patch(
            f"/api/v1/leads/{due_lead.uuid}/",
            {"next_action_at": earlier_past.isoformat()},
            format="json",
        ).status_code
        == 200
    )
    third = client.get("/api/v1/notifications/")
    assert third.status_code == 200
    assert third.data["count"] == 2
    assert (
        Notification.objects.filter(
            user=alice, kind=NotificationKind.LEAD_FOLLOWUP_DUE
        ).count()
        == 2
    )

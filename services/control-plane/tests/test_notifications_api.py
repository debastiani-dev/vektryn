from django.contrib.auth import get_user_model
from django.utils import timezone
import pytest
from rest_framework.test import APIClient

from apps.base.models.notification import Notification
from vektryn_contracts.enums import NotificationKind

User = get_user_model()


@pytest.mark.django_db
def test_notifications_list_filtering_and_global_unread_count() -> None:
    alice = User.objects.create_user(username="alice-notif", password="secret")
    bob = User.objects.create_user(username="bob-notif", password="secret")

    n_match = Notification.objects.create(
        user=alice,
        kind=NotificationKind.MATCH_ALERT,
        title="92% Fit: Staff Python Engineer",
        body="Acme matched your resume.",
        payload={"fit_score": 92, "match_score_uuid": "ms-1"},
    )
    Notification.objects.create(
        user=alice,
        kind=NotificationKind.TRACKED_JOB_CLOSED,
        title="Tracked role closed: Backend Engineer",
        body="Beta closed this listing.",
        payload={"job_posting_uuid": "job-2"},
    )
    Notification.objects.create(
        user=alice,
        kind=NotificationKind.PIPELINE_ERROR,
        title="Pipeline error in matcher-worker",
        body="Timeout",
        read_at=timezone.now(),
    )
    Notification.objects.create(
        user=alice,
        kind=NotificationKind.MATCH_ALERT,
        title="Dismissed alert",
        dismissed_at=timezone.now(),
    )
    Notification.objects.create(
        user=bob,
        kind=NotificationKind.MATCH_ALERT,
        title="Bob private alert",
    )

    client = APIClient()
    client.force_authenticate(user=alice)

    res_all = client.get("/api/v1/notifications/")
    assert res_all.status_code == 200
    assert res_all.data["count"] == 3
    assert res_all.data["unread_count"] == 2
    returned_uuids = {row["uuid"] for row in res_all.data["results"]}
    assert str(n_match.uuid) in returned_uuids

    # Filtering by kind must keep unread_count global across all non-dismissed unread rows
    res_kind = client.get("/api/v1/notifications/?kind=pipeline_error")
    assert res_kind.status_code == 200
    assert res_kind.data["count"] == 1
    assert res_kind.data["unread_count"] == 2

    res_unread = client.get("/api/v1/notifications/?unread=true")
    assert res_unread.status_code == 200
    assert res_unread.data["count"] == 2
    assert res_unread.data["unread_count"] == 2


@pytest.mark.django_db
def test_notifications_read_dismiss_read_all_and_idor_isolation() -> None:
    alice = User.objects.create_user(username="alice-actions", password="secret")
    bob = User.objects.create_user(username="bob-actions", password="secret")

    n1 = Notification.objects.create(
        user=alice,
        kind=NotificationKind.MATCH_ALERT,
        title="Match 1",
    )
    n2 = Notification.objects.create(
        user=alice,
        kind=NotificationKind.TRACKED_JOB_CLOSED,
        title="Closed 2",
    )
    n3 = Notification.objects.create(
        user=alice,
        kind=NotificationKind.PIPELINE_ERROR,
        title="Error 3",
    )
    bob_notif = Notification.objects.create(
        user=bob,
        kind=NotificationKind.MATCH_ALERT,
        title="Bob secret",
    )

    client = APIClient()
    client.force_authenticate(user=alice)

    # IDOR checks: Alice cannot read or dismiss Bob's notification
    assert (
        client.patch(f"/api/v1/notifications/{bob_notif.uuid}/read/").status_code == 404
    )
    assert (
        client.patch(f"/api/v1/notifications/{bob_notif.uuid}/dismiss/").status_code
        == 404
    )

    # Mark n1 read (idempotent)
    read_res = client.patch(f"/api/v1/notifications/{n1.uuid}/read/")
    assert read_res.status_code == 200
    assert read_res.data["notification"]["is_read"] is True
    assert read_res.data["notification"]["read_at"] is not None
    assert read_res.data["unread_count"] == 2

    read_again = client.patch(f"/api/v1/notifications/{n1.uuid}/read/")
    assert read_again.status_code == 200
    assert read_again.data["unread_count"] == 2

    # Dismissing unread n2 sets both dismissed_at and read_at and decrements unread_count
    dismiss_res = client.patch(f"/api/v1/notifications/{n2.uuid}/dismiss/")
    assert dismiss_res.status_code == 200
    assert dismiss_res.data["notification"]["dismissed_at"] is not None
    assert dismiss_res.data["notification"]["read_at"] is not None
    assert dismiss_res.data["unread_count"] == 1

    # Read all marks remaining unread (n3) read without touching Bob's notification
    read_all_res = client.post("/api/v1/notifications/read-all/")
    assert read_all_res.status_code == 200
    assert read_all_res.data == {"updated_count": 1, "unread_count": 0}

    n3.refresh_from_db()
    bob_notif.refresh_from_db()
    assert n3.read_at is not None
    assert bob_notif.read_at is None

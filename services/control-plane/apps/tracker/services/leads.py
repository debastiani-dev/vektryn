from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.base.models.notification import Notification
from apps.tracker.models import ApplicationLead
from vektryn_contracts.enums import LeadStatus, NotificationKind

_UNSET = object()
_TERMINAL_LEAD_STATUSES = (LeadStatus.REJECTED, LeadStatus.WITHDRAWN)


def sync_due_followup_notifications_for_user(user) -> int:
    """Atomically claims due active leads for `user` and persists lead_followup_due notifications."""
    now = timezone.now()
    with transaction.atomic():
        due_leads = list(
            ApplicationLead.objects.select_for_update(of=("self",), skip_locked=True)
            .select_related("job_posting")
            .filter(
                user=user,
                job_posting__is_deleted=False,
                next_action_at__isnull=False,
                next_action_at__lte=now,
            )
            .exclude(status__in=_TERMINAL_LEAD_STATUSES)
            .filter(
                Q(followup_notified_at__isnull=True)
                | Q(followup_notified_at__lt=F("next_action_at"))
            )
        )
        if not due_leads:
            return 0

        notifications: list[Notification] = []
        claimed_pks = []
        for lead in due_leads:
            claimed_pks.append(lead.pk)
            due_dt = lead.next_action_at
            due_iso = due_dt.isoformat() if due_dt is not None else ""
            due_label = due_dt.strftime("%b %d, %Y") if due_dt is not None else ""
            job = lead.job_posting
            notifications.append(
                Notification(
                    user=user,
                    kind=NotificationKind.LEAD_FOLLOWUP_DUE,
                    title=f"Follow-up due: {job.title}"[:255],
                    body=(
                        f"Scheduled follow-up for {job.company_name} ({lead.status}) "
                        f"was due on {due_label}."
                    ),
                    payload={
                        "lead_uuid": str(lead.uuid),
                        "job_posting_uuid": str(job.uuid),
                        "lead_status": str(lead.status),
                        "next_action_at": due_iso,
                        "title": job.title,
                        "company_name": job.company_name,
                        "apply_url": job.apply_url,
                    },
                )
            )

        Notification.objects.bulk_create(notifications)
        ApplicationLead.objects.filter(pk__in=claimed_pks).update(
            followup_notified_at=now,
            modified_at=now,
        )
        return len(notifications)


@transaction.atomic
def create_lead(*, user, validated_data: dict) -> ApplicationLead:
    now = timezone.now()
    status = validated_data.get("status", LeadStatus.SAVED)
    notes = (validated_data.get("notes") or "").strip()

    lead = ApplicationLead(
        user=user,
        **validated_data,
    )
    if status == LeadStatus.APPLIED:
        lead.applied_at = now
    if status != LeadStatus.DISCOVERED or notes or lead.next_action_at is not None:
        lead.last_activity_at = now
    lead.save()
    return lead


@transaction.atomic
def update_lead(lead: ApplicationLead, *, validated_data: dict) -> ApplicationLead:
    now = timezone.now()
    update_fields: list[str] = []

    new_status = validated_data.get("status")
    status_changed = new_status is not None and new_status != lead.status

    new_notes = validated_data.get("notes")
    notes_changed = new_notes is not None and new_notes != lead.notes

    next_action_input = validated_data.get("next_action_at", _UNSET)
    next_action_changed = (
        next_action_input is not _UNSET and next_action_input != lead.next_action_at
    )

    for field, value in validated_data.items():
        setattr(lead, field, value)
        update_fields.append(field)

    if next_action_changed:
        lead.followup_notified_at = None
        update_fields.append("followup_notified_at")

    if status_changed and new_status == LeadStatus.APPLIED and lead.applied_at is None:
        lead.applied_at = now
        update_fields.append("applied_at")

    if status_changed or notes_changed or next_action_changed:
        lead.last_activity_at = now
        update_fields.append("last_activity_at")

    if update_fields:
        lead.save(update_fields=update_fields)
    return lead

from django.db import transaction
from django.utils import timezone

from apps.tracker.models import ApplicationLead
from vektryn_contracts.enums import LeadStatus


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
    if status != LeadStatus.DISCOVERED or notes:
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

    for field, value in validated_data.items():
        setattr(lead, field, value)
        update_fields.append(field)

    if status_changed and new_status == LeadStatus.APPLIED and lead.applied_at is None:
        lead.applied_at = now
        update_fields.append("applied_at")

    if status_changed or notes_changed:
        lead.last_activity_at = now
        update_fields.append("last_activity_at")

    if update_fields:
        lead.save(update_fields=update_fields)
    return lead
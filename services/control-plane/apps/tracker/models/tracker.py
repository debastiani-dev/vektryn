from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.base.models.base_model import BaseModel, enum_choices
from vektryn_contracts.enums import LeadPriority, LeadStatus


class ApplicationLead(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="application_leads",
    )
    job_posting = models.ForeignKey(
        "jobs.JobPosting",
        on_delete=models.CASCADE,
        related_name="application_leads",
    )
    resume_profile = models.ForeignKey(
        "resumes.ResumeProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="application_leads",
    )

    status = models.CharField(
        max_length=32,
        choices=enum_choices(LeadStatus),
        default=LeadStatus.SAVED,
    )
    priority = models.CharField(
        max_length=16,
        choices=enum_choices(LeadPriority),
        default=LeadPriority.MEDIUM,
    )

    applied_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    next_action_at = models.DateTimeField(null=True, blank=True, db_index=True)
    followup_notified_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-modified_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "job_posting"],
                condition=Q(is_deleted=False),
                name="uq_application_lead_active_user_job",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "status", "-modified_at"],
                name="idx_application_lead_board",
            ),
        ]

    def __str__(self) -> str:
        return f"[{self.status}] {self.job_posting.title} @ {self.job_posting.company_name}"

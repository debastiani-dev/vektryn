from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.base.models.base_model import BaseModel


def normalize_company_name(raw: str) -> str:
    """Normalize company names for case- and whitespace-insensitive mute matching."""
    return " ".join((raw or "").strip().lower().split())


class DismissedJob(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dismissed_jobs",
    )
    job_posting = models.ForeignKey(
        "jobs.JobPosting",
        on_delete=models.CASCADE,
        related_name="dismissals",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "job_posting"],
                condition=Q(is_deleted=False),
                name="uq_dismissed_job_active_user_job",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "-created_at"],
                name="idx_dismissed_job_user_created",
            ),
        ]

    def __str__(self) -> str:
        return f"Dismissed {self.job_posting_id} (user={self.user_id})"


class MutedCompany(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="muted_companies",
    )
    company_name_normalized = models.CharField(max_length=180)
    company_name_display = models.CharField(max_length=180)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "company_name_normalized"],
                condition=Q(is_deleted=False),
                name="uq_muted_company_active_user_norm",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "-created_at"],
                name="idx_muted_company_user_created",
            ),
        ]

    def __str__(self) -> str:
        return f"Muted {self.company_name_display} (user={self.user_id})"

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.base.models.base_model import BaseModel


class MatchArtifactKind(models.TextChoices):
    TAILORED_BULLETS = "tailored_bullets", "Tailored Bullets"
    COVER_LETTER = "cover_letter", "Cover Letter"
    RECRUITER_OUTREACH = "recruiter_outreach", "Recruiter Outreach"
    INTERVIEW_QUESTIONS = "interview_questions", "Interview Questions"
    QUESTIONS_TO_ASK = "questions_to_ask", "Questions to Ask"


class MatchArtifact(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="match_artifacts",
    )
    match_score = models.ForeignKey(
        "matching.MatchScore",
        on_delete=models.CASCADE,
        related_name="artifacts",
    )
    kind = models.CharField(
        max_length=32,
        choices=MatchArtifactKind.choices,
    )
    resume_content_hash = models.CharField(max_length=64)
    content_markdown = models.TextField()
    model_name = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["match_score", "kind", "resume_content_hash"],
                condition=Q(is_deleted=False),
                name="uq_match_artifact_active_match_kind_hash",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "match_score", "-created_at"],
                name="idx_match_art_user_match_crt",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} ({self.match_score_id})"

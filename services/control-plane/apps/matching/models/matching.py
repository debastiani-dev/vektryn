from django.db import models
from django.db.models import Q

from apps.base.models.base_model import BaseModel


class MatchScore(BaseModel):
    job_posting = models.ForeignKey(
        "jobs.JobPosting",
        on_delete=models.CASCADE,
        related_name="match_scores",
    )
    resume_profile = models.ForeignKey(
        "resumes.ResumeProfile",
        on_delete=models.CASCADE,
        related_name="match_scores",
    )

    cosine_similarity = models.FloatField()
    fit_score = models.PositiveSmallIntegerField(null=True, blank=True)

    matched_skills = models.JSONField(default=list, blank=True)
    missing_keywords = models.JSONField(default=list, blank=True)
    talking_points = models.JSONField(default=list, blank=True)
    gap_summary = models.TextField(blank=True, default="")
    fit_highlights = models.JSONField(default=list, db_default=[], blank=True)
    watchout_note = models.TextField(blank=True, default="", db_default="")

    resume_content_hash = models.CharField(max_length=64)
    scoring_model = models.CharField(max_length=64, blank=True, default="")
    alert_sent_at = models.DateTimeField(null=True, blank=True)
    is_routed_winner = models.BooleanField(
        default=True,
        db_default=True,
        db_index=True,
    )

    class Meta:
        ordering = ["-fit_score", "-cosine_similarity", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["job_posting", "resume_profile"],
                name="uq_match_score_job_resume",
            ),
            models.CheckConstraint(
                condition=Q(cosine_similarity__gte=0.0) & Q(cosine_similarity__lte=1.0),
                name="chk_match_score_cosine_range",
            ),
            models.CheckConstraint(
                condition=Q(fit_score__isnull=True)
                | (Q(fit_score__gte=0) & Q(fit_score__lte=100)),
                name="chk_match_score_fit_score_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=["resume_profile", "-fit_score", "-created_at"],
                name="idx_match_score_profile_rank",
            ),
            models.Index(
                fields=[
                    "resume_profile",
                    "is_routed_winner",
                    "-fit_score",
                    "-created_at",
                ],
                name="idx_match_profile_winner_rank",
            ),
            models.Index(
                fields=["job_posting", "is_routed_winner"],
                name="idx_match_job_winner",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.resume_profile.label} -> {self.job_posting.title} ({self.fit_score})"

from django.contrib import admin

from apps.matching.models.artifacts import MatchArtifact
from apps.matching.models.matching import MatchScore


@admin.register(MatchScore)
class MatchScoreAdmin(admin.ModelAdmin):
    list_display = (
        "job_posting",
        "resume_profile",
        "cosine_similarity",
        "fit_score",
        "alert_sent_at",
        "created_at",
    )
    list_filter = ("scoring_model", "is_deleted")
    readonly_fields = ("uuid", "resume_content_hash", "created_at", "modified_at")


@admin.register(MatchArtifact)
class MatchArtifactAdmin(admin.ModelAdmin):
    list_display = (
        "match_score",
        "user",
        "kind",
        "model_name",
        "is_deleted",
        "modified_at",
    )
    list_filter = ("kind", "model_name", "is_deleted")
    readonly_fields = ("uuid", "resume_content_hash", "created_at", "modified_at")

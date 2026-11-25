from rest_framework import serializers

from apps.jobs.serializers.jobs import JobPostingSummarySerializer
from apps.matching.models.matching import MatchScore


class MatchScoreSerializer(serializers.ModelSerializer):
    job_posting = JobPostingSummarySerializer(read_only=True)
    resume_profile_uuid = serializers.UUIDField(
        source="resume_profile.uuid", read_only=True
    )
    resume_profile_label = serializers.CharField(
        source="resume_profile.label", read_only=True
    )
    resume_min_alert_score = serializers.IntegerField(
        source="resume_profile.min_alert_score", read_only=True
    )
    is_stale = serializers.SerializerMethodField()

    class Meta:
        model = MatchScore
        fields = [
            "uuid",
            "job_posting",
            "resume_profile_uuid",
            "resume_profile_label",
            "resume_min_alert_score",
            "cosine_similarity",
            "fit_score",
            "matched_skills",
            "missing_keywords",
            "talking_points",
            "gap_summary",
            "scoring_model",
            "is_stale",
            "alert_sent_at",
            "created_at",
        ]

    def get_is_stale(self, obj: MatchScore) -> bool:
        return obj.resume_content_hash != obj.resume_profile.content_hash

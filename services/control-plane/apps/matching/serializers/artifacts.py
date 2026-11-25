from rest_framework import serializers

from apps.matching.models.artifacts import MatchArtifact, MatchArtifactKind
from apps.matching.services.copilot import (
    COPILOT_TONE_CHOICES,
    MAX_GUIDANCE_CHARS,
)


class MatchArtifactSerializer(serializers.ModelSerializer):
    is_stale = serializers.SerializerMethodField()

    class Meta:
        model = MatchArtifact
        fields = [
            "uuid",
            "match_score",
            "kind",
            "resume_content_hash",
            "content_markdown",
            "model_name",
            "is_stale",
            "created_at",
            "modified_at",
        ]
        read_only_fields = fields

    def get_is_stale(self, obj: MatchArtifact) -> bool:
        return obj.resume_content_hash != obj.match_score.resume_profile.content_hash


class MatchArtifactGenerateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=MatchArtifactKind.choices)
    regenerate = serializers.BooleanField(default=False, required=False)
    tone = serializers.ChoiceField(
        choices=COPILOT_TONE_CHOICES,
        default=None,
        allow_null=True,
        required=False,
    )
    guidance = serializers.CharField(
        max_length=MAX_GUIDANCE_CHARS,
        required=False,
        allow_blank=True,
        default="",
    )

    def validate_guidance(self, value: str) -> str:
        return value.strip()

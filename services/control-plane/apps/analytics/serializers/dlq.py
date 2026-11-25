from rest_framework import serializers

from apps.analytics.services.dlq_inspector import (
    DEFAULT_DLQ_REPLAY_LIMIT,
    MAX_DLQ_REPLAY_LIMIT,
    REPLAYABLE_TOPICS,
)


class DlqReplayRequestSerializer(serializers.Serializer):
    dry_run = serializers.BooleanField(default=True, required=False)
    event_ids = serializers.ListField(
        child=serializers.UUIDField(format="hex_verbose"),
        required=False,
        allow_empty=True,
        max_length=MAX_DLQ_REPLAY_LIMIT,
    )
    limit = serializers.IntegerField(
        min_value=1,
        max_value=MAX_DLQ_REPLAY_LIMIT,
        default=DEFAULT_DLQ_REPLAY_LIMIT,
        required=False,
    )
    original_topic = serializers.ChoiceField(
        choices=sorted(REPLAYABLE_TOPICS),
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    def validate_event_ids(self, value: list) -> list[str]:
        return [str(item) for item in value]

    def validate_original_topic(self, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None


class DlqDismissRequestSerializer(serializers.Serializer):
    event_ids = serializers.ListField(
        child=serializers.CharField(max_length=128, allow_blank=False),
        allow_empty=False,
        max_length=MAX_DLQ_REPLAY_LIMIT,
    )

    def validate_event_ids(self, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise serializers.ValidationError("At least one event_id is required.")
        return cleaned

from typing import Any

from rest_framework import serializers

from apps.jobs.models.saved_filter import SavedFilter

ALLOWED_QUERY_PARAM_KEYS = frozenset(
    {
        "search",
        "resume_profile",
        "min_score",
        "evaluated_only",
        "seniority",
        "contract_type",
        "work_mode",
        "region",
        "ats_source",
        "sort_by",
        "hide_dismissed",
        "hide_muted",
        "untracked_only",
    }
)

BOOLEAN_QUERY_PARAM_KEYS = frozenset(
    {
        "evaluated_only",
        "hide_dismissed",
        "hide_muted",
        "untracked_only",
    }
)


class SavedFilterSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedFilter
        fields = (
            "uuid",
            "name",
            "query_params",
            "created_at",
            "modified_at",
        )
        read_only_fields = ("uuid", "created_at", "modified_at")

    def validate_name(self, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise serializers.ValidationError("Preset name cannot be blank.")
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            existing = SavedFilter.objects.filter(user=request.user, name=cleaned)
            if self.instance is not None:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError(
                    "You already have a saved filter preset with this name."
                )
        return cleaned

    def validate_query_params(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise serializers.ValidationError("query_params must be a JSON object.")
        unknown_keys = set(value.keys()) - ALLOWED_QUERY_PARAM_KEYS
        if unknown_keys:
            sorted_unknown = ", ".join(sorted(unknown_keys))
            raise serializers.ValidationError(
                f"Unsupported filter parameter(s): {sorted_unknown}."
            )
        for bool_key in BOOLEAN_QUERY_PARAM_KEYS:
            if bool_key in value and not isinstance(value[bool_key], bool):
                raise serializers.ValidationError(
                    f"Filter parameter '{bool_key}' must be a boolean."
                )
        return value

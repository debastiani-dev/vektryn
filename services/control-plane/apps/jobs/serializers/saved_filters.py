from typing import Any

from rest_framework import serializers

from apps.jobs.models.saved_filter import SavedFilter
from vektryn_contracts.language import normalize_language_code

ALLOWED_QUERY_PARAM_KEYS = frozenset(
    {
        "search",
        "resume_profile",
        "min_score",
        "evaluated_only",
        "seniority",
        "contract_type",
        "work_mode",
        "language",
        "region",
        "ats_source",
        "sort_by",
        "hide_dismissed",
        "hide_muted",
        "hide_reposts",
        "untracked_only",
    }
)

BOOLEAN_QUERY_PARAM_KEYS = frozenset(
    {
        "evaluated_only",
        "hide_dismissed",
        "hide_muted",
        "hide_reposts",
        "untracked_only",
    }
)


def _normalize_language_query_param(raw_lang: Any) -> str:
    if not isinstance(raw_lang, str):
        raise serializers.ValidationError(
            "Filter parameter 'language' must be a string."
        )
    tokens = [part.strip() for part in raw_lang.split(",") if part.strip()]
    normalized_tokens: list[str] = []
    for token in tokens:
        try:
            code = normalize_language_code(token, strict=True)
        except ValueError as exc:
            raise serializers.ValidationError(
                f"Invalid language filter value: {token!r}."
            ) from exc
        if code not in normalized_tokens:
            normalized_tokens.append(code)
    return ",".join(normalized_tokens)


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
        if "language" in value and value["language"] not in (None, ""):
            normalized = _normalize_language_query_param(value["language"])
            value = {**value, "language": normalized}
        return value

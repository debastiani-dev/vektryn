from decimal import Decimal, InvalidOperation
from typing import Any

from rest_framework import serializers

from apps.jobs.models.saved_filter import SavedFilter
from apps.jobs.services.fx_rates import get_fx_snapshot
from vektryn_contracts import (
    SalaryPeriod,
    normalize_currency_code,
    resolve_annualization_multiplier,
)
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
        "min_salary",
        "max_salary",
        "salary_currency",
        "salary_period",
        "disclosed_salary_only",
    }
)

BOOLEAN_QUERY_PARAM_KEYS = frozenset(
    {
        "evaluated_only",
        "hide_dismissed",
        "hide_muted",
        "hide_reposts",
        "untracked_only",
        "disclosed_salary_only",
    }
)

_SALARY_NUMERIC_KEYS = ("min_salary", "max_salary")


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


def _parse_saved_salary_bound(raw: Any, key: str) -> Decimal | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, bool):
        raise serializers.ValidationError(f"Filter parameter '{key}' must be a number.")
    try:
        parsed = Decimal(str(raw).strip())
    except InvalidOperation as exc:
        raise serializers.ValidationError(
            f"Filter parameter '{key}' must be a valid number."
        ) from exc
    if not parsed.is_finite() or parsed < 0:
        raise serializers.ValidationError(
            f"Filter parameter '{key}' must be greater than or equal to 0."
        )
    return parsed


def _validate_salary_query_params(value: dict[str, Any]) -> dict[str, Any]:
    parsed_bounds: dict[str, Decimal | None] = {
        key: _parse_saved_salary_bound(value.get(key), key)
        for key in _SALARY_NUMERIC_KEYS
        if key in value
    }
    min_sal = parsed_bounds.get("min_salary")
    max_sal = parsed_bounds.get("max_salary")
    if min_sal is not None and max_sal is not None and max_sal < min_sal:
        raise serializers.ValidationError(
            "Filter parameter 'max_salary' must be greater than or equal to 'min_salary'."
        )

    updated = dict(value)
    if "salary_currency" in value and value["salary_currency"] not in (None, ""):
        raw_currency = value["salary_currency"]
        if not isinstance(raw_currency, str):
            raise serializers.ValidationError(
                "Filter parameter 'salary_currency' must be a string."
            )
        code = normalize_currency_code(raw_currency)
        fx_rates = get_fx_snapshot().rates
        if not code or code not in fx_rates:
            raise serializers.ValidationError(
                f"Invalid salary_currency filter value: {raw_currency!r}."
            )
        updated["salary_currency"] = code

    if "salary_period" in value and value["salary_period"] not in (None, ""):
        raw_period = value["salary_period"]
        if not isinstance(raw_period, str):
            raise serializers.ValidationError(
                "Filter parameter 'salary_period' must be a string."
            )
        cleaned = raw_period.strip().lower()
        if resolve_annualization_multiplier(cleaned) is None:
            raise serializers.ValidationError(
                f"Invalid salary_period filter value: {raw_period!r}."
            )
        updated["salary_period"] = SalaryPeriod(cleaned).value

    return updated


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
        value = _validate_salary_query_params(value)
        return value

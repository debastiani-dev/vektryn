from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.base.models.user_profile import (
    CopilotToneChoice,
    PreferredCurrency,
    PreferredGeminiModelChoice,
)
from apps.base.services.user_management import (
    validate_http_url,
    validate_iana_timezone,
)
from vektryn_contracts import normalize_api_key


class _StrictStringField(serializers.CharField):
    """CharField that rejects non-string JSON values (e.g. ints, lists, dicts)."""

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class LoginSerializer(serializers.Serializer):
    username = _StrictStringField(required=True, allow_blank=False)
    password = _StrictStringField(
        required=True, allow_blank=False, trim_whitespace=False
    )


class ChangePasswordSerializer(serializers.Serializer):
    current_password = _StrictStringField(
        write_only=True,
        required=True,
        allow_blank=False,
        trim_whitespace=False,
    )
    new_password = _StrictStringField(
        write_only=True,
        required=True,
        allow_blank=False,
        trim_whitespace=False,
    )
    confirm_password = _StrictStringField(
        write_only=True,
        required=False,
        allow_blank=False,
        trim_whitespace=False,
    )

    def validate(self, attrs: dict[str, str]) -> dict[str, str]:
        user = self.context["request"].user
        current_password = attrs["current_password"]
        new_password = attrs["new_password"]

        if not user.check_password(current_password):
            raise serializers.ValidationError(
                {"current_password": ["Current password is incorrect."]}
            )

        if new_password == current_password:
            raise serializers.ValidationError(
                {
                    "new_password": [
                        "New password must be different from your current password."
                    ]
                }
            )

        if "confirm_password" in attrs and attrs["confirm_password"] != new_password:
            raise serializers.ValidationError(
                {"confirm_password": ["New passwords do not match."]}
            )

        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)})

        return attrs


class ProfileFieldsValidationMixin:
    def validate_display_name(self, value: str) -> str:
        return value.strip()

    def validate_timezone(self, value: str) -> str:
        try:
            return validate_iana_timezone(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def _validate_link(self, value: str) -> str:
        try:
            return validate_http_url(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate_linkedin_url(self, value: str) -> str:
        return self._validate_link(value)

    def validate_github_url(self, value: str) -> str:
        return self._validate_link(value)

    def validate_portfolio_url(self, value: str) -> str:
        return self._validate_link(value)


class SelfProfileUpdateSerializer(ProfileFieldsValidationMixin, serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True, max_length=254)
    display_name = _StrictStringField(required=False, allow_blank=True, max_length=120)
    timezone = _StrictStringField(required=False, allow_blank=False, max_length=64)
    preferred_currency = serializers.ChoiceField(
        choices=PreferredCurrency.choices, required=False
    )
    default_copilot_tone = serializers.ChoiceField(
        choices=CopilotToneChoice.choices, required=False
    )
    linkedin_url = _StrictStringField(required=False, allow_blank=True, max_length=300)
    github_url = _StrictStringField(required=False, allow_blank=True, max_length=300)
    portfolio_url = _StrictStringField(required=False, allow_blank=True, max_length=300)
    gemini_api_key = _StrictStringField(
        write_only=True,
        required=False,
        allow_blank=True,
        allow_null=True,
        trim_whitespace=False,
    )
    preferred_gemini_model = serializers.ChoiceField(
        choices=PreferredGeminiModelChoice.choices, required=False
    )
    allow_model_fallback = serializers.BooleanField(required=False)

    def validate_email(self, value: str) -> str:
        return value.strip().lower()

    def validate_gemini_api_key(self, value: str | None) -> str:
        if value is None or not value.strip():
            return ""
        try:
            return normalize_api_key(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class AccountDeactivateSerializer(serializers.Serializer):
    current_password = _StrictStringField(
        write_only=True,
        required=True,
        allow_blank=False,
        trim_whitespace=False,
    )

    def validate_current_password(self, value: str) -> str:
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

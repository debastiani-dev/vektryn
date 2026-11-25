from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.base.models.user_profile import CopilotToneChoice, PreferredCurrency
from apps.base.serializers.auth import ProfileFieldsValidationMixin, _StrictStringField
from apps.base.services.user_management import serialize_profile_full

User = get_user_model()
_USERNAME_VALIDATOR = UnicodeUsernameValidator()


class StaffUserProfileInputSerializer(
    ProfileFieldsValidationMixin, serializers.Serializer
):
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


class StaffUserSerializer(serializers.ModelSerializer):
    profile = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "is_active",
            "is_staff",
            "is_superuser",
            "date_joined",
            "last_login",
            "profile",
        ]
        read_only_fields = fields

    def get_profile(self, obj) -> dict[str, str]:
        try:
            profile = obj.profile
        except User.profile.RelatedObjectDoesNotExist:
            profile = None
        if profile is not None and profile.is_deleted:
            profile = None
        return serialize_profile_full(profile)


def _reject_superuser_mutation(initial_data) -> None:
    if isinstance(initial_data, dict) and "is_superuser" in initial_data:
        raise serializers.ValidationError(
            {"is_superuser": ["is_superuser cannot be modified via the API."]}
        )


class StaffUserCreateSerializer(serializers.Serializer):
    username = _StrictStringField(required=True, allow_blank=False, max_length=150)
    email = serializers.EmailField(
        required=False, allow_blank=True, default="", max_length=254
    )
    password = _StrictStringField(
        write_only=True,
        required=True,
        allow_blank=False,
        trim_whitespace=False,
    )
    is_staff = serializers.BooleanField(required=False, default=False)
    is_active = serializers.BooleanField(required=False, default=True)
    profile = StaffUserProfileInputSerializer(required=False)

    def validate_username(self, value: str) -> str:
        cleaned = value.strip()
        try:
            _USERNAME_VALIDATOR(cleaned)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        if User.objects.filter(username__iexact=cleaned).exists():
            raise serializers.ValidationError(
                "A user with that username already exists."
            )
        return cleaned

    def validate_email(self, value: str) -> str:
        return value.strip().lower()

    def validate(self, attrs: dict) -> dict:
        _reject_superuser_mutation(self.initial_data)
        candidate_user = User(
            username=attrs["username"],
            email=attrs.get("email", ""),
        )
        try:
            validate_password(attrs["password"], user=candidate_user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs


class StaffUserUpdateSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True, max_length=254)
    is_active = serializers.BooleanField(required=False)
    is_staff = serializers.BooleanField(required=False)
    profile = StaffUserProfileInputSerializer(required=False)

    def validate_email(self, value: str) -> str:
        return value.strip().lower()

    def validate(self, attrs: dict) -> dict:
        _reject_superuser_mutation(self.initial_data)
        return attrs

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers


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

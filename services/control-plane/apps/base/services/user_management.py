from urllib.parse import urlparse
from zoneinfo import available_timezones

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.base.models.user_profile import (
    CopilotToneChoice,
    PreferredCurrency,
    UserProfile,
    get_or_create_user_profile,
)
from apps.base.services.auth_security import invalidate_user_sessions

User = get_user_model()

VALID_IANA_TIMEZONES: frozenset[str] = frozenset(available_timezones())
_HTTP_URL_VALIDATOR = URLValidator(schemes=["http", "https"])

PROFILE_MUTABLE_FIELDS: tuple[str, ...] = (
    "display_name",
    "timezone",
    "preferred_currency",
    "default_copilot_tone",
    "linkedin_url",
    "github_url",
    "portfolio_url",
)


class PrivilegedGuardError(ValueError):
    """Raised when an operation would violate active staff/superuser invariants."""


class DuplicateUsernameError(ValueError):
    """Raised when a username already exists (including concurrent races)."""


def validate_iana_timezone(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or cleaned not in VALID_IANA_TIMEZONES:
        raise ValueError(
            "Enter a valid IANA timezone (e.g., UTC, America/Sao_Paulo, America/New_York)."
        )
    return cleaned


def validate_http_url(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    try:
        _HTTP_URL_VALIDATOR(cleaned)
    except DjangoValidationError as exc:
        raise ValueError("Enter a valid http:// or https:// URL.") from exc
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Enter a valid http:// or https:// URL.")
    return cleaned


def default_profile_payload() -> dict[str, str]:
    return {
        "display_name": "",
        "timezone": "UTC",
        "preferred_currency": PreferredCurrency.USD,
        "default_copilot_tone": CopilotToneChoice.BALANCED,
        "linkedin_url": "",
        "github_url": "",
        "portfolio_url": "",
    }


def serialize_profile_summary(profile: UserProfile | None) -> dict[str, str]:
    if profile is None or profile.is_deleted:
        defaults = default_profile_payload()
        return {
            "display_name": defaults["display_name"],
            "timezone": defaults["timezone"],
            "preferred_currency": defaults["preferred_currency"],
            "default_copilot_tone": defaults["default_copilot_tone"],
        }
    return {
        "display_name": profile.display_name,
        "timezone": profile.timezone,
        "preferred_currency": profile.preferred_currency,
        "default_copilot_tone": profile.default_copilot_tone,
    }


def serialize_profile_full(profile: UserProfile | None) -> dict[str, str]:
    if profile is None or profile.is_deleted:
        return default_profile_payload()
    return {
        "display_name": profile.display_name,
        "timezone": profile.timezone,
        "preferred_currency": profile.preferred_currency,
        "default_copilot_tone": profile.default_copilot_tone,
        "linkedin_url": profile.linkedin_url,
        "github_url": profile.github_url,
        "portfolio_url": profile.portfolio_url,
    }


def _lock_privileged_users() -> None:
    list(
        User.objects.select_for_update()
        .filter(Q(is_active=True) & (Q(is_staff=True) | Q(is_superuser=True)))
        .order_by("pk")
    )


def assert_privileged_invariants(
    *,
    target_user,
    new_is_active: bool,
    new_is_staff: bool,
) -> None:
    """Enforce separate active-staff and active-superuser invariants under row lock."""
    _lock_privileged_users()

    loses_active_staff = (
        target_user.is_active
        and target_user.is_staff
        and (not new_is_active or not new_is_staff)
    )
    if loses_active_staff:
        has_other_staff = (
            User.objects.filter(is_active=True, is_staff=True)
            .exclude(pk=target_user.pk)
            .exists()
        )
        if not has_other_staff:
            raise PrivilegedGuardError(
                "Cannot deactivate or demote the last active staff account."
            )

    loses_active_superuser = (
        target_user.is_active and target_user.is_superuser and not new_is_active
    )
    if loses_active_superuser:
        has_other_superuser = (
            User.objects.filter(is_active=True, is_superuser=True)
            .exclude(pk=target_user.pk)
            .exists()
        )
        if not has_other_superuser:
            raise PrivilegedGuardError(
                "Cannot deactivate the last active superuser account."
            )


def apply_profile_updates(
    profile: UserProfile, profile_data: dict[str, str]
) -> UserProfile:
    updated_fields: list[str] = []
    for field in PROFILE_MUTABLE_FIELDS:
        if field in profile_data:
            setattr(profile, field, profile_data[field])
            updated_fields.append(field)
    if updated_fields:
        profile.save(update_fields=updated_fields)
    return profile


def update_self_profile(
    *,
    user,
    email: str | None,
    profile_data: dict[str, str],
) -> tuple[object, UserProfile]:
    with transaction.atomic():
        if email is not None and user.email != email:
            user.email = email
            user.save(update_fields=["email"])
        profile = get_or_create_user_profile(user)
        apply_profile_updates(profile, profile_data)
    return user, profile


def deactivate_self_account(user) -> None:
    with transaction.atomic():
        locked_user = User.objects.select_for_update().get(pk=user.pk)
        assert_privileged_invariants(
            target_user=locked_user,
            new_is_active=False,
            new_is_staff=locked_user.is_staff,
        )
        locked_user.is_active = False
        locked_user.save(update_fields=["is_active"])
    user.is_active = False


def create_staff_managed_user(
    *,
    username: str,
    password: str,
    email: str = "",
    is_staff: bool = False,
    is_active: bool = True,
    profile_data: dict[str, str] | None = None,
) -> tuple[object, UserProfile]:
    with transaction.atomic():
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    is_staff=is_staff,
                    is_active=is_active,
                )
        except IntegrityError as exc:
            raise DuplicateUsernameError(
                "A user with that username already exists."
            ) from exc

        profile = get_or_create_user_profile(user)
        if profile_data:
            apply_profile_updates(profile, profile_data)
    return user, profile


def update_staff_managed_user(
    *,
    target_user,
    email: str | None = None,
    is_active: bool | None = None,
    is_staff: bool | None = None,
    profile_data: dict[str, str] | None = None,
) -> tuple[object, UserProfile]:
    deactivated = False
    with transaction.atomic():
        locked_target = User.objects.select_for_update().get(pk=target_user.pk)
        next_is_active = locked_target.is_active if is_active is None else is_active
        next_is_staff = locked_target.is_staff if is_staff is None else is_staff
        assert_privileged_invariants(
            target_user=locked_target,
            new_is_active=next_is_active,
            new_is_staff=next_is_staff,
        )

        update_fields: list[str] = []
        if email is not None and locked_target.email != email:
            locked_target.email = email
            update_fields.append("email")
        if is_active is not None and locked_target.is_active != is_active:
            deactivated = locked_target.is_active and not is_active
            locked_target.is_active = is_active
            update_fields.append("is_active")
        if is_staff is not None and locked_target.is_staff != is_staff:
            locked_target.is_staff = is_staff
            update_fields.append("is_staff")
        if update_fields:
            locked_target.save(update_fields=update_fields)

        profile = get_or_create_user_profile(locked_target)
        if profile_data:
            apply_profile_updates(profile, profile_data)

    if deactivated:
        invalidate_user_sessions(locked_target.pk)
    return locked_target, profile


def soft_deactivate_staff_managed_user(*, target_user) -> tuple[object, UserProfile]:
    with transaction.atomic():
        locked_target = User.objects.select_for_update().get(pk=target_user.pk)
        assert_privileged_invariants(
            target_user=locked_target,
            new_is_active=False,
            new_is_staff=locked_target.is_staff,
        )
        if locked_target.is_active:
            locked_target.is_active = False
            locked_target.save(update_fields=["is_active"])
        profile = get_or_create_user_profile(locked_target)

    invalidate_user_sessions(locked_target.pk)
    return locked_target, profile

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from pgvector.django import VectorField

from apps.base.models.base_model import BaseModel, enum_choices
from vektryn_contracts.enums import (
    UNKNOWN_LANGUAGE,
    ContractType,
    RegionEligibility,
    SeniorityLevel,
    WorkMode,
)
from vektryn_contracts.events import EMBEDDING_DIMENSIONS
from vektryn_contracts.language import is_valid_language_code


def default_target_work_modes() -> list[str]:
    return [WorkMode.REMOTE.value]


def validate_resume_language_code(value: str) -> None:
    if not is_valid_language_code(value, allow_unknown=True):
        raise ValidationError(f"Invalid ISO 639-1 language code: {value!r}")


class ResumeProfile(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="resume_profiles",
    )
    label = models.CharField(max_length=120)

    target_seniority = ArrayField(
        base_field=models.CharField(
            max_length=32,
            choices=enum_choices(SeniorityLevel),
        ),
        default=list,
        blank=True,
    )
    target_contract_types = ArrayField(
        base_field=models.CharField(
            max_length=32,
            choices=enum_choices(ContractType),
        ),
        default=list,
        blank=True,
    )
    target_regions = ArrayField(
        base_field=models.CharField(
            max_length=32,
            choices=enum_choices(RegionEligibility),
        ),
        default=list,
        blank=True,
    )
    target_work_modes = ArrayField(
        base_field=models.CharField(
            max_length=16,
            choices=enum_choices(WorkMode),
        ),
        default=default_target_work_modes,
        blank=True,
    )
    language = models.CharField(
        max_length=16,
        default=UNKNOWN_LANGUAGE,
        db_default=UNKNOWN_LANGUAGE,
        db_index=True,
        validators=[validate_resume_language_code],
    )
    strict_language_match = models.BooleanField(
        default=False,
        db_default=False,
    )
    min_alert_score = models.PositiveSmallIntegerField(
        default=70,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    raw_text = models.TextField()
    source_file_gcs_uri = models.CharField(max_length=512, blank=True, default="")
    content_hash = models.CharField(max_length=64)

    extracted_skills = models.JSONField(default=list, blank=True)
    embedding = VectorField(
        dimensions=EMBEDDING_DIMENSIONS,
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "label"],
                condition=Q(is_deleted=False),
                name="uq_resume_profile_active_user_label",
            ),
            models.CheckConstraint(
                condition=Q(min_alert_score__gte=0) & Q(min_alert_score__lte=100),
                name="chk_resume_profile_min_alert_score_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "is_active"],
                name="idx_resume_profile_user_active",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.user})"

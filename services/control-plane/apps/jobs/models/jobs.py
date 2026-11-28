from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from pgvector.django import HnswIndex, VectorField

from apps.base.models.base_model import BaseModel, enum_choices
from vektryn_contracts.enums import (
    UNKNOWN_LANGUAGE,
    ATSSource,
    ContractType,
    RegionEligibility,
    SalaryPeriod,
    SeniorityLevel,
    WorkMode,
)
from vektryn_contracts.events import EMBEDDING_DIMENSIONS, validate_apply_url
from vektryn_contracts.language import is_valid_language_code


def validate_apply_url_field(value: str) -> None:
    try:
        validate_apply_url(value)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def validate_language_code_field(value: str) -> None:
    if not is_valid_language_code(value, allow_unknown=True):
        raise ValidationError(f"Invalid ISO 639-1 language code: {value!r}")


class JobPosting(BaseModel):
    ats_source = models.CharField(
        max_length=32,
        choices=enum_choices(ATSSource),
    )
    external_id = models.CharField(max_length=128)
    content_hash = models.CharField(max_length=64, unique=True)

    title = models.CharField(max_length=255)
    company_name = models.CharField(max_length=180)
    apply_url = models.CharField(
        max_length=512,
        validators=[validate_apply_url_field],
    )
    raw_html_gcs_uri = models.CharField(max_length=512)
    location_raw = models.CharField(max_length=255, blank=True, default="")
    description_clean = models.TextField()

    seniority = models.CharField(
        max_length=32,
        choices=enum_choices(SeniorityLevel),
        default=SeniorityLevel.UNKNOWN,
    )
    contract_type = models.CharField(
        max_length=32,
        choices=enum_choices(ContractType),
        default=ContractType.UNKNOWN,
    )
    work_mode = models.CharField(
        max_length=16,
        choices=enum_choices(WorkMode),
        default=WorkMode.UNKNOWN,
        db_default=WorkMode.UNKNOWN,
        db_index=True,
    )
    language = models.CharField(
        max_length=16,
        default=UNKNOWN_LANGUAGE,
        db_default=UNKNOWN_LANGUAGE,
        db_index=True,
        validators=[validate_language_code_field],
    )
    region_eligibility = ArrayField(
        base_field=models.CharField(
            max_length=32,
            choices=enum_choices(RegionEligibility),
        ),
        default=list,
        blank=True,
    )

    salary_min = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    salary_max = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    salary_currency = models.CharField(max_length=3, blank=True, default="")
    salary_period = models.CharField(
        max_length=16,
        choices=enum_choices(SalaryPeriod),
        null=True,
        blank=True,
    )
    salary_annual_min_usd = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, db_index=True
    )
    salary_annual_max_usd = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, db_index=True
    )
    salary_annual_mid_usd = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, db_index=True
    )
    tech_stack = models.JSONField(default=list, blank=True)

    embedding = VectorField(
        dimensions=EMBEDDING_DIMENSIONS,
        null=True,
        blank=True,
    )
    search_vector = SearchVectorField(
        null=True,
        blank=True,
        editable=False,
    )

    is_active = models.BooleanField(default=True, db_index=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    company_name_normalized = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_default="",
        db_index=True,
    )
    title_normalized = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_default="",
    )
    description_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_default="",
        db_index=True,
    )
    repost_count = models.PositiveSmallIntegerField(default=0, db_default=0)
    last_reposted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["ats_source", "external_id"],
                name="uq_job_posting_ats_external_id",
            ),
            models.CheckConstraint(
                condition=(
                    Q(salary_min__isnull=True)
                    | Q(salary_max__isnull=True)
                    | Q(salary_max__gte=F("salary_min"))
                ),
                name="chk_job_posting_salary_max_gte_min",
            ),
            models.CheckConstraint(
                condition=(
                    Q(salary_annual_max_usd__isnull=True)
                    | Q(salary_annual_min_usd__isnull=True)
                    | Q(salary_annual_max_usd__gte=F("salary_annual_min_usd"))
                ),
                name="ck_job_salary_annual_usd_order",
            ),
        ]
        indexes = [
            GinIndex(fields=["tech_stack"], name="gin_job_posting_tech_stack"),
            GinIndex(
                fields=["region_eligibility"],
                name="gin_job_posting_region_elig",
            ),
            GinIndex(
                fields=["search_vector"],
                name="gin_job_posting_search_vector",
            ),
            HnswIndex(
                name="hnsw_job_posting_embedding",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
            models.Index(
                fields=["company_name_normalized", "is_deleted", "-modified_at"],
                name="idx_job_dedup_company_active",
            ),
            models.Index(
                fields=["company_name_normalized", "description_fingerprint"],
                condition=Q(is_deleted=False) & ~Q(description_fingerprint=""),
                name="idx_job_dedup_company_fp",
            ),
            models.Index(
                fields=["-salary_annual_mid_usd"],
                condition=Q(
                    is_deleted=False,
                    is_active=True,
                    salary_annual_mid_usd__isnull=False,
                ),
                name="idx_job_salary_mid_active",
            ),
            models.Index(
                fields=["-salary_annual_max_usd"],
                condition=Q(
                    is_deleted=False,
                    is_active=True,
                    salary_annual_max_usd__isnull=False,
                ),
                name="idx_job_salary_max_active",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} @ {self.company_name} ({self.ats_source})"


class JobPostingSource(BaseModel):
    job_posting = models.ForeignKey(
        JobPosting,
        on_delete=models.CASCADE,
        related_name="sources",
    )
    ats_source = models.CharField(
        max_length=32,
        choices=enum_choices(ATSSource),
    )
    external_id = models.CharField(max_length=255)
    apply_url = models.CharField(
        max_length=512,
        validators=[validate_apply_url_field],
    )
    raw_html_gcs_uri = models.CharField(
        max_length=512,
        blank=True,
        default="",
        db_default="",
    )
    is_primary = models.BooleanField(default=False, db_default=False)
    is_active = models.BooleanField(default=True, db_default=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-is_primary", "first_seen_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["ats_source", "external_id"],
                condition=Q(is_deleted=False),
                name="uq_job_source_ats_ext",
            ),
            models.UniqueConstraint(
                fields=["job_posting"],
                condition=Q(is_primary=True, is_deleted=False),
                name="uq_job_source_single_primary",
            ),
        ]
        indexes = [
            models.Index(
                fields=["job_posting", "is_primary", "is_active"],
                name="idx_job_source_primary_active",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.ats_source}:{self.external_id} -> {self.job_posting_id}"
            f" ({'primary' if self.is_primary else 'secondary'})"
        )

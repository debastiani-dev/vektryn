from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import F, Q
from pgvector.django import HnswIndex, VectorField

from apps.base.models.base_model import BaseModel, enum_choices
from vektryn_contracts.enums import (
    ATSSource,
    ContractType,
    RegionEligibility,
    SalaryPeriod,
    SeniorityLevel,
)
from vektryn_contracts.events import EMBEDDING_DIMENSIONS


class JobPosting(BaseModel):
    ats_source = models.CharField(
        max_length=32,
        choices=enum_choices(ATSSource),
    )
    external_id = models.CharField(max_length=128)
    content_hash = models.CharField(max_length=64, unique=True)

    title = models.CharField(max_length=255)
    company_name = models.CharField(max_length=180)
    apply_url = models.URLField(max_length=512)
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
    tech_stack = models.JSONField(default=list, blank=True)

    embedding = VectorField(
        dimensions=EMBEDDING_DIMENSIONS,
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(default=True, db_index=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

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
        ]
        indexes = [
            GinIndex(fields=["tech_stack"], name="gin_job_posting_tech_stack"),
            GinIndex(
                fields=["region_eligibility"],
                name="gin_job_posting_region_elig",
            ),
            HnswIndex(
                name="hnsw_job_posting_embedding",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} @ {self.company_name} ({self.ats_source})"
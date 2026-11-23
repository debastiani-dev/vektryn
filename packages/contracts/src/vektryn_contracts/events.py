from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from vektryn_contracts.enums import (
    ATSSource,
    ContractType,
    RegionEligibility,
    SalaryPeriod,
    SeniorityLevel,
)

EMBEDDING_DIMENSIONS = 768


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    event_id: UUID = Field(default_factory=uuid4)
    schema_version: str = Field(default="1.0", min_length=1, max_length=16)
    produced_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    trace_id: str = Field(
        default="00000000000000000000000000000000",
        min_length=32,
        max_length=32,
        description="W3C OpenTelemetry 32-hex-char trace ID",
    )


class JobRawEvent(EventEnvelope):
    ats_source: ATSSource
    external_id: str = Field(min_length=1, max_length=128)
    content_hash: str = Field(min_length=64, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    company_name: str = Field(min_length=1, max_length=180)
    apply_url: HttpUrl
    raw_html_gcs_uri: str = Field(min_length=1, max_length=512)
    location_raw: str = Field(default="", max_length=255)
    description_clean: str = Field(min_length=1)
    posted_at: datetime | None = None


class JobEnrichedEvent(JobRawEvent):
    seniority: SeniorityLevel = SeniorityLevel.UNKNOWN
    contract_type: ContractType = ContractType.UNKNOWN
    region_eligibility: list[RegionEligibility] = Field(default_factory=list)
    salary_min: Decimal | None = Field(default=None, ge=0)
    salary_max: Decimal | None = Field(default=None, ge=0)
    salary_currency: str = Field(default="", max_length=3)
    salary_period: SalaryPeriod | None = None
    tech_stack: list[str] = Field(default_factory=list)
    embedding: list[float]

    @field_validator("tech_stack")
    @classmethod
    def normalize_tech_stack(cls, tags: list[str]) -> list[str]:
        seen: set[str] = set()
        normalized: list[str] = []
        for tag in tags:
            clean = tag.strip().lower()
            if clean and clean not in seen:
                seen.add(clean)
                normalized.append(clean)
        return normalized

    @field_validator("embedding")
    @classmethod
    def validate_embedding_dimensions(cls, vector: list[float]) -> list[float]:
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Expected {EMBEDDING_DIMENSIONS}-dim embedding, got {len(vector)}"
            )
        return vector

    @model_validator(mode="after")
    def validate_salary_range(self) -> "JobEnrichedEvent":
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_max < self.salary_min
        ):
            raise ValueError("salary_max must be greater than or equal to salary_min")
        return self


class JobMatchAlertEvent(EventEnvelope):
    user_id: int | UUID
    job_posting_uuid: UUID
    resume_profile_uuid: UUID
    match_score_uuid: UUID
    title: str = Field(min_length=1, max_length=255)
    company_name: str = Field(min_length=1, max_length=180)
    fit_score: int = Field(ge=0, le=100)
    cosine_similarity: float = Field(ge=0.0, le=1.0)
    matched_skills: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    apply_url: HttpUrl


class DeadLetterEvent(EventEnvelope):
    original_topic: str = Field(min_length=1, max_length=128)
    partition: int = Field(ge=0)
    offset: int = Field(ge=0)
    error_type: str = Field(min_length=1, max_length=128)
    error_message: str = Field(min_length=1)
    retry_count: int = Field(default=0, ge=0)
    raw_payload: dict[str, Any] | str
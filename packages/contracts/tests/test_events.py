from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from vektryn_contracts import (
    EMBEDDING_DIMENSIONS,
    ATSSource,
    ContractType,
    DeadLetterEvent,
    JobEnrichedEvent,
    JobMatchAlertEvent,
    JobRawEvent,
    JobRescoreEvent,
    KafkaTopic,
    RegionEligibility,
    SalaryPeriod,
    SeniorityLevel,
    alert_partition_key,
    dlq_partition_key,
    job_partition_key,
    rescore_partition_key,
    sign_stream_token,
    verify_stream_token,
)


def _sample_raw_kwargs() -> dict:
    return {
        "ats_source": ATSSource.GREENHOUSE,
        "external_id": "gh-987654",
        "content_hash": "a" * 64,
        "title": "Senior Python Backend Engineer",
        "company_name": "Acme Cloud",
        "apply_url": "https://boards.greenhouse.io/acme/jobs/987654",
        "raw_html_gcs_uri": "gs://vektryn-raw-html/greenhouse/gh-987654.html",
        "location_raw": "Remote - LATAM",
        "description_clean": "Build distributed Python, Django, and Kafka systems.",
    }


def test_job_raw_event_json_roundtrip() -> None:
    event = JobRawEvent(**_sample_raw_kwargs())
    serialized = event.model_dump_json()
    restored = JobRawEvent.model_validate_json(serialized)

    assert restored.event_id == event.event_id
    assert restored.ats_source == ATSSource.GREENHOUSE
    assert (
        job_partition_key(restored.ats_source, restored.external_id)
        == "greenhouse:gh-987654"
    )


def test_job_enriched_event_normalizes_stack_and_validates_vector() -> None:
    event = JobEnrichedEvent(
        **_sample_raw_kwargs(),
        seniority=SeniorityLevel.SENIOR,
        contract_type=ContractType.PJ,
        region_eligibility=[RegionEligibility.BRAZIL, RegionEligibility.LATAM],
        salary_min=Decimal("8000.00"),
        salary_max=Decimal("10000.00"),
        salary_currency="USD",
        salary_period=SalaryPeriod.MONTHLY,
        tech_stack=["Python", " python ", "Django", "KAFKA"],
        embedding=[0.01] * EMBEDDING_DIMENSIONS,
    )

    assert event.tech_stack == ["python", "django", "kafka"]
    assert len(event.embedding) == 768


def test_job_enriched_event_rejects_invalid_embedding_size() -> None:
    with pytest.raises(ValidationError, match="768-dim embedding"):
        JobEnrichedEvent(
            **_sample_raw_kwargs(),
            embedding=[0.1] * 512,
        )


def test_job_enriched_event_rejects_inverted_salary_range() -> None:
    with pytest.raises(ValidationError, match="salary_max"):
        JobEnrichedEvent(
            **_sample_raw_kwargs(),
            salary_min=Decimal("12000.00"),
            salary_max=Decimal("9000.00"),
            embedding=[0.0] * EMBEDDING_DIMENSIONS,
        )


def test_job_match_alert_and_dlq_contracts() -> None:
    alert = JobMatchAlertEvent(
        user_id=42,
        job_posting_uuid=uuid4(),
        resume_profile_uuid=uuid4(),
        match_score_uuid=uuid4(),
        title="Senior Python Backend Engineer",
        company_name="Acme Cloud",
        fit_score=88,
        cosine_similarity=0.84,
        matched_skills=["python", "django"],
        missing_keywords=["terraform"],
        apply_url="https://boards.greenhouse.io/acme/jobs/987654",
    )
    assert alert_partition_key(alert.user_id) == "42"

    dlq = DeadLetterEvent(
        original_topic=KafkaTopic.JOBS_RAW,
        partition=1,
        offset=104,
        error_type="ValidationError",
        error_message="Missing description_clean",
        retry_count=3,
        raw_payload={"external_id": "gh-987654"},
    )
    assert dlq_partition_key(dlq.original_topic) == "jobs.raw"


def test_stream_token_sign_and_verify() -> None:
    token = sign_stream_token("42", "super-secret", ttl_seconds=60, now=1_000_000)
    assert verify_stream_token(token, "super-secret", now=1_000_030) == "42"
    assert verify_stream_token(token, "wrong-secret", now=1_000_030) is None
    assert verify_stream_token(token, "super-secret", now=1_000_060) is None
    assert (
        verify_stream_token(f"{token}tampered", "super-secret", now=1_000_030) is None
    )


def test_job_rescore_event_defaults_bounds_and_partition_key() -> None:
    resume_uuid = uuid4()
    event = JobRescoreEvent(resume_profile_uuid=resume_uuid, user_id=42)
    restored = JobRescoreEvent.model_validate_json(event.model_dump_json())

    assert KafkaTopic.JOBS_RESCORE == "jobs.rescore"
    assert restored.resume_profile_uuid == resume_uuid
    assert restored.user_id == 42
    assert restored.max_jobs == 50
    assert restored.force is False
    assert rescore_partition_key(resume_uuid) == str(resume_uuid)

    with pytest.raises(ValidationError):
        JobRescoreEvent(resume_profile_uuid=resume_uuid, user_id=42, max_jobs=0)
    with pytest.raises(ValidationError):
        JobRescoreEvent(resume_profile_uuid=resume_uuid, user_id=42, max_jobs=101)

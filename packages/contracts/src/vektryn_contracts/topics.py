from enum import StrEnum
from uuid import UUID

from vektryn_contracts.enums import ATSSource


class KafkaTopic(StrEnum):
    JOBS_RAW = "jobs.raw"
    JOBS_ENRICHED = "jobs.enriched"
    JOBS_ALERTS = "jobs.alerts"
    JOBS_DLQ = "jobs.dlq"


def job_partition_key(ats_source: ATSSource | str, external_id: str) -> str:
    """Guarantees ordering per upstream ATS posting across partitions."""
    return f"{ats_source}:{external_id}"


def alert_partition_key(user_id: int | UUID | str) -> str:
    """Routes all live SSE match alerts for a user to the same partition."""
    return str(user_id)


def dlq_partition_key(original_topic: KafkaTopic | str) -> str:
    """Groups dead-letter events by source topic for targeted replay."""
    return str(original_topic)

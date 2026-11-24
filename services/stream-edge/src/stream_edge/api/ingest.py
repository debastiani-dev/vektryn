from datetime import datetime
import hashlib
import hmac
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, HttpUrl

from stream_edge.clients.gcs import SnapshotStorageClient
from stream_edge.clients.kafka import KafkaEventProducer
from stream_edge.config import settings
from vektryn_contracts import (
    ATSSource,
    JobRawEvent,
    KafkaTopic,
    job_partition_key,
)

router = APIRouter(prefix="/ingest", tags=["ingestion"])


class IngestJobRequest(BaseModel):
    ats_source: ATSSource
    external_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    company_name: str = Field(min_length=1, max_length=180)
    apply_url: HttpUrl
    location_raw: str = Field(default="", max_length=255)
    raw_html: str = Field(min_length=1)
    description_clean: str = Field(min_length=1)
    posted_at: datetime | None = None


class IngestJobResponse(BaseModel):
    event_id: uuid.UUID
    trace_id: str
    content_hash: str
    raw_html_gcs_uri: str
    topic: str


def _extract_trace_id(traceparent: str | None) -> str:
    """Extracts the 32-hex-char trace_id from W3C traceparent or generates a new one."""
    if traceparent:
        parts = traceparent.strip().split("-")
        if len(parts) >= 2 and len(parts[1]) == 32:
            return parts[1].lower()
    return uuid.uuid4().hex


def _compute_content_hash(
    ats_source: ATSSource,
    title: str,
    company_name: str,
    description_clean: str,
) -> str:
    canonical = "|".join(
        [
            ats_source.value,
            " ".join(title.lower().split()),
            " ".join(company_name.lower().split()),
            " ".join(description_clean.lower().split()),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_producer(request: Request) -> KafkaEventProducer:
    return request.app.state.kafka_producer


def get_storage(request: Request) -> SnapshotStorageClient:
    return request.app.state.snapshot_storage


def verify_ingest_api_key(
    x_ingest_api_key: str | None = Header(default=None, alias="X-Ingest-API-Key"),
) -> None:
    expected = settings.ingest_api_key.strip()
    if not expected:
        return
    if not x_ingest_api_key or not hmac.compare_digest(x_ingest_api_key.strip(), expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing ingest API key",
        )


@router.post(
    "/jobs",
    response_model=IngestJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_ingest_api_key)],
)
async def ingest_job(
    payload: IngestJobRequest,
    traceparent: str | None = Header(default=None),
    producer: KafkaEventProducer = Depends(get_producer),
    storage: SnapshotStorageClient = Depends(get_storage),
) -> IngestJobResponse:
    trace_id = _extract_trace_id(traceparent)
    content_hash = _compute_content_hash(
        ats_source=payload.ats_source,
        title=payload.title,
        company_name=payload.company_name,
        description_clean=payload.description_clean,
    )

    raw_html_gcs_uri = await storage.save_raw_html(
        ats_source=payload.ats_source.value,
        external_id=payload.external_id,
        content_hash=content_hash,
        raw_html=payload.raw_html,
    )

    event = JobRawEvent(
        trace_id=trace_id,
        ats_source=payload.ats_source,
        external_id=payload.external_id,
        content_hash=content_hash,
        title=payload.title,
        company_name=payload.company_name,
        apply_url=payload.apply_url,
        raw_html_gcs_uri=raw_html_gcs_uri,
        location_raw=payload.location_raw,
        description_clean=payload.description_clean,
        posted_at=payload.posted_at,
    )

    await producer.publish(
        topic=KafkaTopic.JOBS_RAW,
        key=job_partition_key(event.ats_source, event.external_id),
        event=event,
    )

    return IngestJobResponse(
        event_id=event.event_id,
        trace_id=event.trace_id,
        content_hash=event.content_hash,
        raw_html_gcs_uri=event.raw_html_gcs_uri,
        topic=KafkaTopic.JOBS_RAW.value,
    )
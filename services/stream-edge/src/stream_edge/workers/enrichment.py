import asyncio
import logging
import signal

from confluent_kafka import KafkaError

from stream_edge.clients.gemini import GeminiStreamClient
from stream_edge.clients.heartbeat import WorkerHeartbeat
from stream_edge.clients.kafka import (
    KafkaEventProducer,
    create_kafka_consumer,
    ensure_topics_exist,
)
from stream_edge.clients.notifications import persist_pipeline_error_notifications
from stream_edge.clients.redis import DedupRedisClient
from stream_edge.config import settings
from stream_edge.telemetry import (
    capture_worker_exception,
    configure_sentry,
    flush_sentry,
)
from vektryn_contracts import (
    JobEnrichedEvent,
    JobRawEvent,
    KafkaTopic,
    job_partition_key,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def process_raw_message(
    *,
    raw_bytes: bytes,
    gemini: GeminiStreamClient,
    redis_client: DedupRedisClient,
    producer: KafkaEventProducer,
) -> None:
    raw_event = JobRawEvent.model_validate_json(raw_bytes.decode("utf-8"))

    claimed = await redis_client.acquire_content_hash(raw_event.content_hash)
    if not claimed:
        logger.info(
            "Duplicate content_hash skipped: %s (%s:%s)",
            raw_event.content_hash[:12],
            raw_event.ats_source.value,
            raw_event.external_id,
        )
        return

    try:
        metadata = await gemini.extract_job_metadata(
            title=raw_event.title,
            company_name=raw_event.company_name,
            location_raw=raw_event.location_raw,
            description_clean=raw_event.description_clean,
        )
        embedding = await gemini.embed_job_text(
            title=raw_event.title,
            company_name=raw_event.company_name,
            tech_stack=metadata.tech_stack,
            description_clean=raw_event.description_clean,
        )
    except Exception:
        # Release lock so transient failures can be retried/replayed cleanly
        await redis_client.release_content_hash(raw_event.content_hash)
        raise

    enriched = JobEnrichedEvent(
        trace_id=raw_event.trace_id,
        ats_source=raw_event.ats_source,
        external_id=raw_event.external_id,
        content_hash=raw_event.content_hash,
        title=raw_event.title,
        company_name=raw_event.company_name,
        apply_url=raw_event.apply_url,
        raw_html_gcs_uri=raw_event.raw_html_gcs_uri,
        location_raw=raw_event.location_raw,
        description_clean=raw_event.description_clean,
        posted_at=raw_event.posted_at,
        submitted_by_user_id=raw_event.submitted_by_user_id,
        seniority=metadata.seniority,
        contract_type=metadata.contract_type,
        region_eligibility=metadata.region_eligibility,
        salary_min=metadata.salary_min,
        salary_max=metadata.salary_max,
        salary_currency=metadata.salary_currency,
        salary_period=metadata.salary_period,
        tech_stack=metadata.tech_stack,
        embedding=embedding,
    )

    await producer.publish(
        topic=KafkaTopic.JOBS_ENRICHED,
        key=job_partition_key(enriched.ats_source, enriched.external_id),
        event=enriched,
    )
    logger.info(
        "Enriched %s:%s -> stack=%s",
        enriched.ats_source.value,
        enriched.external_id,
        enriched.tech_stack,
    )


async def run_enrichment_worker() -> None:
    configure_sentry("enrichment-worker")
    ensure_topics_exist()
    gemini = GeminiStreamClient()
    redis_client = DedupRedisClient()
    heartbeat = WorkerHeartbeat("enrichment-worker")
    producer = KafkaEventProducer()
    consumer = create_kafka_consumer(
        group_id=settings.kafka_enrichment_group_id,
        topics=[KafkaTopic.JOBS_RAW],
    )

    running = True

    def _stop(*_args) -> None:
        nonlocal running
        running = False

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop)

    logger.info(
        "Enrichment worker started (group=%s)", settings.kafka_enrichment_group_id
    )
    await heartbeat.start()
    try:
        while running:
            msg = await asyncio.to_thread(consumer.poll, 1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    logger.error("Kafka consumer error: %s", msg.error())
                continue

            try:
                await process_raw_message(
                    raw_bytes=msg.value() or b"",
                    gemini=gemini,
                    redis_client=redis_client,
                    producer=producer,
                )
                heartbeat.record_message()
                await asyncio.to_thread(
                    consumer.commit, message=msg, asynchronous=False
                )
            except Exception as exc:
                logger.exception("Failed enriching message; routing to DLQ: %s", exc)
                capture_worker_exception(
                    exc,
                    worker="enrichment-worker",
                    topic=msg.topic(),
                )
                await producer.publish_dlq(msg=msg, error=exc)
                await asyncio.to_thread(
                    persist_pipeline_error_notifications,
                    source="enrichment-worker",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    extra_payload={"topic": msg.topic()},
                )
                await asyncio.to_thread(
                    consumer.commit, message=msg, asynchronous=False
                )
    finally:
        await heartbeat.stop()
        await redis_client.close()
        await asyncio.to_thread(producer.flush, 5.0)
        await asyncio.to_thread(consumer.close)
        flush_sentry(timeout=5.0)


if __name__ == "__main__":
    asyncio.run(run_enrichment_worker())

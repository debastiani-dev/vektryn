import asyncio
from dataclasses import dataclass
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
    UNKNOWN_LANGUAGE,
    ATSSource,
    JobEnrichedEvent,
    JobRawEvent,
    KafkaTopic,
    compute_description_fingerprint,
    detect_content_language,
    get_source_priority_rank,
    is_generic_company_name,
    job_partition_key,
    normalize_company_for_dedup,
    normalize_currency_code,
    normalize_language_code,
)

DAILY_CAP_ALERT_THROTTLE_SECONDS = 60 * 60 * 24

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _WaveGuardClaim:
    allowed: bool
    claimed: bool = False
    company_norm: str = ""
    desc_fp: str = ""
    previous_tier: int | None = None


async def _try_claim_wave_guard(
    raw_event: JobRawEvent,
    redis_client: DedupRedisClient,
) -> _WaveGuardClaim:
    if raw_event.ats_source == ATSSource.MANUAL:
        return _WaveGuardClaim(allowed=True)

    company_norm = normalize_company_for_dedup(raw_event.company_name)
    if is_generic_company_name(company_norm):
        return _WaveGuardClaim(allowed=True)

    desc_fp, fp_len = compute_description_fingerprint(
        raw_event.description_clean,
        min_chars=settings.min_dedup_desc_chars,
    )
    if not desc_fp or fp_len < settings.min_dedup_desc_chars:
        return _WaveGuardClaim(allowed=True)

    incoming_tier = get_source_priority_rank(raw_event.ats_source)
    allowed, previous_tier = await redis_client.claim_wave_fingerprint(
        company_norm,
        desc_fp,
        incoming_tier,
    )
    if not allowed:
        logger.info(
            "Suppressed equal/lower-tier wave duplicate: %s:%s (tier=%d >= cached=%s)",
            raw_event.ats_source.value,
            raw_event.external_id,
            incoming_tier,
            previous_tier,
        )
        return _WaveGuardClaim(allowed=False)

    return _WaveGuardClaim(
        allowed=True,
        claimed=True,
        company_norm=company_norm,
        desc_fp=desc_fp,
        previous_tier=previous_tier,
    )


async def _release_enrichment_locks(
    *,
    redis_client: DedupRedisClient,
    content_hash: str,
    wave_claim: _WaveGuardClaim,
    consumed_daily_quota: bool,
) -> None:
    await redis_client.release_content_hash(content_hash)
    if wave_claim.claimed:
        await redis_client.release_wave_fingerprint(
            wave_claim.company_norm,
            wave_claim.desc_fp,
            previous_tier=wave_claim.previous_tier,
        )
    if consumed_daily_quota:
        await redis_client.release_enrichment_daily_quota()


async def _consume_daily_quota_or_notify(
    *,
    raw_event: JobRawEvent,
    redis_client: DedupRedisClient,
    wave_claim: _WaveGuardClaim,
) -> tuple[bool, bool]:
    """Return (proceed, consumed_quota)."""
    daily_cap = max(0, int(settings.enrichment_daily_cap))
    if raw_event.ats_source == ATSSource.MANUAL or daily_cap <= 0:
        return True, False

    allowed, current_count = await redis_client.try_consume_enrichment_daily_quota(
        daily_cap=daily_cap
    )
    if allowed:
        return True, True

    await _release_enrichment_locks(
        redis_client=redis_client,
        content_hash=raw_event.content_hash,
        wave_claim=wave_claim,
        consumed_daily_quota=False,
    )
    logger.warning(
        "Enrichment daily cap reached (%d/%d); skipping automated job %s:%s for tomorrow's run",
        current_count,
        daily_cap,
        raw_event.ats_source.value,
        raw_event.external_id,
    )
    await asyncio.to_thread(
        persist_pipeline_error_notifications,
        source="enrichment-worker",
        error_type="EnrichmentDailyCapReached",
        error_message=(
            f"Automated enrichment daily cap ({daily_cap} jobs/day) was reached. "
            "Excess automated postings were skipped (dedup locks released for next run). "
            "Manual imports remain unaffected."
        ),
        extra_payload={"daily_cap": daily_cap},
        throttle_seconds=DAILY_CAP_ALERT_THROTTLE_SECONDS,
    )
    return False, False


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

    wave_claim = await _try_claim_wave_guard(raw_event, redis_client)
    if not wave_claim.allowed:
        return

    proceed, consumed_daily_quota = await _consume_daily_quota_or_notify(
        raw_event=raw_event,
        redis_client=redis_client,
        wave_claim=wave_claim,
    )
    if not proceed:
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
        # Release locks so transient failures can be retried/replayed cleanly
        await _release_enrichment_locks(
            redis_client=redis_client,
            content_hash=raw_event.content_hash,
            wave_claim=wave_claim,
            consumed_daily_quota=consumed_daily_quota,
        )
        raise

    resolved_language = normalize_language_code(
        getattr(metadata, "language", UNKNOWN_LANGUAGE),
        strict=False,
    )
    if resolved_language == UNKNOWN_LANGUAGE:
        resolved_language = detect_content_language(
            f"{raw_event.title}\n\n{raw_event.description_clean}"
        )

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
        work_mode=metadata.work_mode,
        language=resolved_language,
        region_eligibility=metadata.region_eligibility,
        salary_min=metadata.salary_min,
        salary_max=metadata.salary_max,
        salary_currency=normalize_currency_code(metadata.salary_currency),
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
        "Enriched %s:%s -> work_mode=%s language=%s stack=%s",
        enriched.ats_source.value,
        enriched.external_id,
        enriched.work_mode.value,
        enriched.language,
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

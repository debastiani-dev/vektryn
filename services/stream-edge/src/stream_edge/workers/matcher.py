import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
import signal
import time
import uuid

from confluent_kafka import KafkaError
from opentelemetry import trace
from pgvector.psycopg import register_vector
import psycopg

from stream_edge.clients.gemini import GeminiStreamClient
from stream_edge.clients.kafka import (
    KafkaEventProducer,
    create_kafka_consumer,
    ensure_topics_exist,
)
from stream_edge.config import settings
from stream_edge.metrics import (
    MATCH_ALERTS_EMITTED_TOTAL,
    WORKER_MESSAGES_TOTAL,
    WORKER_PROCESSING_SECONDS,
    start_worker_metrics_server,
)
from stream_edge.telemetry import configure_tracing
from vektryn_contracts import (
    JobEnrichedEvent,
    JobMatchAlertEvent,
    KafkaTopic,
    alert_partition_key,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)
tracer = trace.get_tracer("vektryn-matcher-worker")


@dataclass
class _EvaluationOutcome:
    fit_score: int | None = None
    matched_skills: list[str] | None = None
    missing_keywords: list[str] | None = None
    talking_points: list[str] | None = None
    gap_summary: str = ""
    scoring_model: str = ""


def _matches_profile_constraints(
    *,
    enriched: JobEnrichedEvent,
    target_seniority: list[str] | None,
    target_contract_types: list[str] | None,
    target_regions: list[str] | None,
) -> bool:
    if target_seniority and enriched.seniority.value != "unknown":
        if enriched.seniority.value not in target_seniority:
            return False

    if target_contract_types and enriched.contract_type.value != "unknown":
        if enriched.contract_type.value not in target_contract_types:
            return False

    if target_regions:
        job_regions = {r.value for r in enriched.region_eligibility}
        if job_regions and job_regions != {"unknown"}:
            if not (job_regions & set(target_regions)):
                return False

    return True


def _run_llm_evaluation(
    *,
    gemini: GeminiStreamClient,
    enriched: JobEnrichedEvent,
    job_posting_uuid: uuid.UUID,
    resume_uuid: uuid.UUID,
    raw_text: str,
    extracted_skills: list[str] | str | None,
    cosine_val: float,
) -> _EvaluationOutcome:
    skills_list = (
        extracted_skills
        if isinstance(extracted_skills, list)
        else json.loads(extracted_skills or "[]")
    )
    try:
        eval_result, model_used = asyncio.run(
            gemini.evaluate_resume_fit(
                resume_text=raw_text,
                resume_skills=skills_list,
                job_title=enriched.title,
                company_name=enriched.company_name,
                job_description=enriched.description_clean,
                job_stack=enriched.tech_stack,
            )
        )
        return _EvaluationOutcome(
            fit_score=eval_result.fit_score,
            matched_skills=eval_result.matched_skills,
            missing_keywords=eval_result.missing_keywords,
            talking_points=eval_result.talking_points,
            gap_summary=eval_result.gap_summary,
            scoring_model=model_used,
        )
    except Exception as exc:
        logger.warning(
            "Gap analysis failed for job=%s resume=%s (cosine=%.4f); "
            "persisting vector match without LLM score: %s",
            job_posting_uuid,
            resume_uuid,
            cosine_val,
            exc,
        )
        return _EvaluationOutcome()


def _upsert_job_posting(
    cur: psycopg.Cursor,
    enriched: JobEnrichedEvent,
    now: datetime,
) -> uuid.UUID:
    region_list = [r.value for r in enriched.region_eligibility]
    cur.execute(
        """
        INSERT INTO jobs_jobposting (
            uuid, created_at, modified_at, is_deleted,
            ats_source, external_id, content_hash,
            title, company_name, apply_url, raw_html_gcs_uri,
            location_raw, description_clean,
            seniority, contract_type, region_eligibility,
            salary_min, salary_max, salary_currency, salary_period,
            tech_stack, embedding, is_active, posted_at
        )
        VALUES (
            %s, %s, %s, FALSE,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s::jsonb, %s::vector, TRUE, %s
        )
        ON CONFLICT (ats_source, external_id) DO UPDATE SET
            modified_at = EXCLUDED.modified_at,
            content_hash = EXCLUDED.content_hash,
            title = EXCLUDED.title,
            company_name = EXCLUDED.company_name,
            apply_url = EXCLUDED.apply_url,
            raw_html_gcs_uri = EXCLUDED.raw_html_gcs_uri,
            location_raw = EXCLUDED.location_raw,
            description_clean = EXCLUDED.description_clean,
            seniority = EXCLUDED.seniority,
            contract_type = EXCLUDED.contract_type,
            region_eligibility = EXCLUDED.region_eligibility,
            salary_min = EXCLUDED.salary_min,
            salary_max = EXCLUDED.salary_max,
            salary_currency = EXCLUDED.salary_currency,
            salary_period = EXCLUDED.salary_period,
            tech_stack = EXCLUDED.tech_stack,
            embedding = EXCLUDED.embedding,
            is_active = TRUE,
            posted_at = COALESCE(EXCLUDED.posted_at, jobs_jobposting.posted_at)
        RETURNING uuid
        """,
        (
            uuid.uuid4(),
            now,
            now,
            enriched.ats_source.value,
            enriched.external_id,
            enriched.content_hash,
            enriched.title,
            enriched.company_name,
            str(enriched.apply_url),
            enriched.raw_html_gcs_uri,
            enriched.location_raw,
            enriched.description_clean,
            enriched.seniority.value,
            enriched.contract_type.value,
            region_list,
            enriched.salary_min,
            enriched.salary_max,
            enriched.salary_currency,
            enriched.salary_period.value if enriched.salary_period else None,
            json.dumps(enriched.tech_stack),
            enriched.embedding,
            enriched.posted_at,
        ),
    )
    return cur.fetchone()[0]


def _upsert_match_score(
    cur: psycopg.Cursor,
    *,
    now: datetime,
    job_posting_uuid: uuid.UUID,
    resume_uuid: uuid.UUID,
    cosine_val: float,
    outcome: _EvaluationOutcome,
    resume_hash: str,
) -> tuple[uuid.UUID, datetime | None]:
    cur.execute(
        """
        INSERT INTO matching_matchscore (
            uuid, created_at, modified_at, is_deleted,
            job_posting_id, resume_profile_id,
            cosine_similarity, fit_score,
            matched_skills, missing_keywords, talking_points, gap_summary,
            resume_content_hash, scoring_model, alert_sent_at
        )
        VALUES (
            %s, %s, %s, FALSE,
            %s, %s,
            %s, %s,
            %s::jsonb, %s::jsonb, %s::jsonb, %s,
            %s, %s, NULL
        )
        ON CONFLICT (job_posting_id, resume_profile_id) DO UPDATE SET
            modified_at = EXCLUDED.modified_at,
            cosine_similarity = EXCLUDED.cosine_similarity,
            fit_score = COALESCE(EXCLUDED.fit_score, matching_matchscore.fit_score),
            matched_skills = CASE
                WHEN EXCLUDED.fit_score IS NOT NULL THEN EXCLUDED.matched_skills
                ELSE matching_matchscore.matched_skills
            END,
            missing_keywords = CASE
                WHEN EXCLUDED.fit_score IS NOT NULL THEN EXCLUDED.missing_keywords
                ELSE matching_matchscore.missing_keywords
            END,
            talking_points = CASE
                WHEN EXCLUDED.fit_score IS NOT NULL THEN EXCLUDED.talking_points
                ELSE matching_matchscore.talking_points
            END,
            gap_summary = CASE
                WHEN EXCLUDED.fit_score IS NOT NULL THEN EXCLUDED.gap_summary
                ELSE matching_matchscore.gap_summary
            END,
            resume_content_hash = EXCLUDED.resume_content_hash,
            scoring_model = CASE
                WHEN EXCLUDED.scoring_model <> '' THEN EXCLUDED.scoring_model
                ELSE matching_matchscore.scoring_model
            END
        RETURNING uuid, alert_sent_at
        """,
        (
            uuid.uuid4(),
            now,
            now,
            job_posting_uuid,
            resume_uuid,
            cosine_val,
            outcome.fit_score,
            json.dumps(outcome.matched_skills or []),
            json.dumps(outcome.missing_keywords or []),
            json.dumps(outcome.talking_points or []),
            outcome.gap_summary,
            resume_hash,
            outcome.scoring_model,
        ),
    )
    return cur.fetchone()


def _upsert_job_and_score_sync(
    *,
    enriched: JobEnrichedEvent,
    gemini: GeminiStreamClient,
    producer: KafkaEventProducer,
) -> None:
    now = datetime.now(UTC)

    with psycopg.connect(settings.postgres_dsn, autocommit=False) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            job_posting_uuid = _upsert_job_posting(cur, enriched, now)

            cur.execute(
                """
                SELECT
                    uuid,
                    user_id,
                    label,
                    raw_text,
                    content_hash,
                    extracted_skills,
                    target_seniority,
                    target_contract_types,
                    target_regions,
                    min_alert_score,
                    GREATEST(0.0, LEAST(1.0, 1 - (embedding <=> %s::vector))) AS cosine_sim
                FROM resumes_resumeprofile
                WHERE is_deleted = FALSE
                  AND is_active = TRUE
                  AND embedding IS NOT NULL
                """,
                (enriched.embedding,),
            )
            profiles = cur.fetchall()

            for (
                resume_uuid,
                user_id,
                _label,
                raw_text,
                resume_hash,
                extracted_skills,
                target_seniority,
                target_contract_types,
                target_regions,
                min_alert_score,
                cosine_sim,
            ) in profiles:
                cosine_val = float(cosine_sim)
                should_score = (
                    cosine_val >= settings.cosine_similarity_threshold
                    and _matches_profile_constraints(
                        enriched=enriched,
                        target_seniority=target_seniority,
                        target_contract_types=target_contract_types,
                        target_regions=target_regions,
                    )
                )
                outcome = (
                    _run_llm_evaluation(
                        gemini=gemini,
                        enriched=enriched,
                        job_posting_uuid=job_posting_uuid,
                        resume_uuid=resume_uuid,
                        raw_text=raw_text,
                        extracted_skills=extracted_skills,
                        cosine_val=cosine_val,
                    )
                    if should_score
                    else _EvaluationOutcome()
                )

                match_score_uuid, alert_sent_at = _upsert_match_score(
                    cur,
                    now=now,
                    job_posting_uuid=job_posting_uuid,
                    resume_uuid=resume_uuid,
                    cosine_val=cosine_val,
                    outcome=outcome,
                    resume_hash=resume_hash,
                )

                if (
                    outcome.fit_score is not None
                    and outcome.fit_score >= min_alert_score
                    and alert_sent_at is None
                ):
                    cur.execute(
                        "UPDATE matching_matchscore SET alert_sent_at = %s, modified_at = %s WHERE uuid = %s",
                        (now, now, match_score_uuid),
                    )
                    alert_event = JobMatchAlertEvent(
                        trace_id=enriched.trace_id,
                        user_id=user_id,
                        job_posting_uuid=job_posting_uuid,
                        resume_profile_uuid=resume_uuid,
                        match_score_uuid=match_score_uuid,
                        title=enriched.title,
                        company_name=enriched.company_name,
                        fit_score=outcome.fit_score,
                        cosine_similarity=cosine_val,
                        matched_skills=outcome.matched_skills or [],
                        missing_keywords=outcome.missing_keywords or [],
                        apply_url=enriched.apply_url,
                    )
                    producer._publish_sync(
                        topic=KafkaTopic.JOBS_ALERTS,
                        key=alert_partition_key(user_id),
                        event=alert_event,
                    )
                    MATCH_ALERTS_EMITTED_TOTAL.inc()
                logger.info(
                    "Evaluated %s @ %s against resume=%s | cosine=%.4f | fit_score=%s | alert=%s",
                    enriched.title,
                    enriched.company_name,
                    resume_uuid,
                    cosine_val,
                    outcome.fit_score,
                    outcome.fit_score is not None
                    and outcome.fit_score >= min_alert_score,
                )

        conn.commit()
        producer.flush(5.0)


async def run_matcher_worker() -> None:
    configure_tracing("vektryn-matcher-worker")
    start_worker_metrics_server(9102)
    ensure_topics_exist()
    gemini = GeminiStreamClient()
    producer = KafkaEventProducer()
    consumer = create_kafka_consumer(
        group_id=settings.kafka_matcher_group_id,
        topics=[KafkaTopic.JOBS_ENRICHED],
    )

    running = True

    def _stop(*_args) -> None:
        nonlocal running
        running = False

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop)

    logger.info("Matcher worker started (group=%s)", settings.kafka_matcher_group_id)
    try:
        while running:
            msg = await asyncio.to_thread(consumer.poll, 1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    logger.error("Kafka consumer error: %s", msg.error())
                continue

            started = time.perf_counter()
            try:
                raw_value = (msg.value() or b"").decode("utf-8")
                enriched = JobEnrichedEvent.model_validate_json(raw_value)
                with tracer.start_as_current_span(
                    "matcher.upsert_and_score",
                    attributes={
                        "vektryn.ats_source": enriched.ats_source.value,
                        "vektryn.external_id": enriched.external_id,
                        "vektryn.trace_id": enriched.trace_id,
                    },
                ):
                    await asyncio.to_thread(
                        _upsert_job_and_score_sync,
                        enriched=enriched,
                        gemini=gemini,
                        producer=producer,
                    )
                WORKER_MESSAGES_TOTAL.labels(
                    worker="matcher", outcome="processed"
                ).inc()
                WORKER_MESSAGES_TOTAL.labels(
                    worker="matcher", outcome="processed"
                ).inc()
                await asyncio.to_thread(
                    consumer.commit, message=msg, asynchronous=False
                )
            except Exception as exc:
                WORKER_MESSAGES_TOTAL.labels(worker="matcher", outcome="dlq").inc()
                logger.exception("Failed matching message; routing to DLQ: %s", exc)
                await producer.publish_dlq(msg=msg, error=exc)
                await asyncio.to_thread(
                    consumer.commit, message=msg, asynchronous=False
                )
            finally:
                WORKER_PROCESSING_SECONDS.labels(worker="matcher").observe(
                    time.perf_counter() - started
                )
    finally:
        await asyncio.to_thread(producer.flush, 5.0)
        await asyncio.to_thread(consumer.close)


if __name__ == "__main__":
    asyncio.run(run_matcher_worker())

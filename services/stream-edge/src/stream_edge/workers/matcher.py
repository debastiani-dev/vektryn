import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
import signal
import uuid

from confluent_kafka import KafkaError
from pgvector.psycopg import register_vector
import psycopg

from stream_edge.clients.gemini import (
    UserGeminiScoringManager,
    UserScoringPausedError,
)
from stream_edge.clients.heartbeat import WorkerHeartbeat
from stream_edge.clients.kafka import (
    KafkaEventProducer,
    create_kafka_consumer,
    ensure_topics_exist,
)
from stream_edge.clients.notifications import (
    insert_notification_with_cursor,
    persist_pipeline_error_notifications,
    persist_user_ai_notification,
)
from stream_edge.config import settings
from stream_edge.telemetry import (
    capture_worker_error_message,
    capture_worker_exception,
    configure_sentry,
    flush_sentry,
)
from vektryn_contracts import (
    AUTO_GEMINI_MODEL,
    ATSSource,
    BYOKCryptoError,
    BYOKKeyNotConfiguredError,
    JobEnrichedEvent,
    JobMatchAlertEvent,
    JobRescoreEvent,
    KafkaTopic,
    NotificationKind,
    alert_partition_key,
    build_fernet,
    decrypt_api_key,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

MATCHER_MAX_POLL_INTERVAL_MS = 600_000


@dataclass
class _EvaluationOutcome:
    fit_score: int | None = None
    matched_skills: list[str] | None = None
    missing_keywords: list[str] | None = None
    talking_points: list[str] | None = None
    gap_summary: str = ""
    fit_highlights: list[str] | None = None
    watchout_note: str = ""
    scoring_model: str = ""


@dataclass
class _JobCandidate:
    uuid: uuid.UUID
    title: str
    company_name: str
    apply_url: str
    description_clean: str
    seniority: str
    contract_type: str
    region_eligibility: list[str]
    tech_stack: list[str]
    ats_source: str = ""
    submitted_by_user_id: int | uuid.UUID | None = None


@dataclass
class _PairScoreResult:
    alert: JobMatchAlertEvent | None = None
    scored: bool = False


def _parse_json_list(raw: list[str] | str | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return [str(item) for item in json.loads(raw or "[]")]


def _matches_profile_constraints(
    *,
    seniority: str,
    contract_type: str,
    region_eligibility: list[str],
    target_seniority: list[str] | None,
    target_contract_types: list[str] | None,
    target_regions: list[str] | None,
) -> bool:
    if target_seniority and seniority != "unknown":
        if seniority not in target_seniority:
            return False

    if target_contract_types and contract_type != "unknown":
        if contract_type not in target_contract_types:
            return False

    if target_regions:
        job_regions = set(region_eligibility)
        if job_regions and job_regions != {"unknown"}:
            if not (job_regions & set(target_regions)):
                return False

    return True


@dataclass(frozen=True)
class _UserBYOKConfig:
    api_key_encrypted: str = ""
    preferred_model: str = AUTO_GEMINI_MODEL
    allow_model_fallback: bool = True


def _decrypt_user_byok_key(
    *,
    user_id: int,
    encrypted_key: str,
    encryption_key: str,
) -> str | None:
    cleaned_ciphertext = (encrypted_key or "").strip()
    if not cleaned_ciphertext or not (encryption_key or "").strip():
        return None
    try:
        return decrypt_api_key(cleaned_ciphertext, encryption_key)
    except BYOKKeyNotConfiguredError:
        return None
    except BYOKCryptoError as exc:
        logger.warning("Unable to decrypt BYOK key for user=%s: %s", user_id, exc)
        persist_user_ai_notification(
            user_id=user_id,
            kind=NotificationKind.AI_KEY_INVALID,
            title="Gemini API key could not be decrypted",
            body=(
                "Your stored Gemini API key could not be decrypted for match scoring. "
                "Please re-enter your key in Account Settings -> AI & API Key."
            ),
            payload={"reason": "decrypt_failed", "source": "matcher-worker"},
        )
        return None


def _run_llm_evaluation(
    *,
    scoring_manager: UserGeminiScoringManager,
    user_id: int,
    api_key: str | None,
    preferred_model: str,
    allow_model_fallback: bool,
    job: _JobCandidate,
    resume_uuid: uuid.UUID,
    raw_text: str,
    extracted_skills: list[str] | str | None,
    cosine_val: float,
    propagate_pause: bool = False,
) -> _EvaluationOutcome:
    if not api_key:
        return _EvaluationOutcome()
    skills_list = _parse_json_list(extracted_skills)
    try:
        eval_result, model_used = scoring_manager.evaluate_resume_fit_sync(
            user_id=user_id,
            api_key=api_key,
            preferred_model=preferred_model,
            allow_model_fallback=allow_model_fallback,
            resume_text=raw_text,
            resume_skills=skills_list,
            job_title=job.title,
            company_name=job.company_name,
            job_description=job.description_clean,
            job_stack=job.tech_stack,
        )
        return _EvaluationOutcome(
            fit_score=eval_result.fit_score,
            matched_skills=eval_result.matched_skills,
            missing_keywords=eval_result.missing_keywords,
            talking_points=eval_result.talking_points,
            gap_summary=eval_result.gap_summary,
            fit_highlights=eval_result.fit_highlights,
            watchout_note=eval_result.watchout_note,
            scoring_model=model_used,
        )
    except UserScoringPausedError:
        if propagate_pause:
            raise
        logger.info(
            "Stage 2 skipped for paused user=%s job=%s resume=%s (cosine=%.4f)",
            user_id,
            job.uuid,
            resume_uuid,
            cosine_val,
        )
        return _EvaluationOutcome()
    except Exception as exc:
        logger.warning(
            "Gap analysis failed for user=%s job=%s resume=%s (cosine=%.4f); "
            "persisting vector match without LLM score: %s",
            user_id,
            job.uuid,
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
            is_deleted = FALSE,
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
            closed_at = NULL,
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
    replace_evaluation: bool = False,
) -> tuple[uuid.UUID, datetime | None]:
    cur.execute(
        """
        INSERT INTO matching_matchscore (
            uuid, created_at, modified_at, is_deleted,
            job_posting_id, resume_profile_id,
            cosine_similarity, fit_score,
            matched_skills, missing_keywords, talking_points,
            gap_summary, fit_highlights, watchout_note,
            resume_content_hash, scoring_model, alert_sent_at
        )
        VALUES (
            %s, %s, %s, FALSE,
            %s, %s,
            %s, %s,
            %s::jsonb, %s::jsonb, %s::jsonb,
            %s, %s::jsonb, %s,
            %s, %s, NULL
        )
        ON CONFLICT (job_posting_id, resume_profile_id) DO UPDATE SET
            modified_at = EXCLUDED.modified_at,
            cosine_similarity = EXCLUDED.cosine_similarity,
            fit_score = CASE
                WHEN %s OR EXCLUDED.resume_content_hash <> matching_matchscore.resume_content_hash
                THEN EXCLUDED.fit_score
                ELSE COALESCE(EXCLUDED.fit_score, matching_matchscore.fit_score)
            END,
            matched_skills = CASE
                WHEN %s OR EXCLUDED.resume_content_hash <> matching_matchscore.resume_content_hash OR EXCLUDED.fit_score IS NOT NULL
                THEN EXCLUDED.matched_skills
                ELSE matching_matchscore.matched_skills
            END,
            missing_keywords = CASE
                WHEN %s OR EXCLUDED.resume_content_hash <> matching_matchscore.resume_content_hash OR EXCLUDED.fit_score IS NOT NULL
                THEN EXCLUDED.missing_keywords
                ELSE matching_matchscore.missing_keywords
            END,
            talking_points = CASE
                WHEN %s OR EXCLUDED.resume_content_hash <> matching_matchscore.resume_content_hash OR EXCLUDED.fit_score IS NOT NULL
                THEN EXCLUDED.talking_points
                ELSE matching_matchscore.talking_points
            END,
            gap_summary = CASE
                WHEN %s OR EXCLUDED.resume_content_hash <> matching_matchscore.resume_content_hash OR EXCLUDED.fit_score IS NOT NULL
                THEN EXCLUDED.gap_summary
                ELSE matching_matchscore.gap_summary
            END,
            fit_highlights = CASE
                WHEN %s OR EXCLUDED.resume_content_hash <> matching_matchscore.resume_content_hash OR EXCLUDED.fit_score IS NOT NULL
                THEN EXCLUDED.fit_highlights
                ELSE matching_matchscore.fit_highlights
            END,
            watchout_note = CASE
                WHEN %s OR EXCLUDED.resume_content_hash <> matching_matchscore.resume_content_hash OR EXCLUDED.fit_score IS NOT NULL
                THEN EXCLUDED.watchout_note
                ELSE matching_matchscore.watchout_note
            END,
            resume_content_hash = EXCLUDED.resume_content_hash,
            scoring_model = CASE
                WHEN %s OR EXCLUDED.resume_content_hash <> matching_matchscore.resume_content_hash OR EXCLUDED.scoring_model <> ''
                THEN EXCLUDED.scoring_model
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
            json.dumps(outcome.fit_highlights or []),
            outcome.watchout_note,
            resume_hash,
            outcome.scoring_model,
            replace_evaluation,
            replace_evaluation,
            replace_evaluation,
            replace_evaluation,
            replace_evaluation,
            replace_evaluation,
            replace_evaluation,
            replace_evaluation,
        ),
    )
    return cur.fetchone()


def _claim_and_persist_match_alert(
    cur: psycopg.Cursor,
    *,
    now: datetime,
    trace_id: str,
    job: _JobCandidate,
    resume_uuid: uuid.UUID,
    user_id: int | uuid.UUID,
    match_score_uuid: uuid.UUID,
    cosine_val: float,
    outcome: _EvaluationOutcome,
) -> JobMatchAlertEvent | None:
    cur.execute(
        """
        UPDATE matching_matchscore
        SET alert_sent_at = %s, modified_at = %s
        WHERE uuid = %s AND alert_sent_at IS NULL
        RETURNING uuid
        """,
        (now, now, match_score_uuid),
    )
    if cur.fetchone() is None:
        return None

    notification_uuid = uuid.uuid4()
    fit_score = int(outcome.fit_score or 0)
    sim_pct = round(cosine_val * 100)
    matched_skills = outcome.matched_skills or []
    missing_keywords = outcome.missing_keywords or []

    insert_notification_with_cursor(
        cur,
        notification_uuid=notification_uuid,
        user_id=user_id,
        kind=NotificationKind.MATCH_ALERT,
        title=f"{fit_score}% Fit: {job.title}"[:255],
        body=(
            f"{job.company_name} matched your resume "
            f"({sim_pct}% vector similarity)."
        ),
        payload={
            "job_posting_uuid": str(job.uuid),
            "resume_profile_uuid": str(resume_uuid),
            "match_score_uuid": str(match_score_uuid),
            "title": job.title,
            "company_name": job.company_name,
            "fit_score": fit_score,
            "cosine_similarity": cosine_val,
            "matched_skills": matched_skills,
            "missing_keywords": missing_keywords,
            "apply_url": job.apply_url,
        },
        now=now,
    )
    return JobMatchAlertEvent(
        trace_id=trace_id,
        notification_uuid=notification_uuid,
        user_id=user_id,
        job_posting_uuid=job.uuid,
        resume_profile_uuid=resume_uuid,
        match_score_uuid=match_score_uuid,
        title=job.title,
        company_name=job.company_name,
        fit_score=fit_score,
        cosine_similarity=cosine_val,
        matched_skills=matched_skills,
        missing_keywords=missing_keywords,
        apply_url=job.apply_url,
    )


def _publish_match_alerts(
    producer: KafkaEventProducer,
    alerts: list[JobMatchAlertEvent],
) -> None:
    for alert_event in alerts:
        producer._publish_sync(
            topic=KafkaTopic.JOBS_ALERTS,
            key=alert_partition_key(alert_event.user_id),
            event=alert_event,
        )


def _persist_manual_import_ready(
    cur: psycopg.Cursor,
    *,
    now: datetime,
    job: _JobCandidate,
    resume_uuid: uuid.UUID,
    user_id: int | uuid.UUID,
    match_score_uuid: uuid.UUID,
    cosine_val: float,
    outcome: _EvaluationOutcome,
) -> None:
    if job.submitted_by_user_id is not None and str(user_id) != str(
        job.submitted_by_user_id
    ):
        return

    fit_score = int(outcome.fit_score or 0)
    sim_pct = round(cosine_val * 100)
    insert_notification_with_cursor(
        cur,
        notification_uuid=uuid.uuid4(),
        user_id=user_id,
        kind=NotificationKind.MANUAL_IMPORT_READY,
        title=f"Import scored ({fit_score}% Fit): {job.title}"[:255],
        body=(
            f"{job.company_name} is ready for gap analysis "
            f"({sim_pct}% vector similarity)."
        ),
        payload={
            "job_posting_uuid": str(job.uuid),
            "resume_profile_uuid": str(resume_uuid),
            "match_score_uuid": str(match_score_uuid),
            "title": job.title,
            "company_name": job.company_name,
            "fit_score": fit_score,
            "cosine_similarity": cosine_val,
            "matched_skills": outcome.matched_skills or [],
            "missing_keywords": outcome.missing_keywords or [],
            "apply_url": job.apply_url,
        },
        now=now,
    )


def _persist_rescore_completed(
    cur: psycopg.Cursor,
    *,
    now: datetime,
    user_id: int | uuid.UUID,
    resume_uuid: uuid.UUID,
    resume_label: str,
    processed_count: int,
    scored_count: int,
    alerts_count: int,
    force: bool,
) -> None:
    role_word = "role" if processed_count == 1 else "roles"
    alert_word = "alert" if alerts_count == 1 else "alerts"
    insert_notification_with_cursor(
        cur,
        notification_uuid=uuid.uuid4(),
        user_id=user_id,
        kind=NotificationKind.RESCORE_COMPLETED,
        title=f"Rescore complete: {resume_label}"[:255],
        body=(
            f"Evaluated {processed_count} active {role_word} "
            f"({scored_count} AI-scored, {alerts_count} high-fit {alert_word})."
        ),
        payload={
            "resume_profile_uuid": str(resume_uuid),
            "resume_label": resume_label,
            "processed_count": processed_count,
            "scored_count": scored_count,
            "alerts_count": alerts_count,
            "force": force,
        },
        now=now,
    )


def _score_and_persist_pair(
    cur: psycopg.Cursor,
    *,
    now: datetime,
    trace_id: str,
    job: _JobCandidate,
    resume_uuid: uuid.UUID,
    user_id: int | uuid.UUID,
    raw_text: str,
    resume_hash: str,
    extracted_skills: list[str] | str | None,
    target_seniority: list[str] | None,
    target_contract_types: list[str] | None,
    target_regions: list[str] | None,
    min_alert_score: int,
    cosine_val: float,
    scoring_manager: UserGeminiScoringManager,
    user_api_key: str | None,
    preferred_model: str = AUTO_GEMINI_MODEL,
    allow_model_fallback: bool = True,
    replace_evaluation: bool = False,
    notify_manual_import: bool = False,
    propagate_pause: bool = False,
) -> _PairScoreResult:
    is_manual = job.ats_source == ATSSource.MANUAL.value
    should_score = bool(user_api_key) and (
        is_manual
        or (
            cosine_val >= settings.cosine_similarity_threshold
            and _matches_profile_constraints(
                seniority=job.seniority,
                contract_type=job.contract_type,
                region_eligibility=job.region_eligibility,
                target_seniority=target_seniority,
                target_contract_types=target_contract_types,
                target_regions=target_regions,
            )
        )
    )
    outcome = (
        _run_llm_evaluation(
            scoring_manager=scoring_manager,
            user_id=int(user_id),
            api_key=user_api_key,
            preferred_model=preferred_model,
            allow_model_fallback=allow_model_fallback,
            job=job,
            resume_uuid=resume_uuid,
            raw_text=raw_text,
            extracted_skills=extracted_skills,
            cosine_val=cosine_val,
            propagate_pause=propagate_pause,
        )
        if should_score
        else _EvaluationOutcome()
    )

    match_score_uuid, _alert_sent_at = _upsert_match_score(
        cur,
        now=now,
        job_posting_uuid=job.uuid,
        resume_uuid=resume_uuid,
        cosine_val=cosine_val,
        outcome=outcome,
        resume_hash=resume_hash,
        replace_evaluation=replace_evaluation,
    )

    pending_alert: JobMatchAlertEvent | None = None
    if outcome.fit_score is not None and outcome.fit_score >= min_alert_score:
        pending_alert = _claim_and_persist_match_alert(
            cur,
            now=now,
            trace_id=trace_id,
            job=job,
            resume_uuid=resume_uuid,
            user_id=user_id,
            match_score_uuid=match_score_uuid,
            cosine_val=cosine_val,
            outcome=outcome,
        )
    elif is_manual and notify_manual_import and outcome.fit_score is not None:
        _persist_manual_import_ready(
            cur,
            now=now,
            job=job,
            resume_uuid=resume_uuid,
            user_id=user_id,
            match_score_uuid=match_score_uuid,
            cosine_val=cosine_val,
            outcome=outcome,
        )
    logger.info(
        "Evaluated %s @ %s against resume=%s | cosine=%.4f | fit_score=%s | alert=%s",
        job.title,
        job.company_name,
        resume_uuid,
        cosine_val,
        outcome.fit_score,
        pending_alert is not None,
    )
    return _PairScoreResult(
        alert=pending_alert,
        scored=outcome.fit_score is not None,
    )


def _upsert_job_and_score_sync(
    *,
    enriched: JobEnrichedEvent,
    scoring_manager: UserGeminiScoringManager,
    producer: KafkaEventProducer,
    byok_encryption_key: str | None = None,
) -> None:
    now = datetime.now(UTC)
    encryption_key = (
        settings.byok_encryption_key
        if byok_encryption_key is None
        else byok_encryption_key
    )

    with psycopg.connect(settings.postgres_dsn, autocommit=False) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            job_posting_uuid = _upsert_job_posting(cur, enriched, now)
            candidate = _JobCandidate(
                uuid=job_posting_uuid,
                title=enriched.title,
                company_name=enriched.company_name,
                apply_url=str(enriched.apply_url),
                description_clean=enriched.description_clean,
                seniority=enriched.seniority.value,
                contract_type=enriched.contract_type.value,
                region_eligibility=[r.value for r in enriched.region_eligibility],
                tech_stack=enriched.tech_stack,
                ats_source=enriched.ats_source.value,
                submitted_by_user_id=enriched.submitted_by_user_id,
            )

            cur.execute(
                """
                SELECT
                    r.uuid,
                    r.user_id,
                    r.label,
                    r.raw_text,
                    r.content_hash,
                    r.extracted_skills,
                    r.target_seniority,
                    r.target_contract_types,
                    r.target_regions,
                    r.min_alert_score,
                    GREATEST(0.0, LEAST(1.0, 1 - (r.embedding <=> %s::vector))) AS cosine_sim,
                    COALESCE(p.gemini_api_key_encrypted, '') AS gemini_api_key_encrypted,
                    COALESCE(p.preferred_gemini_model, 'auto') AS preferred_gemini_model,
                    COALESCE(p.allow_model_fallback, TRUE) AS allow_model_fallback
                FROM resumes_resumeprofile r
                INNER JOIN auth_user u
                  ON u.id = r.user_id
                 AND u.is_active = TRUE
                LEFT JOIN base_userprofile p
                  ON p.user_id = r.user_id
                 AND p.is_deleted = FALSE
                WHERE r.is_deleted = FALSE
                  AND r.is_active = TRUE
                  AND r.embedding IS NOT NULL
                """,
                (enriched.embedding,),
            )
            profiles = cur.fetchall()

            pending_alerts: list[JobMatchAlertEvent] = []
            for row in profiles:
                (
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
                    *byok_cols,
                ) = row
                encrypted_key = (
                    str(byok_cols[0]) if len(byok_cols) >= 1 and byok_cols[0] else ""
                )
                preferred_model = (
                    str(byok_cols[1])
                    if len(byok_cols) >= 2 and byok_cols[1]
                    else AUTO_GEMINI_MODEL
                )
                allow_fallback = bool(byok_cols[2]) if len(byok_cols) >= 3 else True

                try:
                    user_api_key = _decrypt_user_byok_key(
                        user_id=int(user_id),
                        encrypted_key=encrypted_key,
                        encryption_key=encryption_key,
                    )
                    pair_result = _score_and_persist_pair(
                        cur,
                        now=now,
                        trace_id=enriched.trace_id,
                        job=candidate,
                        resume_uuid=resume_uuid,
                        user_id=user_id,
                        raw_text=raw_text,
                        resume_hash=resume_hash,
                        extracted_skills=extracted_skills,
                        target_seniority=target_seniority,
                        target_contract_types=target_contract_types,
                        target_regions=target_regions,
                        min_alert_score=min_alert_score,
                        cosine_val=float(cosine_sim),
                        scoring_manager=scoring_manager,
                        user_api_key=user_api_key,
                        preferred_model=preferred_model,
                        allow_model_fallback=allow_fallback,
                        replace_evaluation=False,
                        notify_manual_import=True,
                        propagate_pause=False,
                    )
                    if pair_result.alert is not None:
                        pending_alerts.append(pair_result.alert)
                except Exception as exc:
                    logger.warning(
                        "Per-user scoring boundary caught error for user=%s resume=%s job=%s: %s",
                        user_id,
                        resume_uuid,
                        job_posting_uuid,
                        exc,
                    )

        conn.commit()
        if pending_alerts:
            _publish_match_alerts(producer, pending_alerts)
        producer.flush(5.0)


def _select_rescore_candidates(
    cur: psycopg.Cursor,
    *,
    resume_uuid: uuid.UUID,
    resume_hash: str,
    resume_embedding: object,
    max_jobs: int,
    force: bool,
    produced_at: datetime,
) -> list[tuple]:
    if force:
        cur.execute(
            """
            SELECT
                j.uuid,
                j.title,
                j.company_name,
                j.apply_url,
                j.description_clean,
                j.seniority,
                j.contract_type,
                j.region_eligibility,
                j.tech_stack,
                GREATEST(0.0, LEAST(1.0, 1 - (j.embedding <=> %s::vector))) AS cosine_sim,
                j.ats_source
            FROM jobs_jobposting j
            LEFT JOIN matching_matchscore m
              ON m.job_posting_id = j.uuid
             AND m.resume_profile_id = %s
             AND m.is_deleted = FALSE
            WHERE j.is_deleted = FALSE
              AND j.is_active = TRUE
              AND j.embedding IS NOT NULL
              AND (m.uuid IS NULL OR m.modified_at < %s)
            ORDER BY j.embedding <=> %s::vector ASC
            LIMIT %s
            """,
            (resume_embedding, resume_uuid, produced_at, resume_embedding, max_jobs),
        )
        return cur.fetchall()

    # Query 1: refresh existing stale MatchScore rows first so visible UI badges never starve
    cur.execute(
        """
        SELECT
            j.uuid,
            j.title,
            j.company_name,
            j.apply_url,
            j.description_clean,
            j.seniority,
            j.contract_type,
            j.region_eligibility,
            j.tech_stack,
            GREATEST(0.0, LEAST(1.0, 1 - (j.embedding <=> %s::vector))) AS cosine_sim,
            j.ats_source
        FROM jobs_jobposting j
        INNER JOIN matching_matchscore m
          ON m.job_posting_id = j.uuid
         AND m.resume_profile_id = %s
         AND m.is_deleted = FALSE
        WHERE j.is_deleted = FALSE
          AND j.is_active = TRUE
          AND j.embedding IS NOT NULL
          AND m.resume_content_hash <> %s
        ORDER BY j.embedding <=> %s::vector ASC
        LIMIT %s
        """,
        (resume_embedding, resume_uuid, resume_hash, resume_embedding, max_jobs),
    )
    rows = list(cur.fetchall())
    remaining = max_jobs - len(rows)
    if remaining <= 0:
        return rows

    # Query 2: backfill unscored active jobs ordered by ascending cosine distance (HNSW index)
    cur.execute(
        """
        SELECT
            j.uuid,
            j.title,
            j.company_name,
            j.apply_url,
            j.description_clean,
            j.seniority,
            j.contract_type,
            j.region_eligibility,
            j.tech_stack,
            GREATEST(0.0, LEAST(1.0, 1 - (j.embedding <=> %s::vector))) AS cosine_sim,
            j.ats_source
        FROM jobs_jobposting j
        WHERE j.is_deleted = FALSE
          AND j.is_active = TRUE
          AND j.embedding IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM matching_matchscore m
              WHERE m.job_posting_id = j.uuid
                AND m.resume_profile_id = %s
                AND m.is_deleted = FALSE
          )
        ORDER BY j.embedding <=> %s::vector ASC
        LIMIT %s
        """,
        (resume_embedding, resume_uuid, resume_embedding, remaining),
    )
    rows.extend(cur.fetchall())
    return rows


@dataclass(frozen=True)
class _RescoreContext:
    resume_uuid: uuid.UUID
    user_id: int | uuid.UUID
    raw_text: str
    resume_hash: str
    extracted_skills: list[str] | str | None
    target_seniority: list[str] | None
    target_contract_types: list[str] | None
    target_regions: list[str] | None
    min_alert_score: int
    resume_embedding: object
    resume_label: str
    user_api_key: str
    preferred_model: str
    allow_fallback: bool


def _load_rescore_context(
    cur: psycopg.Cursor,
    *,
    event: JobRescoreEvent,
    scoring_manager: UserGeminiScoringManager,
    encryption_key: str,
) -> _RescoreContext | None:
    cur.execute(
        """
        SELECT
            r.uuid,
            r.user_id,
            r.raw_text,
            r.content_hash,
            r.extracted_skills,
            r.target_seniority,
            r.target_contract_types,
            r.target_regions,
            r.min_alert_score,
            r.embedding,
            r.label,
            COALESCE(p.gemini_api_key_encrypted, '') AS gemini_api_key_encrypted,
            COALESCE(p.preferred_gemini_model, 'auto') AS preferred_gemini_model,
            COALESCE(p.allow_model_fallback, TRUE) AS allow_model_fallback
        FROM resumes_resumeprofile r
        INNER JOIN auth_user u
          ON u.id = r.user_id
         AND u.is_active = TRUE
        LEFT JOIN base_userprofile p
          ON p.user_id = r.user_id
         AND p.is_deleted = FALSE
        WHERE r.uuid = %s
          AND r.is_deleted = FALSE
          AND r.is_active = TRUE
          AND r.embedding IS NOT NULL
        """,
        (event.resume_profile_uuid,),
    )
    profile_row = cur.fetchone()
    if profile_row is None:
        logger.info(
            "Skipping jobs.rescore for resume=%s (not found, inactive user/resume, or missing embedding)",
            event.resume_profile_uuid,
        )
        return None

    (
        resume_uuid,
        user_id,
        raw_text,
        resume_hash,
        extracted_skills,
        target_seniority,
        target_contract_types,
        target_regions,
        min_alert_score,
        resume_embedding,
        *extra_profile,
    ) = profile_row
    resume_label = (
        str(extra_profile[0]).strip()
        if extra_profile and extra_profile[0]
        else "Active Resume"
    )
    encrypted_key = (
        str(extra_profile[1]) if len(extra_profile) >= 2 and extra_profile[1] else ""
    )
    preferred_model = (
        str(extra_profile[2])
        if len(extra_profile) >= 3 and extra_profile[2]
        else AUTO_GEMINI_MODEL
    )
    allow_fallback = bool(extra_profile[3]) if len(extra_profile) >= 4 else True

    user_api_key = _decrypt_user_byok_key(
        user_id=int(user_id),
        encrypted_key=encrypted_key,
        encryption_key=encryption_key,
    )
    if not user_api_key:
        logger.info(
            "Skipping jobs.rescore for keyless user=%s resume=%s to preserve existing scores",
            user_id,
            resume_uuid,
        )
        return None

    if scoring_manager.get_pause_state(int(user_id)) is not None:
        logger.info(
            "Skipping jobs.rescore for paused user=%s resume=%s",
            user_id,
            resume_uuid,
        )
        return None

    return _RescoreContext(
        resume_uuid=resume_uuid,
        user_id=user_id,
        raw_text=raw_text,
        resume_hash=resume_hash,
        extracted_skills=extracted_skills,
        target_seniority=target_seniority,
        target_contract_types=target_contract_types,
        target_regions=target_regions,
        min_alert_score=min_alert_score,
        resume_embedding=resume_embedding,
        resume_label=resume_label,
        user_api_key=user_api_key,
        preferred_model=preferred_model,
        allow_fallback=allow_fallback,
    )


def _row_to_job_candidate(row: tuple) -> tuple[_JobCandidate, float]:
    (
        job_uuid,
        title,
        company_name,
        apply_url,
        description_clean,
        seniority,
        contract_type,
        region_eligibility,
        tech_stack,
        cosine_sim,
        *rest,
    ) = row
    ats_source = str(rest[0]) if rest else ""
    return (
        _JobCandidate(
            uuid=job_uuid,
            title=title,
            company_name=company_name,
            apply_url=apply_url,
            description_clean=description_clean,
            seniority=seniority,
            contract_type=contract_type,
            region_eligibility=list(region_eligibility or []),
            tech_stack=_parse_json_list(tech_stack),
            ats_source=ats_source,
        ),
        float(cosine_sim),
    )


def _score_rescore_candidates(
    conn: psycopg.Connection,
    cur: psycopg.Cursor,
    *,
    ctx: _RescoreContext,
    event: JobRescoreEvent,
    candidates: list[tuple],
    scoring_manager: UserGeminiScoringManager,
    producer: KafkaEventProducer,
) -> tuple[int, int, int]:
    processed = 0
    scored_count = 0
    alerts_count = 0
    for row in candidates:
        candidate, cosine_val = _row_to_job_candidate(row)
        try:
            pair_result = _score_and_persist_pair(
                cur,
                now=datetime.now(UTC),
                trace_id=event.trace_id,
                job=candidate,
                resume_uuid=ctx.resume_uuid,
                user_id=ctx.user_id,
                raw_text=ctx.raw_text,
                resume_hash=ctx.resume_hash,
                extracted_skills=ctx.extracted_skills,
                target_seniority=ctx.target_seniority,
                target_contract_types=ctx.target_contract_types,
                target_regions=ctx.target_regions,
                min_alert_score=ctx.min_alert_score,
                cosine_val=cosine_val,
                scoring_manager=scoring_manager,
                user_api_key=ctx.user_api_key,
                preferred_model=ctx.preferred_model,
                allow_model_fallback=ctx.allow_fallback,
                replace_evaluation=True,
                propagate_pause=True,
            )
        except UserScoringPausedError as exc:
            logger.info(
                "Stopping jobs.rescore early for user=%s resume=%s after %d jobs (%s)",
                ctx.user_id,
                ctx.resume_uuid,
                processed,
                exc.action.value,
            )
            break

        # Commit per job so partial progress survives restarts and retries stay idempotent
        conn.commit()
        if pair_result.scored:
            scored_count += 1
        if pair_result.alert is not None:
            alerts_count += 1
            _publish_match_alerts(producer, [pair_result.alert])
        processed += 1
    return processed, scored_count, alerts_count


def _rescore_resume_sync(
    *,
    event: JobRescoreEvent,
    scoring_manager: UserGeminiScoringManager,
    producer: KafkaEventProducer,
    byok_encryption_key: str | None = None,
) -> int:
    encryption_key = (
        settings.byok_encryption_key
        if byok_encryption_key is None
        else byok_encryption_key
    )
    with psycopg.connect(settings.postgres_dsn, autocommit=False) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            ctx = _load_rescore_context(
                cur,
                event=event,
                scoring_manager=scoring_manager,
                encryption_key=encryption_key,
            )
            if ctx is None:
                return 0

            candidates = _select_rescore_candidates(
                cur,
                resume_uuid=ctx.resume_uuid,
                resume_hash=ctx.resume_hash,
                resume_embedding=ctx.resume_embedding,
                max_jobs=event.max_jobs,
                force=event.force,
                produced_at=event.produced_at,
            )
            processed, scored_count, alerts_count = _score_rescore_candidates(
                conn,
                cur,
                ctx=ctx,
                event=event,
                candidates=candidates,
                scoring_manager=scoring_manager,
                producer=producer,
            )
            if processed > 0:
                _persist_rescore_completed(
                    cur,
                    now=datetime.now(UTC),
                    user_id=ctx.user_id,
                    resume_uuid=ctx.resume_uuid,
                    resume_label=ctx.resume_label,
                    processed_count=processed,
                    scored_count=scored_count,
                    alerts_count=alerts_count,
                    force=event.force,
                )
                conn.commit()

        producer.flush(5.0)
        logger.info(
            "Rescore complete for resume=%s | processed=%d | max_jobs=%d | force=%s",
            ctx.resume_uuid,
            processed,
            event.max_jobs,
            event.force,
        )
        return processed


def _validate_byok_encryption_key_once() -> str:
    raw = (settings.byok_encryption_key or "").strip()
    try:
        build_fernet(raw)
        return raw
    except BYOKKeyNotConfiguredError as exc:
        logger.error(
            "BYOK_ENCRYPTION_KEY is missing or invalid in matcher-worker (%s). "
            "Treating all users as keyless (Stage 1 cosine matching continues).",
            exc,
        )
        capture_worker_error_message(
            "BYOK_ENCRYPTION_KEY is missing or invalid in matcher-worker; Stage 2 AI scoring paused.",
            worker="matcher-worker",
            error_type="BYOKKeyNotConfiguredError",
        )
        return ""


async def run_matcher_worker() -> None:
    configure_sentry("matcher-worker")
    ensure_topics_exist()
    byok_key = _validate_byok_encryption_key_once()
    scoring_manager = UserGeminiScoringManager()
    heartbeat = WorkerHeartbeat("matcher-worker")
    producer = KafkaEventProducer()
    consumer = create_kafka_consumer(
        group_id=settings.kafka_matcher_group_id,
        topics=[KafkaTopic.JOBS_ENRICHED, KafkaTopic.JOBS_RESCORE],
        max_poll_interval_ms=MATCHER_MAX_POLL_INTERVAL_MS,
    )

    running = True

    def _stop(*_args) -> None:
        nonlocal running
        running = False

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop)

    logger.info(
        "Matcher worker started (group=%s, topics=[%s, %s], byok_ready=%s)",
        settings.kafka_matcher_group_id,
        KafkaTopic.JOBS_ENRICHED.value,
        KafkaTopic.JOBS_RESCORE.value,
        bool(byok_key),
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
                raw_value = (msg.value() or b"").decode("utf-8")
                topic = msg.topic()
                if topic == KafkaTopic.JOBS_RESCORE.value:
                    rescore_event = JobRescoreEvent.model_validate_json(raw_value)
                    await asyncio.to_thread(
                        _rescore_resume_sync,
                        event=rescore_event,
                        scoring_manager=scoring_manager,
                        producer=producer,
                        byok_encryption_key=byok_key,
                    )
                else:
                    enriched = JobEnrichedEvent.model_validate_json(raw_value)
                    await asyncio.to_thread(
                        _upsert_job_and_score_sync,
                        enriched=enriched,
                        scoring_manager=scoring_manager,
                        producer=producer,
                        byok_encryption_key=byok_key,
                    )
                heartbeat.record_message()
                await asyncio.to_thread(
                    consumer.commit, message=msg, asynchronous=False
                )
            except Exception as exc:
                logger.exception("Failed matching message; routing to DLQ: %s", exc)
                capture_worker_exception(
                    exc,
                    worker="matcher-worker",
                    topic=msg.topic(),
                )
                await producer.publish_dlq(msg=msg, error=exc)
                await asyncio.to_thread(
                    persist_pipeline_error_notifications,
                    source="matcher-worker",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    extra_payload={"topic": msg.topic()},
                )
                await asyncio.to_thread(
                    consumer.commit, message=msg, asynchronous=False
                )
    finally:
        await heartbeat.stop()
        await asyncio.to_thread(producer.flush, 5.0)
        await asyncio.to_thread(consumer.close)
        flush_sentry(timeout=5.0)


if __name__ == "__main__":
    asyncio.run(run_matcher_worker())

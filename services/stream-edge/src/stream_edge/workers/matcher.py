import asyncio
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
import logging
import math
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
    UNKNOWN_LANGUAGE,
    ATSSource,
    BYOKCryptoError,
    BYOKKeyNotConfiguredError,
    JobEnrichedEvent,
    JobMatchAlertEvent,
    JobRescoreEvent,
    KafkaTopic,
    NotificationKind,
    alert_partition_key,
    are_regions_compatible,
    build_fernet,
    compute_description_fingerprint,
    decrypt_api_key,
    get_source_priority_rank,
    is_direct_ats_source,
    is_generic_company_name,
    normalize_company_for_dedup,
    normalize_language_code,
    normalize_title_for_dedup,
    token_jaccard_similarity,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

MATCHER_MAX_POLL_INTERVAL_MS = 600_000
_EPOCH_UTC = datetime.fromtimestamp(0, tz=UTC)


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
    work_mode: str = "unknown"
    language: str = UNKNOWN_LANGUAGE
    ats_source: str = ""
    submitted_by_user_id: int | uuid.UUID | None = None
    incoming_ats_source: str = ""
    merged_into_existing: bool = False


@dataclass(frozen=True)
class _ActiveProfile:
    uuid: uuid.UUID
    user_id: int | uuid.UUID
    label: str
    raw_text: str
    content_hash: str
    extracted_skills: list[str] | str | None
    target_seniority: list[str] | None
    target_contract_types: list[str] | None
    target_regions: list[str] | None
    min_alert_score: int
    cosine_similarity: float = 0.0
    target_work_modes: list[str] | None = None
    language: str = UNKNOWN_LANGUAGE
    strict_language_match: bool = False
    modified_at: datetime = field(default_factory=lambda: _EPOCH_UTC)
    embedding: object = None
    api_key_encrypted: str = ""
    preferred_model: str = AUTO_GEMINI_MODEL
    allow_model_fallback: bool = True


@dataclass
class _PairScoreResult:
    alert: JobMatchAlertEvent | None = None
    scored: bool = False


@dataclass(frozen=True)
class _RescoreCandidateState:
    job: _JobCandidate
    target_cosine: float
    job_embedding: object = None
    existing_resume_hash: str | None = None
    existing_fit_score: int | None = None
    target_is_routed_winner: bool | None = None


def _parse_json_list(raw: list[str] | str | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return [str(item) for item in json.loads(raw or "[]")]


def _coerce_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return _EPOCH_UTC


def _coerce_vector(raw: object) -> list[float] | None:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        return [float(v) for v in raw]
    if hasattr(raw, "tolist"):
        converted = raw.tolist()
        if isinstance(converted, list):
            return [float(v) for v in converted]
    if isinstance(raw, str) and raw.startswith("[") and raw.endswith("]"):
        return [float(item) for item in json.loads(raw)]
    return None


def _vector_cosine_similarity(vec_a: object, vec_b: object) -> float:
    a = _coerce_vector(vec_a)
    b = _coerce_vector(vec_b)
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if math.isclose(norm_a, 0.0, abs_tol=1e-12) or math.isclose(
        norm_b, 0.0, abs_tol=1e-12
    ):
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def _matches_profile_constraints(
    *,
    seniority: str,
    contract_type: str,
    region_eligibility: list[str],
    target_seniority: list[str] | None,
    target_contract_types: list[str] | None,
    target_regions: list[str] | None,
    work_mode: str = "unknown",
    target_work_modes: list[str] | None = None,
) -> bool:
    if target_work_modes and work_mode not in target_work_modes:
        return False

    if (
        target_seniority
        and seniority != "unknown"
        and seniority not in target_seniority
    ):
        return False

    if (
        target_contract_types
        and contract_type != "unknown"
        and contract_type not in target_contract_types
    ):
        return False

    if target_regions:
        job_regions = set(region_eligibility)
        if job_regions and job_regions != {"unknown"}:
            if not (job_regions & set(target_regions)):
                return False

    return True


def is_profile_eligible(profile: _ActiveProfile, job: _JobCandidate) -> bool:
    """Step 1: Evaluate hard targeting gates and strict_language_match."""
    if not _matches_profile_constraints(
        seniority=job.seniority,
        contract_type=job.contract_type,
        region_eligibility=job.region_eligibility,
        target_seniority=profile.target_seniority,
        target_contract_types=profile.target_contract_types,
        target_regions=profile.target_regions,
        work_mode=job.work_mode,
        target_work_modes=profile.target_work_modes,
    ):
        return False

    job_lang = normalize_language_code(job.language, strict=False)
    profile_lang = normalize_language_code(profile.language, strict=False)
    if (
        profile.strict_language_match
        and job_lang != UNKNOWN_LANGUAGE
        and profile_lang != UNKNOWN_LANGUAGE
        and profile_lang != job_lang
    ):
        return False

    return True


def select_winning_profile(
    profiles: Sequence[_ActiveProfile],
    job: _JobCandidate,
    *,
    ignore_gates: bool = False,
) -> _ActiveProfile | None:
    """Steps 1-3: Deterministic language-aware single-winner router for one user."""
    eligible = (
        list(profiles)
        if ignore_gates
        else [p for p in profiles if is_profile_eligible(p, job)]
    )
    if not eligible:
        return None

    job_lang = normalize_language_code(job.language, strict=False)
    if job_lang != UNKNOWN_LANGUAGE:
        same_lang = [
            p
            for p in eligible
            if normalize_language_code(p.language, strict=False) == job_lang
        ]
        pool = same_lang if same_lang else eligible
    else:
        pool = eligible

    pool.sort(
        key=lambda p: (
            -float(p.cosine_similarity),
            -_coerce_datetime(p.modified_at).timestamp(),
            str(p.uuid),
        )
    )
    return pool[0]


def _acquire_winner_lock(
    cur: psycopg.Cursor,
    *,
    user_id: int | uuid.UUID,
    job_posting_uuid: uuid.UUID,
) -> None:
    """Acquire standardized 64-bit transaction-scoped advisory lock on (user, job)."""
    cur.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended('vektryn:winner:' || %s || ':' || %s, 0))",
        (str(user_id), str(job_posting_uuid)),
    )


def _demote_sibling_winners(
    cur: psycopg.Cursor,
    *,
    user_id: int | uuid.UUID,
    job_posting_uuid: uuid.UUID,
    winner_resume_uuid: uuid.UUID,
    now: datetime,
) -> None:
    cur.execute(
        """
        UPDATE matching_matchscore ms
        SET is_routed_winner = FALSE, modified_at = %s
        FROM resumes_resumeprofile rp
        WHERE ms.resume_profile_id = rp.uuid
          AND rp.user_id = %s
          AND ms.job_posting_id = %s
          AND ms.resume_profile_id <> %s
          AND ms.is_routed_winner = TRUE
        """,
        (now, user_id, job_posting_uuid, winner_resume_uuid),
    )


def _demote_non_winner_on_rescore(
    cur: psycopg.Cursor,
    *,
    user_id: int | uuid.UUID,
    job_posting_uuid: uuid.UUID,
    target_resume_uuid: uuid.UUID,
    winner_resume_uuid: uuid.UUID | None,
    now: datetime,
) -> None:
    """Case A mandatory demotion: demote R_target and promote winner's existing score."""
    _acquire_winner_lock(cur, user_id=user_id, job_posting_uuid=job_posting_uuid)
    cur.execute(
        """
        UPDATE matching_matchscore
        SET is_routed_winner = FALSE, modified_at = %s
        WHERE job_posting_id = %s
          AND resume_profile_id = %s
          AND is_routed_winner = TRUE
        """,
        (now, job_posting_uuid, target_resume_uuid),
    )
    if winner_resume_uuid is not None:
        cur.execute(
            """
            UPDATE matching_matchscore
            SET is_routed_winner = TRUE, modified_at = %s
            WHERE job_posting_id = %s
              AND resume_profile_id = %s
              AND is_deleted = FALSE
            RETURNING uuid
            """,
            (now, job_posting_uuid, winner_resume_uuid),
        )
        if cur.fetchone() is not None:
            _demote_sibling_winners(
                cur,
                user_id=user_id,
                job_posting_uuid=job_posting_uuid,
                winner_resume_uuid=winner_resume_uuid,
                now=now,
            )


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
    resume_language: str = UNKNOWN_LANGUAGE,
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
            job_language=job.language,
            resume_language=resume_language,
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


STAGE0_TITLE_JACCARD_THRESHOLD = 0.75

_CANONICAL_SELECT_COLUMNS = """
    j.uuid,
    j.ats_source,
    j.external_id,
    j.title,
    j.company_name,
    j.apply_url,
    j.description_clean,
    j.seniority,
    j.contract_type,
    j.work_mode,
    j.language,
    j.region_eligibility,
    j.salary_min,
    j.salary_max,
    j.salary_currency,
    j.salary_period,
    j.tech_stack,
    j.is_active,
    j.repost_count,
    j.last_reposted_at,
    j.created_at,
    j.company_name_normalized,
    j.title_normalized,
    j.description_fingerprint
"""


def _acquire_company_dedup_lock(cur: psycopg.Cursor, company_norm: str) -> None:
    if not is_generic_company_name(company_norm):
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended('vektryn:job_dedup:' || %s, 0))",
            (company_norm,),
        )


def _upsert_canonical_source_row(
    cur: psycopg.Cursor,
    *,
    canonical_uuid: uuid.UUID,
    enriched: JobEnrichedEvent,
    incoming_apply_url: str,
    now: datetime,
) -> tuple[uuid.UUID, bool]:
    cur.execute(
        """
        SELECT uuid, job_posting_id, is_primary
        FROM jobs_jobpostingsource
        WHERE ats_source = %s
          AND external_id = %s
          AND is_deleted = FALSE
        LIMIT 1
        """,
        (enriched.ats_source.value, enriched.external_id),
    )
    existing_source = cur.fetchone()
    if existing_source is not None:
        source_uuid = existing_source[0]
        source_already_linked = existing_source[1] == canonical_uuid
        cur.execute(
            """
            UPDATE jobs_jobpostingsource
            SET job_posting_id = %s,
                apply_url = %s,
                raw_html_gcs_uri = CASE
                    WHEN %s <> '' THEN %s
                    ELSE raw_html_gcs_uri
                END,
                is_active = TRUE,
                last_seen_at = %s,
                modified_at = %s
            WHERE uuid = %s
            """,
            (
                canonical_uuid,
                incoming_apply_url,
                enriched.raw_html_gcs_uri,
                enriched.raw_html_gcs_uri,
                now,
                now,
                source_uuid,
            ),
        )
        return source_uuid, source_already_linked

    source_uuid = uuid.uuid4()
    cur.execute(
        """
        INSERT INTO jobs_jobpostingsource (
            uuid, created_at, modified_at, is_deleted,
            job_posting_id, ats_source, external_id,
            apply_url, raw_html_gcs_uri,
            is_primary, is_active, first_seen_at, last_seen_at
        )
        VALUES (%s, %s, %s, FALSE, %s, %s, %s, %s, %s, FALSE, TRUE, %s, %s)
        """,
        (
            source_uuid,
            now,
            now,
            canonical_uuid,
            enriched.ats_source.value,
            enriched.external_id,
            incoming_apply_url,
            enriched.raw_html_gcs_uri,
            now,
            now,
        ),
    )
    return source_uuid, False


def _resolve_effective_primary_url(
    cur: psycopg.Cursor,
    *,
    canonical_uuid: uuid.UUID,
    canonical_apply_url: str,
    source_uuid: uuid.UUID,
    incoming_source: ATSSource,
    incoming_apply_url: str,
    now: datetime,
) -> str:
    cur.execute(
        """
        SELECT uuid, ats_source, is_active
        FROM jobs_jobpostingsource
        WHERE job_posting_id = %s
          AND is_primary = TRUE
          AND is_deleted = FALSE
        LIMIT 1
        """,
        (canonical_uuid,),
    )
    current_primary = cur.fetchone()
    incoming_rank = get_source_priority_rank(incoming_source)
    should_promote = (
        current_primary is None
        or not bool(current_primary[2])
        or incoming_rank < get_source_priority_rank(current_primary[1])
    )
    if should_promote:
        if current_primary is None or current_primary[0] != source_uuid:
            cur.execute(
                """
                UPDATE jobs_jobpostingsource
                SET is_primary = FALSE, modified_at = %s
                WHERE job_posting_id = %s
                  AND is_primary = TRUE
                  AND is_deleted = FALSE
                """,
                (now, canonical_uuid),
            )
            cur.execute(
                """
                UPDATE jobs_jobpostingsource
                SET is_primary = TRUE, is_active = TRUE, modified_at = %s
                WHERE uuid = %s
                """,
                (now, source_uuid),
            )
        return incoming_apply_url
    if current_primary is not None and current_primary[0] == source_uuid:
        return incoming_apply_url
    return canonical_apply_url


def _backfill_unknown(
    current: str, incoming: str, unknown_value: str = "unknown"
) -> str:
    if current == unknown_value and incoming != unknown_value:
        return incoming
    return current


def _compute_repost_state(
    cur: psycopg.Cursor,
    *,
    canonical_uuid: uuid.UUID,
    canonical_is_active: bool,
    canonical_repost_count: int,
    canonical_last_reposted_at: object,
    canonical_created_at: object,
    source_already_linked: bool,
    enriched: JobEnrichedEvent,
    now: datetime,
) -> tuple[bool, int, object]:
    was_inactive = not bool(canonical_is_active)
    same_source_repost = False
    if not source_already_linked:
        cur.execute(
            """
            SELECT 1
            FROM jobs_jobpostingsource
            WHERE job_posting_id = %s
              AND ats_source = %s
              AND external_id <> %s
              AND is_deleted = FALSE
            LIMIT 1
            """,
            (canonical_uuid, enriched.ats_source.value, enriched.external_id),
        )
        has_prior_same_source = cur.fetchone() is not None
        anchor_ts = _coerce_datetime(canonical_last_reposted_at or canonical_created_at)
        same_source_repost = has_prior_same_source and (now - anchor_ts) >= timedelta(
            days=settings.repost_min_age_days
        )

    if was_inactive or same_source_repost:
        return was_inactive, int(canonical_repost_count or 0) + 1, now
    return was_inactive, int(canonical_repost_count or 0), canonical_last_reposted_at


def _merge_into_canonical_job(
    cur: psycopg.Cursor,
    *,
    canonical_row: tuple,
    enriched: JobEnrichedEvent,
    company_norm: str,
    title_norm: str,
    desc_fp: str,
    now: datetime,
) -> _JobCandidate:
    (
        canonical_uuid,
        canonical_ats_source,
        _canonical_ext_id,
        canonical_title,
        canonical_company,
        canonical_apply_url,
        canonical_desc,
        canonical_seniority,
        canonical_contract,
        canonical_work_mode,
        canonical_language,
        canonical_regions_raw,
        canonical_salary_min,
        canonical_salary_max,
        canonical_salary_currency,
        canonical_salary_period,
        canonical_tech_stack_raw,
        canonical_is_active,
        canonical_repost_count,
        canonical_last_reposted_at,
        canonical_created_at,
        canonical_company_norm,
        canonical_title_norm,
        canonical_desc_fp,
    ) = canonical_row[:24]

    incoming_apply_url = str(enriched.apply_url)
    source_uuid, source_already_linked = _upsert_canonical_source_row(
        cur,
        canonical_uuid=canonical_uuid,
        enriched=enriched,
        incoming_apply_url=incoming_apply_url,
        now=now,
    )
    effective_apply_url = _resolve_effective_primary_url(
        cur,
        canonical_uuid=canonical_uuid,
        canonical_apply_url=canonical_apply_url,
        source_uuid=source_uuid,
        incoming_source=enriched.ats_source,
        incoming_apply_url=incoming_apply_url,
        now=now,
    )

    backfill_salary = canonical_salary_min is None and enriched.salary_min is not None
    merged_salary_min = enriched.salary_min if backfill_salary else canonical_salary_min
    merged_salary_max = (
        enriched.salary_max
        if backfill_salary or canonical_salary_max is None
        else canonical_salary_max
    )
    merged_salary_currency = canonical_salary_currency or enriched.salary_currency
    incoming_period = enriched.salary_period.value if enriched.salary_period else None
    merged_salary_period = (
        incoming_period if canonical_salary_period is None else canonical_salary_period
    )
    merged_work_mode = _backfill_unknown(canonical_work_mode, enriched.work_mode.value)
    merged_language = _backfill_unknown(
        canonical_language, enriched.language, UNKNOWN_LANGUAGE
    )
    merged_seniority = _backfill_unknown(canonical_seniority, enriched.seniority.value)
    merged_contract = _backfill_unknown(
        canonical_contract, enriched.contract_type.value
    )
    merged_stack = list(
        dict.fromkeys(
            [*_parse_json_list(canonical_tech_stack_raw), *enriched.tech_stack]
        )
    )
    merged_regions = list(
        dict.fromkeys(
            [
                *list(canonical_regions_raw or []),
                *[r.value for r in enriched.region_eligibility],
            ]
        )
    )

    was_inactive, new_repost_count, new_last_reposted_at = _compute_repost_state(
        cur,
        canonical_uuid=canonical_uuid,
        canonical_is_active=bool(canonical_is_active),
        canonical_repost_count=int(canonical_repost_count or 0),
        canonical_last_reposted_at=canonical_last_reposted_at,
        canonical_created_at=canonical_created_at,
        source_already_linked=source_already_linked,
        enriched=enriched,
        now=now,
    )
    effective_desc = enriched.description_clean if was_inactive else canonical_desc

    common_params = (
        merged_seniority,
        merged_contract,
        merged_work_mode,
        merged_language,
        merged_regions,
        merged_salary_min,
        merged_salary_max,
        merged_salary_currency,
        merged_salary_period,
        json.dumps(merged_stack),
        canonical_company_norm or company_norm,
        canonical_title_norm or title_norm,
        canonical_desc_fp or desc_fp,
        new_repost_count,
        new_last_reposted_at,
        canonical_uuid,
    )
    if was_inactive:
        cur.execute(
            """
            UPDATE jobs_jobposting
            SET modified_at = %s,
                apply_url = %s,
                description_clean = %s,
                embedding = %s::vector,
                seniority = %s,
                contract_type = %s,
                work_mode = %s,
                language = %s,
                region_eligibility = %s,
                salary_min = %s,
                salary_max = %s,
                salary_currency = %s,
                salary_period = %s,
                tech_stack = %s::jsonb,
                company_name_normalized = %s,
                title_normalized = %s,
                description_fingerprint = %s,
                repost_count = %s,
                last_reposted_at = %s,
                is_active = TRUE,
                closed_at = NULL
            WHERE uuid = %s
            """,
            (
                now,
                effective_apply_url,
                effective_desc,
                enriched.embedding,
                *common_params,
            ),
        )
    else:
        cur.execute(
            """
            UPDATE jobs_jobposting
            SET modified_at = %s,
                apply_url = %s,
                seniority = %s,
                contract_type = %s,
                work_mode = %s,
                language = %s,
                region_eligibility = %s,
                salary_min = %s,
                salary_max = %s,
                salary_currency = %s,
                salary_period = %s,
                tech_stack = %s::jsonb,
                company_name_normalized = %s,
                title_normalized = %s,
                description_fingerprint = %s,
                repost_count = %s,
                last_reposted_at = %s
            WHERE uuid = %s
            """,
            (now, effective_apply_url, *common_params),
        )

    return _JobCandidate(
        uuid=canonical_uuid,
        title=canonical_title,
        company_name=canonical_company,
        apply_url=effective_apply_url,
        description_clean=effective_desc,
        seniority=merged_seniority,
        contract_type=merged_contract,
        region_eligibility=merged_regions,
        tech_stack=merged_stack,
        work_mode=merged_work_mode,
        language=merged_language,
        ats_source=canonical_ats_source,
        submitted_by_user_id=enriched.submitted_by_user_id,
        incoming_ats_source=enriched.ats_source.value,
        merged_into_existing=True,
    )


def _find_fast_path_canonical(
    cur: psycopg.Cursor,
    enriched: JobEnrichedEvent,
) -> tuple | None:
    cur.execute(
        f"""
        SELECT {_CANONICAL_SELECT_COLUMNS}
        FROM jobs_jobpostingsource s
        INNER JOIN jobs_jobposting j ON j.uuid = s.job_posting_id
        WHERE s.ats_source = %s
          AND s.external_id = %s
          AND s.is_deleted = FALSE
          AND j.is_deleted = FALSE
        LIMIT 1
        """,
        (enriched.ats_source.value, enriched.external_id),
    )
    row = cur.fetchone()
    if row is not None and len(row) >= 24:
        return row

    cur.execute(
        f"""
        SELECT {_CANONICAL_SELECT_COLUMNS}
        FROM jobs_jobposting j
        WHERE j.is_deleted = FALSE
          AND (
              (j.ats_source = %s AND j.external_id = %s)
              OR j.content_hash = %s
          )
        ORDER BY j.created_at ASC
        LIMIT 1
        """,
        (enriched.ats_source.value, enriched.external_id, enriched.content_hash),
    )
    row = cur.fetchone()
    return row if row is not None and len(row) >= 24 else None


def _known_values_conflict(
    val_a: str,
    val_b: str,
    unknown_value: str = "unknown",
) -> bool:
    return val_a != unknown_value and val_b != unknown_value and val_a != val_b


def _candidate_passes_stage0_guardrails(
    row: tuple,
    *,
    enriched: JobEnrichedEvent,
    title_norm: str,
    incoming_regions: list[str],
) -> tuple[float, int, float] | None:
    if len(row) < 26:
        return None
    cand_seniority = str(row[7] or "unknown")
    cand_work_mode = str(row[9] or "unknown")
    cand_language = normalize_language_code(str(row[10] or ""), strict=False)
    cand_regions = list(row[11] or [])
    cand_title_norm = str(row[22] or "") or normalize_title_for_dedup(str(row[3] or ""))
    cosine_sim = float(row[24])

    has_conflict = (
        _known_values_conflict(cand_language, enriched.language, UNKNOWN_LANGUAGE)
        or _known_values_conflict(cand_seniority, enriched.seniority.value)
        or _known_values_conflict(cand_work_mode, enriched.work_mode.value)
        or not are_regions_compatible(incoming_regions, cand_regions)
    )
    if has_conflict:
        return None
    if (
        token_jaccard_similarity(title_norm, cand_title_norm)
        < STAGE0_TITLE_JACCARD_THRESHOLD
        or cosine_sim < settings.near_dup_cosine_threshold
    ):
        return None

    primary_source = str(row[25] or row[1])
    return (
        cosine_sim,
        1 if is_direct_ats_source(primary_source) else 0,
        -_coerce_datetime(row[20]).timestamp(),
    )


def _find_semantic_canonical(
    cur: psycopg.Cursor,
    *,
    enriched: JobEnrichedEvent,
    company_norm: str,
    title_norm: str,
    now: datetime,
) -> tuple | None:
    lookback_cutoff = now - timedelta(days=settings.near_dup_lookback_days)
    incoming_regions = [r.value for r in enriched.region_eligibility]
    cur.execute(
        f"""
        SELECT
            {_CANONICAL_SELECT_COLUMNS},
            GREATEST(0.0, LEAST(1.0, 1 - (j.embedding <=> %s::vector))) AS cosine_sim,
            COALESCE(
                (
                    SELECT s.ats_source
                    FROM jobs_jobpostingsource s
                    WHERE s.job_posting_id = j.uuid
                      AND s.is_primary = TRUE
                      AND s.is_deleted = FALSE
                    LIMIT 1
                ),
                j.ats_source
            ) AS primary_ats_source
        FROM jobs_jobposting j
        WHERE j.embedding IS NOT NULL
          AND j.is_deleted = FALSE
          AND j.company_name_normalized = %s
          AND COALESCE(j.modified_at, j.created_at) >= %s
        """,
        (enriched.embedding, company_norm, lookback_cutoff),
    )
    best_row: tuple | None = None
    best_rank: tuple[float, int, float] | None = None
    for row in cur.fetchall():
        rank_key = _candidate_passes_stage0_guardrails(
            row,
            enriched=enriched,
            title_norm=title_norm,
            incoming_regions=incoming_regions,
        )
        if rank_key is not None and (best_rank is None or rank_key > best_rank):
            best_row = row
            best_rank = rank_key
    return best_row


def _upsert_or_merge_canonical_job(
    cur: psycopg.Cursor,
    enriched: JobEnrichedEvent,
    now: datetime,
) -> _JobCandidate:
    company_norm = normalize_company_for_dedup(enriched.company_name)[:255]
    title_norm = normalize_title_for_dedup(enriched.title)[:255]
    desc_fp, _ = compute_description_fingerprint(
        enriched.description_clean,
        min_chars=settings.min_dedup_desc_chars,
    )
    generic_company = is_generic_company_name(company_norm)
    if not generic_company:
        _acquire_company_dedup_lock(cur, company_norm)

    canonical_row = _find_fast_path_canonical(cur, enriched)
    if canonical_row is None and not generic_company:
        canonical_row = _find_semantic_canonical(
            cur,
            enriched=enriched,
            company_norm=company_norm,
            title_norm=title_norm,
            now=now,
        )

    if canonical_row is not None:
        return _merge_into_canonical_job(
            cur,
            canonical_row=canonical_row,
            enriched=enriched,
            company_norm=company_norm,
            title_norm=title_norm,
            desc_fp=desc_fp,
            now=now,
        )

    # No canonical match: insert brand-new JobPosting + primary JobPostingSource
    region_list = [r.value for r in enriched.region_eligibility]
    new_job_uuid = uuid.uuid4()
    cur.execute(
        """
        INSERT INTO jobs_jobposting (
            uuid, created_at, modified_at, is_deleted,
            ats_source, external_id, content_hash,
            title, company_name, apply_url, raw_html_gcs_uri,
            location_raw, description_clean,
            seniority, contract_type, work_mode, language, region_eligibility,
            salary_min, salary_max, salary_currency, salary_period,
            tech_stack, embedding, is_active, posted_at,
            company_name_normalized, title_normalized, description_fingerprint,
            repost_count
        )
        VALUES (
            %s, %s, %s, FALSE,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s::jsonb, %s::vector, TRUE, %s,
            %s, %s, %s,
            0
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
            work_mode = EXCLUDED.work_mode,
            language = EXCLUDED.language,
            region_eligibility = EXCLUDED.region_eligibility,
            salary_min = EXCLUDED.salary_min,
            salary_max = EXCLUDED.salary_max,
            salary_currency = EXCLUDED.salary_currency,
            salary_period = EXCLUDED.salary_period,
            tech_stack = EXCLUDED.tech_stack,
            embedding = EXCLUDED.embedding,
            is_active = TRUE,
            closed_at = NULL,
            posted_at = COALESCE(EXCLUDED.posted_at, jobs_jobposting.posted_at),
            company_name_normalized = EXCLUDED.company_name_normalized,
            title_normalized = EXCLUDED.title_normalized,
            description_fingerprint = EXCLUDED.description_fingerprint
        RETURNING uuid
        """,
        (
            new_job_uuid,
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
            enriched.work_mode.value,
            enriched.language,
            region_list,
            enriched.salary_min,
            enriched.salary_max,
            enriched.salary_currency,
            enriched.salary_period.value if enriched.salary_period else None,
            json.dumps(enriched.tech_stack),
            enriched.embedding,
            enriched.posted_at,
            company_norm,
            title_norm,
            desc_fp,
        ),
    )
    job_uuid = cur.fetchone()[0]

    cur.execute(
        """
        INSERT INTO jobs_jobpostingsource (
            uuid, created_at, modified_at, is_deleted,
            job_posting_id, ats_source, external_id,
            apply_url, raw_html_gcs_uri,
            is_primary, is_active, first_seen_at, last_seen_at
        )
        VALUES (%s, %s, %s, FALSE, %s, %s, %s, %s, %s, TRUE, TRUE, %s, %s)
        ON CONFLICT (ats_source, external_id) WHERE is_deleted = FALSE DO UPDATE SET
            apply_url = EXCLUDED.apply_url,
            raw_html_gcs_uri = EXCLUDED.raw_html_gcs_uri,
            is_active = TRUE,
            last_seen_at = EXCLUDED.last_seen_at,
            modified_at = EXCLUDED.modified_at
        """,
        (
            uuid.uuid4(),
            now,
            now,
            job_uuid,
            enriched.ats_source.value,
            enriched.external_id,
            str(enriched.apply_url),
            enriched.raw_html_gcs_uri,
            now,
            now,
        ),
    )

    return _JobCandidate(
        uuid=job_uuid,
        title=enriched.title,
        company_name=enriched.company_name,
        apply_url=str(enriched.apply_url),
        description_clean=enriched.description_clean,
        seniority=enriched.seniority.value,
        contract_type=enriched.contract_type.value,
        region_eligibility=region_list,
        tech_stack=enriched.tech_stack,
        work_mode=enriched.work_mode.value,
        language=enriched.language,
        ats_source=enriched.ats_source.value,
        submitted_by_user_id=enriched.submitted_by_user_id,
        incoming_ats_source=enriched.ats_source.value,
        merged_into_existing=False,
    )


def _upsert_job_posting(
    cur: psycopg.Cursor,
    enriched: JobEnrichedEvent,
    now: datetime,
) -> _JobCandidate:
    return _upsert_or_merge_canonical_job(cur, enriched, now)


def _upsert_match_score(
    cur: psycopg.Cursor,
    *,
    now: datetime,
    job_posting_uuid: uuid.UUID,
    resume_uuid: uuid.UUID,
    cosine_val: float,
    outcome: _EvaluationOutcome,
    resume_hash: str,
    is_routed_winner: bool = True,
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
            resume_content_hash, scoring_model, alert_sent_at,
            is_routed_winner
        )
        VALUES (
            %s, %s, %s, FALSE,
            %s, %s,
            %s, %s,
            %s::jsonb, %s::jsonb, %s::jsonb,
            %s, %s::jsonb, %s,
            %s, %s, NULL,
            %s
        )
        ON CONFLICT (job_posting_id, resume_profile_id) DO UPDATE SET
            modified_at = EXCLUDED.modified_at,
            is_deleted = FALSE,
            cosine_similarity = EXCLUDED.cosine_similarity,
            is_routed_winner = EXCLUDED.is_routed_winner,
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
            is_routed_winner,
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
    resume_label: str = "",
    resume_language: str = UNKNOWN_LANGUAGE,
) -> JobMatchAlertEvent | None:
    cur.execute(
        """
        UPDATE matching_matchscore target
        SET alert_sent_at = %s, modified_at = %s
        WHERE target.uuid = %s
          AND target.alert_sent_at IS NULL
          AND NOT EXISTS (
              SELECT 1
              FROM matching_matchscore other
              INNER JOIN resumes_resumeprofile rp
                ON rp.uuid = other.resume_profile_id
              WHERE rp.user_id = %s
                AND other.job_posting_id = %s
                AND other.alert_sent_at IS NOT NULL
          )
        RETURNING uuid
        """,
        (now, now, match_score_uuid, user_id, job.uuid),
    )
    if cur.fetchone() is None:
        return None

    notification_uuid = uuid.uuid4()
    fit_score = int(outcome.fit_score or 0)
    sim_pct = round(cosine_val * 100)
    matched_skills = outcome.matched_skills or []
    missing_keywords = outcome.missing_keywords or []
    clean_label = (resume_label or "").strip()
    clean_lang = normalize_language_code(resume_language, strict=False)
    matched_target = clean_label if clean_label else "your resume"

    insert_notification_with_cursor(
        cur,
        notification_uuid=notification_uuid,
        user_id=user_id,
        kind=NotificationKind.MATCH_ALERT,
        title=f"{fit_score}% Fit: {job.title}"[:255],
        body=(
            f"{job.company_name} matched {matched_target} "
            f"({sim_pct}% vector similarity)."
        ),
        payload={
            "job_posting_uuid": str(job.uuid),
            "resume_profile_uuid": str(resume_uuid),
            "resume_profile_label": clean_label,
            "resume_language": clean_lang,
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
        resume_profile_label=clean_label[:120],
        resume_language=clean_lang,
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
    resume_label: str = "",
    resume_language: str = UNKNOWN_LANGUAGE,
) -> None:
    if job.submitted_by_user_id is not None and str(user_id) != str(
        job.submitted_by_user_id
    ):
        return

    fit_score = int(outcome.fit_score or 0)
    sim_pct = round(cosine_val * 100)
    clean_label = (resume_label or "").strip()
    clean_lang = normalize_language_code(resume_language, strict=False)
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
            "resume_profile_label": clean_label,
            "resume_language": clean_lang,
            "match_score_uuid": str(match_score_uuid),
            "title": job.title,
            "company_name": job.company_name,
            "fit_score": fit_score,
            "cosine_similarity": cosine_val,
            "matched_skills": outcome.matched_skills or [],
            "missing_keywords": outcome.missing_keywords or [],
            "apply_url": job.apply_url,
            "merged_into_existing": job.merged_into_existing,
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


def _score_and_persist_winner(
    cur: psycopg.Cursor,
    *,
    now: datetime,
    trace_id: str,
    job: _JobCandidate,
    winner: _ActiveProfile,
    scoring_manager: UserGeminiScoringManager,
    user_api_key: str | None,
    bypass_threshold: bool = False,
    replace_evaluation: bool = False,
    notify_manual_import: bool = False,
    propagate_pause: bool = False,
) -> _PairScoreResult:
    cosine_val = float(winner.cosine_similarity)
    should_score = bool(user_api_key) and (
        bypass_threshold or cosine_val >= settings.cosine_similarity_threshold
    )
    outcome = (
        _run_llm_evaluation(
            scoring_manager=scoring_manager,
            user_id=int(winner.user_id),
            api_key=user_api_key,
            preferred_model=winner.preferred_model,
            allow_model_fallback=winner.allow_model_fallback,
            job=job,
            resume_uuid=winner.uuid,
            raw_text=winner.raw_text,
            extracted_skills=winner.extracted_skills,
            cosine_val=cosine_val,
            resume_language=winner.language,
            propagate_pause=propagate_pause,
        )
        if should_score
        else _EvaluationOutcome()
    )

    _acquire_winner_lock(cur, user_id=winner.user_id, job_posting_uuid=job.uuid)
    match_score_uuid, _alert_sent_at = _upsert_match_score(
        cur,
        now=now,
        job_posting_uuid=job.uuid,
        resume_uuid=winner.uuid,
        cosine_val=cosine_val,
        outcome=outcome,
        resume_hash=winner.content_hash,
        is_routed_winner=True,
        replace_evaluation=replace_evaluation,
    )
    _demote_sibling_winners(
        cur,
        user_id=winner.user_id,
        job_posting_uuid=job.uuid,
        winner_resume_uuid=winner.uuid,
        now=now,
    )

    pending_alert: JobMatchAlertEvent | None = None
    if outcome.fit_score is not None and outcome.fit_score >= winner.min_alert_score:
        pending_alert = _claim_and_persist_match_alert(
            cur,
            now=now,
            trace_id=trace_id,
            job=job,
            resume_uuid=winner.uuid,
            resume_label=winner.label,
            resume_language=winner.language,
            user_id=winner.user_id,
            match_score_uuid=match_score_uuid,
            cosine_val=cosine_val,
            outcome=outcome,
        )
    elif (
        bypass_threshold
        and (job.incoming_ats_source or job.ats_source) == ATSSource.MANUAL.value
        and notify_manual_import
        and outcome.fit_score is not None
    ):
        _persist_manual_import_ready(
            cur,
            now=now,
            job=job,
            resume_uuid=winner.uuid,
            resume_label=winner.label,
            resume_language=winner.language,
            user_id=winner.user_id,
            match_score_uuid=match_score_uuid,
            cosine_val=cosine_val,
            outcome=outcome,
        )

    logger.info(
        "Routed %s @ %s (%s) -> winner resume=%s (%s) | cosine=%.4f | fit_score=%s | alert=%s",
        job.title,
        job.company_name,
        job.language,
        winner.uuid,
        winner.language,
        cosine_val,
        outcome.fit_score,
        pending_alert is not None,
    )
    return _PairScoreResult(
        alert=pending_alert,
        scored=outcome.fit_score is not None,
    )


def _row_to_active_profile(row: tuple) -> _ActiveProfile:
    (
        resume_uuid,
        user_id,
        label,
        raw_text,
        resume_hash,
        extracted_skills,
        target_seniority,
        target_contract_types,
        target_regions,
        min_alert_score,
        cosine_sim,
        *extra,
    ) = row
    encrypted_key = str(extra[0]) if len(extra) >= 1 and extra[0] else ""
    preferred_model = (
        str(extra[1]) if len(extra) >= 2 and extra[1] else AUTO_GEMINI_MODEL
    )
    allow_fallback = bool(extra[2]) if len(extra) >= 3 else True
    target_work_modes = (
        list(extra[3]) if len(extra) >= 4 and extra[3] is not None else None
    )
    language = (
        normalize_language_code(str(extra[4]), strict=False)
        if len(extra) >= 5 and extra[4]
        else UNKNOWN_LANGUAGE
    )
    strict_language_match = bool(extra[5]) if len(extra) >= 6 else False
    modified_at = _coerce_datetime(extra[6]) if len(extra) >= 7 else _EPOCH_UTC
    return _ActiveProfile(
        uuid=resume_uuid,
        user_id=user_id,
        label=str(label or "").strip(),
        raw_text=raw_text,
        content_hash=resume_hash,
        extracted_skills=extracted_skills,
        target_seniority=target_seniority,
        target_contract_types=target_contract_types,
        target_regions=target_regions,
        min_alert_score=min_alert_score,
        cosine_similarity=float(cosine_sim),
        target_work_modes=target_work_modes,
        language=language,
        strict_language_match=strict_language_match,
        modified_at=modified_at,
        api_key_encrypted=encrypted_key,
        preferred_model=preferred_model,
        allow_model_fallback=allow_fallback,
    )


def _is_manual_bypass_user(job: _JobCandidate, user_id: int | uuid.UUID) -> bool:
    effective_source = job.incoming_ats_source or job.ats_source
    if effective_source != ATSSource.MANUAL.value:
        return False
    if job.submitted_by_user_id is None:
        return True
    return str(user_id) == str(job.submitted_by_user_id)


def _route_job_for_user(
    cur: psycopg.Cursor,
    *,
    now: datetime,
    trace_id: str,
    job: _JobCandidate,
    user_id: int | uuid.UUID,
    user_profiles: list[_ActiveProfile],
    scoring_manager: UserGeminiScoringManager,
    encryption_key: str,
) -> JobMatchAlertEvent | None:
    is_manual_bypass = _is_manual_bypass_user(job, user_id)
    winner = select_winning_profile(user_profiles, job)
    if winner is None and is_manual_bypass:
        winner = select_winning_profile(user_profiles, job, ignore_gates=True)
    if winner is None:
        return None

    # BYOK & Alert Cost Protection: skip Stage 2 if user already has a fresh MatchScore on canonical job
    if job.merged_into_existing:
        cur.execute(
            """
            SELECT uuid, resume_content_hash, fit_score, cosine_similarity,
                   matched_skills, missing_keywords
            FROM matching_matchscore
            WHERE job_posting_id = %s
              AND resume_profile_id = %s
              AND is_deleted = FALSE
            LIMIT 1
            """,
            (job.uuid, winner.uuid),
        )
        existing_row = cur.fetchone()
        if (
            existing_row is not None
            and existing_row[1] == winner.content_hash
            and existing_row[2] is not None
        ):
            logger.info(
                "Skipping Stage 2 BYOK for already-scored user=%s canonical job=%s resume=%s",
                user_id,
                job.uuid,
                winner.uuid,
            )
            if is_manual_bypass:
                _persist_manual_import_ready(
                    cur,
                    now=now,
                    job=job,
                    resume_uuid=winner.uuid,
                    resume_label=winner.label,
                    resume_language=winner.language,
                    user_id=user_id,
                    match_score_uuid=existing_row[0],
                    cosine_val=float(existing_row[3]),
                    outcome=_EvaluationOutcome(
                        fit_score=int(existing_row[2]),
                        matched_skills=_parse_json_list(existing_row[4]),
                        missing_keywords=_parse_json_list(existing_row[5]),
                    ),
                )
            return None

    user_api_key = _decrypt_user_byok_key(
        user_id=int(user_id),
        encrypted_key=winner.api_key_encrypted,
        encryption_key=encryption_key,
    )
    pair_result = _score_and_persist_winner(
        cur,
        now=now,
        trace_id=trace_id,
        job=job,
        winner=winner,
        scoring_manager=scoring_manager,
        user_api_key=user_api_key,
        bypass_threshold=is_manual_bypass,
        replace_evaluation=False,
        notify_manual_import=True,
        propagate_pause=False,
    )
    return pair_result.alert


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
            upsert_result = _upsert_job_posting(cur, enriched, now)
            if isinstance(upsert_result, _JobCandidate):
                candidate = upsert_result
            else:
                candidate = _JobCandidate(
                    uuid=upsert_result,
                    title=enriched.title,
                    company_name=enriched.company_name,
                    apply_url=str(enriched.apply_url),
                    description_clean=enriched.description_clean,
                    seniority=enriched.seniority.value,
                    contract_type=enriched.contract_type.value,
                    region_eligibility=[r.value for r in enriched.region_eligibility],
                    tech_stack=enriched.tech_stack,
                    work_mode=enriched.work_mode.value,
                    language=enriched.language,
                    ats_source=enriched.ats_source.value,
                    submitted_by_user_id=enriched.submitted_by_user_id,
                    incoming_ats_source=enriched.ats_source.value,
                )
            job_posting_uuid = candidate.uuid

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
                    COALESCE(p.allow_model_fallback, TRUE) AS allow_model_fallback,
                    r.target_work_modes,
                    r.language,
                    r.strict_language_match,
                    r.modified_at
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
            raw_profiles = cur.fetchall()

            profiles_by_user: dict[int | uuid.UUID, list[_ActiveProfile]] = defaultdict(
                list
            )
            for row in raw_profiles:
                profile = _row_to_active_profile(row)
                profiles_by_user[profile.user_id].append(profile)

            pending_alerts: list[JobMatchAlertEvent] = []
            for user_id, user_profiles in profiles_by_user.items():
                try:
                    alert = _route_job_for_user(
                        cur,
                        now=now,
                        trace_id=enriched.trace_id,
                        job=candidate,
                        user_id=user_id,
                        user_profiles=user_profiles,
                        scoring_manager=scoring_manager,
                        encryption_key=encryption_key,
                    )
                    if alert is not None:
                        pending_alerts.append(alert)
                except Exception as exc:
                    logger.warning(
                        "Per-user scoring boundary caught error for user=%s job=%s: %s",
                        user_id,
                        job_posting_uuid,
                        exc,
                    )

        conn.commit()
        if pending_alerts:
            _publish_match_alerts(producer, pending_alerts)
        producer.flush(5.0)


@dataclass(frozen=True)
class _RescoreContext:
    target: _ActiveProfile
    all_user_profiles: tuple[_ActiveProfile, ...]
    user_api_key: str


def _row_to_rescore_profile(row: tuple) -> _ActiveProfile:
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
        *extra,
    ) = row
    label = str(extra[0]).strip() if len(extra) >= 1 and extra[0] else "Active Resume"
    encrypted_key = str(extra[1]) if len(extra) >= 2 and extra[1] else ""
    preferred_model = (
        str(extra[2]) if len(extra) >= 3 and extra[2] else AUTO_GEMINI_MODEL
    )
    allow_fallback = bool(extra[3]) if len(extra) >= 4 else True
    target_work_modes = (
        list(extra[4]) if len(extra) >= 5 and extra[4] is not None else None
    )
    language = (
        normalize_language_code(str(extra[5]), strict=False)
        if len(extra) >= 6 and extra[5]
        else UNKNOWN_LANGUAGE
    )
    strict_language_match = bool(extra[6]) if len(extra) >= 7 else False
    modified_at = _coerce_datetime(extra[7]) if len(extra) >= 8 else _EPOCH_UTC
    return _ActiveProfile(
        uuid=resume_uuid,
        user_id=user_id,
        label=label,
        raw_text=raw_text,
        content_hash=resume_hash,
        extracted_skills=extracted_skills,
        target_seniority=target_seniority,
        target_contract_types=target_contract_types,
        target_regions=target_regions,
        min_alert_score=min_alert_score,
        target_work_modes=target_work_modes,
        language=language,
        strict_language_match=strict_language_match,
        modified_at=modified_at,
        embedding=resume_embedding,
        api_key_encrypted=encrypted_key,
        preferred_model=preferred_model,
        allow_model_fallback=allow_fallback,
    )


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
            COALESCE(p.allow_model_fallback, TRUE) AS allow_model_fallback,
            r.target_work_modes,
            r.language,
            r.strict_language_match,
            r.modified_at
        FROM resumes_resumeprofile r
        INNER JOIN auth_user u
          ON u.id = r.user_id
         AND u.is_active = TRUE
        LEFT JOIN base_userprofile p
          ON p.user_id = r.user_id
         AND p.is_deleted = FALSE
        WHERE r.user_id = (
            SELECT t.user_id
            FROM resumes_resumeprofile t
            WHERE t.uuid = %s
              AND t.is_deleted = FALSE
              AND t.is_active = TRUE
              AND t.embedding IS NOT NULL
        )
          AND r.is_deleted = FALSE
          AND r.is_active = TRUE
          AND r.embedding IS NOT NULL
        """,
        (event.resume_profile_uuid,),
    )
    rows = cur.fetchall()
    if not rows:
        logger.info(
            "Skipping jobs.rescore for resume=%s (not found, inactive user/resume, or missing embedding)",
            event.resume_profile_uuid,
        )
        return None

    all_profiles = tuple(_row_to_rescore_profile(row) for row in rows)
    target = next(
        (p for p in all_profiles if str(p.uuid) == str(event.resume_profile_uuid)),
        None,
    )
    if target is None:
        return None

    user_api_key = _decrypt_user_byok_key(
        user_id=int(target.user_id),
        encrypted_key=target.api_key_encrypted,
        encryption_key=encryption_key,
    )
    if not user_api_key:
        logger.info(
            "Skipping jobs.rescore for keyless user=%s resume=%s to preserve existing scores",
            target.user_id,
            target.uuid,
        )
        return None

    if scoring_manager.get_pause_state(int(target.user_id)) is not None:
        logger.info(
            "Skipping jobs.rescore for paused user=%s resume=%s",
            target.user_id,
            target.uuid,
        )
        return None

    return _RescoreContext(
        target=target,
        all_user_profiles=all_profiles,
        user_api_key=user_api_key,
    )


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
                j.ats_source,
                j.work_mode,
                j.language,
                j.embedding,
                m.resume_content_hash,
                m.fit_score,
                m.is_routed_winner
            FROM jobs_jobposting j
            LEFT JOIN matching_matchscore m
              ON m.job_posting_id = j.uuid
             AND m.resume_profile_id = %s
             AND m.is_deleted = FALSE
            WHERE j.is_deleted = FALSE
              AND j.is_active = TRUE
              AND j.embedding IS NOT NULL
              AND (m.uuid IS NULL OR m.modified_at < %s OR m.is_routed_winner = TRUE)
            ORDER BY j.embedding <=> %s::vector ASC
            LIMIT %s
            """,
            (resume_embedding, resume_uuid, produced_at, resume_embedding, max_jobs),
        )
        return list(cur.fetchall())

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
            j.ats_source,
            j.work_mode,
            j.language,
            j.embedding,
            m.resume_content_hash,
            m.fit_score,
            m.is_routed_winner
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
            j.ats_source,
            j.work_mode,
            j.language,
            j.embedding,
            NULL::text AS resume_content_hash,
            NULL::smallint AS fit_score,
            FALSE AS is_routed_winner
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


def _row_to_rescore_state(row: tuple) -> _RescoreCandidateState:
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
    ats_source = str(rest[0]) if len(rest) >= 1 and rest[0] else ""
    work_mode = str(rest[1]) if len(rest) >= 2 and rest[1] else "unknown"
    language = (
        normalize_language_code(str(rest[2]), strict=False)
        if len(rest) >= 3 and rest[2]
        else UNKNOWN_LANGUAGE
    )
    job_embedding = rest[3] if len(rest) >= 4 else None
    existing_hash = str(rest[4]) if len(rest) >= 5 and rest[4] is not None else None
    existing_fit = int(rest[5]) if len(rest) >= 6 and rest[5] is not None else None
    target_winner = bool(rest[6]) if len(rest) >= 7 and rest[6] is not None else None

    return _RescoreCandidateState(
        job=_JobCandidate(
            uuid=job_uuid,
            title=title,
            company_name=company_name,
            apply_url=apply_url,
            description_clean=description_clean,
            seniority=seniority,
            contract_type=contract_type,
            region_eligibility=list(region_eligibility or []),
            tech_stack=_parse_json_list(tech_stack),
            work_mode=work_mode,
            language=language,
            ats_source=ats_source,
        ),
        target_cosine=float(cosine_sim),
        job_embedding=job_embedding,
        existing_resume_hash=existing_hash,
        existing_fit_score=existing_fit,
        target_is_routed_winner=target_winner,
    )


def _profiles_with_job_cosines(
    ctx: _RescoreContext,
    state: _RescoreCandidateState,
) -> list[_ActiveProfile]:
    scored_profiles: list[_ActiveProfile] = []
    for profile in ctx.all_user_profiles:
        if str(profile.uuid) == str(ctx.target.uuid):
            cosine_val = state.target_cosine
        else:
            cosine_val = _vector_cosine_similarity(
                state.job_embedding, profile.embedding
            )
        scored_profiles.append(
            _ActiveProfile(
                uuid=profile.uuid,
                user_id=profile.user_id,
                label=profile.label,
                raw_text=profile.raw_text,
                content_hash=profile.content_hash,
                extracted_skills=profile.extracted_skills,
                target_seniority=profile.target_seniority,
                target_contract_types=profile.target_contract_types,
                target_regions=profile.target_regions,
                min_alert_score=profile.min_alert_score,
                cosine_similarity=cosine_val,
                target_work_modes=profile.target_work_modes,
                language=profile.language,
                strict_language_match=profile.strict_language_match,
                modified_at=profile.modified_at,
                embedding=profile.embedding,
                api_key_encrypted=profile.api_key_encrypted,
                preferred_model=profile.preferred_model,
                allow_model_fallback=profile.allow_model_fallback,
            )
        )
    return scored_profiles


def _flip_fresh_winner_only(
    cur: psycopg.Cursor,
    *,
    user_id: int | uuid.UUID,
    job_posting_uuid: uuid.UUID,
    winner_resume_uuid: uuid.UUID,
    now: datetime,
) -> None:
    _acquire_winner_lock(cur, user_id=user_id, job_posting_uuid=job_posting_uuid)
    cur.execute(
        """
        UPDATE matching_matchscore
        SET is_routed_winner = TRUE, modified_at = %s
        WHERE job_posting_id = %s
          AND resume_profile_id = %s
          AND is_deleted = FALSE
        """,
        (now, job_posting_uuid, winner_resume_uuid),
    )
    _demote_sibling_winners(
        cur,
        user_id=user_id,
        job_posting_uuid=job_posting_uuid,
        winner_resume_uuid=winner_resume_uuid,
        now=now,
    )


def _has_reusable_fresh_match(
    state: _RescoreCandidateState,
    *,
    target_hash: str,
    winner_cosine: float,
    force: bool,
) -> bool:
    if force or state.existing_resume_hash != target_hash:
        return False
    return (
        state.existing_fit_score is not None
        or winner_cosine < settings.cosine_similarity_threshold
    )


def _process_single_rescore_candidate(
    conn: psycopg.Connection,
    cur: psycopg.Cursor,
    *,
    ctx: _RescoreContext,
    event: JobRescoreEvent,
    row: tuple,
    scoring_manager: UserGeminiScoringManager,
) -> _PairScoreResult | None:
    state = _row_to_rescore_state(row)
    now = datetime.now(UTC)
    profiles_for_job = _profiles_with_job_cosines(ctx, state)
    winner = select_winning_profile(profiles_for_job, state.job)

    # Case A: R_target is not the routed winner -> $0 BYOK spend + mandatory demotion
    if winner is None or str(winner.uuid) != str(ctx.target.uuid):
        if state.target_is_routed_winner is not False:
            _demote_non_winner_on_rescore(
                cur,
                user_id=ctx.target.user_id,
                job_posting_uuid=state.job.uuid,
                target_resume_uuid=ctx.target.uuid,
                winner_resume_uuid=winner.uuid if winner is not None else None,
                now=now,
            )
            conn.commit()
        return None

    # Case B1: R_target is the winner and already has a fresh MatchScore -> flip only ($0 BYOK)
    if _has_reusable_fresh_match(
        state,
        target_hash=ctx.target.content_hash,
        winner_cosine=winner.cosine_similarity,
        force=event.force,
    ):
        _flip_fresh_winner_only(
            cur,
            user_id=ctx.target.user_id,
            job_posting_uuid=state.job.uuid,
            winner_resume_uuid=ctx.target.uuid,
            now=now,
        )
        conn.commit()
        return None

    # Case B2: R_target is the winner and needs fresh Stage 2 evaluation
    pair_result = _score_and_persist_winner(
        cur,
        now=now,
        trace_id=event.trace_id,
        job=state.job,
        winner=winner,
        scoring_manager=scoring_manager,
        user_api_key=ctx.user_api_key,
        bypass_threshold=False,
        replace_evaluation=True,
        propagate_pause=True,
    )
    conn.commit()
    return pair_result


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
        try:
            pair_result = _process_single_rescore_candidate(
                conn,
                cur,
                ctx=ctx,
                event=event,
                row=row,
                scoring_manager=scoring_manager,
            )
        except UserScoringPausedError as exc:
            logger.info(
                "Stopping jobs.rescore early for user=%s resume=%s after %d jobs (%s)",
                ctx.target.user_id,
                ctx.target.uuid,
                processed,
                exc.action.value,
            )
            break

        processed += 1
        if pair_result is None:
            continue
        if pair_result.scored:
            scored_count += 1
        if pair_result.alert is not None:
            alerts_count += 1
            _publish_match_alerts(producer, [pair_result.alert])
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
                resume_uuid=ctx.target.uuid,
                resume_hash=ctx.target.content_hash,
                resume_embedding=ctx.target.embedding,
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
                    user_id=ctx.target.user_id,
                    resume_uuid=ctx.target.uuid,
                    resume_label=ctx.target.label,
                    processed_count=processed,
                    scored_count=scored_count,
                    alerts_count=alerts_count,
                    force=event.force,
                )
                conn.commit()

        producer.flush(5.0)
        logger.info(
            "Rescore complete for resume=%s | processed=%d | max_jobs=%d | force=%s",
            ctx.target.uuid,
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

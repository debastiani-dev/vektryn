import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import logging
import os
import time
import uuid

import httpx
import psycopg
import redis.asyncio as aioredis

from stream_edge.clients.notifications import (
    persist_collector_sync_notifications,
    persist_pipeline_error_notifications,
)
from stream_edge.clients.redis import DedupRedisClient
from stream_edge.collectors.ashby import AshbyCollector
from stream_edge.collectors.ats_boards import (
    BreezyCollector,
    InHireCollector,
    LeverCollector,
    RecruiteeCollector,
    SmartRecruitersCollector,
    WorkableCollector,
)
from stream_edge.collectors.base import (
    BaseATSCollector,
    CollectedJob,
    push_jobs_with_stats,
)
from stream_edge.collectors.discovery import discover_all_ats_boards
from stream_edge.collectors.greenhouse import GreenhouseCollector
from stream_edge.collectors.prefilter import (
    ResumeFilterCriteria,
    detect_deterministic_work_mode,
    filter_and_rank_jobs,
    filter_and_score_jobs,
    load_resume_criteria,
)
from stream_edge.collectors.remote_feeds import MultiCompanyFeedCollector
from stream_edge.collectors.taxonomy import sync_dynamic_stacks
from stream_edge.config import settings
from stream_edge.telemetry import (
    capture_worker_error_message,
    capture_worker_exception,
    configure_sentry,
    flush_sentry,
)
from vektryn_contracts import (
    WorkMode,
    clean_description_for_dedup,
    compute_description_fingerprint,
    compute_job_content_hash,
    get_source_priority_rank,
    is_generic_company_name,
    normalize_company_for_dedup,
    normalize_title_for_dedup,
    token_jaccard_similarity,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

COLLECTOR_LOG_RETENTION_DAYS = 90
COLLECT_RUNNING_REDIS_KEY = "vektryn:system:collect_running"
COLLECT_RUNNING_TTL_SECONDS = 900


async def _set_collect_running_marker(started_at: datetime) -> None:
    if not settings.redis_url:
        return
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.set(
            COLLECT_RUNNING_REDIS_KEY,
            json.dumps({"started_at": started_at.isoformat()}),
            ex=COLLECT_RUNNING_TTL_SECONDS,
        )
    except Exception as exc:
        logger.debug("Failed setting collect running marker in Redis: %s", exc)
    finally:
        await client.aclose()


async def _clear_collect_running_marker() -> None:
    if not settings.redis_url:
        return
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.delete(COLLECT_RUNNING_REDIS_KEY)
    except Exception as exc:
        logger.debug("Failed clearing collect running marker in Redis: %s", exc)
    finally:
        await client.aclose()


@dataclass
class SourceRunMetrics:
    fetched_count: int = 0
    ingested_count: int = 0
    deduped_count: int = 0
    error_count: int = 0
    duration_ms: int = 0


def _board_label(token: str) -> str:
    return token.replace("-", " ").replace("_", " ").title()


def compute_collected_job_hash(job: CollectedJob) -> str:
    """Computes canonical content_hash matching stream_edge.api.ingest verbatim."""
    return compute_job_content_hash(
        ats_source=job.ats_source,
        title=job.title,
        company_name=job.company_name,
        description_clean=job.description_clean,
    )


LAYER1_DESC_JACCARD_THRESHOLD = 0.88


@dataclass
class _DedupCluster:
    representative: CollectedJob
    best_score: int
    company_norm: str
    title_norm: str
    desc_fp: str
    desc_clean: str
    desc_len: int
    work_mode: WorkMode


def _work_modes_compatible(mode_a: WorkMode | str, mode_b: WorkMode | str) -> bool:
    val_a = mode_a.value if isinstance(mode_a, WorkMode) else str(mode_a or "unknown")
    val_b = mode_b.value if isinstance(mode_b, WorkMode) else str(mode_b or "unknown")
    if val_a == WorkMode.UNKNOWN.value or val_b == WorkMode.UNKNOWN.value:
        return True
    return val_a == val_b


def _cluster_matches_job(
    existing: _DedupCluster,
    *,
    title_norm: str,
    desc_fp: str,
    desc_clean: str,
    min_chars: int,
    work_mode: WorkMode,
) -> bool:
    if existing.desc_len < min_chars:
        return False
    if desc_fp and existing.desc_fp and desc_fp == existing.desc_fp:
        return True
    return (
        bool(title_norm)
        and title_norm == existing.title_norm
        and _work_modes_compatible(work_mode, existing.work_mode)
        and token_jaccard_similarity(desc_clean, existing.desc_clean)
        >= LAYER1_DESC_JACCARD_THRESHOLD
    )


def _find_matching_cluster(
    clusters_by_company: dict[str, list[_DedupCluster]],
    *,
    company_norm: str,
    title_norm: str,
    desc_fp: str,
    desc_clean: str,
    desc_len: int,
    min_chars: int,
    work_mode: WorkMode,
) -> _DedupCluster | None:
    if is_generic_company_name(company_norm) or desc_len < min_chars:
        return None
    for existing in clusters_by_company.get(company_norm, []):
        if _cluster_matches_job(
            existing,
            title_norm=title_norm,
            desc_fp=desc_fp,
            desc_clean=desc_clean,
            min_chars=min_chars,
            work_mode=work_mode,
        ):
            return existing
    return None


def deduplicate_scored_batch(
    scored_jobs: list[tuple[int, CollectedJob]],
) -> tuple[list[tuple[int, CollectedJob]], list[CollectedJob]]:
    """Priority-ordered in-batch dedup keeping cluster's best relevance score.

    Within each duplicate cluster, SOURCE_PRIORITY_RANK picks the winning source
    (Direct ATS over Aggregator) while retaining the cluster's highest relevance
    score. Surviving distinct roles are then sorted by (-best_score, priority_rank)
    so low-relevance Direct ATS items never crowd out high-relevance Aggregators.
    """
    if not scored_jobs:
        return [], []

    priority_ordered = sorted(
        scored_jobs,
        key=lambda item: (
            get_source_priority_rank(item[1].ats_source),
            -item[0],
        ),
    )

    clusters: list[_DedupCluster] = []
    clusters_by_company: dict[str, list[_DedupCluster]] = {}
    seen_hashes: set[str] = set()
    in_batch_deduped: list[CollectedJob] = []
    min_chars = settings.min_dedup_desc_chars

    for score, job in priority_ordered:
        content_hash = compute_collected_job_hash(job)
        if content_hash in seen_hashes:
            in_batch_deduped.append(job)
            continue

        company_norm = normalize_company_for_dedup(job.company_name)
        title_norm = normalize_title_for_dedup(job.title)
        desc_clean = clean_description_for_dedup(job.description_clean)
        desc_fp, desc_len = compute_description_fingerprint(
            job.description_clean,
            min_chars=min_chars,
        )
        work_mode = detect_deterministic_work_mode(job)

        matched_cluster = _find_matching_cluster(
            clusters_by_company,
            company_norm=company_norm,
            title_norm=title_norm,
            desc_fp=desc_fp,
            desc_clean=desc_clean,
            desc_len=desc_len,
            min_chars=min_chars,
            work_mode=work_mode,
        )
        if matched_cluster is not None:
            matched_cluster.best_score = max(matched_cluster.best_score, score)
            in_batch_deduped.append(job)
            continue

        seen_hashes.add(content_hash)
        cluster = _DedupCluster(
            representative=job,
            best_score=score,
            company_norm=company_norm,
            title_norm=title_norm,
            desc_fp=desc_fp,
            desc_clean=desc_clean,
            desc_len=desc_len,
            work_mode=work_mode,
        )
        clusters.append(cluster)
        if not is_generic_company_name(company_norm):
            clusters_by_company.setdefault(company_norm, []).append(cluster)

    clusters.sort(
        key=lambda c: (
            -c.best_score,
            get_source_priority_rank(c.representative.ats_source),
        )
    )
    return [(c.best_score, c.representative) for c in clusters], in_batch_deduped


def _attach_layer1_source_sync(
    cur: psycopg.Cursor,
    *,
    canonical_uuid: uuid.UUID,
    canonical_created_at: datetime,
    canonical_last_reposted_at: datetime | None,
    canonical_repost_count: int,
    company_norm: str,
    job: CollectedJob,
    now: datetime,
) -> None:
    """Attach/promote a Layer 1 matched source directly in Postgres under advisory lock."""
    cur.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"vektryn:job_dedup:{company_norm}",),
    )

    cur.execute(
        """
        SELECT uuid, is_primary
        FROM jobs_jobpostingsource
        WHERE ats_source = %s
          AND external_id = %s
          AND is_deleted = FALSE
        LIMIT 1
        """,
        (job.ats_source.value, job.external_id),
    )
    existing_source = cur.fetchone()
    source_already_linked = existing_source is not None

    if existing_source is not None:
        source_uuid = existing_source[0]
        cur.execute(
            """
            UPDATE jobs_jobpostingsource
            SET apply_url = %s,
                is_active = TRUE,
                last_seen_at = %s,
                modified_at = %s
            WHERE uuid = %s
            """,
            (job.apply_url, now, now, source_uuid),
        )
    else:
        source_uuid = uuid.uuid4()
        cur.execute(
            """
            INSERT INTO jobs_jobpostingsource (
                uuid, created_at, modified_at, is_deleted,
                job_posting_id, ats_source, external_id,
                apply_url, raw_html_gcs_uri,
                is_primary, is_active, first_seen_at, last_seen_at
            )
            VALUES (%s, %s, %s, FALSE, %s, %s, %s, %s, '', FALSE, TRUE, %s, %s)
            """,
            (
                source_uuid,
                now,
                now,
                canonical_uuid,
                job.ats_source.value,
                job.external_id,
                job.apply_url,
                now,
                now,
            ),
        )

    # Check primary source precedence & failover (two-step swap)
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
    incoming_rank = get_source_priority_rank(job.ats_source)
    should_promote = (
        current_primary is None
        or not bool(current_primary[2])
        or incoming_rank < get_source_priority_rank(current_primary[1])
    )

    if should_promote and (
        current_primary is None or current_primary[0] != source_uuid
    ):
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
        cur.execute(
            """
            UPDATE jobs_jobposting
            SET apply_url = %s, modified_at = %s
            WHERE uuid = %s
            """,
            (job.apply_url, now, canonical_uuid),
        )

    # Apply same-source repost classification if a new external_id arrives after REPOST_MIN_AGE_DAYS
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
            (canonical_uuid, job.ats_source.value, job.external_id),
        )
        has_prior_same_source = cur.fetchone() is not None
        anchor_ts = canonical_last_reposted_at or canonical_created_at
        if anchor_ts.tzinfo is None:
            anchor_ts = anchor_ts.replace(tzinfo=UTC)
        if has_prior_same_source and (now - anchor_ts) >= timedelta(
            days=settings.repost_min_age_days
        ):
            cur.execute(
                """
                UPDATE jobs_jobposting
                SET repost_count = %s,
                    last_reposted_at = %s,
                    modified_at = %s
                WHERE uuid = %s
                """,
                (canonical_repost_count + 1, now, now, canonical_uuid),
            )


@dataclass(frozen=True)
class _Layer1Candidate:
    job: CollectedJob
    company_norm: str
    title_norm: str
    desc_fp: str
    desc_clean: str
    work_mode: WorkMode


def _check_known_source_pairs_sync(
    cur: psycopg.Cursor,
    source_pairs: list[tuple[str, str]],
    now: datetime,
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    deduped_pairs: set[tuple[str, str]] = set()
    closed_pairs: set[tuple[str, str]] = set()
    if not source_pairs:
        return deduped_pairs, closed_pairs

    cur.execute(
        """
        SELECT s.uuid, s.ats_source, s.external_id, j.is_active
        FROM jobs_jobpostingsource s
        INNER JOIN jobs_jobposting j ON j.uuid = s.job_posting_id
        INNER JOIN unnest(%s::text[], %s::text[]) AS inp(ats_source, external_id)
          ON s.ats_source = inp.ats_source
         AND s.external_id = inp.external_id
        WHERE s.is_deleted = FALSE
          AND j.is_deleted = FALSE
        """,
        ([s for s, _ in source_pairs], [e for _, e in source_pairs]),
    )
    active_source_uuids: list[uuid.UUID] = []
    for src_uuid, src_name, ext_id, job_is_active in cur.fetchall():
        pair = (str(src_name), str(ext_id))
        if job_is_active:
            active_source_uuids.append(src_uuid)
            deduped_pairs.add(pair)
        else:
            # Closed canonical job -> allow through to Stage 0 reactivation
            closed_pairs.add(pair)

    if active_source_uuids:
        cur.execute(
            """
            UPDATE jobs_jobpostingsource
            SET last_seen_at = %s,
                is_active = TRUE,
                modified_at = %s
            WHERE uuid = ANY(%s::uuid[])
            """,
            (now, now, active_source_uuids),
        )
    return deduped_pairs, closed_pairs


def _check_exact_active_hashes_sync(
    cur: psycopg.Cursor,
    hashes: list[str],
) -> set[str]:
    if not hashes:
        return set()
    cur.execute(
        """
        SELECT content_hash
        FROM jobs_jobposting
        WHERE is_active = TRUE
          AND is_deleted = FALSE
          AND content_hash = ANY(%s)
        """,
        (hashes,),
    )
    return {row[0] for row in cur.fetchall() if row and row[0]}


def _prepare_layer1_cross_source_candidates(
    jobs: list[CollectedJob],
    *,
    deduped_pairs: set[tuple[str, str]],
    closed_pairs: set[tuple[str, str]],
    deduped_hashes: set[str],
    min_chars: int,
) -> tuple[list[_Layer1Candidate], set[str]]:
    candidates: list[_Layer1Candidate] = []
    companies: set[str] = set()
    for job in jobs:
        pair = (job.ats_source.value, job.external_id)
        c_hash = compute_collected_job_hash(job)
        if pair in deduped_pairs or pair in closed_pairs or c_hash in deduped_hashes:
            continue
        comp_norm = normalize_company_for_dedup(job.company_name)
        if is_generic_company_name(comp_norm):
            continue
        desc_fp, desc_len = compute_description_fingerprint(
            job.description_clean,
            min_chars=min_chars,
        )
        if desc_len < min_chars:
            continue
        candidates.append(
            _Layer1Candidate(
                job=job,
                company_norm=comp_norm,
                title_norm=normalize_title_for_dedup(job.title),
                desc_fp=desc_fp,
                desc_clean=clean_description_for_dedup(job.description_clean),
                work_mode=detect_deterministic_work_mode(job),
            )
        )
        companies.add(comp_norm)
    return candidates, companies


def _row_matches_layer1_candidate(
    cand_row: tuple,
    incoming: _Layer1Candidate,
    *,
    min_chars: int,
) -> bool:
    cand_title_norm = cand_row[2]
    cand_fp = cand_row[3]
    cand_desc = cand_row[4]
    cand_wm = cand_row[5]

    if incoming.desc_fp and cand_fp and incoming.desc_fp == cand_fp:
        return True
    if not (
        incoming.title_norm
        and incoming.title_norm == cand_title_norm
        and _work_modes_compatible(incoming.work_mode, cand_wm)
    ):
        return False
    cand_clean = clean_description_for_dedup(cand_desc)
    return (
        len(cand_clean) >= min_chars
        and token_jaccard_similarity(incoming.desc_clean, cand_clean)
        >= LAYER1_DESC_JACCARD_THRESHOLD
    )


def _dedup_cross_source_candidates_sync(
    cur: psycopg.Cursor,
    candidates: list[_Layer1Candidate],
    companies: set[str],
    *,
    min_chars: int,
    now: datetime,
) -> set[tuple[str, str]]:
    if not candidates or not companies:
        return set()

    lookback_cutoff = now - timedelta(days=settings.near_dup_lookback_days)
    cur.execute(
        """
        SELECT
            uuid,
            company_name_normalized,
            title_normalized,
            description_fingerprint,
            description_clean,
            work_mode,
            created_at,
            last_reposted_at,
            repost_count
        FROM jobs_jobposting
        WHERE is_active = TRUE
          AND is_deleted = FALSE
          AND company_name_normalized = ANY(%s)
          AND COALESCE(modified_at, created_at) >= %s
        ORDER BY created_at ASC
        """,
        (list(companies), lookback_cutoff),
    )
    candidates_by_company: dict[str, list[tuple]] = {}
    for row in cur.fetchall():
        candidates_by_company.setdefault(row[1], []).append(row)

    matched_pairs: set[tuple[str, str]] = set()
    for incoming in candidates:
        matched_row = next(
            (
                cand
                for cand in candidates_by_company.get(incoming.company_norm, [])
                if _row_matches_layer1_candidate(cand, incoming, min_chars=min_chars)
            ),
            None,
        )
        if matched_row is None:
            continue
        _attach_layer1_source_sync(
            cur,
            canonical_uuid=matched_row[0],
            canonical_created_at=matched_row[6],
            canonical_last_reposted_at=matched_row[7],
            canonical_repost_count=int(matched_row[8] or 0),
            company_norm=incoming.company_norm,
            job=incoming.job,
            now=now,
        )
        matched_pairs.add((incoming.job.ats_source.value, incoming.job.external_id))
    return matched_pairs


def _pre_dedup_against_postgres_sync(
    jobs: list[CollectedJob],
) -> tuple[set[str], set[tuple[str, str]]]:
    """Check exact hashes, JobPostingSource pairs, and Layer 1 active cross-source matches.

    Returns (deduped_hashes, deduped_source_pairs). Matches against closed
    (is_active=False) canonical postings are intentionally NOT added so they
    flow through to Layer 2 / Stage 0 for re-enrichment and reactivation.
    """
    if not jobs:
        return set(), set()

    now = datetime.now(UTC)
    hashes = list({compute_collected_job_hash(j) for j in jobs})
    source_pairs = list({(j.ats_source.value, j.external_id) for j in jobs})
    min_chars = settings.min_dedup_desc_chars

    try:
        with psycopg.connect(settings.postgres_dsn, autocommit=False) as conn:
            with conn.cursor() as cur:
                deduped_pairs, closed_pairs = _check_known_source_pairs_sync(
                    cur, source_pairs, now
                )
                deduped_hashes = _check_exact_active_hashes_sync(cur, hashes)
                remaining, companies = _prepare_layer1_cross_source_candidates(
                    jobs,
                    deduped_pairs=deduped_pairs,
                    closed_pairs=closed_pairs,
                    deduped_hashes=deduped_hashes,
                    min_chars=min_chars,
                )
                cross_source_pairs = _dedup_cross_source_candidates_sync(
                    cur,
                    remaining,
                    companies,
                    min_chars=min_chars,
                    now=now,
                )
                deduped_pairs.update(cross_source_pairs)
            conn.commit()
    except Exception as exc:
        logger.warning("Pre-dedup Postgres check failed (will push all): %s", exc)
        return set(), set()

    return deduped_hashes, deduped_pairs


def _find_existing_active_hashes_sync(hashes: list[str]) -> set[str]:
    if not hashes:
        return set()
    try:
        with psycopg.connect(settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT content_hash
                    FROM jobs_jobposting
                    WHERE is_active = TRUE
                      AND is_deleted = FALSE
                      AND content_hash = ANY(%s)
                    """,
                    (hashes,),
                )
                return {row[0] for row in cur.fetchall() if row and row[0]}
    except Exception as exc:
        logger.warning("Pre-dedup Postgres check failed (will push all): %s", exc)
        return set()


async def _find_redis_claimed_hashes(hashes: list[str]) -> set[str]:
    if not hashes or not settings.redis_url:
        return set()
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        keys = [f"{DedupRedisClient.KEY_PREFIX}{h}" for h in hashes]
        values = await client.mget(keys)
        return {
            content_hash
            for content_hash, value in zip(hashes, values, strict=True)
            if value is not None
        }
    except Exception as exc:
        logger.warning("Pre-dedup Redis check failed (falling back to DB): %s", exc)
        return set()
    finally:
        await client.aclose()


async def partition_new_and_deduped_jobs(
    jobs: list[CollectedJob],
) -> tuple[list[CollectedJob], list[CollectedJob]]:
    if not jobs:
        return [], []

    # Preserve caller order when invoked directly without explicit scores
    total = len(jobs)
    scored_input = [(total - idx, job) for idx, job in enumerate(jobs)]
    surviving_scored, in_batch_deduped = deduplicate_scored_batch(scored_input)
    surviving_jobs = [job for _, job in surviving_scored]

    hashed = [(job, compute_collected_job_hash(job)) for job in surviving_jobs]
    unique_hashes = list({h for _, h in hashed})
    db_existing_hashes, (db_hashes, db_pairs), redis_claimed = await asyncio.gather(
        asyncio.to_thread(_find_existing_active_hashes_sync, unique_hashes),
        asyncio.to_thread(_pre_dedup_against_postgres_sync, surviving_jobs),
        _find_redis_claimed_hashes(unique_hashes),
    )
    known_hashes = db_existing_hashes | db_hashes | redis_claimed

    to_ingest: list[CollectedJob] = []
    deduped: list[CollectedJob] = []
    seen_in_batch: set[str] = set()

    for job, content_hash in hashed:
        pair = (job.ats_source.value, job.external_id)
        if (
            pair in db_pairs
            or content_hash in known_hashes
            or content_hash in seen_in_batch
        ):
            deduped.append(job)
        else:
            seen_in_batch.add(content_hash)
            to_ingest.append(job)
    deduped.extend(in_batch_deduped)
    return to_ingest, deduped


def persist_collector_run_logs_sync(
    metrics_by_source: dict[str, SourceRunMetrics],
    ran_at: datetime,
) -> int:
    if not metrics_by_source:
        return 0
    cutoff = ran_at - timedelta(days=COLLECTOR_LOG_RETENTION_DAYS)
    rows = [
        (
            ran_at,
            ran_at,
            source,
            stats.fetched_count,
            stats.ingested_count,
            stats.deduped_count,
            stats.error_count,
            stats.duration_ms,
            ran_at,
        )
        for source, stats in sorted(metrics_by_source.items())
    ]
    with psycopg.connect(settings.postgres_dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO analytics_collectorrunlog (
                    created_at, modified_at,
                    source, fetched_count, ingested_count,
                    deduped_count, error_count, duration_ms, ran_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )
            cur.execute(
                "DELETE FROM analytics_collectorrunlog WHERE ran_at < %s",
                (cutoff,),
            )
        conn.commit()
    return len(rows)


async def _collect_board(
    collector: BaseATSCollector,
    source_name: str,
    board_token: str,
    criteria: ResumeFilterCriteria | None,
    dynamic_stacks: frozenset[str],
    max_per_board: int,
    min_skill_matches: int,
    semaphore: asyncio.Semaphore,
) -> tuple[str, list[CollectedJob], int, int, int]:
    async with semaphore:
        started = time.perf_counter()
        try:
            raw_jobs = await collector.fetch_board(
                board_token=board_token,
                company_name=_board_label(board_token),
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.debug("Board %s[%s] skipped: %s", source_name, board_token, exc)
            return source_name, [], 0, 1, elapsed_ms
        elapsed_ms = int((time.perf_counter() - started) * 1000)

    matched = filter_and_rank_jobs(
        raw_jobs,
        criteria,
        dynamic_stacks=dynamic_stacks,
        min_skill_matches=min_skill_matches,
    )
    if matched:
        logger.info(
            "%s[%s]: %d/%d postings survived resume pre-filter",
            source_name,
            board_token,
            len(matched),
            len(raw_jobs),
        )
    return source_name, matched[:max_per_board], len(raw_jobs), 0, elapsed_ms


async def run_collection(
    *,
    edge_url: str = "http://localhost:8001",
    max_per_board: int = 8,
    boards_per_ats: int = 25,
    max_total: int = 30,
    resume_id: str | None = None,
    min_skill_matches: int = 2,
    refresh_discovery: bool = False,
) -> dict[str, SourceRunMetrics]:
    run_timestamp = datetime.now(UTC)
    metrics_by_source: dict[str, SourceRunMetrics] = {}
    await _set_collect_running_marker(run_timestamp)

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            # 1. Sync dynamic language/framework catalog (cached in Redis) & load resume criteria
            dynamic_stacks = await sync_dynamic_stacks(
                client, force_refresh=refresh_discovery
            )
            criteria = await asyncio.to_thread(
                load_resume_criteria,
                resume_id,
                dynamic_stacks=dynamic_stacks,
            )

            # 2. Global + Brazilian multi-company feeds (Remotive, Himalayas, Jobicy, Gupy, Trampos, GitHub Vagas)
            feed_collector = MultiCompanyFeedCollector(http_client=client)
            raw_feed_jobs, feed_stats = await feed_collector.fetch_all_with_stats()
            for source_key, stat in feed_stats.items():
                entry = metrics_by_source.setdefault(source_key, SourceRunMetrics())
                entry.fetched_count += stat["fetched"]
                entry.error_count += stat["errors"]
                entry.duration_ms = max(entry.duration_ms, stat["duration_ms"])

            feed_candidates = filter_and_rank_jobs(
                raw_feed_jobs,
                criteria,
                dynamic_stacks=dynamic_stacks,
                min_skill_matches=min_skill_matches,
            )
            logger.info(
                "Multi-company feeds (Global + BR): %d/%d postings survived resume pre-filter",
                len(feed_candidates),
                len(raw_feed_jobs),
            )

            # 3. Dynamic discovery & verification across all 8 Global + BR ATS platforms
            board_pools = await discover_all_ats_boards(
                client,
                seed_jobs=raw_feed_jobs,
                force_refresh=refresh_discovery,
            )

            collectors: dict[str, BaseATSCollector] = {
                "greenhouse": GreenhouseCollector(http_client=client),
                "ashby": AshbyCollector(http_client=client),
                "lever": LeverCollector(http_client=client),
                "workable": WorkableCollector(http_client=client),
                "smartrecruiters": SmartRecruitersCollector(http_client=client),
                "recruitee": RecruiteeCollector(http_client=client),
                "breezy": BreezyCollector(http_client=client),
                "inhire": InHireCollector(http_client=client),
            }

            pinned_boards: dict[str, list[str]] = {
                "greenhouse": settings.greenhouse_boards,
                "ashby": settings.ashby_boards,
            }

            sem = asyncio.Semaphore(12)
            board_tasks = [
                _collect_board(
                    collector,
                    ats_name,
                    token,
                    criteria,
                    dynamic_stacks,
                    max_per_board,
                    min_skill_matches,
                    sem,
                )
                for ats_name, collector in collectors.items()
                for token in dict.fromkeys(
                    [
                        *pinned_boards.get(ats_name, []),
                        *board_pools.sample(ats_name, boards_per_ats),
                    ]
                )
            ]

            board_results = await asyncio.gather(*board_tasks)
            ats_candidates: list[CollectedJob] = []
            for source_name, batch, fetched, errors, elapsed_ms in board_results:
                entry = metrics_by_source.setdefault(source_name, SourceRunMetrics())
                entry.fetched_count += fetched
                entry.error_count += errors
                entry.duration_ms = max(entry.duration_ms, elapsed_ms)
                ats_candidates.extend(batch)

            # 4. Score, run priority-ordered in-batch + Postgres Layer 1 pre-dedup, then cap to max_total
            scored_pool = filter_and_score_jobs(
                [*feed_candidates, *ats_candidates],
                criteria,
                dynamic_stacks=dynamic_stacks,
                min_skill_matches=min_skill_matches,
            )
            clustered_scored, in_batch_deduped = deduplicate_scored_batch(scored_pool)
            merged = [job for _, job in clustered_scored]

            to_ingest_all, pg_deduped = await partition_new_and_deduped_jobs(merged)
            deduped = [*in_batch_deduped, *pg_deduped]
            to_ingest = to_ingest_all[:max_total]
            for job in deduped:
                entry = metrics_by_source.setdefault(
                    job.ats_source.value, SourceRunMetrics()
                )
                entry.deduped_count += 1

            push_stats = await push_jobs_with_stats(
                http_client=client,
                edge_base_url=edge_url,
                jobs=to_ingest,
            )
            for source_key, (accepted, push_errors) in push_stats.items():
                entry = metrics_by_source.setdefault(source_key, SourceRunMetrics())
                entry.ingested_count += accepted
                entry.error_count += push_errors

        pushed_total = sum(s.ingested_count for s in metrics_by_source.values())
        deduped_total = sum(s.deduped_count for s in metrics_by_source.values())
        fetched_total = sum(s.fetched_count for s in metrics_by_source.values())
        errors_total = sum(s.error_count for s in metrics_by_source.values())
        logger.info(
            "Collection complete: pushed %d new, skipped %d deduped (of %d ranked) to %s",
            pushed_total,
            deduped_total,
            len(merged),
            edge_url,
        )

        if errors_total > 0 and fetched_total == 0 and pushed_total == 0:
            total_failure_msg = f"Collector sync finished with {errors_total} errors and 0 jobs fetched."
            capture_worker_error_message(
                total_failure_msg,
                worker="vektryn-collect",
                error_type="CollectorTotalFailure",
                topic="collectors",
                extra={"error_count": errors_total},
            )
            await asyncio.to_thread(
                persist_pipeline_error_notifications,
                source="vektryn-collect",
                error_type="CollectorTotalFailure",
                error_message=total_failure_msg,
                extra_payload={"error_count": errors_total},
            )
        elif pushed_total > 0 or errors_total > 0:
            await asyncio.to_thread(
                persist_collector_sync_notifications,
                fetched_count=fetched_total,
                ingested_count=pushed_total,
                deduped_count=deduped_total,
                error_count=errors_total,
                sources_count=len(metrics_by_source),
            )

        try:
            persisted = await asyncio.to_thread(
                persist_collector_run_logs_sync,
                metrics_by_source,
                run_timestamp,
            )
            logger.info("Persisted %d CollectorRunLog telemetry rows", persisted)
        except Exception as exc:
            logger.warning("Failed persisting CollectorRunLog rows: %s", exc)
    finally:
        await _clear_collect_running_marker()

    return metrics_by_source


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Vektryn Global + Brazil ATS & feed collectors"
    )
    parser.add_argument("--resume-id", default=os.getenv("COLLECT_RESUME_ID") or None)
    parser.add_argument(
        "--min-skills", type=int, default=int(os.getenv("COLLECT_MIN_SKILLS", "2"))
    )
    parser.add_argument(
        "--max-total", type=int, default=int(os.getenv("COLLECT_MAX_TOTAL", "30"))
    )
    parser.add_argument(
        "--boards-per-ats",
        type=int,
        default=int(os.getenv("COLLECT_BOARDS_PER_ATS", "25")),
    )
    parser.add_argument("--refresh-discovery", action="store_true")
    return parser.parse_args()


def main() -> None:
    configure_sentry("vektryn-collect")
    args = _parse_args()
    edge = os.getenv("STREAM_EDGE_URL", "http://localhost:8001")
    cap_per_board = int(os.getenv("COLLECT_MAX_PER_BOARD", "8"))
    try:
        asyncio.run(
            run_collection(
                edge_url=edge,
                max_per_board=cap_per_board,
                boards_per_ats=args.boards_per_ats,
                max_total=args.max_total,
                resume_id=args.resume_id,
                min_skill_matches=args.min_skills,
                refresh_discovery=args.refresh_discovery,
            )
        )
    except Exception as exc:
        capture_worker_exception(exc, worker="vektryn-collect", topic="collectors")
        raise
    finally:
        flush_sentry(timeout=5.0)


if __name__ == "__main__":
    main()

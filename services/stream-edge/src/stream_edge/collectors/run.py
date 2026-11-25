import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import logging
import os
import time

import httpx
import psycopg
import redis.asyncio as aioredis

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
    filter_and_rank_jobs,
    load_resume_criteria,
)
from stream_edge.collectors.remote_feeds import MultiCompanyFeedCollector
from stream_edge.collectors.taxonomy import sync_dynamic_stacks
from stream_edge.config import settings
from vektryn_contracts import compute_job_content_hash

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

    hashed = [(job, compute_collected_job_hash(job)) for job in jobs]
    unique_hashes = list({h for _, h in hashed})
    db_existing, redis_claimed = await asyncio.gather(
        asyncio.to_thread(_find_existing_active_hashes_sync, unique_hashes),
        _find_redis_claimed_hashes(unique_hashes),
    )
    known = db_existing | redis_claimed

    to_ingest: list[CollectedJob] = []
    deduped: list[CollectedJob] = []
    seen_in_batch: set[str] = set()

    for job, content_hash in hashed:
        if content_hash in known or content_hash in seen_in_batch:
            deduped.append(job)
        else:
            seen_in_batch.add(content_hash)
            to_ingest.append(job)
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

            # 4. Merge, rank by resume skill overlap, pre-dedup unchanged active jobs, and push new postings
            merged = filter_and_rank_jobs(
                [*feed_candidates, *ats_candidates],
                criteria,
                dynamic_stacks=dynamic_stacks,
                min_skill_matches=min_skill_matches,
            )[:max_total]

            to_ingest, deduped = await partition_new_and_deduped_jobs(merged)
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
        logger.info(
            "Collection complete: pushed %d new, skipped %d deduped (of %d ranked) to %s",
            pushed_total,
            deduped_total,
            len(merged),
            edge_url,
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


if __name__ == "__main__":
    args = _parse_args()
    edge = os.getenv("STREAM_EDGE_URL", "http://localhost:8001")
    cap_per_board = int(os.getenv("COLLECT_MAX_PER_BOARD", "8"))
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

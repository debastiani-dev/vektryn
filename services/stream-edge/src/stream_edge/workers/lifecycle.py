import asyncio
from datetime import datetime, timezone
import logging

import httpx
import psycopg

from stream_edge.config import settings

logger = logging.getLogger(__name__)

_CLOSED_HTTP_STATUSES = frozenset({404, 410})
_CLOSED_BODY_MARKERS = (
    "no longer accepting applications",
    "job has been closed",
    "position has been filled",
    "this job is no longer available",
    "vaga encerrada",
)
_MAX_CONCURRENCY = 8

_FETCH_ACTIVE_SQL = """
    SELECT uuid, apply_url
    FROM jobs_jobposting
    WHERE is_active = TRUE
      AND is_deleted = FALSE
    ORDER BY COALESCE(modified_at, created_at) ASC
    LIMIT %s
"""

_MARK_CLOSED_SQL = """
    UPDATE jobs_jobposting
    SET is_active = FALSE,
        closed_at = %s,
        modified_at = %s
    WHERE uuid = ANY(%s::uuid[])
"""


async def _is_posting_closed(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    posting_uuid: str,
    apply_url: str,
) -> str | None:
    async with semaphore:
        try:
            resp = await client.get(apply_url, follow_redirects=True)
            if resp.status_code in _CLOSED_HTTP_STATUSES:
                return posting_uuid
            if resp.status_code == 200:
                snippet = resp.text[:4000].lower()
                if any(marker in snippet for marker in _CLOSED_BODY_MARKERS):
                    return posting_uuid
        except httpx.HTTPError as exc:
            logger.debug(
                "Skipping transient lifecycle probe error for %s: %s", apply_url, exc
            )
    return None


async def run_lifecycle_check(batch_size: int = 200) -> int:
    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(_FETCH_ACTIVE_SQL, (batch_size,))
            rows = cur.fetchall()

    if not rows:
        logger.info("No active JobPosting records to verify")
        return 0

    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(12.0),
        headers={"User-Agent": "VektrynLifecycleBot/0.2"},
    ) as client:
        results = await asyncio.gather(
            *(_is_posting_closed(client, semaphore, str(uid), url) for uid, url in rows)
        )

    closed_uuids = [uid for uid in results if uid is not None]
    if not closed_uuids:
        logger.info("Verified %d active postings; 0 closed upstream", len(rows))
        return 0

    now = datetime.now(timezone.utc)
    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(_MARK_CLOSED_SQL, (now, now, closed_uuids))
        conn.commit()

    logger.info(
        "Marked %d of %d checked postings as closed upstream",
        len(closed_uuids),
        len(rows),
    )
    return len(closed_uuids)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
    )
    asyncio.run(run_lifecycle_check())

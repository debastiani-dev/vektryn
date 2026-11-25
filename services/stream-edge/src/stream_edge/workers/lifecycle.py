import asyncio
from datetime import UTC, datetime
import logging
import uuid

import httpx
import psycopg

from stream_edge.clients.notifications import (
    DEFAULT_NOTIFICATION_RETENTION_DAYS,
    insert_notification_with_cursor,
    prune_expired_notifications_sync,
)
from stream_edge.config import settings
from vektryn_contracts import NotificationKind

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
      AND (apply_url LIKE 'http://%' OR apply_url LIKE 'https://%')
    ORDER BY COALESCE(modified_at, created_at) ASC
    LIMIT %s
"""

_MARK_CLOSED_SQL = """
    UPDATE jobs_jobposting
    SET is_active = FALSE,
        closed_at = %s,
        modified_at = %s
    WHERE uuid = ANY(%s::uuid[])
      AND is_active = TRUE
    RETURNING uuid, title, company_name, apply_url
"""

_ACTIVE_LEADS_FOR_JOBS_SQL = """
    SELECT uuid, user_id, job_posting_id, status
    FROM tracker_applicationlead
    WHERE job_posting_id = ANY(%s::uuid[])
      AND is_deleted = FALSE
      AND status NOT IN ('rejected', 'withdrawn')
"""

_CLAIM_DUE_FOLLOWUPS_SQL = """
    UPDATE tracker_applicationlead AS l
    SET followup_notified_at = %s,
        modified_at = %s
    FROM jobs_jobposting AS j
    WHERE l.job_posting_id = j.uuid
      AND l.is_deleted = FALSE
      AND j.is_deleted = FALSE
      AND l.status NOT IN ('rejected', 'withdrawn')
      AND l.next_action_at IS NOT NULL
      AND l.next_action_at <= %s
      AND (l.followup_notified_at IS NULL OR l.followup_notified_at < l.next_action_at)
    RETURNING l.uuid, l.user_id, l.job_posting_id, l.status, l.next_action_at,
              j.title, j.company_name, j.apply_url
"""


async def _is_posting_closed(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    posting_uuid: str,
    apply_url: str,
) -> str | None:
    if not apply_url.lower().startswith(("http://", "https://")):
        return None
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


def _mark_closed_and_notify_sync(
    closed_uuids: list[str],
    now: datetime,
) -> tuple[int, int]:
    if not closed_uuids:
        return 0, 0

    with psycopg.connect(settings.postgres_dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(_MARK_CLOSED_SQL, (now, now, closed_uuids))
            transitioned = cur.fetchall()
            if not transitioned:
                conn.commit()
                return 0, 0

            jobs_by_uuid = {
                str(job_uuid): (title, company_name, apply_url)
                for job_uuid, title, company_name, apply_url in transitioned
            }
            cur.execute(_ACTIVE_LEADS_FOR_JOBS_SQL, (list(jobs_by_uuid.keys()),))
            leads = cur.fetchall()

            for lead_uuid, user_id, job_uuid, lead_status in leads:
                title, company_name, apply_url = jobs_by_uuid[str(job_uuid)]
                insert_notification_with_cursor(
                    cur,
                    notification_uuid=uuid.uuid4(),
                    user_id=user_id,
                    kind=NotificationKind.TRACKED_JOB_CLOSED,
                    title=f"Tracked role closed: {title}"[:255],
                    body=(
                        f"{company_name} appears to have closed this listing upstream "
                        f"(currently '{lead_status}' in your Pipeline Tracker)."
                    ),
                    payload={
                        "job_posting_uuid": str(job_uuid),
                        "lead_uuid": str(lead_uuid),
                        "lead_status": str(lead_status),
                        "title": title,
                        "company_name": company_name,
                        "apply_url": apply_url,
                    },
                    now=now,
                )
        conn.commit()
    return len(transitioned), len(leads)


def _notify_due_followups_sync(now: datetime) -> int:
    with psycopg.connect(settings.postgres_dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(_CLAIM_DUE_FOLLOWUPS_SQL, (now, now, now))
            due_rows = cur.fetchall()
            for (
                lead_uuid,
                user_id,
                job_uuid,
                lead_status,
                next_action_at,
                title,
                company_name,
                apply_url,
            ) in due_rows:
                due_iso = (
                    next_action_at.isoformat()
                    if hasattr(next_action_at, "isoformat")
                    else str(next_action_at)
                )
                due_label = (
                    next_action_at.strftime("%b %d, %Y")
                    if hasattr(next_action_at, "strftime")
                    else due_iso[:10]
                )
                insert_notification_with_cursor(
                    cur,
                    notification_uuid=uuid.uuid4(),
                    user_id=user_id,
                    kind=NotificationKind.LEAD_FOLLOWUP_DUE,
                    title=f"Follow-up due: {title}"[:255],
                    body=(
                        f"Scheduled follow-up for {company_name} ({lead_status}) "
                        f"was due on {due_label}."
                    ),
                    payload={
                        "lead_uuid": str(lead_uuid),
                        "job_posting_uuid": str(job_uuid),
                        "lead_status": str(lead_status),
                        "next_action_at": due_iso,
                        "title": title,
                        "company_name": company_name,
                        "apply_url": apply_url,
                    },
                    now=now,
                )
        conn.commit()
    return len(due_rows)


def _run_due_followups_sync(now: datetime) -> int:
    try:
        notified = _notify_due_followups_sync(now)
        if notified > 0:
            logger.info("Emitted %d lead_followup_due notifications", notified)
        return notified
    except Exception as exc:
        logger.warning("Due follow-up notification sweep failed: %s", exc)
        return 0


def _run_notification_retention_sync(now: datetime) -> int:
    try:
        pruned = prune_expired_notifications_sync(
            now=now,
            retention_days=DEFAULT_NOTIFICATION_RETENTION_DAYS,
        )
        if pruned > 0:
            logger.info("Pruned %d expired notifications (>30d)", pruned)
        return pruned
    except Exception as exc:
        logger.warning("Notification retention sweep failed: %s", exc)
        return 0


async def run_lifecycle_check(batch_size: int = 200) -> int:
    now = datetime.now(UTC)
    closed_count = 0
    try:
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
                *(
                    _is_posting_closed(client, semaphore, str(uid), url)
                    for uid, url in rows
                )
            )

        closed_uuids = [uid for uid in results if uid is not None]
        if not closed_uuids:
            logger.info("Verified %d active postings; 0 closed upstream", len(rows))
            return 0

        closed_count, notified_count = await asyncio.to_thread(
            _mark_closed_and_notify_sync,
            closed_uuids,
            now,
        )
        logger.info(
            "Marked %d of %d checked postings as closed upstream (notified %d active leads)",
            closed_count,
            len(rows),
            notified_count,
        )
        return closed_count
    finally:
        await asyncio.to_thread(_run_due_followups_sync, now)
        await asyncio.to_thread(_run_notification_retention_sync, now)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
    )
    asyncio.run(run_lifecycle_check())

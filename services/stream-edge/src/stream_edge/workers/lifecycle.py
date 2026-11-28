import asyncio
from collections import defaultdict
from dataclasses import dataclass
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
from stream_edge.telemetry import (
    capture_worker_exception,
    configure_sentry,
    flush_sentry,
)
from vektryn_contracts import (
    NotificationKind,
    get_source_priority_rank,
    is_direct_ats_source,
    is_generic_company_name,
)

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

_FETCH_ACTIVE_SOURCES_SQL = """
    SELECT
        s.uuid,
        s.job_posting_id,
        s.ats_source,
        s.apply_url,
        s.is_primary,
        COALESCE(j.company_name_normalized, '')
    FROM jobs_jobpostingsource s
    INNER JOIN jobs_jobposting j ON j.uuid = s.job_posting_id
    WHERE s.is_active = TRUE
      AND s.is_deleted = FALSE
      AND j.is_active = TRUE
      AND j.is_deleted = FALSE
      AND (s.apply_url ILIKE 'http://%%' OR s.apply_url ILIKE 'https://%%')
    ORDER BY s.last_seen_at ASC
    LIMIT %s
"""

_FETCH_ACTIVE_SQL = _FETCH_ACTIVE_SOURCES_SQL

_FETCH_LEGACY_ACTIVE_SQL = """
    SELECT j.uuid, j.apply_url
    FROM jobs_jobposting j
    WHERE j.is_active = TRUE
      AND j.is_deleted = FALSE
      AND (j.apply_url ILIKE 'http://%%' OR j.apply_url ILIKE 'https://%%')
      AND NOT EXISTS (
          SELECT 1
          FROM jobs_jobpostingsource s
          WHERE s.job_posting_id = j.uuid
            AND s.is_deleted = FALSE
      )
    ORDER BY COALESCE(j.modified_at, j.created_at) ASC
    LIMIT %s
"""

_TOUCH_LIVE_SOURCES_SQL = """
    UPDATE jobs_jobpostingsource
    SET last_seen_at = %s,
        modified_at = %s
    WHERE uuid = ANY(%s::uuid[])
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


@dataclass(frozen=True)
class _ProbedSource:
    source_uuid: str
    job_uuid: str
    ats_source: str
    apply_url: str
    is_primary: bool
    company_norm: str


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


async def _probe_source(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    source: _ProbedSource,
) -> tuple[_ProbedSource, bool | None]:
    """Return (source, True) if closed, (source, False) if live, (source, None) on transient error."""
    if not source.apply_url.lower().startswith(("http://", "https://")):
        return source, None
    async with semaphore:
        try:
            resp = await client.get(source.apply_url, follow_redirects=True)
            if resp.status_code in _CLOSED_HTTP_STATUSES:
                return source, True
            if resp.status_code == 200:
                snippet = resp.text[:4000].lower()
                if any(marker in snippet for marker in _CLOSED_BODY_MARKERS):
                    return source, True
            return source, False
        except httpx.HTTPError as exc:
            logger.debug(
                "Skipping transient lifecycle probe error for %s: %s",
                source.apply_url,
                exc,
            )
            return source, None


def _notify_closed_jobs_with_cursor(
    cur: psycopg.Cursor,
    closed_uuids: list[str],
    now: datetime,
) -> tuple[int, int]:
    if not closed_uuids:
        return 0, 0
    cur.execute(_MARK_CLOSED_SQL, (now, now, closed_uuids))
    transitioned = cur.fetchall()
    if not transitioned:
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
    return len(transitioned), len(leads)


def _mark_closed_and_notify_sync(
    closed_uuids: list[str],
    now: datetime,
) -> tuple[int, int]:
    if not closed_uuids:
        return 0, 0
    with psycopg.connect(settings.postgres_dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            closed_count, notified_count = _notify_closed_jobs_with_cursor(
                cur, closed_uuids, now
            )
        conn.commit()
    return closed_count, notified_count


def _failover_primary_source(
    cur: psycopg.Cursor,
    *,
    job_uuid: str,
    remaining: list[tuple],
    now: datetime,
) -> None:
    best = min(
        remaining,
        key=lambda row: (get_source_priority_rank(str(row[1])), row[4]),
    )
    best_uuid, _best_ats, best_url = best[0], best[1], best[2]
    cur.execute(
        """
        UPDATE jobs_jobpostingsource
        SET is_primary = FALSE, modified_at = %s
        WHERE job_posting_id = %s
          AND is_primary = TRUE
          AND is_deleted = FALSE
        """,
        (now, job_uuid),
    )
    cur.execute(
        """
        UPDATE jobs_jobpostingsource
        SET is_primary = TRUE, modified_at = %s
        WHERE uuid = %s
        """,
        (now, best_uuid),
    )
    cur.execute(
        """
        UPDATE jobs_jobposting
        SET apply_url = %s, modified_at = %s
        WHERE uuid = %s
        """,
        (best_url, now, job_uuid),
    )


def _process_closed_sources_for_job(
    cur: psycopg.Cursor,
    *,
    job_uuid: str,
    job_closed_sources: list[_ProbedSource],
    now: datetime,
) -> tuple[bool, bool]:
    """Handle closed sources for one job. Returns (should_close_job, failed_over)."""
    company_norm = job_closed_sources[0].company_norm
    if not is_generic_company_name(company_norm):
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"vektryn:job_dedup:{company_norm}",),
        )

    cur.execute(
        """
        UPDATE jobs_jobpostingsource
        SET is_active = FALSE,
            modified_at = %s
        WHERE uuid = ANY(%s::uuid[])
          AND is_deleted = FALSE
        """,
        (now, [s.source_uuid for s in job_closed_sources]),
    )

    # Rule 1: Direct ATS primary closed -> close canonical job immediately
    if any(
        s.is_primary and is_direct_ats_source(s.ats_source) for s in job_closed_sources
    ):
        return True, False

    cur.execute(
        """
        SELECT uuid, ats_source, apply_url, is_primary, first_seen_at
        FROM jobs_jobpostingsource
        WHERE job_posting_id = %s
          AND is_active = TRUE
          AND is_deleted = FALSE
        ORDER BY first_seen_at ASC
        """,
        (job_uuid,),
    )
    remaining = cur.fetchall()
    if not remaining:
        return True, False

    # Rule 2: Primary aggregator closed while active sources remain -> atomic failover
    any_primary_closed = any(s.is_primary for s in job_closed_sources)
    has_active_primary = any(bool(row[3]) for row in remaining)
    if any_primary_closed or not has_active_primary:
        _failover_primary_source(cur, job_uuid=job_uuid, remaining=remaining, now=now)
        return False, True

    return False, False


def _apply_source_lifecycle_outcomes_sync(
    *,
    live_source_uuids: list[str],
    closed_sources: list[_ProbedSource],
    now: datetime,
) -> tuple[int, int, int]:
    """Persist live touches, close sources, fail over aggregator primaries, and close canonical jobs.

    Returns (closed_jobs_count, failover_count, leads_notified_count).
    """
    if not live_source_uuids and not closed_sources:
        return 0, 0, 0

    closed_by_job: dict[str, list[_ProbedSource]] = defaultdict(list)
    for src in closed_sources:
        closed_by_job[src.job_uuid].append(src)

    jobs_to_close: list[str] = []
    failover_count = 0

    with psycopg.connect(settings.postgres_dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            if live_source_uuids:
                cur.execute(_TOUCH_LIVE_SOURCES_SQL, (now, now, live_source_uuids))

            for job_uuid in sorted(closed_by_job.keys()):
                should_close, failed_over = _process_closed_sources_for_job(
                    cur,
                    job_uuid=job_uuid,
                    job_closed_sources=closed_by_job[job_uuid],
                    now=now,
                )
                if should_close:
                    jobs_to_close.append(job_uuid)
                elif failed_over:
                    failover_count += 1

            closed_jobs_count, leads_notified = _notify_closed_jobs_with_cursor(
                cur, jobs_to_close, now
            )
        conn.commit()

    return closed_jobs_count, failover_count, leads_notified


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
                cur.execute(_FETCH_ACTIVE_SOURCES_SQL, (batch_size,))
                source_rows = cur.fetchall()
                remaining_budget = max(0, batch_size - len(source_rows))
                legacy_rows: list[tuple] = []
                if remaining_budget > 0:
                    cur.execute(_FETCH_LEGACY_ACTIVE_SQL, (remaining_budget,))
                    legacy_rows = cur.fetchall()

        if not source_rows and not legacy_rows:
            logger.info("No active JobPostingSource or JobPosting records to verify")
            return 0

        probed_sources = [
            _ProbedSource(
                source_uuid=str(row[0]),
                job_uuid=str(row[1]),
                ats_source=str(row[2]),
                apply_url=str(row[3]),
                is_primary=bool(row[4]),
                company_norm=str(row[5] or ""),
            )
            for row in source_rows
        ]

        semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(12.0),
            headers={"User-Agent": "VektrynLifecycleBot/0.2"},
        ) as client:
            source_results = await asyncio.gather(
                *(_probe_source(client, semaphore, src) for src in probed_sources)
            )
            legacy_results = await asyncio.gather(
                *(
                    _is_posting_closed(client, semaphore, str(uid), url)
                    for uid, url in legacy_rows
                )
            )

        live_source_uuids = [
            src.source_uuid for src, is_closed in source_results if is_closed is False
        ]
        closed_sources = [src for src, is_closed in source_results if is_closed is True]
        closed_legacy_uuids = [uid for uid in legacy_results if uid is not None]

        source_closed_jobs, failovers, source_leads = (
            _apply_source_lifecycle_outcomes_sync(
                live_source_uuids=live_source_uuids,
                closed_sources=closed_sources,
                now=now,
            )
        )
        legacy_closed_jobs, legacy_leads = _mark_closed_and_notify_sync(
            closed_legacy_uuids, now
        )
        closed_count = source_closed_jobs + legacy_closed_jobs
        notified_leads = source_leads + legacy_leads

        logger.info(
            "Lifecycle check complete: probed %d sources + %d legacy postings; "
            "closed %d jobs, failed over %d primaries, notified %d tracked leads",
            len(probed_sources),
            len(legacy_rows),
            closed_count,
            failovers,
            notified_leads,
        )
        return closed_count
    finally:
        _run_due_followups_sync(now)
        _run_notification_retention_sync(now)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    configure_sentry("vektryn-lifecycle")
    try:
        asyncio.run(run_lifecycle_check())
    except Exception as exc:
        capture_worker_exception(
            exc,
            worker="vektryn-lifecycle",
            topic="lifecycle",
        )
        raise
    finally:
        flush_sentry(timeout=5.0)


if __name__ == "__main__":
    main()

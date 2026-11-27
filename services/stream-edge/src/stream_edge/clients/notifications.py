from datetime import UTC, datetime, timedelta
import json
import logging
from typing import Any
import uuid

import psycopg
import redis

from stream_edge.config import settings
from vektryn_contracts import (
    NOTIFICATION_THROTTLE_SECONDS,
    NotificationKind,
    gemini_notification_throttle_key,
)

logger = logging.getLogger(__name__)

DEFAULT_NOTIFICATION_RETENTION_DAYS = 30
PIPELINE_ERROR_THROTTLE_SECONDS = 1800
PIPELINE_ERROR_KEY_PREFIX = "vektryn:notif:pipeline_error:"
DB_ERROR_NOTIF_CONNECT_TIMEOUT = 3
DB_ERROR_NOTIF_STATEMENT_TIMEOUT_MS = 3000

INSERT_NOTIFICATION_SQL = """
INSERT INTO base_notification (
    uuid, created_at, modified_at, is_deleted,
    user_id, kind, title, body, payload, read_at, dismissed_at
)
VALUES (%s, %s, %s, FALSE, %s, %s, %s, %s, %s::jsonb, NULL, NULL)
"""

PRUNE_NOTIFICATIONS_SQL = """
DELETE FROM base_notification
WHERE (read_at IS NOT NULL OR dismissed_at IS NOT NULL OR is_deleted = TRUE)
  AND created_at < %s
"""

ACTIVE_STAFF_USERS_SQL = """
SELECT id
FROM auth_user
WHERE is_staff = TRUE
  AND is_active = TRUE
"""


def insert_notification_with_cursor(
    cur: psycopg.Cursor,
    *,
    notification_uuid: uuid.UUID,
    user_id: int | uuid.UUID,
    kind: NotificationKind | str,
    title: str,
    body: str,
    payload: dict[str, Any],
    now: datetime,
) -> uuid.UUID:
    kind_value = kind.value if isinstance(kind, NotificationKind) else str(kind)
    cur.execute(
        INSERT_NOTIFICATION_SQL,
        (
            notification_uuid,
            now,
            now,
            user_id,
            kind_value,
            title[:255],
            body,
            json.dumps(payload),
        ),
    )
    return notification_uuid


def prune_expired_notifications_sync(
    now: datetime | None = None,
    retention_days: int = DEFAULT_NOTIFICATION_RETENTION_DAYS,
) -> int:
    reference = now or datetime.now(UTC)
    cutoff = reference - timedelta(days=retention_days)
    with psycopg.connect(settings.postgres_dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(PRUNE_NOTIFICATIONS_SQL, (cutoff,))
            deleted = cur.rowcount or 0
        conn.commit()
    return int(deleted)


def _acquire_pipeline_error_throttle(
    source: str,
    error_type: str,
    throttle_seconds: int = PIPELINE_ERROR_THROTTLE_SECONDS,
) -> bool:
    redis_url = (settings.redis_url or "").strip()
    if not redis_url:
        return True
    key = f"{PIPELINE_ERROR_KEY_PREFIX}{source}:{error_type}"
    client = redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )
    try:
        return bool(client.set(key, "1", nx=True, ex=max(60, int(throttle_seconds))))
    except Exception as exc:
        logger.debug("Redis throttle unavailable for pipeline_error alert: %s", exc)
        return True
    finally:
        try:
            client.close()
        except Exception as close_exc:
            logger.debug("Ignoring Redis close error: %s", close_exc)


def persist_pipeline_error_notifications(
    *,
    source: str,
    error_type: str,
    error_message: str,
    extra_payload: dict[str, Any] | None = None,
    throttle_seconds: int = PIPELINE_ERROR_THROTTLE_SECONDS,
) -> int:
    """Persists throttled pipeline_error notifications for active staff users."""
    acquired = (
        _acquire_pipeline_error_throttle(source, error_type)
        if throttle_seconds == PIPELINE_ERROR_THROTTLE_SECONDS
        else _acquire_pipeline_error_throttle(source, error_type, throttle_seconds)
    )
    if not acquired:
        return 0

    now = datetime.now(UTC)
    clean_message = (error_message or "").strip()[:1000]
    title = f"Pipeline error in {source}: {error_type}"[:255]
    body = clean_message or f"{source} encountered {error_type}."
    payload: dict[str, Any] = {
        "source": source,
        "error_type": error_type,
        "error_message": clean_message,
        **(extra_payload or {}),
    }

    try:
        with psycopg.connect(
            settings.postgres_dsn,
            autocommit=False,
            connect_timeout=DB_ERROR_NOTIF_CONNECT_TIMEOUT,
            options=f"-c statement_timeout={DB_ERROR_NOTIF_STATEMENT_TIMEOUT_MS}",
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(ACTIVE_STAFF_USERS_SQL)
                staff_rows = cur.fetchall()
                for (staff_user_id,) in staff_rows:
                    insert_notification_with_cursor(
                        cur,
                        notification_uuid=uuid.uuid4(),
                        user_id=staff_user_id,
                        kind=NotificationKind.PIPELINE_ERROR,
                        title=title,
                        body=body,
                        payload=payload,
                        now=now,
                    )
            conn.commit()
        return len(staff_rows)
    except Exception as exc:
        logger.warning(
            "Failed persisting pipeline_error notification for %s (%s): %s",
            source,
            error_type,
            exc,
        )
        return 0


def persist_collector_sync_notifications(
    *,
    fetched_count: int,
    ingested_count: int,
    deduped_count: int,
    error_count: int,
    sources_count: int,
) -> int:
    """Persists collector_sync_completed digest for active staff users when new jobs or errors occur."""
    if ingested_count <= 0 and error_count <= 0:
        return 0

    now = datetime.now(UTC)
    if ingested_count > 0:
        role_word = "role" if ingested_count == 1 else "roles"
        title = f"Collector sync: +{ingested_count} new {role_word}"[:255]
    else:
        err_word = "error" if error_count == 1 else "errors"
        title = f"Collector sync completed with {error_count} source {err_word}"[:255]

    body = (
        f"Fetched {fetched_count} postings across {sources_count} sources "
        f"({ingested_count} ingested, {deduped_count} deduped, {error_count} errors)."
    )
    payload: dict[str, Any] = {
        "fetched_count": fetched_count,
        "ingested_count": ingested_count,
        "deduped_count": deduped_count,
        "error_count": error_count,
        "sources_count": sources_count,
    }

    try:
        with psycopg.connect(
            settings.postgres_dsn,
            autocommit=False,
            connect_timeout=DB_ERROR_NOTIF_CONNECT_TIMEOUT,
            options=f"-c statement_timeout={DB_ERROR_NOTIF_STATEMENT_TIMEOUT_MS}",
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(ACTIVE_STAFF_USERS_SQL)
                staff_rows = cur.fetchall()
                for (staff_user_id,) in staff_rows:
                    insert_notification_with_cursor(
                        cur,
                        notification_uuid=uuid.uuid4(),
                        user_id=staff_user_id,
                        kind=NotificationKind.COLLECTOR_SYNC_COMPLETED,
                        title=title,
                        body=body,
                        payload=payload,
                        now=now,
                    )
            conn.commit()
        return len(staff_rows)
    except Exception as exc:
        logger.warning(
            "Failed persisting collector_sync_completed notification: %s", exc
        )
        return 0


def _acquire_user_ai_notification_throttle(
    user_id: int | uuid.UUID, kind: NotificationKind
) -> bool | None:
    """Return True if acquired in Redis, False if throttled, None if Redis unavailable."""
    redis_url = (settings.redis_url or "").strip()
    if not redis_url:
        return None
    key = gemini_notification_throttle_key(int(user_id), kind)
    client = redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )
    try:
        return bool(client.set(key, "1", nx=True, ex=NOTIFICATION_THROTTLE_SECONDS))
    except Exception as exc:
        logger.debug("Redis throttle unavailable for user AI notification: %s", exc)
        return None
    finally:
        try:
            client.close()
        except Exception as close_exc:
            logger.debug("Ignoring Redis close error: %s", close_exc)


def persist_user_ai_notification(
    *,
    user_id: int | uuid.UUID,
    kind: NotificationKind,
    title: str,
    body: str,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Persist a 6h-throttled per-user AI BYOK notification (ai_key_invalid / ai_quota_exhausted)."""
    throttle_result = _acquire_user_ai_notification_throttle(user_id, kind)
    if throttle_result is False:
        return False

    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=NOTIFICATION_THROTTLE_SECONDS)
    try:
        with psycopg.connect(
            settings.postgres_dsn,
            autocommit=False,
            connect_timeout=DB_ERROR_NOTIF_CONNECT_TIMEOUT,
            options=f"-c statement_timeout={DB_ERROR_NOTIF_STATEMENT_TIMEOUT_MS}",
        ) as conn:
            with conn.cursor() as cur:
                if throttle_result is None:
                    cur.execute(
                        """
                        SELECT 1
                        FROM base_notification
                        WHERE user_id = %s
                          AND kind = %s
                          AND is_deleted = FALSE
                          AND created_at >= %s
                        LIMIT 1
                        """,
                        (user_id, kind.value, cutoff),
                    )
                    if cur.fetchone() is not None:
                        return False
                insert_notification_with_cursor(
                    cur,
                    notification_uuid=uuid.uuid4(),
                    user_id=user_id,
                    kind=kind,
                    title=title,
                    body=body,
                    payload=payload or {},
                    now=now,
                )
            conn.commit()
        return True
    except Exception as exc:
        logger.warning(
            "Failed persisting user AI notification user=%s kind=%s: %s",
            user_id,
            kind.value,
            exc,
        )
        return False

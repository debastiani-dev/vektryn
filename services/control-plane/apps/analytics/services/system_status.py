from datetime import UTC, datetime, timedelta
import json
import logging
from typing import Any, Literal

from confluent_kafka import Consumer, TopicPartition
from django.conf import settings
from django.db.models import Exists, Max, OuterRef, Sum
import redis

from apps.analytics.models.analytics import CollectorRunLog, StackTrendDaily
from apps.analytics.services.collector_trigger import (
    get_collect_cooldown_remaining,
    get_collect_running_state,
)
from apps.analytics.services.dlq_inspector import (
    MAX_DLQ_INSPECT_LIMIT,
    count_unresolved_recent_dlq_messages,
)
from apps.analytics.services.kafka_probe import (
    DLQ_CACHE_KEY,
    KAFKA_PROBE_TIMEOUT_SECONDS,
    build_kafka_probe_config as _build_kafka_probe_config,
    close_consumer_safely as _close_consumer_safely,
    close_redis_safely as _close_redis_safely,
)
from apps.jobs.models.jobs import JobPosting
from apps.matching.models.matching import MatchScore
from apps.resumes.models.resumes import ResumeProfile
from vektryn_contracts import KafkaTopic

logger = logging.getLogger(__name__)

DLQ_CACHE_TTL_SECONDS = 30
COLLECT_STALE_HOURS = 12
MATCH_LAG_WINDOW_HOURS = 2
DLQ_LOOKBACK_HOURS = 24

EXPECTED_WORKERS: tuple[str, ...] = ("enrichment-worker", "matcher-worker")
WORKER_HEARTBEAT_KEY_PREFIX = "vektryn:worker:heartbeat:"
WORKER_HEARTBEAT_STALE_SECONDS = 60

OverallStatus = Literal["healthy", "warning", "degraded"]
WorkerLivenessStatus = Literal["alive", "stale", "offline", "unknown"]


def _get_redis_client() -> redis.Redis | None:
    redis_url = (getattr(settings, "REDIS_URL", "") or "").strip()
    if not redis_url:
        return None
    try:
        return redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
    except Exception as exc:
        logger.debug("Redis unavailable for system status cache: %s", exc)
        return None


def _unavailable_dlq_health() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "recent_24h_count": None,
        "total_count": None,
    }


def _count_partition_dlq_messages(
    consumer: Consumer,
    dlq_topic: str,
    partition_id: int,
    ts_24h_ms: int,
) -> tuple[int, int]:
    tp = TopicPartition(dlq_topic, partition_id)
    low, high = consumer.get_watermark_offsets(tp, timeout=KAFKA_PROBE_TIMEOUT_SECONDS)
    total = max(0, high - low)
    if high <= low:
        return total, 0

    ts_results = consumer.offsets_for_times(
        [TopicPartition(dlq_topic, partition_id, ts_24h_ms)],
        timeout=KAFKA_PROBE_TIMEOUT_SECONDS,
    )
    tp_24h = ts_results[0] if ts_results else None
    # OFFSET_INVALID (-1) means all messages in this partition are older than 24h
    if tp_24h is None or tp_24h.offset < 0:
        return total, 0
    return total, max(0, high - max(low, tp_24h.offset))


def _probe_kafka_dlq_health() -> dict[str, Any]:
    config = _build_kafka_probe_config()
    if config is None:
        return _unavailable_dlq_health()

    dlq_topic = KafkaTopic.JOBS_DLQ.value
    consumer: Consumer | None = None
    try:
        consumer = Consumer(config)
        cluster_meta = consumer.list_topics(
            topic=dlq_topic, timeout=KAFKA_PROBE_TIMEOUT_SECONDS
        )
        topic_meta = cluster_meta.topics.get(dlq_topic)
        if topic_meta is None or topic_meta.error is not None:
            return _unavailable_dlq_health()

        ts_24h_ms = int(
            (datetime.now(UTC) - timedelta(hours=DLQ_LOOKBACK_HOURS)).timestamp() * 1000
        )
        total_count = 0
        recent_24h_count = 0

        for partition_id in topic_meta.partitions:
            part_total, part_recent = _count_partition_dlq_messages(
                consumer, dlq_topic, partition_id, ts_24h_ms
            )
            total_count += part_total
            recent_24h_count += part_recent

        return {
            "status": "warning" if recent_24h_count > 0 else "healthy",
            "recent_24h_count": recent_24h_count,
            "total_count": total_count,
        }
    except Exception as exc:
        logger.warning("Kafka DLQ health probe failed: %s", exc)
        return _unavailable_dlq_health()
    finally:
        _close_consumer_safely(consumer)


def _read_cached_dlq_health(client: redis.Redis | None) -> dict[str, Any] | None:
    if client is None:
        return None
    try:
        cached = client.get(DLQ_CACHE_KEY)
        if not isinstance(cached, str) or not cached:
            return None
        parsed = json.loads(cached)
        if isinstance(parsed, dict) and "status" in parsed:
            return parsed
    except Exception as exc:
        logger.debug("Failed reading cached DLQ health: %s", exc)
    return None


def _refine_dlq_health_with_resolutions(health: dict[str, Any]) -> None:
    raw_recent = int(health.get("recent_24h_count") or 0)
    if raw_recent <= 0 or health.get("status") == "unavailable":
        return
    unresolved = _count_unresolved_recent_dlq(
        since_dt=datetime.now(UTC) - timedelta(hours=DLQ_LOOKBACK_HOURS),
        raw_recent_count=raw_recent,
    )
    if unresolved is not None:
        health["recent_24h_count"] = unresolved
        health["status"] = "warning" if unresolved > 0 else "healthy"


def _cache_dlq_health(client: redis.Redis | None, health: dict[str, Any]) -> None:
    if client is None:
        return
    try:
        client.set(DLQ_CACHE_KEY, json.dumps(health), ex=DLQ_CACHE_TTL_SECONDS)
    except Exception as exc:
        logger.debug("Failed caching DLQ health: %s", exc)


def get_dlq_health() -> dict[str, Any]:
    client = _get_redis_client()
    try:
        cached = _read_cached_dlq_health(client)
        if cached is not None:
            return cached

        health = _probe_kafka_dlq_health()
        if client is not None:
            _refine_dlq_health_with_resolutions(health)
            _cache_dlq_health(client, health)
        return health
    finally:
        _close_redis_safely(client)


def _count_unresolved_recent_dlq(
    *,
    since_dt: datetime,
    raw_recent_count: int,
) -> int | None:
    if raw_recent_count > MAX_DLQ_INSPECT_LIMIT:
        return None
    return count_unresolved_recent_dlq_messages(
        since_dt=since_dt,
        max_scan_per_partition=raw_recent_count,
    )


def _unknown_workers_payload() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "items": [
            {
                "worker": name,
                "status": "unknown",
                "last_heartbeat_at": None,
                "last_message_at": None,
                "processed_count": 0,
                "age_seconds": None,
            }
            for name in EXPECTED_WORKERS
        ],
    }


def _parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def _parse_worker_entry(
    worker_name: str,
    raw_value: object,
    now: datetime,
) -> dict[str, Any]:
    if not isinstance(raw_value, str) or not raw_value:
        return {
            "worker": worker_name,
            "status": "offline",
            "last_heartbeat_at": None,
            "last_message_at": None,
            "processed_count": 0,
            "age_seconds": None,
        }

    try:
        parsed = json.loads(raw_value)
    except (ValueError, TypeError):
        parsed = None

    if not isinstance(parsed, dict):
        return {
            "worker": worker_name,
            "status": "offline",
            "last_heartbeat_at": None,
            "last_message_at": None,
            "processed_count": 0,
            "age_seconds": None,
        }

    hb_dt = _parse_iso_datetime(parsed.get("last_heartbeat_at"))
    if hb_dt is None:
        return {
            "worker": worker_name,
            "status": "offline",
            "last_heartbeat_at": None,
            "last_message_at": None,
            "processed_count": 0,
            "age_seconds": None,
        }

    age_seconds = max(0, int((now - hb_dt).total_seconds()))
    liveness: WorkerLivenessStatus = (
        "alive" if age_seconds <= WORKER_HEARTBEAT_STALE_SECONDS else "stale"
    )
    msg_dt = _parse_iso_datetime(parsed.get("last_message_at"))
    raw_count = parsed.get("processed_count", 0)
    processed_count = (
        max(0, int(raw_count))
        if isinstance(raw_count, (int, float)) and not isinstance(raw_count, bool)
        else 0
    )
    return {
        "worker": worker_name,
        "status": liveness,
        "last_heartbeat_at": hb_dt.isoformat(),
        "last_message_at": msg_dt.isoformat() if msg_dt else None,
        "processed_count": processed_count,
        "age_seconds": age_seconds,
    }


def _aggregate_worker_status(items: list[dict[str, Any]]) -> str:
    statuses = {item["status"] for item in items}
    if "offline" in statuses:
        return "degraded"
    if "stale" in statuses:
        return "warning"
    if statuses == {"alive"}:
        return "healthy"
    return "unavailable"


def get_worker_health() -> tuple[dict[str, Any], bool]:
    """Returns (workers_payload, redis_runtime_error)."""
    client = _get_redis_client()
    if client is None:
        return _unknown_workers_payload(), False

    keys = [f"{WORKER_HEARTBEAT_KEY_PREFIX}{name}" for name in EXPECTED_WORKERS]
    now = datetime.now(UTC)
    try:
        values = client.mget(keys)
    except Exception as exc:
        logger.warning("Redis unavailable while reading worker heartbeats: %s", exc)
        return _unknown_workers_payload(), True
    finally:
        _close_redis_safely(client)

    items = [
        _parse_worker_entry(
            name,
            values[idx] if idx < len(values) else None,
            now,
        )
        for idx, name in enumerate(EXPECTED_WORKERS)
    ]
    return {"status": _aggregate_worker_status(items), "items": items}, False


def _get_collector_telemetry() -> (
    tuple[datetime | None, dict[str, int], list[dict[str, Any]]]
):
    latest_per_source_qs = CollectorRunLog.objects.order_by(
        "source", "-ran_at"
    ).distinct("source")
    sources = [
        {
            "source": row.source,
            "fetched_count": row.fetched_count,
            "ingested_count": row.ingested_count,
            "deduped_count": row.deduped_count,
            "error_count": row.error_count,
            "duration_ms": row.duration_ms,
            "ran_at": row.ran_at.isoformat(),
        }
        for row in latest_per_source_qs
    ]

    last_collect_at: datetime | None = CollectorRunLog.objects.aggregate(
        latest=Max("ran_at")
    )["latest"]
    if last_collect_at is None:
        empty_totals = {
            "fetched_count": 0,
            "ingested_count": 0,
            "deduped_count": 0,
            "error_count": 0,
            "duration_ms": 0,
        }
        return None, empty_totals, sources

    batch_agg = CollectorRunLog.objects.filter(ran_at=last_collect_at).aggregate(
        fetched_count=Sum("fetched_count"),
        ingested_count=Sum("ingested_count"),
        deduped_count=Sum("deduped_count"),
        error_count=Sum("error_count"),
        duration_ms=Max("duration_ms"),
    )
    totals = {
        "fetched_count": int(batch_agg["fetched_count"] or 0),
        "ingested_count": int(batch_agg["ingested_count"] or 0),
        "deduped_count": int(batch_agg["deduped_count"] or 0),
        "error_count": int(batch_agg["error_count"] or 0),
        "duration_ms": int(batch_agg["duration_ms"] or 0),
    }
    return last_collect_at, totals, sources


def _get_job_backlog_metrics(user) -> dict[str, int]:
    active_jobs = JobPosting.objects.filter(is_active=True)
    active_count = active_jobs.count()
    unembedded_active_count = active_jobs.filter(embedding__isnull=True).count()

    active_resumes = ResumeProfile.objects.filter(
        user=user,
        is_active=True,
        embedding__isnull=False,
    )
    if not active_resumes.exists():
        return {
            "active_count": active_count,
            "matched_active_count": 0,
            "ai_scored_count": 0,
            "unscored_active_count": active_count,
            "pending_match_count": 0,
            "recent_unmatched_count": 0,
            "unembedded_active_count": unembedded_active_count,
        }

    any_match_exists = Exists(
        MatchScore.objects.filter(
            job_posting=OuterRef("pk"),
            resume_profile__in=active_resumes,
        )
    )
    scored_match_exists = Exists(
        MatchScore.objects.filter(
            job_posting=OuterRef("pk"),
            resume_profile__in=active_resumes,
            fit_score__isnull=False,
        )
    )
    ai_scored_count = active_jobs.filter(scored_match_exists).count()
    pending_match_count = active_jobs.filter(~any_match_exists).count()
    lag_cutoff = datetime.now(UTC) - timedelta(hours=MATCH_LAG_WINDOW_HOURS)
    recent_unmatched_count = (
        active_jobs.filter(created_at__gte=lag_cutoff).filter(~any_match_exists).count()
    )

    return {
        "active_count": active_count,
        "matched_active_count": max(0, active_count - pending_match_count),
        "ai_scored_count": ai_scored_count,
        "unscored_active_count": max(0, active_count - ai_scored_count),
        "pending_match_count": pending_match_count,
        "recent_unmatched_count": recent_unmatched_count,
        "unembedded_active_count": unembedded_active_count,
    }


def _get_rollup_metrics() -> dict[str, str | None]:
    agg = StackTrendDaily.objects.aggregate(
        latest_bucket_date=Max("bucket_date"),
        latest_updated_at=Max("modified_at"),
    )
    bucket_date = agg["latest_bucket_date"]
    updated_at = agg["latest_updated_at"]
    return {
        "latest_bucket_date": bucket_date.isoformat() if bucket_date else None,
        "latest_updated_at": updated_at.isoformat() if updated_at else None,
    }


def _workers_with_status(workers: dict[str, Any] | None, target: str) -> list[str]:
    items = (workers or {}).get("items") or []
    return [
        str(item["worker"])
        for item in items
        if isinstance(item, dict) and item.get("status") == target
    ]


def _collect_degraded_reasons(
    *,
    last_collect_at: datetime | None,
    latest_run_totals: dict[str, int],
    dlq: dict[str, Any],
    workers: dict[str, Any] | None,
) -> list[str]:
    reasons: list[str] = []
    recent_dlq = int(dlq.get("recent_24h_count") or 0)
    if recent_dlq > 0:
        noun = "failure" if recent_dlq == 1 else "failures"
        reasons.append(f"Dead-letter queue has {recent_dlq} unresolved {noun} (24h).")

    offline_workers = _workers_with_status(workers, "offline")
    if offline_workers:
        reasons.append(f"Worker offline: {', '.join(offline_workers)}.")
    elif (workers or {}).get("status") == "degraded":
        reasons.append("One or more Kafka workers are offline.")

    if (
        last_collect_at is not None
        and latest_run_totals["error_count"] > 0
        and latest_run_totals["fetched_count"] == 0
        and latest_run_totals["ingested_count"] == 0
    ):
        reasons.append("Latest collector sync failed across all sources.")

    return reasons


def _collect_warning_reasons(
    *,
    last_collect_at: datetime | None,
    jobs_metrics: dict[str, int],
    dlq: dict[str, Any],
    workers: dict[str, Any] | None,
    workers_redis_error: bool,
) -> list[str]:
    reasons: list[str] = []
    stale_cutoff = datetime.now(UTC) - timedelta(hours=COLLECT_STALE_HOURS)
    if last_collect_at is None:
        reasons.append("No collector sync recorded yet.")
    elif last_collect_at < stale_cutoff:
        reasons.append(f"Last collector sync is older than {COLLECT_STALE_HOURS}h.")

    if dlq.get("status") == "unavailable":
        reasons.append("Kafka broker unavailable — DLQ health could not be verified.")

    stale_workers = _workers_with_status(workers, "stale")
    if stale_workers:
        reasons.append(f"Stale worker heartbeat: {', '.join(stale_workers)}.")
    elif (workers or {}).get("status") == "warning":
        reasons.append("One or more Kafka worker heartbeats are stale.")

    if workers_redis_error:
        reasons.append("Redis unavailable — worker heartbeats could not be verified.")

    unembedded = int(jobs_metrics.get("unembedded_active_count") or 0)
    if unembedded > 0:
        noun = "job is" if unembedded == 1 else "jobs are"
        reasons.append(f"{unembedded} active {noun} missing embeddings.")

    return reasons


def _evaluate_overall_status(
    *,
    last_collect_at: datetime | None,
    latest_run_totals: dict[str, int],
    jobs_metrics: dict[str, int],
    dlq: dict[str, Any],
    workers: dict[str, Any] | None = None,
    workers_redis_error: bool = False,
) -> tuple[OverallStatus, list[str]]:
    degraded_reasons = _collect_degraded_reasons(
        last_collect_at=last_collect_at,
        latest_run_totals=latest_run_totals,
        dlq=dlq,
        workers=workers,
    )
    warning_reasons = _collect_warning_reasons(
        last_collect_at=last_collect_at,
        jobs_metrics=jobs_metrics,
        dlq=dlq,
        workers=workers,
        workers_redis_error=workers_redis_error,
    )
    if degraded_reasons:
        return "degraded", [*degraded_reasons, *warning_reasons]
    if warning_reasons:
        return "warning", warning_reasons
    return "healthy", []


def _derive_overall_status(
    *,
    last_collect_at: datetime | None,
    latest_run_totals: dict[str, int],
    jobs_metrics: dict[str, int],
    dlq: dict[str, Any],
    workers: dict[str, Any] | None = None,
    workers_redis_error: bool = False,
) -> OverallStatus:
    status, _ = _evaluate_overall_status(
        last_collect_at=last_collect_at,
        latest_run_totals=latest_run_totals,
        jobs_metrics=jobs_metrics,
        dlq=dlq,
        workers=workers,
        workers_redis_error=workers_redis_error,
    )
    return status


def build_system_status_payload(user) -> dict[str, Any]:
    last_collect_at, latest_run_totals, sources = _get_collector_telemetry()
    jobs_metrics = _get_job_backlog_metrics(user)
    rollup_metrics = _get_rollup_metrics()
    dlq_health = get_dlq_health()
    workers_health, workers_redis_error = get_worker_health()
    overall_status, status_reasons = _evaluate_overall_status(
        last_collect_at=last_collect_at,
        latest_run_totals=latest_run_totals,
        jobs_metrics=jobs_metrics,
        dlq=dlq_health,
        workers=workers_health,
        workers_redis_error=workers_redis_error,
    )

    is_running, running_started_at = get_collect_running_state(last_collect_at)

    return {
        "overall_status": overall_status,
        "status_reasons": status_reasons,
        "last_collect_at": last_collect_at.isoformat() if last_collect_at else None,
        "latest_run_totals": latest_run_totals,
        "sources": sources,
        "jobs": jobs_metrics,
        "rollup": rollup_metrics,
        "dlq": dlq_health,
        "workers": workers_health,
        "collect_trigger": {
            "can_trigger": bool(getattr(user, "is_staff", False)),
            "is_running": is_running,
            "running_started_at": running_started_at,
            "cooldown_remaining_seconds": get_collect_cooldown_remaining(),
        },
    }

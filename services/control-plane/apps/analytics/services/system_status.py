from datetime import UTC, datetime, timedelta
import json
import logging
from typing import Any, Literal

from confluent_kafka import Consumer, TopicPartition
from django.conf import settings
from django.db.models import Exists, Max, OuterRef, Sum
import redis

from apps.analytics.models.analytics import CollectorRunLog, StackTrendDaily
from apps.analytics.services.collector_trigger import get_collect_cooldown_remaining
from apps.jobs.models.jobs import JobPosting
from apps.matching.models.matching import MatchScore
from apps.resumes.models.resumes import ResumeProfile
from vektryn_contracts import KafkaTopic

logger = logging.getLogger(__name__)

DLQ_CACHE_KEY = "vektryn:system:dlq_health:v1"
DLQ_CACHE_TTL_SECONDS = 30
COLLECT_STALE_HOURS = 12
MATCH_LAG_WINDOW_HOURS = 2
DLQ_LOOKBACK_HOURS = 24
KAFKA_PROBE_TIMEOUT_SECONDS = 1.5
KAFKA_PROBE_GROUP_ID = "vektryn-system-status-probe"

OverallStatus = Literal["healthy", "warning", "degraded"]


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


def _build_kafka_probe_config() -> dict[str, Any] | None:
    bootstrap = (getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "") or "").strip()
    if not bootstrap:
        return None
    config: dict[str, Any] = {
        "bootstrap.servers": bootstrap,
        "group.id": KAFKA_PROBE_GROUP_ID,
        "enable.auto.commit": False,
        "socket.timeout.ms": int(KAFKA_PROBE_TIMEOUT_SECONDS * 1000),
        "metadata.request.timeout.ms": int(KAFKA_PROBE_TIMEOUT_SECONDS * 1000),
    }
    protocol = (getattr(settings, "KAFKA_SECURITY_PROTOCOL", "") or "").strip()
    if protocol:
        config["security.protocol"] = protocol
    mechanism = (getattr(settings, "KAFKA_SASL_MECHANISM", "") or "").strip()
    if mechanism:
        config["sasl.mechanism"] = mechanism
    username = (getattr(settings, "KAFKA_SASL_USERNAME", "") or "").strip()
    if username:
        config["sasl.username"] = username
    password = (getattr(settings, "KAFKA_SASL_PASSWORD", "") or "").strip()
    if password:
        config["sasl.password"] = password
    return config


def _unavailable_dlq_health() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "recent_24h_count": None,
        "total_count": None,
    }


def _close_consumer_safely(consumer: Consumer | None) -> None:
    if consumer is None:
        return
    try:
        consumer.close()
    except Exception as close_exc:
        logger.debug("Ignoring Kafka probe consumer close error: %s", close_exc)


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


def get_dlq_health() -> dict[str, Any]:
    client = _get_redis_client()
    if client is not None:
        try:
            cached = client.get(DLQ_CACHE_KEY)
            if isinstance(cached, str) and cached:
                parsed = json.loads(cached)
                if isinstance(parsed, dict) and "status" in parsed:
                    return parsed
        except Exception as exc:
            logger.debug("Failed reading cached DLQ health: %s", exc)

    health = _probe_kafka_dlq_health()
    if client is not None:
        try:
            client.set(DLQ_CACHE_KEY, json.dumps(health), ex=DLQ_CACHE_TTL_SECONDS)
        except Exception as exc:
            logger.debug("Failed caching DLQ health: %s", exc)
    return health


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


def _derive_overall_status(
    *,
    last_collect_at: datetime | None,
    latest_run_totals: dict[str, int],
    jobs_metrics: dict[str, int],
    dlq: dict[str, Any],
) -> OverallStatus:
    recent_dlq = dlq.get("recent_24h_count") or 0
    if recent_dlq > 0:
        return "degraded"
    if (
        last_collect_at is not None
        and latest_run_totals["error_count"] > 0
        and latest_run_totals["fetched_count"] == 0
        and latest_run_totals["ingested_count"] == 0
    ):
        return "degraded"

    stale_cutoff = datetime.now(UTC) - timedelta(hours=COLLECT_STALE_HOURS)
    if (
        last_collect_at is None
        or last_collect_at < stale_cutoff
        or dlq.get("status") == "unavailable"
        or jobs_metrics["unembedded_active_count"] > 0
        or jobs_metrics["recent_unmatched_count"] > 0
    ):
        return "warning"

    return "healthy"


def build_system_status_payload(user) -> dict[str, Any]:
    last_collect_at, latest_run_totals, sources = _get_collector_telemetry()
    jobs_metrics = _get_job_backlog_metrics(user)
    rollup_metrics = _get_rollup_metrics()
    dlq_health = get_dlq_health()
    overall_status = _derive_overall_status(
        last_collect_at=last_collect_at,
        latest_run_totals=latest_run_totals,
        jobs_metrics=jobs_metrics,
        dlq=dlq_health,
    )

    return {
        "overall_status": overall_status,
        "last_collect_at": last_collect_at.isoformat() if last_collect_at else None,
        "latest_run_totals": latest_run_totals,
        "sources": sources,
        "jobs": jobs_metrics,
        "rollup": rollup_metrics,
        "dlq": dlq_health,
        "collect_trigger": {
            "can_trigger": bool(getattr(user, "is_staff", False)),
            "cooldown_remaining_seconds": get_collect_cooldown_remaining(),
        },
    }

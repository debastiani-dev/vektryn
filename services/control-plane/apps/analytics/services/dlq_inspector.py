from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
import time
from typing import Any
from uuid import uuid4

from confluent_kafka import Consumer, KafkaError, Producer, TopicPartition
from django.conf import settings
import redis

from apps.analytics.services.kafka_probe import (
    DLQ_CACHE_KEY,
    build_kafka_probe_config as _build_kafka_probe_config,
    close_consumer_safely as _close_consumer_safely,
    close_redis_safely as _close_redis_safely,
)
from vektryn_contracts import DeadLetterEvent, KafkaTopic

logger = logging.getLogger(__name__)

DEFAULT_DLQ_INSPECT_LIMIT = 25
MAX_DLQ_INSPECT_LIMIT = 100
DEFAULT_DLQ_REPLAY_LIMIT = 10
MAX_DLQ_REPLAY_LIMIT = 50
MAX_PAYLOAD_PREVIEW_CHARS = 500
DLQ_PEEK_DEADLINE_SECONDS = 3.0
DLQ_POLL_SLICE_SECONDS = 0.25
DLQ_PRODUCE_TIMEOUT_MS = 3000
DLQ_FLUSH_TIMEOUT_SECONDS = 5.0

DLQ_REPLAY_COOLDOWN_KEY = "vektryn:system:dlq_replay_lock"
DLQ_REPLAY_COOLDOWN_SECONDS = 30
DLQ_REPLAYED_KEY_PREFIX = "vektryn:dlq:replayed:"
DLQ_DISMISSED_KEY_PREFIX = "vektryn:dlq:dismissed:"
DLQ_RESOLUTION_TTL_SECONDS = 7 * 24 * 3600

REPLAYABLE_TOPICS: frozenset[str] = frozenset(
    {
        KafkaTopic.JOBS_RAW.value,
        KafkaTopic.JOBS_ENRICHED.value,
        KafkaTopic.JOBS_RESCORE.value,
    }
)


class DlqBrokerUnavailableError(RuntimeError):
    """Raised when Kafka is unconfigured or unreachable for DLQ inspection/replay."""


class DlqReplayCooldownError(RuntimeError):
    """Raised when another DLQ replay ran recently or is in flight (HTTP 429)."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, int(retry_after))
        super().__init__(
            f"DLQ replay is on cooldown. Try again in {self.retry_after}s."
        )


@dataclass
class _DlqRecord:
    event_id: str
    original_topic: str
    partition: int
    offset: int
    dlq_partition: int
    dlq_offset: int
    error_type: str
    error_message: str
    retry_count: int
    produced_at: datetime | None
    raw_payload: dict[str, Any] | str
    malformed: bool = False
    replayed_at: str | None = None


def _get_redis_client() -> redis.Redis | None:
    redis_url = (getattr(settings, "REDIS_URL", "") or "").strip()
    if not redis_url:
        return None
    try:
        return redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=1.5,
            socket_timeout=1.5,
        )
    except Exception as exc:
        logger.debug("Redis unavailable for DLQ inspector: %s", exc)
        return None


def _build_dlq_consumer_config() -> dict[str, Any]:
    base = _build_kafka_probe_config()
    if base is None:
        raise DlqBrokerUnavailableError("Kafka broker is not configured.")
    return {
        **base,
        "group.id": f"vektryn-dlq-inspect-{uuid4().hex[:8]}",
        "enable.auto.commit": False,
        "enable.partition.eof": True,
    }


def _build_dlq_producer_config() -> dict[str, Any]:
    bootstrap = (getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "") or "").strip()
    if not bootstrap:
        raise DlqBrokerUnavailableError("Kafka broker is not configured.")
    config: dict[str, Any] = {
        "bootstrap.servers": bootstrap,
        "client.id": "vektryn-control-plane-dlq-replay",
        "acks": "all",
        "enable.idempotence": True,
        "message.timeout.ms": DLQ_PRODUCE_TIMEOUT_MS,
    }
    if (getattr(settings, "KAFKA_SECURITY_PROTOCOL", "") or "").strip():
        config["security.protocol"] = settings.KAFKA_SECURITY_PROTOCOL.strip()
    if (getattr(settings, "KAFKA_SASL_MECHANISM", "") or "").strip():
        config["sasl.mechanism"] = settings.KAFKA_SASL_MECHANISM.strip()
    if (getattr(settings, "KAFKA_SASL_USERNAME", "") or "").strip():
        config["sasl.username"] = settings.KAFKA_SASL_USERNAME.strip()
    if (getattr(settings, "KAFKA_SASL_PASSWORD", "") or "").strip():
        config["sasl.password"] = settings.KAFKA_SASL_PASSWORD.strip()
    return config


def _parse_dlq_record(msg: Any) -> _DlqRecord:
    dlq_partition = int(msg.partition() if msg.partition() is not None else 0)
    dlq_offset = int(msg.offset() if msg.offset() is not None else 0)
    raw_bytes = msg.value() or b""
    raw_text = raw_bytes.decode("utf-8", errors="replace")

    try:
        event = DeadLetterEvent.model_validate_json(raw_text)
        return _DlqRecord(
            event_id=str(event.event_id),
            original_topic=event.original_topic,
            partition=event.partition,
            offset=event.offset,
            dlq_partition=dlq_partition,
            dlq_offset=dlq_offset,
            error_type=event.error_type,
            error_message=event.error_message,
            retry_count=event.retry_count,
            produced_at=event.produced_at,
            raw_payload=event.raw_payload,
            malformed=False,
        )
    except Exception as exc:
        return _DlqRecord(
            event_id=f"malformed-{dlq_partition}-{dlq_offset}",
            original_topic="unknown",
            partition=dlq_partition,
            offset=dlq_offset,
            dlq_partition=dlq_partition,
            dlq_offset=dlq_offset,
            error_type="MalformedDeadLetterEvent",
            error_message=f"Unable to parse DeadLetterEvent JSON: {exc}",
            retry_count=0,
            produced_at=None,
            raw_payload=raw_text,
            malformed=True,
        )


def _format_payload_preview(raw_payload: dict[str, Any] | str) -> tuple[str, bool]:
    text = (
        raw_payload
        if isinstance(raw_payload, str)
        else json.dumps(raw_payload, ensure_ascii=False, sort_keys=True)
    )
    if len(text) <= MAX_PAYLOAD_PREVIEW_CHARS:
        return text, False
    return f"{text[:MAX_PAYLOAD_PREVIEW_CHARS]}…", True


def _load_resolution_markers(
    event_ids: list[str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Loads (replayed_at_by_id, dismissed_at_by_id) in a single Redis MGET."""
    if not event_ids:
        return {}, {}
    client = _get_redis_client()
    if client is None:
        return {}, {}
    replayed_keys = [f"{DLQ_REPLAYED_KEY_PREFIX}{eid}" for eid in event_ids]
    dismissed_keys = [f"{DLQ_DISMISSED_KEY_PREFIX}{eid}" for eid in event_ids]
    try:
        values = client.mget(replayed_keys + dismissed_keys)
    except Exception as exc:
        logger.debug("Failed loading DLQ resolution markers: %s", exc)
        return {}, {}
    finally:
        _close_redis_safely(client)

    count = len(event_ids)
    replayed: dict[str, str] = {}
    dismissed: dict[str, str] = {}
    for idx, eid in enumerate(event_ids):
        rep_val = values[idx] if idx < len(values) else None
        if isinstance(rep_val, str) and rep_val:
            replayed[eid] = rep_val
        dis_idx = count + idx
        dis_val = values[dis_idx] if dis_idx < len(values) else None
        if isinstance(dis_val, str) and dis_val:
            dismissed[eid] = dis_val
    return replayed, dismissed


def _mark_replayed_events(event_ids: list[str], replayed_at_iso: str) -> None:
    if not event_ids:
        return
    client = _get_redis_client()
    if client is None:
        return
    try:
        pipe = client.pipeline(transaction=False)
        for eid in event_ids:
            pipe.set(
                f"{DLQ_REPLAYED_KEY_PREFIX}{eid}",
                replayed_at_iso,
                ex=DLQ_RESOLUTION_TTL_SECONDS,
            )
            pipe.delete(f"{DLQ_DISMISSED_KEY_PREFIX}{eid}")
        pipe.delete(DLQ_CACHE_KEY)
        pipe.execute()
    except Exception as exc:
        logger.warning("Failed persisting DLQ replayed markers: %s", exc)
    finally:
        _close_redis_safely(client)


def dismiss_dlq_messages(event_ids: list[str]) -> dict[str, Any]:
    cleaned = list(
        dict.fromkeys(str(eid).strip() for eid in event_ids if str(eid).strip())
    )
    if not cleaned:
        return {"dismissed_count": 0, "dismissed_at": None, "event_ids": []}

    client = _get_redis_client()
    if client is None:
        raise DlqBrokerUnavailableError(
            "Redis is unavailable; cannot persist DLQ dismissals."
        )

    dismissed_at = datetime.now(UTC).isoformat()
    try:
        pipe = client.pipeline(transaction=False)
        for eid in cleaned:
            pipe.set(
                f"{DLQ_DISMISSED_KEY_PREFIX}{eid}",
                dismissed_at,
                ex=DLQ_RESOLUTION_TTL_SECONDS,
            )
        pipe.delete(DLQ_CACHE_KEY)
        pipe.execute()
    except Exception as exc:
        logger.warning("Failed persisting DLQ dismissed markers: %s", exc)
        raise DlqBrokerUnavailableError(
            "Failed persisting DLQ dismissal state to Redis."
        ) from exc
    finally:
        _close_redis_safely(client)

    return {
        "dismissed_count": len(cleaned),
        "dismissed_at": dismissed_at,
        "event_ids": cleaned,
    }


def count_unresolved_recent_dlq_messages(
    *,
    since_dt: datetime,
    max_scan_per_partition: int = MAX_DLQ_INSPECT_LIMIT,
) -> int | None:
    """Returns count of DLQ records since `since_dt` that are neither replayed nor dismissed."""
    try:
        records, _total = _collect_recent_dlq_records(
            fetch_per_partition=max(
                1, min(MAX_DLQ_INSPECT_LIMIT, max_scan_per_partition)
            )
        )
    except Exception as exc:
        logger.debug("Skipping unresolved DLQ count refinement: %s", exc)
        return None

    recent_records = [
        rec for rec in records if rec.produced_at is None or rec.produced_at >= since_dt
    ]
    if not recent_records:
        return 0

    replayed, dismissed = _load_resolution_markers(
        [rec.event_id for rec in recent_records]
    )
    unresolved = [
        rec
        for rec in recent_records
        if rec.event_id not in replayed and rec.event_id not in dismissed
    ]
    return len(unresolved)


def dismiss_dlq_messages(event_ids: list[str]) -> dict[str, Any]:
    cleaned = list(
        dict.fromkeys(str(eid).strip() for eid in event_ids if str(eid).strip())
    )
    if not cleaned:
        return {"dismissed_count": 0, "dismissed_at": None, "event_ids": []}

    client = _get_redis_client()
    if client is None:
        raise DlqBrokerUnavailableError(
            "Redis is unavailable; cannot persist DLQ dismissals."
        )

    dismissed_at = datetime.now(UTC).isoformat()
    try:
        pipe = client.pipeline(transaction=False)
        for eid in cleaned:
            pipe.set(
                f"{DLQ_DISMISSED_KEY_PREFIX}{eid}",
                dismissed_at,
                ex=DLQ_RESOLUTION_TTL_SECONDS,
            )
        pipe.delete(DLQ_CACHE_KEY)
        pipe.execute()
    except Exception as exc:
        logger.warning("Failed persisting DLQ dismissed markers: %s", exc)
        raise DlqBrokerUnavailableError(
            "Failed persisting DLQ dismissal state to Redis."
        ) from exc
    finally:
        _close_redis_safely(client)

    return {
        "dismissed_count": len(cleaned),
        "dismissed_at": dismissed_at,
        "event_ids": cleaned,
    }


def count_unresolved_recent_dlq_messages(
    *,
    since_dt: datetime,
    max_scan_per_partition: int = MAX_DLQ_INSPECT_LIMIT,
) -> int | None:
    """Returns count of DLQ records since `since_dt` that are neither replayed nor dismissed."""
    try:
        records, _total = _collect_recent_dlq_records(
            fetch_per_partition=max(1, min(MAX_DLQ_INSPECT_LIMIT, max_scan_per_partition))
        )
    except Exception as exc:
        logger.debug("Skipping unresolved DLQ count refinement: %s", exc)
        return None

    recent_records = [
        rec
        for rec in records
        if rec.produced_at is None or rec.produced_at >= since_dt
    ]
    if not recent_records:
        return 0

    replayed, dismissed = _load_resolution_markers([rec.event_id for rec in recent_records])
    unresolved = [
        rec
        for rec in recent_records
        if rec.event_id not in replayed and rec.event_id not in dismissed
    ]
    return len(unresolved)


def get_dlq_replay_cooldown_remaining() -> int:
    client = _get_redis_client()
    if client is None:
        return 0
    try:
        ttl = client.ttl(DLQ_REPLAY_COOLDOWN_KEY)
        return max(0, int(ttl)) if isinstance(ttl, int) and ttl > 0 else 0
    except Exception as exc:
        logger.debug("Failed checking DLQ replay cooldown TTL: %s", exc)
        return 0
    finally:
        _close_redis_safely(client)


def _acquire_replay_cooldown() -> bool:
    client = _get_redis_client()
    if client is None:
        return False
    try:
        acquired = client.set(
            DLQ_REPLAY_COOLDOWN_KEY,
            "1",
            nx=True,
            ex=DLQ_REPLAY_COOLDOWN_SECONDS,
        )
        if not acquired:
            ttl = int(client.ttl(DLQ_REPLAY_COOLDOWN_KEY))
            if ttl < 0:
                client.expire(DLQ_REPLAY_COOLDOWN_KEY, DLQ_REPLAY_COOLDOWN_SECONDS)
                ttl = DLQ_REPLAY_COOLDOWN_SECONDS
            raise DlqReplayCooldownError(retry_after=max(1, ttl))
        return True
    except DlqReplayCooldownError:
        raise
    except Exception as exc:
        logger.warning("Redis unavailable for DLQ replay lock (fail-open): %s", exc)
        return False
    finally:
        _close_redis_safely(client)


def _release_replay_cooldown() -> None:
    client = _get_redis_client()
    if client is None:
        return
    try:
        client.delete(DLQ_REPLAY_COOLDOWN_KEY)
    except Exception as exc:
        logger.debug("Failed releasing DLQ replay lock: %s", exc)
    finally:
        _close_redis_safely(client)


def _plan_dlq_assignments(
    consumer: Consumer,
    dlq_topic: str,
    partition_ids: list[int],
    fetch_per_partition: int,
) -> tuple[list[TopicPartition], dict[int, int], int]:
    assignments: list[TopicPartition] = []
    remaining_targets: dict[int, int] = {}
    total_count = 0

    for partition_id in sorted(partition_ids):
        low, high = consumer.get_watermark_offsets(
            TopicPartition(dlq_topic, partition_id),
            timeout=2.0,
        )
        total_count += max(0, high - low)
        if high <= low:
            continue
        start_offset = max(low, high - fetch_per_partition)
        assignments.append(TopicPartition(dlq_topic, partition_id, start_offset))
        remaining_targets[partition_id] = high - 1

    return assignments, remaining_targets, total_count


def _handle_poll_error(msg: Any, remaining_targets: dict[int, int]) -> None:
    err = msg.error()
    if err.code() == KafkaError._PARTITION_EOF:
        part_id = msg.partition()
        if part_id is not None:
            remaining_targets.pop(int(part_id), None)
        return
    logger.warning("DLQ peek consumer error: %s", err)


def _poll_assigned_dlq_records(
    consumer: Consumer,
    remaining_targets: dict[int, int],
) -> list[_DlqRecord]:
    records: list[_DlqRecord] = []
    deadline = time.monotonic() + DLQ_PEEK_DEADLINE_SECONDS

    while remaining_targets and time.monotonic() < deadline:
        remaining_budget = max(0.05, deadline - time.monotonic())
        msg = consumer.poll(min(DLQ_POLL_SLICE_SECONDS, remaining_budget))
        if msg is None:
            continue
        if msg.error() is not None:
            _handle_poll_error(msg, remaining_targets)
            continue

        record = _parse_dlq_record(msg)
        records.append(record)
        target_last = remaining_targets.get(record.dlq_partition)
        if target_last is not None and record.dlq_offset >= target_last:
            remaining_targets.pop(record.dlq_partition, None)

    return records


def _collect_recent_dlq_records(
    *,
    fetch_per_partition: int,
) -> tuple[list[_DlqRecord], int]:
    config = _build_dlq_consumer_config()
    dlq_topic = KafkaTopic.JOBS_DLQ.value
    consumer: Consumer | None = None
    try:
        consumer = Consumer(config)
        cluster_meta = consumer.list_topics(topic=dlq_topic, timeout=2.0)
        topic_meta = cluster_meta.topics.get(dlq_topic)
        if topic_meta is None or topic_meta.error is not None:
            raise DlqBrokerUnavailableError(
                f"Kafka DLQ topic '{dlq_topic}' is unavailable."
            )

        assignments, remaining_targets, total_count = _plan_dlq_assignments(
            consumer,
            dlq_topic,
            list(topic_meta.partitions.keys()),
            fetch_per_partition,
        )
        if not assignments:
            return [], total_count

        consumer.assign(assignments)
        records = _poll_assigned_dlq_records(consumer, remaining_targets)
        return records, total_count
    except DlqBrokerUnavailableError:
        raise
    except Exception as exc:
        logger.warning("Kafka DLQ peek failed: %s", exc)
        raise DlqBrokerUnavailableError(
            "Kafka broker is unreachable for DLQ inspection."
        ) from exc
    finally:
        _close_consumer_safely(consumer)


def _sort_records_newest_first(records: list[_DlqRecord]) -> list[_DlqRecord]:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    return sorted(
        records,
        key=lambda rec: (rec.produced_at or epoch, rec.dlq_offset, rec.dlq_partition),
        reverse=True,
    )


def _is_record_replayable(record: _DlqRecord) -> tuple[bool, str]:
    if record.malformed:
        return False, "malformed_dlq_event"
    if record.original_topic not in REPLAYABLE_TOPICS:
        return False, f"topic_not_replayable:{record.original_topic}"
    if isinstance(record.raw_payload, str) and not record.raw_payload.strip():
        return False, "empty_payload"
    if isinstance(record.raw_payload, dict) and not record.raw_payload:
        return False, "empty_payload"
    return True, ""


def inspect_dlq_messages(
    *,
    limit: int = DEFAULT_DLQ_INSPECT_LIMIT,
    original_topic: str | None = None,
) -> dict[str, Any]:
    clamped_limit = max(1, min(MAX_DLQ_INSPECT_LIMIT, int(limit)))
    clean_topic = (original_topic or "").strip() or None
    fetch_per_partition = (
        MAX_DLQ_INSPECT_LIMIT if clean_topic is not None else clamped_limit
    )

    records, total_count = _collect_recent_dlq_records(
        fetch_per_partition=fetch_per_partition
    )
    sorted_records = _sort_records_newest_first(records)
    if clean_topic is not None:
        sorted_records = [
            rec for rec in sorted_records if rec.original_topic == clean_topic
        ]
    sliced = sorted_records[:clamped_limit]

    replayed_markers, dismissed_markers = _load_resolution_markers(
        [rec.event_id for rec in sliced]
    )

    items: list[dict[str, Any]] = []
    for rec in sliced:
        preview, truncated = _format_payload_preview(rec.raw_payload)
        replayable, _reason = _is_record_replayable(rec)
        items.append(
            {
                "event_id": rec.event_id,
                "original_topic": rec.original_topic,
                "partition": rec.partition,
                "offset": rec.offset,
                "dlq_partition": rec.dlq_partition,
                "dlq_offset": rec.dlq_offset,
                "error_type": rec.error_type,
                "error_message": rec.error_message,
                "retry_count": rec.retry_count,
                "produced_at": rec.produced_at.isoformat() if rec.produced_at else None,
                "payload_preview": preview,
                "payload_truncated": truncated,
                "replayable": replayable,
                "replayed_at": replayed_markers.get(rec.event_id),
                "dismissed_at": dismissed_markers.get(rec.event_id),
            }
        )

    return {
        "total_count": total_count,
        "returned_count": len(items),
        "limit": clamped_limit,
        "replay_cooldown_remaining_seconds": get_dlq_replay_cooldown_remaining(),
        "items": items,
    }


def _serialize_replay_payload(record: _DlqRecord) -> tuple[bytes, bytes]:
    """Returns (partition_key_bytes, payload_bytes) matching dlq_replay.py parity."""
    payload_dict: dict[str, Any] = {}
    if isinstance(record.raw_payload, dict):
        payload_dict = record.raw_payload
        payload_bytes = json.dumps(record.raw_payload).encode("utf-8")
    else:
        payload_bytes = record.raw_payload.encode("utf-8")
        with suppress(json.JSONDecodeError, TypeError):
            parsed = json.loads(record.raw_payload)
            if isinstance(parsed, dict):
                payload_dict = parsed

    if record.original_topic == KafkaTopic.JOBS_RESCORE.value:
        key_str = str(payload_dict.get("resume_profile_uuid") or record.event_id)
    else:
        ats_source = payload_dict.get("ats_source") or "dlq"
        external_id = payload_dict.get("external_id") or record.event_id
        key_str = f"{ats_source}:{external_id}"

    return key_str.encode("utf-8"), payload_bytes


def _select_replay_candidates(
    *,
    records: list[_DlqRecord],
    event_ids: list[str] | None,
    limit: int,
    original_topic: str | None,
) -> tuple[list[_DlqRecord], list[str]]:
    sorted_records = _sort_records_newest_first(records)
    if event_ids:
        by_id: dict[str, _DlqRecord] = {}
        for rec in sorted_records:
            by_id.setdefault(rec.event_id, rec)
        selected: list[_DlqRecord] = []
        missing_ids: list[str] = []
        for eid in event_ids:
            if eid in by_id:
                selected.append(by_id[eid])
            else:
                missing_ids.append(eid)
        return selected, missing_ids

    clean_topic = (original_topic or "").strip() or None
    if clean_topic is not None:
        sorted_records = [
            rec for rec in sorted_records if rec.original_topic == clean_topic
        ]
    return sorted_records[:limit], []


def _classify_replay_candidates(
    *,
    candidates: list[_DlqRecord],
    replayed_markers: dict[str, str],
    dismissed_markers: dict[str, str],
    explicit_selection: bool,
) -> tuple[list[_DlqRecord], list[dict[str, Any]]]:
    eligible: list[_DlqRecord] = []
    skipped_items: list[dict[str, Any]] = []

    for rec in candidates:
        replayable, reason = _is_record_replayable(rec)
        if not replayable:
            skipped_items.append(
                {
                    "event_id": rec.event_id,
                    "original_topic": rec.original_topic,
                    "dlq_partition": rec.dlq_partition,
                    "dlq_offset": rec.dlq_offset,
                    "status": "skipped",
                    "reason": reason,
                }
            )
            continue

        if not explicit_selection and rec.event_id in replayed_markers:
            skipped_items.append(
                {
                    "event_id": rec.event_id,
                    "original_topic": rec.original_topic,
                    "dlq_partition": rec.dlq_partition,
                    "dlq_offset": rec.dlq_offset,
                    "status": "skipped",
                    "reason": "already_replayed",
                }
            )
            continue

        if not explicit_selection and rec.event_id in dismissed_markers:
            skipped_items.append(
                {
                    "event_id": rec.event_id,
                    "original_topic": rec.original_topic,
                    "dlq_partition": rec.dlq_partition,
                    "dlq_offset": rec.dlq_offset,
                    "status": "skipped",
                    "reason": "already_dismissed",
                }
            )
            continue

        eligible.append(rec)

    return eligible, skipped_items


def _format_delivery_failure_reason(
    outcome: tuple[bool, str] | None,
    remaining: int,
) -> str:
    if outcome is not None and outcome[1]:
        return outcome[1]
    if remaining:
        return f"flush_timeout ({remaining} queued)"
    return "delivery_unconfirmed"


def _build_publish_item_result(
    rec: _DlqRecord,
    outcome: tuple[bool, str] | None,
    remaining: int,
) -> tuple[dict[str, Any], bool]:
    delivered = outcome is not None and outcome[0]
    status = "replayed" if delivered else "failed"
    reason = "" if delivered else _format_delivery_failure_reason(outcome, remaining)
    item = {
        "event_id": rec.event_id,
        "original_topic": rec.original_topic,
        "dlq_partition": rec.dlq_partition,
        "dlq_offset": rec.dlq_offset,
        "status": status,
        "reason": reason,
    }
    return item, delivered


def _publish_eligible_records(
    eligible: list[_DlqRecord],
) -> tuple[list[dict[str, Any]], list[str]]:
    producer = Producer(_build_dlq_producer_config())
    outcomes: dict[int, tuple[bool, str]] = {}

    def _make_callback(idx: int):
        def _on_delivery(err: KafkaError | None, _msg: Any) -> None:
            outcomes[idx] = (err is None, "" if err is None else str(err))

        return _on_delivery

    for idx, rec in enumerate(eligible):
        key_bytes, payload_bytes = _serialize_replay_payload(rec)
        producer.produce(
            topic=rec.original_topic,
            key=key_bytes,
            value=payload_bytes,
            on_delivery=_make_callback(idx),
        )
        producer.poll(0)

    remaining = producer.flush(DLQ_FLUSH_TIMEOUT_SECONDS)

    item_results: list[dict[str, Any]] = []
    confirmed_ids: list[str] = []
    for idx, rec in enumerate(eligible):
        item, delivered = _build_publish_item_result(rec, outcomes.get(idx), remaining)
        item_results.append(item)
        if delivered:
            confirmed_ids.append(rec.event_id)

    return item_results, confirmed_ids


def replay_dlq_messages(
    *,
    event_ids: list[str] | None = None,
    limit: int = DEFAULT_DLQ_REPLAY_LIMIT,
    original_topic: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    clamped_limit = max(1, min(MAX_DLQ_REPLAY_LIMIT, int(limit)))
    normalized_ids = [str(eid).strip() for eid in (event_ids or []) if str(eid).strip()]
    explicit_selection = bool(normalized_ids)

    records, _total_count = _collect_recent_dlq_records(
        fetch_per_partition=MAX_DLQ_INSPECT_LIMIT
    )
    candidates, missing_ids = _select_replay_candidates(
        records=records,
        event_ids=normalized_ids if explicit_selection else None,
        limit=clamped_limit,
        original_topic=original_topic,
    )
    replayed_markers, dismissed_markers = _load_resolution_markers(
        [rec.event_id for rec in candidates]
    )
    eligible, skipped_items = _classify_replay_candidates(
        candidates=candidates,
        replayed_markers=replayed_markers,
        dismissed_markers=dismissed_markers,
        explicit_selection=explicit_selection,
    )

    for missing_id in missing_ids:
        skipped_items.append(
            {
                "event_id": missing_id,
                "original_topic": "",
                "dlq_partition": -1,
                "dlq_offset": -1,
                "status": "skipped",
                "reason": "not_found_in_recent_dlq",
            }
        )

    if dry_run:
        preview_items = [
            {
                "event_id": rec.event_id,
                "original_topic": rec.original_topic,
                "dlq_partition": rec.dlq_partition,
                "dlq_offset": rec.dlq_offset,
                "status": "would_replay",
                "reason": "",
            }
            for rec in eligible
        ]
        all_items = preview_items + skipped_items
        return {
            "dry_run": True,
            "matched_count": len(eligible),
            "replayed_count": 0,
            "skipped_count": len(skipped_items),
            "failed_count": 0,
            "cooldown_seconds": DLQ_REPLAY_COOLDOWN_SECONDS,
            "items": all_items,
        }

    if not eligible:
        return {
            "dry_run": False,
            "matched_count": 0,
            "replayed_count": 0,
            "skipped_count": len(skipped_items),
            "failed_count": 0,
            "cooldown_seconds": DLQ_REPLAY_COOLDOWN_SECONDS,
            "items": skipped_items,
        }

    lock_acquired = _acquire_replay_cooldown()
    try:
        published_items, confirmed_ids = _publish_eligible_records(eligible)
    except DlqBrokerUnavailableError:
        if lock_acquired:
            _release_replay_cooldown()
        raise
    except Exception as exc:
        if lock_acquired:
            _release_replay_cooldown()
        logger.warning("Kafka DLQ replay publish failed: %s", exc)
        raise DlqBrokerUnavailableError(
            "Failed publishing replayed messages to Kafka."
        ) from exc

    if confirmed_ids:
        _mark_replayed_events(confirmed_ids, datetime.now(UTC).isoformat())
    elif lock_acquired:
        _release_replay_cooldown()

    failed_count = sum(1 for item in published_items if item["status"] == "failed")
    return {
        "dry_run": False,
        "matched_count": len(eligible),
        "replayed_count": len(confirmed_ids),
        "skipped_count": len(skipped_items),
        "failed_count": failed_count,
        "cooldown_seconds": DLQ_REPLAY_COOLDOWN_SECONDS,
        "items": published_items + skipped_items,
    }

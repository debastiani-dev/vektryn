import logging
from typing import Any
from uuid import UUID, uuid4

from confluent_kafka import KafkaError, Producer
from django.conf import settings
import redis

from vektryn_contracts import JobRescoreEvent, KafkaTopic, rescore_partition_key

logger = logging.getLogger(__name__)

RESCORE_COOLDOWN_SECONDS = 45
KAFKA_MESSAGE_TIMEOUT_MS = 3000
KAFKA_FLUSH_TIMEOUT_SECONDS = 3.5

_producer: Producer | None = None
_producer_bootstrap: str = ""


class RescoreBrokerError(Exception):
    """Raised when a jobs.rescore Kafka event cannot be delivered to the broker."""


class RescoreCooldownError(Exception):
    """Raised when a profile rescore request is throttled by the Redis cooldown."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, retry_after)
        super().__init__(
            f"Rescore already queued recently. Retry in {self.retry_after}s."
        )


def current_trace_id() -> str:
    return uuid4().hex


def _kafka_producer_config(bootstrap_servers: str) -> dict[str, Any]:
    config: dict[str, Any] = {
        "bootstrap.servers": bootstrap_servers,
        "client.id": "vektryn-control-plane-producer",
        "acks": "all",
        "enable.idempotence": True,
        "message.timeout.ms": KAFKA_MESSAGE_TIMEOUT_MS,
    }
    if getattr(settings, "KAFKA_SECURITY_PROTOCOL", ""):
        config["security.protocol"] = settings.KAFKA_SECURITY_PROTOCOL
    if getattr(settings, "KAFKA_SASL_MECHANISM", ""):
        config["sasl.mechanism"] = settings.KAFKA_SASL_MECHANISM
    if getattr(settings, "KAFKA_SASL_USERNAME", ""):
        config["sasl.username"] = settings.KAFKA_SASL_USERNAME
    if getattr(settings, "KAFKA_SASL_PASSWORD", ""):
        config["sasl.password"] = settings.KAFKA_SASL_PASSWORD
    return config


def _get_producer(bootstrap_servers: str) -> Producer:
    global _producer, _producer_bootstrap
    if _producer is None or _producer_bootstrap != bootstrap_servers:
        _producer = Producer(_kafka_producer_config(bootstrap_servers))
        _producer_bootstrap = bootstrap_servers
    return _producer


def publish_rescore_event(
    event: JobRescoreEvent,
    *,
    require_broker: bool = False,
) -> bool:
    bootstrap_servers = (getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "") or "").strip()
    if not bootstrap_servers:
        if require_broker:
            raise RescoreBrokerError("Kafka broker is not configured.")
        logger.warning(
            "Skipping automatic jobs.rescore publish for profile=%s (KAFKA_BOOTSTRAP_SERVERS unset)",
            event.resume_profile_uuid,
        )
        return False

    delivery_errors: list[KafkaError] = []

    def _on_delivery(err: KafkaError | None, _msg: Any) -> None:
        if err is not None:
            delivery_errors.append(err)

    try:
        producer = _get_producer(bootstrap_servers)
        headers = [
            ("traceparent", f"00-{event.trace_id}-0000000000000001-01".encode("utf-8")),
            ("schema_version", event.schema_version.encode("utf-8")),
        ]
        producer.produce(
            topic=KafkaTopic.JOBS_RESCORE.value,
            key=rescore_partition_key(event.resume_profile_uuid).encode("utf-8"),
            value=event.model_dump_json().encode("utf-8"),
            headers=headers,
            on_delivery=_on_delivery,
        )
        remaining = producer.flush(KAFKA_FLUSH_TIMEOUT_SECONDS)
    except Exception as exc:
        raise RescoreBrokerError(f"Kafka produce error: {exc}") from exc

    if remaining != 0 or delivery_errors:
        detail = (
            str(delivery_errors[0])
            if delivery_errors
            else f"{remaining} message(s) still queued after flush timeout"
        )
        raise RescoreBrokerError(f"Failed to deliver jobs.rescore event: {detail}")

    return True


def _cooldown_key(resume_profile_uuid: UUID | str) -> str:
    return f"vektryn:rescore:cooldown:{resume_profile_uuid}"


def _get_redis_client() -> redis.Redis | None:
    redis_url = (getattr(settings, "REDIS_URL", "") or "").strip()
    if not redis_url:
        return None
    return redis.Redis.from_url(
        redis_url,
        socket_connect_timeout=1.5,
        socket_timeout=1.5,
        decode_responses=True,
    )


def acquire_rescore_cooldown(
    resume_profile_uuid: UUID | str,
    *,
    ttl_seconds: int = RESCORE_COOLDOWN_SECONDS,
) -> bool:
    client = _get_redis_client()
    if client is None:
        return False

    key = _cooldown_key(resume_profile_uuid)
    try:
        acquired = bool(client.set(key, "1", nx=True, ex=ttl_seconds))
        if not acquired:
            ttl = client.ttl(key)
            retry_after = ttl if isinstance(ttl, int) and ttl > 0 else ttl_seconds
            raise RescoreCooldownError(retry_after=retry_after)
        return True
    except RescoreCooldownError:
        raise
    except Exception as exc:
        logger.warning(
            "Redis cooldown check failed for profile=%s; failing open: %s",
            resume_profile_uuid,
            exc,
        )
        return False


def release_rescore_cooldown(resume_profile_uuid: UUID | str) -> None:
    client = _get_redis_client()
    if client is None:
        return
    try:
        client.delete(_cooldown_key(resume_profile_uuid))
    except Exception as exc:
        logger.warning(
            "Failed to release Redis cooldown for profile=%s: %s",
            resume_profile_uuid,
            exc,
        )

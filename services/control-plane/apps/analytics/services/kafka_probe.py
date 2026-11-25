from contextlib import suppress
import logging
from typing import Any

from confluent_kafka import Consumer
from django.conf import settings
import redis

logger = logging.getLogger(__name__)

DLQ_CACHE_KEY = "vektryn:system:dlq_health:v1"
KAFKA_PROBE_TIMEOUT_SECONDS = 1.5
KAFKA_PROBE_GROUP_ID = "vektryn-system-status-probe"


def close_redis_safely(client: redis.Redis | None) -> None:
    if client is None:
        return
    with suppress(Exception):
        client.close()


def close_consumer_safely(consumer: Consumer | None) -> None:
    if consumer is None:
        return
    try:
        consumer.close()
    except Exception as close_exc:
        logger.debug("Ignoring Kafka probe consumer close error: %s", close_exc)


def build_kafka_probe_config() -> dict[str, Any] | None:
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

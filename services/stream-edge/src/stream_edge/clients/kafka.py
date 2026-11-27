import asyncio
import json
import logging
import time
from typing import Any

from confluent_kafka import Consumer, KafkaException, Message, Producer
from confluent_kafka.admin import AdminClient, NewTopic

from stream_edge.config import settings
from vektryn_contracts import (
    DeadLetterEvent,
    EventEnvelope,
    KafkaTopic,
    dlq_partition_key,
)

logger = logging.getLogger(__name__)


def _kafka_base_config(bootstrap_servers: str) -> dict[str, Any]:
    config: dict[str, Any] = {"bootstrap.servers": bootstrap_servers}
    if settings.kafka_security_protocol.strip():
        config["security.protocol"] = settings.kafka_security_protocol.strip()
    if settings.kafka_sasl_mechanism.strip():
        config["sasl.mechanism"] = settings.kafka_sasl_mechanism.strip()
    if settings.kafka_sasl_username.strip():
        config["sasl.username"] = settings.kafka_sasl_username.strip()
    if settings.kafka_sasl_password.strip():
        config["sasl.password"] = settings.kafka_sasl_password.strip()
    return config


def _list_existing_topics(
    admin: AdminClient,
    *,
    timeout: float,
    max_attempts: int,
    retry_delay: float,
) -> set[str]:
    attempts = max(1, int(max_attempts))
    for attempt in range(1, attempts + 1):
        try:
            return set(admin.list_topics(timeout=timeout).topics.keys())
        except KafkaException as exc:
            if attempt >= attempts:
                raise
            delay = retry_delay * attempt
            logger.warning(
                "Kafka metadata lookup failed (attempt %d/%d, retrying in %.1fs): %s",
                attempt,
                attempts,
                delay,
                exc,
            )
            time.sleep(delay)
    return set()


def ensure_topics_exist(
    bootstrap_servers: str = settings.kafka_bootstrap_servers,
    *,
    timeout: float = 10.0,
    max_attempts: int = 5,
    retry_delay: float = 2.0,
) -> None:
    admin = AdminClient(_kafka_base_config(bootstrap_servers))
    existing = _list_existing_topics(
        admin,
        timeout=timeout,
        max_attempts=max_attempts,
        retry_delay=retry_delay,
    )
    missing = [
        NewTopic(topic.value, num_partitions=3, replication_factor=1)
        for topic in KafkaTopic
        if topic.value not in existing
    ]
    if not missing:
        return
    futures = admin.create_topics(missing)
    for topic_name, future in futures.items():
        try:
            future.result()
            logger.info("Created Kafka topic: %s", topic_name)
        except Exception as exc:
            logger.debug("Topic creation skipped for %s: %s", topic_name, exc)


class KafkaEventProducer:
    def __init__(
        self,
        bootstrap_servers: str = settings.kafka_bootstrap_servers,
    ) -> None:
        self._producer = Producer(
            {
                **_kafka_base_config(bootstrap_servers),
                "client.id": "vektryn-stream-edge-producer",
                "acks": "all",
                "enable.idempotence": True,
            }
        )

    def _publish_sync(
        self,
        topic: KafkaTopic | str,
        key: str,
        event: EventEnvelope,
    ) -> None:
        topic_name = topic.value if isinstance(topic, KafkaTopic) else topic
        headers = [
            ("traceparent", f"00-{event.trace_id}-0000000000000001-01".encode("utf-8")),
            ("schema_version", event.schema_version.encode("utf-8")),
        ]
        self._producer.produce(
            topic=topic_name,
            key=key.encode("utf-8"),
            value=event.model_dump_json().encode("utf-8"),
            headers=headers,
        )
        self._producer.poll(0)

    async def publish(
        self,
        topic: KafkaTopic | str,
        key: str,
        event: EventEnvelope,
    ) -> None:
        await asyncio.to_thread(self._publish_sync, topic, key, event)

    def _publish_raw_sync(
        self,
        topic: KafkaTopic | str,
        key: str,
        payload: dict[str, Any] | str,
    ) -> None:
        topic_name = topic.value if isinstance(topic, KafkaTopic) else topic
        raw_json = payload if isinstance(payload, str) else json.dumps(payload)
        self._producer.produce(
            topic=topic_name,
            key=key.encode("utf-8"),
            value=raw_json.encode("utf-8"),
        )
        self._producer.poll(0)

    async def publish_raw(
        self,
        *,
        topic: KafkaTopic | str,
        key: str,
        payload: dict[str, Any] | str,
    ) -> None:
        await asyncio.to_thread(self._publish_raw_sync, topic, key, payload)

    async def publish_dlq(
        self,
        *,
        msg: Message,
        error: Exception,
        retry_count: int = 0,
    ) -> None:
        raw_bytes = msg.value() or b""
        raw_text = raw_bytes.decode("utf-8", errors="replace")
        try:
            raw_payload: dict[str, Any] | str = json.loads(raw_text)
        except json.JSONDecodeError:
            raw_payload = raw_text

        original_topic = msg.topic() or "unknown"
        dlq_event = DeadLetterEvent(
            original_topic=original_topic,
            partition=msg.partition() if msg.partition() is not None else 0,
            offset=msg.offset() if msg.offset() is not None else 0,
            error_type=type(error).__name__,
            error_message=str(error),
            retry_count=retry_count,
            raw_payload=raw_payload,
        )
        await self.publish(
            topic=KafkaTopic.JOBS_DLQ,
            key=dlq_partition_key(original_topic),
            event=dlq_event,
        )

    def flush(self, timeout: float = 5.0) -> None:
        self._producer.flush(timeout)

    def close(self, timeout: float = 5.0) -> None:
        self.flush(timeout)


def create_kafka_consumer(
    *,
    group_id: str,
    topics: list[KafkaTopic | str],
    bootstrap_servers: str = settings.kafka_bootstrap_servers,
    auto_offset_reset: str = "earliest",
    max_poll_interval_ms: int | None = None,
) -> Consumer:
    consumer_config: dict[str, Any] = {
        **_kafka_base_config(bootstrap_servers),
        "group.id": group_id,
        "auto.offset.reset": auto_offset_reset,
        "enable.auto.commit": False,
    }
    if max_poll_interval_ms is not None:
        consumer_config["max.poll.interval.ms"] = max_poll_interval_ms
    consumer = Consumer(consumer_config)
    topic_names = [t.value if isinstance(t, KafkaTopic) else t for t in topics]
    consumer.subscribe(topic_names)
    return consumer

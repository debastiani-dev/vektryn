import argparse
import asyncio
import json
import logging
import uuid

from confluent_kafka import KafkaError

from stream_edge.clients.kafka import KafkaEventProducer, create_kafka_consumer
from vektryn_contracts import DeadLetterEvent, KafkaTopic

logger = logging.getLogger(__name__)


def _collect_dlq_events(max_messages: int) -> list[DeadLetterEvent]:
    consumer = create_kafka_consumer(
        group_id=f"vektryn-dlq-replay-{uuid.uuid4().hex[:8]}",
        topics=[KafkaTopic.JOBS_DLQ],
        auto_offset_reset="earliest",
    )
    events: list[DeadLetterEvent] = []
    try:
        while len(events) < max_messages:
            msg = consumer.poll(1.5)
            if msg is None:
                break
            err = msg.error()
            if err is not None:
                if err.code() != KafkaError._PARTITION_EOF:
                    logger.warning("DLQ consumer error: %s", err)
                continue
            raw_text = (msg.value() or b"").decode("utf-8")
            events.append(DeadLetterEvent.model_validate_json(raw_text))
    finally:
        consumer.close()
    return events


async def replay_dlq(*, max_messages: int, execute: bool) -> int:
    events = await asyncio.to_thread(_collect_dlq_events, max_messages)
    if not events:
        logger.info("No messages found in %s", KafkaTopic.JOBS_DLQ.value)
        return 0

    for item in events:
        logger.info(
            "DLQ event_id=%s original_topic=%s error_type=%s retry_count=%d",
            item.event_id,
            item.original_topic,
            item.error_type,
            item.retry_count,
        )

    if not execute:
        logger.info("Dry-run complete (%d messages inspected). Pass --execute to replay.", len(events))
        return len(events)

    producer = KafkaEventProducer()
    try:
        for item in events:
            payload_dict = (
                json.loads(item.raw_payload)
                if isinstance(item.raw_payload, str)
                else item.raw_payload
            )
            partition_key = f"{payload_dict.get('ats_source', 'dlq')}:{payload_dict.get('external_id', item.event_id)}"
            await producer.publish_raw(
                topic=item.original_topic,
                key=partition_key,
                payload=payload_dict,
            )
    finally:
        close_fn = getattr(producer, "close", None)
        if callable(close_fn):
            res = close_fn()
            if asyncio.iscoroutine(res):
                await res

    logger.info("Replayed %d DLQ messages to their original topics", len(events))
    return len(events)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect or replay Vektryn DLQ events")
    parser.add_argument("--limit", type=int, default=50, help="Max DLQ messages to read")
    parser.add_argument("--execute", action="store_true", help="Republish messages (default is dry-run)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    asyncio.run(replay_dlq(max_messages=args.limit, execute=args.execute))


if __name__ == "__main__":
    main()
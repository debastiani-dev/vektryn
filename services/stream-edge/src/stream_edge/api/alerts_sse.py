import asyncio
from collections.abc import AsyncGenerator
import logging
import uuid

from confluent_kafka import KafkaError, Message
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from stream_edge.clients.kafka import create_kafka_consumer
from vektryn_contracts import JobMatchAlertEvent, KafkaTopic

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stream", tags=["streaming"])

_POLL_INTERVAL_SECONDS = 1.0
_KEEPALIVE_INTERVAL_SECONDS = 15.0


def _parse_alert_event(raw_bytes: bytes | None) -> JobMatchAlertEvent | None:
    try:
        raw_value = (raw_bytes or b"").decode("utf-8")
        return JobMatchAlertEvent.model_validate_json(raw_value)
    except Exception as exc:
        logger.warning("Skipping malformed alert message: %s", exc)
        return None


def _format_alert_sse(msg: Message, user_id: str | None) -> str | None:
    err = msg.error()
    if err is not None:
        if err.code() != KafkaError._PARTITION_EOF:
            logger.warning("Kafka SSE consumer error: %s", err)
        return None

    alert = _parse_alert_event(msg.value())
    if alert is None:
        return None
    if user_id is not None and str(alert.user_id) != user_id:
        return None

    return (
        f"id: {alert.event_id}\n"
        f"event: match_alert\n"
        f"data: {alert.model_dump_json()}\n\n"
    )


async def _alert_event_generator(
    request: Request,
    user_id: str | None,
) -> AsyncGenerator[str, None]:
    # Ephemeral consumer group per SSE client so every open browser tab receives live alerts
    group_id = f"vektryn-sse-{uuid.uuid4().hex[:12]}"
    consumer = await asyncio.to_thread(
        create_kafka_consumer,
        group_id=group_id,
        topics=[KafkaTopic.JOBS_ALERTS],
        auto_offset_reset="latest",
    )
    idle_seconds = 0.0

    try:
        yield ": connected\n\n"
        while not await request.is_disconnected():
            msg = await asyncio.to_thread(consumer.poll, _POLL_INTERVAL_SECONDS)
            if msg is None:
                idle_seconds += _POLL_INTERVAL_SECONDS
                if idle_seconds >= _KEEPALIVE_INTERVAL_SECONDS:
                    idle_seconds = 0.0
                    yield ": keepalive\n\n"
                continue

            idle_seconds = 0.0
            sse_frame = _format_alert_sse(msg, user_id)
            if sse_frame is not None:
                yield sse_frame
    finally:
        await asyncio.to_thread(consumer.close)


@router.get("/alerts")
async def stream_match_alerts(
    request: Request,
    user_id: str | None = Query(
        default=None,
        description="Optional user ID filter for match alerts",
    ),
) -> StreamingResponse:
    return StreamingResponse(
        _alert_event_generator(request=request, user_id=user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
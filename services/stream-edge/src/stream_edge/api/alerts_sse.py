import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from stream_edge.clients.kafka import create_kafka_consumer
from vektryn_contracts import JobMatchAlertEvent, KafkaTopic

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stream", tags=["streaming"])


async def _alert_event_generator(
    request: Request,
    user_id: str | None,
) -> AsyncGenerator[str, None]:
    # Ephemeral consumer group per SSE client so every open browser tab receives live alerts
    group_id = f"vektryn-sse-{uuid.uuid4().hex[:12]}"
    consumer = create_kafka_consumer(
        group_id=group_id,
        topics=[KafkaTopic.JOBS_ALERTS],
        auto_offset_reset="latest",
    )

    try:
        yield ": connected\n\n"
        while not await request.is_disconnected():
            msg = await asyncio.to_thread(consumer.poll, 1.0)
            if msg is None:
                yield ": keepalive\n\n"
                continue

            if msg.error():
                logger.warning("Kafka SSE consumer error: %s", msg.error())
                continue

            try:
                raw_value = (msg.value() or b"").decode("utf-8")
                alert = JobMatchAlertEvent.model_validate_json(raw_value)
            except Exception as exc:
                logger.warning("Skipping malformed alert message: %s", exc)
                continue

            if user_id is not None and str(alert.user_id) != user_id:
                continue

            yield (
                f"id: {alert.event_id}\n"
                f"event: match_alert\n"
                f"data: {alert.model_dump_json()}\n\n"
            )
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
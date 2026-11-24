import asyncio
from collections.abc import AsyncGenerator
import logging
import uuid

from confluent_kafka import KafkaError, Message
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from stream_edge.clients.kafka import create_kafka_consumer
from stream_edge.config import settings
from stream_edge.metrics import SSE_ACTIVE_CLIENTS, SSE_ALERTS_SENT_TOTAL
from vektryn_contracts import JobMatchAlertEvent, KafkaTopic, verify_stream_token

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

    SSE_ACTIVE_CLIENTS.inc()
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
                SSE_ALERTS_SENT_TOTAL.inc()
                yield sse_frame
    finally:
        SSE_ACTIVE_CLIENTS.dec()
        await asyncio.to_thread(consumer.close)


def _resolve_stream_user_id(token: str | None, user_id: str | None) -> str | None:
    secret = settings.stream_auth_secret.strip()
    if secret:
        verified_user = verify_stream_token(token or "", secret)
        if verified_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid stream authentication token is required",
            )
        return verified_user
    return user_id


@router.get("/alerts")
async def stream_match_alerts(
    request: Request,
    token: str | None = Query(
        default=None,
        description="Signed HMAC stream token issued by /api/v1/auth/me/",
    ),
    user_id: str | None = Query(
        default=None,
        description="Optional user ID filter (only honored when STREAM_AUTH_SECRET is unset)",
    ),
) -> StreamingResponse:
    scoped_user_id = _resolve_stream_user_id(token=token, user_id=user_id)
    return StreamingResponse(
        _alert_event_generator(request=request, user_id=scoped_user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

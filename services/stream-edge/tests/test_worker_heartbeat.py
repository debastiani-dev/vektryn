import asyncio
from datetime import UTC, datetime
import json
from unittest.mock import AsyncMock

import pytest

from stream_edge.clients.heartbeat import (
    WORKER_HEARTBEAT_KEY_PREFIX,
    WORKER_HEARTBEAT_TTL_SECONDS,
    WorkerHeartbeat,
)


@pytest.mark.asyncio
async def test_worker_heartbeat_writes_expected_payload_and_ttl():
    fake_redis = AsyncMock()
    hb = WorkerHeartbeat(
        "enrichment-worker",
        redis_client=fake_redis,
        ttl_seconds=WORKER_HEARTBEAT_TTL_SECONDS,
    )

    msg_time = datetime(2026, 11, 25, 18, 0, 0, tzinfo=UTC)
    hb.record_message(at=msg_time)
    hb.record_message(at=msg_time)

    ok = await hb.beat()
    assert ok is True
    fake_redis.set.assert_awaited_once()
    call_args = fake_redis.set.await_args
    assert call_args.args[0] == f"{WORKER_HEARTBEAT_KEY_PREFIX}enrichment-worker"
    assert call_args.kwargs["ex"] == 90
    payload = json.loads(call_args.args[1])
    assert payload["worker"] == "enrichment-worker"
    assert payload["processed_count"] == 2
    assert payload["last_message_at"] == msg_time.isoformat()
    assert isinstance(payload["last_heartbeat_at"], str)


@pytest.mark.asyncio
async def test_worker_heartbeat_background_loop_and_clean_stop():
    fake_redis = AsyncMock()
    hb = WorkerHeartbeat(
        "matcher-worker",
        redis_client=fake_redis,
        interval_seconds=0.05,
        ttl_seconds=90,
    )
    await hb.start()
    await asyncio.sleep(0.13)
    await hb.stop()

    assert fake_redis.set.await_count >= 2
    # Must NOT delete heartbeat key on stop (TTL governs offline transition)
    fake_redis.delete.assert_not_called()


@pytest.mark.asyncio
async def test_worker_heartbeat_fail_open_on_redis_error():
    fake_redis = AsyncMock()
    fake_redis.set.side_effect = RuntimeError("redis connection refused")
    hb = WorkerHeartbeat("enrichment-worker", redis_client=fake_redis)

    ok = await hb.beat()
    assert ok is False
    await hb.stop()

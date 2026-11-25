import asyncio
from contextlib import suppress
from datetime import UTC, datetime
import json
import logging
from typing import Any

import redis.asyncio as aioredis

from stream_edge.config import settings

logger = logging.getLogger(__name__)

WORKER_HEARTBEAT_KEY_PREFIX = "vektryn:worker:heartbeat:"
WORKER_HEARTBEAT_INTERVAL_SECONDS = 30.0
WORKER_HEARTBEAT_TTL_SECONDS = 90


class WorkerHeartbeat:
    """Publishes periodic Redis liveness heartbeats for long-running Kafka workers."""

    def __init__(
        self,
        worker_name: str,
        *,
        redis_url: str | None = None,
        interval_seconds: float = WORKER_HEARTBEAT_INTERVAL_SECONDS,
        ttl_seconds: int = WORKER_HEARTBEAT_TTL_SECONDS,
        redis_client: Any = None,
    ) -> None:
        self.worker_name = worker_name
        self.key = f"{WORKER_HEARTBEAT_KEY_PREFIX}{worker_name}"
        self.interval_seconds = max(0.05, float(interval_seconds))
        self.ttl_seconds = max(1, int(ttl_seconds))
        self._last_message_at: str | None = None
        self._processed_count = 0
        self._task: asyncio.Task[None] | None = None
        self._owns_client = redis_client is None
        self._client = redis_client

        if self._client is None:
            resolved_url = (
                settings.redis_url if redis_url is None else redis_url
            ).strip()
            if resolved_url:
                try:
                    self._client = aioredis.from_url(
                        resolved_url,
                        decode_responses=True,
                        socket_connect_timeout=1.5,
                        socket_timeout=1.5,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed initializing Redis heartbeat client for %s: %s",
                        self.worker_name,
                        exc,
                    )
                    self._client = None

    def record_message(self, at: datetime | None = None) -> None:
        timestamp = (at or datetime.now(UTC)).astimezone(UTC)
        self._processed_count += 1
        self._last_message_at = timestamp.isoformat()

    def build_payload(self, now: datetime | None = None) -> dict[str, Any]:
        timestamp = (now or datetime.now(UTC)).astimezone(UTC)
        return {
            "worker": self.worker_name,
            "last_heartbeat_at": timestamp.isoformat(),
            "last_message_at": self._last_message_at,
            "processed_count": self._processed_count,
        }

    async def beat(self) -> bool:
        if self._client is None:
            return False
        payload = self.build_payload()
        try:
            await self._client.set(
                self.key,
                json.dumps(payload),
                ex=self.ttl_seconds,
            )
            return True
        except Exception as exc:
            logger.warning(
                "Failed writing Redis heartbeat for %s (fail-open): %s",
                self.worker_name,
                exc,
            )
            return False

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds)
            await self.beat()

    async def start(self) -> None:
        await self.beat()
        if self._task is None and self._client is not None:
            self._task = asyncio.create_task(
                self._loop(),
                name=f"heartbeat-{self.worker_name}",
            )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        if self._client is not None and self._owns_client:
            with suppress(Exception):
                await self._client.aclose()
            self._client = None

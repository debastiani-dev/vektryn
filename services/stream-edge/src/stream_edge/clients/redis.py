from datetime import UTC, datetime

import redis.asyncio as aioredis

from stream_edge.config import settings


class DedupRedisClient:
    KEY_PREFIX = "vektryn:job:hash:"
    DAILY_ENRICHMENT_PREFIX = "vektryn:enrichment:daily:"
    DAILY_COUNTER_TTL_SECONDS = 60 * 60 * 48

    def __init__(self, redis_url: str = settings.redis_url) -> None:
        self._client = aioredis.from_url(redis_url, decode_responses=True)

    async def acquire_content_hash(
        self,
        content_hash: str,
        ttl_seconds: int = settings.dedup_ttl_seconds,
    ) -> bool:
        """Returns True if this content_hash is new and claimed; False if already seen."""
        key = f"{self.KEY_PREFIX}{content_hash}"
        acquired = await self._client.set(key, "1", nx=True, ex=ttl_seconds)
        return bool(acquired)

    async def release_content_hash(self, content_hash: str) -> None:
        key = f"{self.KEY_PREFIX}{content_hash}"
        await self._client.delete(key)

    async def try_consume_enrichment_daily_quota(
        self,
        *,
        daily_cap: int,
        now: datetime | None = None,
    ) -> tuple[bool, int]:
        """Atomically increment today's UTC enrichment counter up to `daily_cap`."""
        if daily_cap <= 0:
            return True, 0
        day_stamp = (now or datetime.now(UTC)).strftime("%Y%m%d")
        key = f"{self.DAILY_ENRICHMENT_PREFIX}{day_stamp}"
        count = int(await self._client.incr(key))
        if count == 1:
            await self._client.expire(key, self.DAILY_COUNTER_TTL_SECONDS)
        if count > daily_cap:
            await self._client.decr(key)
            return False, daily_cap
        return True, count

    async def release_enrichment_daily_quota(
        self,
        *,
        now: datetime | None = None,
    ) -> None:
        day_stamp = (now or datetime.now(UTC)).strftime("%Y%m%d")
        key = f"{self.DAILY_ENRICHMENT_PREFIX}{day_stamp}"
        current = int(await self._client.decr(key))
        if current < 0:
            await self._client.set(key, "0", ex=self.DAILY_COUNTER_TTL_SECONDS)

    async def ping(self) -> bool:
        return bool(await self._client.ping())

    async def close(self) -> None:
        await self._client.aclose()

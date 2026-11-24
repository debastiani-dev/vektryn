import redis.asyncio as aioredis

from stream_edge.config import settings


class DedupRedisClient:
    KEY_PREFIX = "vektryn:job:hash:"

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

    async def ping(self) -> bool:
        return bool(await self._client.ping())

    async def close(self) -> None:
        await self._client.aclose()

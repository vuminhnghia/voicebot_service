import json

from redis.asyncio import Redis


class RedisCache:
    def __init__(self, redis_url: str, ttl: int = 300) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._ttl = ttl

    async def get(self, key: str) -> dict | None:
        val = await self._redis.get(key)
        if val is None:
            return None
        return json.loads(val)

    async def set(self, key: str, value: dict) -> None:
        await self._redis.setex(key, self._ttl, json.dumps(value))

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def aclose(self) -> None:
        await self._redis.aclose()

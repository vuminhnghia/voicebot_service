import json
import uuid

import redis.asyncio as aioredis

from app.domain.ports.task_store import TaskStorePort

TASK_TTL = 3600  # 1 hour


class RedisTaskStore(TaskStorePort):
    """Task store adapter backed by Redis."""

    def __init__(self, redis_url: str) -> None:
        self._redis: aioredis.Redis = aioredis.from_url(redis_url, decode_responses=False)

    async def create(self) -> str:
        task_id = str(uuid.uuid4())
        await self._redis.setex(
            f"task:{task_id}",
            TASK_TTL,
            json.dumps({"status": "pending"}),
        )
        return task_id

    async def get(self, task_id: str) -> dict | None:
        raw = await self._redis.get(f"task:{task_id}")
        if raw is None:
            return None
        return json.loads(raw)

    async def update(self, task_id: str, **fields) -> None:
        data = await self.get(task_id)
        if data is None:
            return
        data.update(fields)
        await self._redis.setex(f"task:{task_id}", TASK_TTL, json.dumps(data))

    async def set_audio(self, task_id: str, audio: bytes) -> None:
        await self._redis.setex(f"task:{task_id}:audio", TASK_TTL, audio)

    async def get_audio(self, task_id: str) -> bytes | None:
        return await self._redis.get(f"task:{task_id}:audio")

    async def aclose(self) -> None:
        await self._redis.aclose()

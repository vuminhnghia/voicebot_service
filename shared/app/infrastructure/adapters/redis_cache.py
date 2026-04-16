import asyncio
import json

from redis.asyncio import Redis

STREAM_TTL = 3600        # event stream lives 1 hour (matches audio URL TTL)
STREAM_MAXLEN = 200      # max events kept per task stream


class RedisCache:
    def __init__(self, redis_url: str, ttl: int = 300) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._ttl = ttl

    # ── Task cache ────────────────────────────────────────────────────────

    async def get(self, key: str) -> dict | None:
        val = await self._redis.get(key)
        if val is None:
            return None
        return json.loads(val)

    async def set(self, key: str, value: dict) -> None:
        await self._redis.setex(key, self._ttl, json.dumps(value))

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    # ── Streaming events (Redis Streams) ──────────────────────────────────

    async def publish_event(self, task_id: str, event: dict) -> None:
        """Append an event to the task's Redis Stream."""
        key = f"stream:{task_id}"
        await self._redis.xadd(key, {"data": json.dumps(event)}, maxlen=STREAM_MAXLEN)
        await self._redis.expire(key, STREAM_TTL)

    async def iter_events(self, task_id: str, timeout_s: int = 120):
        """Async generator — yields events in order.

        Replays any events already in the stream, then blocks for new ones
        until a 'complete'/'error' event arrives or timeout_s elapses.
        """
        key = f"stream:{task_id}"
        last_id = "0-0"  # start from the very beginning
        deadline = asyncio.get_event_loop().time() + timeout_s

        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break

            block_ms = min(2000, int(remaining * 1000))
            try:
                entries = await self._redis.xread(
                    {key: last_id}, block=block_ms, count=50
                )
            except asyncio.CancelledError:
                return  # client disconnected

            if not entries:
                continue  # timeout block, loop again

            for _stream, messages in entries:
                for msg_id, fields in messages:
                    last_id = msg_id
                    event = json.loads(fields["data"])
                    yield event
                    if event.get("type") in ("complete", "error"):
                        return

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def aclose(self) -> None:
        await self._redis.aclose()

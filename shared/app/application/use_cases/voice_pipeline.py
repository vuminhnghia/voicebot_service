import time
import uuid

import structlog

from app.application.webhook import send_webhook
from app.domain.ports.asr import ASRPort
from app.domain.ports.llm import LLMPort
from app.domain.ports.message_queue import MessageQueuePort
from app.domain.ports.object_storage import ObjectStoragePort
from app.domain.ports.task_repository import TaskRepositoryPort
from app.domain.ports.tts import TTSPort
from app.infrastructure.adapters.redis_cache import RedisCache
from app.metrics import task_counter, task_duration
from app.schemas.task import TaskStatus

logger = structlog.get_logger(__name__)

TASK_TYPE = "voice"


class VoicePipelineUseCase:
    def __init__(
        self,
        task_repo: TaskRepositoryPort,
        object_storage: ObjectStoragePort,
        queue: MessageQueuePort,
        cache: RedisCache,
        asr: ASRPort | None = None,
        llm: LLMPort | None = None,
        tts: TTSPort | None = None,
    ) -> None:
        self._repo = task_repo
        self._storage = object_storage
        self._queue = queue
        self._cache = cache
        self._asr = asr
        self._llm = llm
        self._tts = tts

    async def submit(self, audio_bytes: bytes, webhook_url: str | None) -> str:
        """API side: store input → create DB record → enqueue. Returns task_id."""
        task_id = str(uuid.uuid4())
        input_key = f"tasks/{task_id}/input.audio"
        await self._storage.put(input_key, audio_bytes, content_type="audio/wav")
        await self._repo.create(
            task_id=task_id,
            task_type=TASK_TYPE,
            status=TaskStatus.pending,
            input_object_key=input_key,
            webhook_url=webhook_url,
        )
        await self._cache.set(task_id, {"status": TaskStatus.pending})
        await self._queue.publish(task_id, TASK_TYPE)
        task_counter.labels(task_type=TASK_TYPE, status="submitted").inc()
        logger.info("task_submitted", task_id=task_id, task_type=TASK_TYPE)
        return task_id

    async def execute(self, task_id: str) -> None:
        """Worker side: fetch input → run ASR→LLM→TTS → store output → update state."""
        log = logger.bind(task_id=task_id, task_type=TASK_TYPE)
        task_data = await self._repo.get(task_id)
        if task_data is None:
            raise ValueError(f"Task {task_id} not found")

        await self._repo.update(task_id, status=TaskStatus.processing)
        await self._cache.set(task_id, {"status": TaskStatus.processing})
        log.info("task_processing")

        start = time.perf_counter()
        try:
            audio_bytes = await self._storage.get(task_data["input_object_key"])
            transcript = await self._asr.transcribe(audio_bytes)
            response_text = await self._llm.generate(transcript)
            wav_bytes = await self._tts.synthesize(response_text)

            output_key = f"tasks/{task_id}/output.wav"
            await self._storage.put(output_key, wav_bytes, content_type="audio/wav")

            await self._repo.update(
                task_id,
                status=TaskStatus.completed,
                transcript=transcript,
                response=response_text,
                output_object_key=output_key,
            )
            result = {
                "status": TaskStatus.completed,
                "transcript": transcript,
                "response": response_text,
                "has_audio": True,
            }
            await self._cache.set(task_id, result)

            elapsed = time.perf_counter() - start
            task_duration.labels(task_type=TASK_TYPE).observe(elapsed)
            task_counter.labels(task_type=TASK_TYPE, status="completed").inc()
            log.info("task_completed", duration_s=round(elapsed, 3))

            if task_data.get("webhook_url"):
                await send_webhook(task_data["webhook_url"], {"task_id": task_id, **result})

        except Exception as exc:
            elapsed = time.perf_counter() - start
            task_counter.labels(task_type=TASK_TYPE, status="failed").inc()
            log.error("task_failed", error=str(exc), duration_s=round(elapsed, 3))
            await self._repo.update(task_id, status=TaskStatus.failed, error=str(exc))
            await self._cache.set(task_id, {"status": TaskStatus.failed, "error": str(exc)})
            if task_data.get("webhook_url"):
                await send_webhook(task_data["webhook_url"], {
                    "task_id": task_id,
                    "status": TaskStatus.failed,
                    "error": str(exc),
                })
            raise

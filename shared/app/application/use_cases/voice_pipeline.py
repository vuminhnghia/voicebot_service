import time
import uuid
from datetime import datetime, timedelta, timezone

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
from app.schemas.voice import OutputMode

logger = structlog.get_logger(__name__)

TASK_TYPE = "voice"
SENTENCE_ENDS = frozenset(".!?。！？…")
MIN_SENTENCE_LEN = 8
CHUNK_URL_TTL = 3600  # presigned chunk URLs valid 1 hour


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

    async def submit(
        self,
        audio_bytes: bytes,
        webhook_url: str | None,
        output_mode: OutputMode = OutputMode.audio,
    ) -> str:
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
            output_mode=output_mode,
        )
        await self._cache.set(task_id, {"status": TaskStatus.pending})
        await self._queue.publish(task_id, TASK_TYPE)
        task_counter.labels(task_type=TASK_TYPE, status="submitted").inc()
        logger.info("task_submitted", task_id=task_id, task_type=TASK_TYPE, output_mode=output_mode)
        return task_id

    async def execute(self, task_id: str) -> None:
        """Worker side: ASR → publish transcript → stream LLM → TTS per sentence → complete."""
        log = logger.bind(task_id=task_id, task_type=TASK_TYPE)
        task_data = await self._repo.get(task_id)
        if task_data is None:
            raise ValueError(f"Task {task_id} not found")

        output_mode = task_data.get("output_mode") or OutputMode.audio

        await self._repo.update(task_id, status=TaskStatus.processing)
        await self._cache.set(task_id, {"status": TaskStatus.processing})
        log.info("task_processing", output_mode=output_mode)

        start = time.perf_counter()
        try:
            # 1. ASR — transcribe input audio
            audio_bytes = await self._storage.get(task_data["input_object_key"])
            transcript = await self._asr.transcribe(audio_bytes)
            log.info("asr_done", transcript=transcript)

            # Immediately stream transcript to the client
            await self._cache.publish_event(task_id, {"type": "transcript", "text": transcript})

            # 2. LLM streaming + sentence-level TTS
            response_tokens: list[str] = []
            sentence_buffer = ""
            chunk_index = 0

            async for token in self._llm.stream_generate(transcript):
                response_tokens.append(token)
                sentence_buffer += token

                # Flush when a sentence boundary is detected
                stripped = sentence_buffer.rstrip()
                if len(stripped) >= MIN_SENTENCE_LEN and stripped[-1] in SENTENCE_ENDS:
                    if output_mode == OutputMode.audio:
                        await self._synthesize_chunk(task_id, stripped, chunk_index)
                        chunk_index += 1
                    sentence_buffer = ""

            response_text = "".join(response_tokens).strip()

            # Flush any remaining text that didn't end with punctuation
            remaining = sentence_buffer.strip()
            if remaining and output_mode == OutputMode.audio:
                await self._synthesize_chunk(task_id, remaining, chunk_index)
                chunk_index += 1

            log.info("llm_done", chunks=chunk_index, output_mode=output_mode)

            # 3. Persist final state (no single output_object_key for chunked audio)
            await self._repo.update(
                task_id,
                status=TaskStatus.completed,
                transcript=transcript,
                response=response_text,
                output_object_key=None,
            )
            result = {
                "status": TaskStatus.completed,
                "transcript": transcript,
                "response": response_text,
                "output_object_key": None,
            }
            await self._cache.set(task_id, result)

            # 4. Signal stream end
            await self._cache.publish_event(task_id, {
                "type": "complete",
                "transcript": transcript,
                "response": response_text,
            })

            elapsed = time.perf_counter() - start
            task_duration.labels(task_type=TASK_TYPE).observe(elapsed)
            task_counter.labels(task_type=TASK_TYPE, status="completed").inc()
            log.info("task_completed", duration_s=round(elapsed, 3), output_mode=output_mode, chunks=chunk_index)

            if task_data.get("webhook_url"):
                await send_webhook(task_data["webhook_url"], {"task_id": task_id, **result})

        except Exception as exc:
            elapsed = time.perf_counter() - start
            task_counter.labels(task_type=TASK_TYPE, status="failed").inc()
            log.error("task_failed", error=str(exc), duration_s=round(elapsed, 3))
            await self._repo.update(task_id, status=TaskStatus.failed, error=str(exc))
            await self._cache.set(task_id, {"status": TaskStatus.failed, "error": str(exc)})
            await self._cache.publish_event(task_id, {"type": "error", "message": str(exc)})
            if task_data.get("webhook_url"):
                await send_webhook(task_data["webhook_url"], {
                    "task_id": task_id,
                    "status": TaskStatus.failed,
                    "error": str(exc),
                })
            raise

    async def _synthesize_chunk(self, task_id: str, sentence: str, index: int) -> None:
        """TTS one sentence → store chunk → publish audio_chunk event."""
        wav_bytes = await self._tts.synthesize(sentence)
        chunk_key = f"tasks/{task_id}/chunks/{index}.wav"
        await self._storage.put(chunk_key, wav_bytes, content_type="audio/wav")
        audio_url = await self._storage.presign(chunk_key, ttl=CHUNK_URL_TTL)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=CHUNK_URL_TTL)
        await self._cache.publish_event(task_id, {
            "type": "audio_chunk",
            "index": index,
            "sentence": sentence,
            "audio_url": audio_url,
            "audio_expires_at": expires_at.isoformat(),
        })

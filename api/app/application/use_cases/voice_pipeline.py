from app.application.webhook import send_webhook
from app.domain.ports.asr import ASRPort
from app.domain.ports.llm import LLMPort
from app.domain.ports.task_store import TaskStorePort
from app.domain.ports.tts import TTSPort
from app.schemas.task import TaskStatus


class VoicePipelineUseCase:
    def __init__(
        self,
        asr: ASRPort,
        llm: LLMPort,
        tts: TTSPort,
        tasks: TaskStorePort,
    ) -> None:
        self._asr = asr
        self._llm = llm
        self._tts = tts
        self._tasks = tasks

    async def submit(self) -> str:
        """Create a task and return its ID immediately."""
        return await self._tasks.create()

    async def execute(
        self,
        task_id: str,
        audio_bytes: bytes,
        webhook_url: str | None,
    ) -> None:
        """Run ASR → LLM → TTS pipeline and update task state."""
        await self._tasks.update(task_id, status=TaskStatus.processing)
        try:
            transcript = await self._asr.transcribe(audio_bytes)
            response_text = await self._llm.generate(transcript)
            wav_bytes = await self._tts.synthesize(response_text)
            await self._tasks.set_audio(task_id, wav_bytes)
            await self._tasks.update(
                task_id,
                status=TaskStatus.completed,
                transcript=transcript,
                response=response_text,
                has_audio=True,
            )
            if webhook_url:
                await send_webhook(webhook_url, {
                    "task_id": task_id,
                    "status": TaskStatus.completed,
                    "transcript": transcript,
                    "response": response_text,
                    "has_audio": True,
                })
        except Exception as exc:
            await self._tasks.update(task_id, status=TaskStatus.failed, error=str(exc))
            if webhook_url:
                await send_webhook(webhook_url, {
                    "task_id": task_id,
                    "status": TaskStatus.failed,
                    "error": str(exc),
                })

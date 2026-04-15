from app.application.webhook import send_webhook
from app.domain.ports.llm import LLMPort
from app.domain.ports.task_store import TaskStorePort
from app.schemas.task import TaskStatus


class TextPipelineUseCase:
    def __init__(self, llm: LLMPort, tasks: TaskStorePort) -> None:
        self._llm = llm
        self._tasks = tasks

    async def submit(self) -> str:
        """Create a task and return its ID immediately."""
        return await self._tasks.create()

    async def execute(
        self,
        task_id: str,
        message: str,
        webhook_url: str | None,
    ) -> None:
        """Run LLM pipeline and update task state."""
        await self._tasks.update(task_id, status=TaskStatus.processing)
        try:
            response_text = await self._llm.generate(message)
            await self._tasks.update(
                task_id,
                status=TaskStatus.completed,
                response=response_text,
            )
            if webhook_url:
                await send_webhook(webhook_url, {
                    "task_id": task_id,
                    "status": TaskStatus.completed,
                    "response": response_text,
                })
        except Exception as exc:
            await self._tasks.update(task_id, status=TaskStatus.failed, error=str(exc))
            if webhook_url:
                await send_webhook(webhook_url, {
                    "task_id": task_id,
                    "status": TaskStatus.failed,
                    "error": str(exc),
                })

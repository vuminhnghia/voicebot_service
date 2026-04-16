from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.ports.task_repository import TaskRepositoryPort
from app.infrastructure.db.models import TaskModel


class PostgresTaskRepo(TaskRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create(self, task_id: str, task_type: str, **kwargs) -> None:
        async with self._sf() as session:
            task = TaskModel(id=task_id, task_type=task_type, **kwargs)
            session.add(task)
            await session.commit()

    async def get(self, task_id: str) -> dict | None:
        async with self._sf() as session:
            result = await session.execute(select(TaskModel).where(TaskModel.id == task_id))
            task = result.scalar_one_or_none()
            if task is None:
                return None
            return {
                "status": task.status,
                "task_type": task.task_type,
                "transcript": task.transcript,
                "response": task.response,
                "error": task.error,
                "has_audio": task.output_object_key is not None,
                "input_object_key": task.input_object_key,
                "output_object_key": task.output_object_key,
                "webhook_url": task.webhook_url,
            }

    async def update(self, task_id: str, **fields) -> None:
        fields["updated_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
        async with self._sf() as session:
            await session.execute(
                update(TaskModel).where(TaskModel.id == task_id).values(**fields)
            )
            await session.commit()

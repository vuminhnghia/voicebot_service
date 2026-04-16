from abc import ABC, abstractmethod


class TaskRepositoryPort(ABC):
    @abstractmethod
    async def create(self, task_id: str, task_type: str, **kwargs) -> None: ...

    @abstractmethod
    async def get(self, task_id: str) -> dict | None: ...

    @abstractmethod
    async def update(self, task_id: str, **fields) -> None: ...

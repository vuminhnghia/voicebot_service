from abc import ABC, abstractmethod


class TaskStorePort(ABC):
    @abstractmethod
    async def create(self) -> str: ...

    @abstractmethod
    async def get(self, task_id: str) -> dict | None: ...

    @abstractmethod
    async def update(self, task_id: str, **fields) -> None: ...

    @abstractmethod
    async def set_audio(self, task_id: str, audio: bytes) -> None: ...

    @abstractmethod
    async def get_audio(self, task_id: str) -> bytes | None: ...

    @abstractmethod
    async def aclose(self) -> None: ...

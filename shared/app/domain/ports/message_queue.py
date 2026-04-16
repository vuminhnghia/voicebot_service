from abc import ABC, abstractmethod


class MessageQueuePort(ABC):
    @abstractmethod
    async def publish(self, task_id: str, task_type: str) -> None: ...

    @abstractmethod
    async def aclose(self) -> None: ...

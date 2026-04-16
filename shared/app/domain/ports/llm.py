from abc import ABC, abstractmethod


class LLMPort(ABC):
    @abstractmethod
    async def generate(self, message: str) -> str: ...

    @abstractmethod
    async def aclose(self) -> None: ...

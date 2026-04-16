from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class LLMPort(ABC):
    @abstractmethod
    async def generate(self, message: str) -> str: ...

    @abstractmethod
    def stream_generate(self, message: str) -> AsyncIterator[str]:
        """Yield delta tokens as they are generated."""
        ...

    @abstractmethod
    async def aclose(self) -> None: ...

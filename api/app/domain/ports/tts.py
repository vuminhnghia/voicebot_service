from abc import ABC, abstractmethod


class TTSPort(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> bytes: ...

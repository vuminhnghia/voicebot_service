from abc import ABC, abstractmethod


class ASRPort(ABC):
    @abstractmethod
    async def transcribe(self, audio_bytes: bytes) -> str: ...

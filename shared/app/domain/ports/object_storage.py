from abc import ABC, abstractmethod


class ObjectStoragePort(ABC):
    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...

    @abstractmethod
    async def get(self, key: str) -> bytes | None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def presign(self, key: str, ttl: int = 3600) -> str:
        """Return a presigned GET URL for key, valid for ttl seconds."""
        ...

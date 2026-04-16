from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    triton_url: str = "triton:8000"
    redis_url: str = "redis://redis:6379"
    postgres_url: str = "postgresql+asyncpg://voicebot:voicebot@postgres:5432/voicebot"
    rabbitmq_url: str = "amqp://voicebot:voicebot@rabbitmq:5672/"
    seaweedfs_endpoint: str = "http://seaweedfs:8333"
    seaweedfs_public_endpoint: str | None = None  # public-facing URL for presigned URLs; defaults to seaweedfs_endpoint
    seaweedfs_bucket: str = "voicebot"
    seaweedfs_access_key: str = "any"
    seaweedfs_secret_key: str = "any"

    api_keys: list[str] = []
    system_prompt: str = (
        "Bạn là trợ lý AI giọng nói hữu ích. Trả lời ngắn gọn, tự nhiên bằng tiếng Việt."
    )
    max_tokens: int = 500
    task_retention_days: int = 7

    @field_validator("api_keys", mode="before")
    @classmethod
    def parse_api_keys(cls, v: Any) -> Any:
        if isinstance(v, str):
            return [k.strip() for k in v.split(",") if k.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()

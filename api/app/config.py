from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    triton_url: str = "triton:8000"
    redis_url: str = "redis://redis:6379"
    api_keys: list[str] = []
    system_prompt: str = (
        "Bạn là trợ lý AI giọng nói hữu ích. Trả lời ngắn gọn, tự nhiên bằng tiếng Việt."
    )
    max_tokens: int = 500

    @field_validator("api_keys", mode="before")
    @classmethod
    def parse_api_keys(cls, v: Any) -> Any:
        if isinstance(v, str):
            return [k.strip() for k in v.split(",") if k.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()

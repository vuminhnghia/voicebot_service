from enum import Enum

from pydantic import BaseModel


class OutputMode(str, Enum):
    text = "text"
    audio = "audio"


class TextChatRequest(BaseModel):
    message: str
    webhook_url: str | None = None


class TextChatResponse(BaseModel):
    response: str

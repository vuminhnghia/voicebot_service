from typing import Optional

from pydantic import BaseModel


class TextChatRequest(BaseModel):
    message: str
    webhook_url: Optional[str] = None


class TextChatResponse(BaseModel):
    response: str

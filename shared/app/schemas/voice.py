from pydantic import BaseModel


class TextChatRequest(BaseModel):
    message: str
    webhook_url: str | None = None


class TextChatResponse(BaseModel):
    response: str

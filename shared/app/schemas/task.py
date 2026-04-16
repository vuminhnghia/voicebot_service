from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class TaskStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class TaskCreated(BaseModel):
    task_id: str


class TaskResult(BaseModel):
    task_id: str
    status: TaskStatus
    transcript: str | None = None
    response: str | None = None
    audio_url: str | None = None
    audio_expires_at: datetime | None = None
    error: str | None = None

from enum import Enum
from typing import Optional

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
    transcript: Optional[str] = None
    response: Optional[str] = None
    has_audio: bool = False
    error: Optional[str] = None

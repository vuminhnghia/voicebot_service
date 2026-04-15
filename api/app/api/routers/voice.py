import io

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.application.use_cases.text_pipeline import TextPipelineUseCase
from app.application.use_cases.voice_pipeline import VoicePipelineUseCase
from app.dependencies import verify_api_key
from app.schemas.task import TaskCreated, TaskResult, TaskStatus
from app.schemas.voice import TextChatRequest

router = APIRouter(prefix="/v1", tags=["voice"])

SUPPORTED_CONTENT_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
}


@router.post("/chat/voice", response_model=TaskCreated, status_code=202)
async def voice_chat(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(..., description="Audio file (WAV, MP3, M4A)"),
    webhook_url: str | None = Form(None, description="URL to POST result on completion"),
    _: str = Depends(verify_api_key),
):
    """Submit a voice pipeline job (ASR → LLM → TTS). Poll /v1/tasks/{task_id} for result."""
    if file.content_type not in SUPPORTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported audio format '{file.content_type}'. Accepted: WAV, MP3, M4A.",
        )
    uc: VoicePipelineUseCase = request.app.state.voice_pipeline
    audio_bytes = await file.read()
    task_id = await uc.submit()
    background_tasks.add_task(uc.execute, task_id, audio_bytes, webhook_url)
    return TaskCreated(task_id=task_id)


@router.post("/chat/text", response_model=TaskCreated, status_code=202)
async def text_chat(
    background_tasks: BackgroundTasks,
    request: Request,
    body: TextChatRequest,
    _: str = Depends(verify_api_key),
):
    """Submit a text pipeline job (LLM only). Poll /v1/tasks/{task_id} for result."""
    uc: TextPipelineUseCase = request.app.state.text_pipeline
    task_id = await uc.submit()
    background_tasks.add_task(uc.execute, task_id, body.message, body.webhook_url)
    return TaskCreated(task_id=task_id)


@router.get("/tasks/{task_id}", response_model=TaskResult)
async def get_task(
    task_id: str,
    request: Request,
    _: str = Depends(verify_api_key),
):
    """Poll task status and result."""
    data = await request.app.state.tasks.get(task_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResult(task_id=task_id, **data)


@router.get("/tasks/{task_id}/audio")
async def get_task_audio(
    task_id: str,
    request: Request,
    _: str = Depends(verify_api_key),
):
    """Download synthesized WAV audio for a completed voice task."""
    data = await request.app.state.tasks.get(task_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if data.get("status") != TaskStatus.completed:
        raise HTTPException(status_code=409, detail="Task not completed yet")
    if not data.get("has_audio"):
        raise HTTPException(status_code=404, detail="No audio for this task")
    audio = await request.app.state.tasks.get_audio(task_id)
    if audio is None:
        raise HTTPException(status_code=404, detail="Audio expired or not found")
    return StreamingResponse(io.BytesIO(audio), media_type="audio/wav")

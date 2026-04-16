import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.application.use_cases.text_pipeline import TextPipelineUseCase
from app.application.use_cases.voice_pipeline import VoicePipelineUseCase
from app.dependencies import verify_api_key
from app.domain.ports.task_repository import TaskRepositoryPort
from app.infrastructure.adapters.redis_cache import RedisCache
from app.infrastructure.adapters.seaweedfs import SeaweedFSAdapter
from app.rate_limit import limiter
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
@limiter.limit("20/minute")
async def voice_chat(
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
    task_id = await uc.submit(audio_bytes, webhook_url)
    return TaskCreated(task_id=task_id)


@router.post("/chat/text", response_model=TaskCreated, status_code=202)
@limiter.limit("30/minute")
async def text_chat(
    request: Request,
    body: TextChatRequest,
    _: str = Depends(verify_api_key),
):
    """Submit a text pipeline job (LLM only). Poll /v1/tasks/{task_id} for result."""
    uc: TextPipelineUseCase = request.app.state.text_pipeline
    task_id = await uc.submit(body.message, body.webhook_url)
    return TaskCreated(task_id=task_id)


@router.get("/tasks/{task_id}", response_model=TaskResult)
@limiter.limit("60/minute")
async def get_task(
    task_id: str,
    request: Request,
    _: str = Depends(verify_api_key),
):
    """Poll task status and result. Checks Redis cache first, falls back to Postgres."""
    cache: RedisCache = request.app.state.cache
    data = await cache.get(task_id)
    if data is None:
        repo: TaskRepositoryPort = request.app.state.task_repo
        data = await repo.get(task_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Task not found")
        await cache.set(task_id, {
            "status": data["status"],
            "transcript": data.get("transcript"),
            "response": data.get("response"),
            "has_audio": data.get("has_audio", False),
            "error": data.get("error"),
        })
    return TaskResult(
        task_id=task_id,
        status=data["status"],
        transcript=data.get("transcript"),
        response=data.get("response"),
        has_audio=data.get("has_audio", False),
        error=data.get("error"),
    )


@router.get("/tasks/{task_id}/audio")
@limiter.limit("30/minute")
async def get_task_audio(
    task_id: str,
    request: Request,
    _: str = Depends(verify_api_key),
):
    """Download synthesized WAV audio for a completed voice task."""
    repo: TaskRepositoryPort = request.app.state.task_repo
    data = await repo.get(task_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if data.get("status") != TaskStatus.completed:
        raise HTTPException(status_code=409, detail="Task not completed yet")
    if not data.get("output_object_key"):
        raise HTTPException(status_code=404, detail="No audio for this task")
    storage: SeaweedFSAdapter = request.app.state.storage
    audio = await storage.get(data["output_object_key"])
    if audio is None:
        raise HTTPException(status_code=404, detail="Audio expired or not found")
    return StreamingResponse(io.BytesIO(audio), media_type="audio/wav")

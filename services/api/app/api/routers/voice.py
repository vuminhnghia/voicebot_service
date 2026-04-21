import asyncio
import json
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

logger = structlog.get_logger(__name__)

from app.application.use_cases.text_pipeline import TextPipelineUseCase
from app.application.use_cases.voice_pipeline import VoicePipelineUseCase
from app.dependencies import verify_api_key
from app.domain.ports.task_repository import TaskRepositoryPort
from app.infrastructure.adapters.redis_cache import RedisCache
from app.infrastructure.adapters.seaweedfs import SeaweedFSAdapter
from app.rate_limit import limiter
from app.schemas.task import TaskCreated, TaskResult, TaskStatus
from app.schemas.voice import OutputMode, TextChatRequest

router = APIRouter(prefix="/v1", tags=["voice"])

AUDIO_URL_TTL = 3600  # presigned URL valid for 1 hour

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
    output_mode: OutputMode = Form(OutputMode.audio, description="text = ASR+LLM only; audio = ASR+LLM+TTS"),
    webhook_url: str | None = Form(None, description="URL to POST result on completion"),
    _: str = Depends(verify_api_key),
):
    """Submit a voice pipeline job. Poll /v1/tasks/{task_id} for result."""
    if file.content_type not in SUPPORTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported audio format '{file.content_type}'. Accepted: WAV, MP3, M4A.",
        )
    uc: VoicePipelineUseCase = request.app.state.voice_pipeline
    audio_bytes = await file.read()
    task_id = await uc.submit(audio_bytes, webhook_url, output_mode)
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
    """Poll task status and result. Returns audio_url (presigned, 1h TTL) when audio is ready."""
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
            "output_object_key": data.get("output_object_key"),
            "error": data.get("error"),
        })

    audio_url = None
    audio_expires_at = None
    if data.get("output_object_key"):
        storage: SeaweedFSAdapter = request.app.state.storage
        audio_url = await storage.presign(data["output_object_key"], ttl=AUDIO_URL_TTL)
        audio_expires_at = datetime.now(timezone.utc) + timedelta(seconds=AUDIO_URL_TTL)

    return TaskResult(
        task_id=task_id,
        status=data["status"],
        transcript=data.get("transcript"),
        response=data.get("response"),
        audio_url=audio_url,
        audio_expires_at=audio_expires_at,
        error=data.get("error"),
    )


@router.get("/tasks/{task_id}/stream")
@limiter.limit("30/minute")
async def stream_task_events(
    task_id: str,
    request: Request,
    _: str = Depends(verify_api_key),
):
    """SSE stream of real-time task events.

    Events:
    - **transcript** — ASR result available (`{"type":"transcript","text":"..."}`)
    - **audio_chunk** — TTS chunk ready (`{"type":"audio_chunk","index":0,"sentence":"...","audio_url":"...","audio_expires_at":"..."}`)
    - **complete** — pipeline finished (`{"type":"complete","transcript":"...","response":"..."}`)
    - **error** — pipeline failed (`{"type":"error","message":"..."}`)
    """
    cache: RedisCache = request.app.state.cache
    repo: TaskRepositoryPort = request.app.state.task_repo

    # Verify task exists before opening the stream
    data = await cache.get(task_id)
    if data is None:
        db_data = await repo.get(task_id)
        if db_data is None:
            raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        try:
            async for event in cache.iter_events(task_id, timeout_s=120):
                event_type = event.get("type", "message")
                yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error("sse_stream_error", task_id=task_id, error=str(exc))
            yield f"event: error\ndata: {json.dumps({'type': 'error', 'message': 'Stream interrupted'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

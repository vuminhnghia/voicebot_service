from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routers import voice
from app.application.use_cases.text_pipeline import TextPipelineUseCase
from app.application.use_cases.voice_pipeline import VoicePipelineUseCase
from app.config import get_settings
from app.infrastructure.adapters.redis_task_store import RedisTaskStore
from app.infrastructure.adapters.triton_asr import TritonASRAdapter
from app.infrastructure.adapters.triton_llm import TritonLLMAdapter
from app.infrastructure.adapters.triton_tts import TritonTTSAdapter


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Build adapters
    asr = TritonASRAdapter(settings.triton_url)
    llm = TritonLLMAdapter(settings.triton_url, settings.system_prompt, settings.max_tokens)
    tts = TritonTTSAdapter(settings.triton_url)
    tasks = RedisTaskStore(settings.redis_url)

    # Wire use cases
    app.state.voice_pipeline = VoicePipelineUseCase(asr, llm, tts, tasks)
    app.state.text_pipeline = TextPipelineUseCase(llm, tasks)
    app.state.tasks = tasks

    yield

    await llm.aclose()
    await tasks.aclose()


app = FastAPI(
    title="Voicebot API",
    description="Vietnamese voice bot — ASR → LLM → TTS via Triton Inference Server",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(voice.router)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}

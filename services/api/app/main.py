import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from sqlalchemy import delete, text

from app.api.routers import voice
from app.application.use_cases.text_pipeline import TextPipelineUseCase
from app.application.use_cases.voice_pipeline import VoicePipelineUseCase
from app.config import get_settings
from app.infrastructure.adapters.postgres_task_repo import PostgresTaskRepo
from app.infrastructure.adapters.rabbitmq_publisher import RabbitMQPublisher
from app.infrastructure.adapters.redis_cache import RedisCache
from app.infrastructure.adapters.seaweedfs import SeaweedFSAdapter
from app.infrastructure.db.models import TaskModel
from app.infrastructure.db.session import make_session_factory
from app.logging_config import setup_logging
from app.rate_limit import limiter
from app.schemas.task import TaskStatus

setup_logging()
logger = structlog.get_logger(__name__)


async def _cleanup_loop(session_factory, retention_days: int) -> None:
    while True:
        await asyncio.sleep(24 * 3600)
        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        try:
            async with session_factory() as session:
                result = await session.execute(
                    delete(TaskModel).where(
                        TaskModel.created_at < cutoff,
                        TaskModel.status.in_([TaskStatus.completed, TaskStatus.failed]),
                    )
                )
                await session.commit()
            logger.info("tasks_cleaned_up", deleted=result.rowcount, retention_days=retention_days)
        except Exception as exc:
            logger.error("task_cleanup_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("api_starting", triton_url=settings.triton_url)

    session_factory = make_session_factory(settings.postgres_url)
    task_repo = PostgresTaskRepo(session_factory)

    storage = SeaweedFSAdapter(
        settings.seaweedfs_endpoint,
        settings.seaweedfs_bucket,
        settings.seaweedfs_access_key,
        settings.seaweedfs_secret_key,
        public_endpoint=settings.seaweedfs_public_endpoint,
    )
    await storage.ensure_bucket()

    cache = RedisCache(settings.redis_url)

    queue = RabbitMQPublisher(settings.rabbitmq_url)
    await queue.connect()

    cleanup_task = asyncio.create_task(
        _cleanup_loop(session_factory, settings.task_retention_days)
    )

    app.state.voice_pipeline = VoicePipelineUseCase(task_repo, storage, queue, cache)
    app.state.text_pipeline = TextPipelineUseCase(task_repo, storage, queue, cache)
    app.state.task_repo = task_repo
    app.state.storage = storage
    app.state.cache = cache
    app.state.queue = queue
    app.state.session_factory = session_factory

    logger.info("api_ready")
    yield

    cleanup_task.cancel()
    await queue.aclose()
    await cache.aclose()
    logger.info("api_shutdown")


app = FastAPI(
    title="Voicebot API",
    description="Vietnamese voice bot — ASR → LLM → TTS via Triton Inference Server",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(voice.router)

Instrumentator().instrument(app).expose(app, include_in_schema=False)


@app.get("/health", tags=["health"])
async def health(request: Request):
    checks: dict[str, str] = {}

    try:
        cache: RedisCache = request.app.state.cache
        await cache._redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"

    try:
        sf = request.app.state.session_factory
        async with sf() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "error"

    try:
        queue: RabbitMQPublisher = request.app.state.queue
        checks["rabbitmq"] = "ok" if (queue._connection and not queue._connection.is_closed) else "error"
    except Exception:
        checks["rabbitmq"] = "error"

    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if all_ok else "degraded", "checks": checks},
        status_code=200 if all_ok else 503,
    )

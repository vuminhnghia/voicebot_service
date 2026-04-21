import asyncio
import json

import aio_pika
import aio_pika.abc
import structlog

from app.application.use_cases.text_pipeline import TextPipelineUseCase
from app.application.use_cases.voice_pipeline import VoicePipelineUseCase
from app.config import get_settings
from app.infrastructure.adapters.postgres_task_repo import PostgresTaskRepo
from app.infrastructure.adapters.rabbitmq_publisher import (
    DLQ_NAME,
    QUEUE_NAME,
    RabbitMQPublisher,
)
from app.infrastructure.adapters.redis_cache import RedisCache
from app.infrastructure.adapters.seaweedfs import SeaweedFSAdapter
from app.infrastructure.adapters.triton_asr import TritonASRAdapter
from app.infrastructure.adapters.triton_llm import TritonLLMAdapter
from app.infrastructure.adapters.triton_tts import TritonTTSAdapter
from app.infrastructure.db.session import make_session_factory
from app.logging_config import setup_logging

logger = structlog.get_logger(__name__)

MAX_RETRIES = 2


async def process_message(
    msg: aio_pika.IncomingMessage,
    channel: aio_pika.abc.AbstractChannel,
    voice_uc: VoicePipelineUseCase,
    text_uc: TextPipelineUseCase,
) -> None:
    body = json.loads(msg.body)
    task_id = body["task_id"]
    task_type = body["task_type"]
    headers = dict(msg.headers or {})
    retry_count = int(headers.get("x-retry-count", 0))

    log = logger.bind(task_id=task_id, task_type=task_type, retry=retry_count)

    try:
        if task_type == "voice":
            await voice_uc.execute(task_id)
        elif task_type == "text":
            await text_uc.execute(task_id)
        else:
            log.error("unknown_task_type")
        await msg.ack()

    except Exception as exc:
        log.error("message_processing_failed", error=str(exc), attempt=retry_count + 1)
        if retry_count < MAX_RETRIES:
            await channel.default_exchange.publish(
                aio_pika.Message(
                    body=msg.body,
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    headers={**headers, "x-retry-count": retry_count + 1},
                ),
                routing_key=QUEUE_NAME,
            )
            await msg.ack()
            log.info("task_requeued", retry=retry_count + 1, max_retries=MAX_RETRIES)
        else:
            await msg.nack(requeue=False)
            log.error("task_sent_to_dlq", max_retries=MAX_RETRIES)


async def main() -> None:
    setup_logging()
    settings = get_settings()

    session_factory = make_session_factory(settings.postgres_url)
    task_repo = PostgresTaskRepo(session_factory)

    storage = SeaweedFSAdapter(
        settings.seaweedfs_endpoint,
        settings.seaweedfs_bucket,
        settings.seaweedfs_access_key,
        settings.seaweedfs_secret_key,
    )
    await storage.ensure_bucket()

    cache = RedisCache(settings.redis_url)
    publisher = RabbitMQPublisher(settings.rabbitmq_url)
    await publisher.connect()

    asr = TritonASRAdapter(settings.triton_url)
    llm = TritonLLMAdapter(settings.triton_url, settings.system_prompt, settings.max_tokens)
    tts = TritonTTSAdapter(settings.triton_url)

    voice_uc = VoicePipelineUseCase(task_repo, storage, publisher, cache, asr=asr, llm=llm, tts=tts)
    text_uc = TextPipelineUseCase(task_repo, storage, publisher, cache, llm=llm)

    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=1)

        await channel.declare_queue(DLQ_NAME, durable=True)
        queue = await channel.declare_queue(
            QUEUE_NAME,
            durable=True,
            arguments={
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": DLQ_NAME,
            },
        )

        async def on_message(msg: aio_pika.IncomingMessage) -> None:
            try:
                await process_message(msg, channel, voice_uc, text_uc)
            except Exception:
                logger.exception("unhandled_error_in_handler")
                await msg.nack(requeue=False)

        await queue.consume(on_message)
        logger.info("worker_started", queue=QUEUE_NAME, prefetch=1, max_retries=MAX_RETRIES)

        try:
            await asyncio.Future()
        finally:
            await asr.aclose()
            await llm.aclose()
            await tts.aclose()
            await storage.aclose()
            await cache.aclose()
            await publisher.aclose()
            logger.info("worker_shutdown")


if __name__ == "__main__":
    asyncio.run(main())

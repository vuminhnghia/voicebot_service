import json

import aio_pika
import aio_pika.abc

from app.domain.ports.message_queue import MessageQueuePort

QUEUE_NAME = "voicebot.tasks"
DLQ_NAME = "voicebot.tasks.dlq"


class RabbitMQPublisher(MessageQueuePort):
    def __init__(self, rabbitmq_url: str) -> None:
        self._url = rabbitmq_url
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractRobustChannel | None = None

    async def connect(self) -> None:
        self._connection = await aio_pika.connect_robust(self._url)
        self._channel = await self._connection.channel()
        await self._channel.declare_queue(DLQ_NAME, durable=True)
        await self._channel.declare_queue(
            QUEUE_NAME,
            durable=True,
            arguments={
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": DLQ_NAME,
            },
        )

    async def publish(self, task_id: str, task_type: str) -> None:
        if self._channel is None:
            await self.connect()
        body = json.dumps({"task_id": task_id, "task_type": task_type}).encode()
        await self._channel.default_exchange.publish(
            aio_pika.Message(
                body=body,
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=QUEUE_NAME,
        )

    async def aclose(self) -> None:
        if self._connection:
            await self._connection.close()

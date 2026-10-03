"""RabbitMQ publisher for the gateway."""

import json

import pika

from app.core.config import settings


class JobPublisher:
    def __init__(self, url: str = settings.rabbitmq_url):
        self._url = url
        self._channel = None
        self._conn = None

    def _ensure(self):
        if self._conn is None or self._conn.is_closed:
            self._conn = pika.BlockingConnection(pika.URLParameters(self._url))
            self._channel = self._conn.channel()
            self._channel.queue_declare(queue=settings.job_queue, durable=True)

    def publish(self, job: dict) -> None:
        self._ensure()
        self._channel.basic_publish(
            exchange="",
            routing_key=settings.job_queue,
            body=json.dumps(job),
            properties=pika.BasicProperties(delivery_mode=2),  # persistent
        )

    def close(self) -> None:
        if self._conn and not self._conn.is_closed:
            self._conn.close()
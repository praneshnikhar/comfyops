"""RabbitMQ publisher for the gateway, with reconnect-on-failure.

RabbitMQ can drop connections (restarts, deploys, network blips); the
publisher must recover instead of failing the request. Retries with
backoff and raises only after MAX_RETRIES.
"""

import json
import time

import pika

from app.core.config import settings

MAX_RETRIES = 5
BACKOFF_SECONDS = 1.0


class JobPublisher:
    def __init__(self, url: str = settings.rabbitmq_url):
        self._url = url
        self._channel = None
        self._conn = None

    def _connect(self) -> None:
        self._conn = pika.BlockingConnection(pika.URLParameters(self._url))
        self._channel = self._conn.channel()
        self._channel.queue_declare(queue=settings.job_queue, durable=True)

    def _ensure(self) -> None:
        if self._conn is None or self._conn.is_closed or not self._channel or self._channel.is_closed:
            self._connect()

    def publish(self, job: dict) -> None:
        for attempt in range(MAX_RETRIES):
            try:
                self._ensure()
                self._channel.basic_publish(
                    exchange="",
                    routing_key=settings.job_queue,
                    body=json.dumps(job),
                    properties=pika.BasicProperties(delivery_mode=2),  # persistent
                )
                return
            except (pika.exceptions.AMQPError, pika.exceptions.StreamLostError, OSError) as e:
                self._close()
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(BACKOFF_SECONDS * (2**attempt))

    def _close(self) -> None:
        try:
            if self._conn and not self._conn.is_closed:
                self._conn.close()
        except Exception:
            pass
        self._conn = None
        self._channel = None

    def close(self) -> None:
        self._close()
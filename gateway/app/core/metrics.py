"""Prometheus metrics for the gateway (M2 observability).

Exported on GET /metrics (see routes.py). Queue depth is polled from the
RabbitMQ management API by a background thread started in main.py.
"""

import json
import logging
import threading
import time
import urllib.request

from prometheus_client import Counter, Gauge, Histogram

from app.core.config import settings

log = logging.getLogger("comfyops-gateway.metrics")

JOBS_TOTAL = Counter(
    "comfyops_jobs_total",
    "Jobs accepted by the gateway, by status.",
    ["status"],
)
JOB_LATENCY = Histogram(
    "comfyops_job_latency_seconds",
    "Wall time from job creation to completion.",
    buckets=(10, 30, 60, 120, 240, 480, 900, 1800, 3600),
)
GENERATION_TIME = Histogram(
    "comfyops_generation_time_seconds",
    "ComfyUI generation time reported by the worker.",
    buckets=(10, 30, 60, 120, 240, 480, 900, 1800, 3600),
)
QUEUE_DEPTH = Gauge(
    "comfyops_rabbitmq_queue_depth",
    "Messages currently in the generation job queue (RabbitMQ).",
)
QUEUE_DEPTH.set(-1)


def record_job(status: str) -> None:
    JOBS_TOTAL.labels(status=status).inc()


def record_completion(created_at: float, generation_time: float | None) -> None:
    JOB_LATENCY.observe(time.time() - created_at)
    if generation_time is not None:
        GENERATION_TIME.observe(generation_time)


def _fetch_queue_depth() -> float | None:
    req = urllib.request.Request(_mgmt_url(f"api/queues/%2F/{settings.job_queue}"), headers=_mgmt_headers())
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())
    return float(data["messages"])


def _mgmt_url(path: str) -> str:
    """Python 3.14 urllib rejects userinfo-in-URL; strip it (auth goes in headers)."""
    parsed = urllib.parse.urlsplit(settings.rabbitmq_mgmt_url)
    netloc = parsed.hostname if parsed.port is None else f"{parsed.hostname}:{parsed.port}"
    return urllib.parse.urlunsplit((parsed.scheme, netloc, f"/{path}", "", ""))


def _mgmt_headers() -> dict[str, str]:
    parsed = urllib.parse.urlsplit(settings.rabbitmq_mgmt_url)
    token = f"{parsed.username}:{parsed.password}".encode()
    import base64

    return {"Authorization": "Basic " + base64.b64encode(token).decode()}


def poll_queue_depth(interval: float = 5.0) -> None:
    """Background loop: keep QUEUE_DEPTH fresh without scraping API per request."""
    while True:
        try:
            QUEUE_DEPTH.set(_fetch_queue_depth())
        except Exception:
            log.warning("queue depth poll failed", exc_info=True)
        time.sleep(interval)


def start_poller(interval: float = 5.0) -> threading.Thread:
    t = threading.Thread(target=poll_queue_depth, args=(interval,), daemon=True)
    t.start()
    return t
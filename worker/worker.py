"""ComfyOps Mac worker agent.

Runs natively on macOS next to ComfyUI (MPS). Pulls jobs from the Asus
control plane (RabbitMQ), runs the workflow in ComfyUI, uploads the
result to S3 (SeaweedFS). Push-based from the Asus perspective; pull-based from
the Mac (no inbound ports needed).

M1 flow:
  gateway -> RabbitMQ job -> worker -> ComfyUI -> image bytes
  worker uploads to S3 (SeaweedFS) -> gateway serves result URL

Dev mode: RABBITMQ_URL/MINIO_ENDPOINT point at localhost Docker services
on the Mac. Prod: point them at the Asus k3s cluster.
"""

import json
import logging
import os
import time

import pika
import requests
from minio import Minio
from prometheus_client import Counter, Histogram, start_http_server

from comfy_client import ComfyClient
from workflow_builder import txt2img

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("comfyops-worker")

JOBS_TOTAL = Counter("comfyops_worker_jobs_total", "Jobs processed by the worker.", ["status"])
GENERATION_TIME = Histogram(
    "comfyops_worker_generation_seconds",
    "ComfyUI generation time per job (wall time of client.generate).",
    buckets=(10, 30, 60, 120, 240, 480, 900, 1800, 3600),
)

RABBITMQ_URL = os.getenv("COMFYOPS_RABBITMQ", "127.0.0.1")
MINIO_ENDPOINT = os.getenv("COMFYOPS_MINIO", "127.0.0.1:9000")
MINIO_ACCESS = os.getenv("COMFYOPS_MINIO_ACCESS", "comfyops")
MINIO_SECRET = os.getenv("COMFYOPS_MINIO_SECRET", "comfyops")
BUCKET = os.getenv("COMFYOPS_BUCKET", "comfyops-images")
JOB_QUEUE = os.getenv("COMFYOPS_JOB_QUEUE", "generation-jobs")
GATEWAY_URL = os.getenv("COMFYOPS_GATEWAY", "http://127.0.0.1:8000")


def run_job(client: ComfyClient, job: dict) -> tuple[list[str], float]:
    """Generate images for a job, upload them, return (object keys, generation_time)."""
    workflow = job.get("workflow_json")
    if not workflow:
        workflow = txt2img(prompt=job["prompt"], seed=job.get("seed") or 0)
    started = time.monotonic()
    payloads = client.generate(workflow)
    generation_time = time.monotonic() - started
    GENERATION_TIME.observe(generation_time)
    keys = []
    for i, data in enumerate(payloads):
        key = f"{job['id']}/{i}.png"
        size = len(data)
        obj = minio_client.put_object(
            BUCKET, key, __import__("io").BytesIO(data), size, "image/png"
        )
        keys.append(obj.object_name)
        log.info("job %s image %d uploaded (%d bytes)", job["id"], i, size)
    return keys, generation_time


def complete_job(job: dict, keys: list[str], generation_time: float) -> None:
    """Tell the gateway the job is done (worker -> gateway HTTP)."""
    image_url = GATEWAY_URL.rstrip("/") + f"/images/{job['id']}/{keys[0].split('/')[-1]}"
    try:
        requests.post(
            GATEWAY_URL.rstrip("/") + f"/jobs/{job['id']}/complete",
            json={"image_url": image_url, "generation_time": generation_time},
            timeout=10,
        ).raise_for_status()
        log.info("job %s completed via gateway", job["id"])
    except Exception:
        log.exception("job %s: could not notify gateway (image is in S3 anyway)", job["id"])


minio_client = Minio(MINIO_ENDPOINT, MINIO_ACCESS, MINIO_SECRET, secure=False)


def main() -> None:
    start_http_server(int(os.getenv("COMFYOPS_WORKER_METRICS_PORT", "9100")))
    log.info("prometheus metrics on :9100")

    if not minio_client.bucket_exists(BUCKET):
        minio_client.make_bucket(BUCKET)
        log.info("created bucket %s", BUCKET)

    connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_URL))
    channel = connection.channel()
    channel.queue_declare(queue=JOB_QUEUE, durable=True)
    client = ComfyClient()

    def on_job(ch, method, properties, body):
        job = json.loads(body)
        log.info("job %s: workflow=%s prompt=%r", job["id"], job.get("workflow_id"), job.get("prompt", "")[:60])
        try:
            keys, generation_time = run_job(client, job)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            JOBS_TOTAL.labels(status="done").inc()
            complete_job(job, keys, generation_time)
            log.info("job %s done: %s", job["id"], keys)
        except Exception:
            log.exception("job %s failed", job["id"])
            JOBS_TOTAL.labels(status="failed").inc()
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=JOB_QUEUE, on_message_callback=on_job)
    log.info("worker listening on %s (comfy=%s)", JOB_QUEUE, client.base_url)
    channel.start_consuming()


if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception:
            log.exception("worker crashed, restarting in 5s")
            time.sleep(5)
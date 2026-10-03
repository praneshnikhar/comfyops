# ComfyOps Mac worker agent
# Runs natively on macOS next to ComfyUI (MPS). Pulls jobs from the
# Asus control plane (RabbitMQ), runs the workflow in ComfyUI, uploads
# the result to MinIO. Push-based from the Asus perspective; pull-based
# from the Mac (no inbound ports needed).

import json
import logging
import time

import pika
from minio import Minio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("comfyops-worker")

COMFYUI_URL = "http://127.0.0.1:8188"          # local ComfyUI server
RABBITMQ_URL = "192.168.1.50"                  # Asus control plane
MINIO_ENDPOINT = "192.168.1.50:9000"
MINIO_ACCESS = "comfyops"
MINIO_SECRET = "comfyops"
JOB_QUEUE = "generation-jobs"


def comfyui_generate(workflow_json: dict) -> list[str]:
    """Submit a workflow to the local ComfyUI server, wait, return image paths."""
    raise NotImplementedError("M1: implement /prompt submit + websocket wait")


def main() -> None:
    minio = Minio(MINIO_ENDPOINT, MINIO_ACCESS, MINIO_SECRET, secure=False)
    connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_URL))
    channel = connection.channel()
    channel.queue_declare(queue=JOB_QUEUE, durable=True)

    def on_job(ch, method, properties, body):
        job = json.loads(body)
        log.info("job %s: workflow=%s prompt=%r", job["id"], job["workflow_id"], job["prompt"][:60])
        try:
            images = comfyui_generate(job["workflow_json"])
            for path in images:
                minio.fput_object("comfyops-images", f"{job['id']}/{path}", path)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            log.info("job %s done", job["id"])
        except Exception:
            log.exception("job %s failed", job["id"])
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=JOB_QUEUE, on_message_callback=on_job)
    log.info("worker listening on %s", JOB_QUEUE)
    channel.start_consuming()


if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception:
            log.exception("worker crashed, restarting in 5s")
            time.sleep(5)
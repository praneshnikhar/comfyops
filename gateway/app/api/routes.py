import io
import time

from fastapi import APIRouter, HTTPException, Response
from minio import Minio
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.core import jobs, metrics, promotion, registry
from app.core.config import settings
from app.core.rabbit import JobPublisher
from app.models.schemas import GenerateRequest, GenerateResponse, JobStatusResponse

router = APIRouter()
publisher = JobPublisher()

_s3 = Minio(
    settings.minio_endpoint,
    settings.minio_access_key,
    settings.minio_secret_key,
    secure=False,
)


@router.get("/images/{job_id}/{filename}")
def get_image(job_id: str, filename: str):
    """Stream a generated image from object storage (auth handled here)."""
    key = f"{job_id}/{filename}"
    try:
        resp = _s3.get_object(settings.minio_bucket, key)
    except Exception:
        raise HTTPException(404, "image not found")
    return Response(content=resp.read(), media_type="image/png")


@router.get("/health")
def health():
    return {"status": "ok", "service": "comfyops-gateway"}


@router.get("/metrics")
def metrics_endpoint():
    """Prometheus scrape target."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/workflows")
def list_workflows():
    return [{"name": m["name"], "version": m["version"], "valid": m["valid"],
             "errors": m["errors"], "versions": m["versions"]}
            for m in registry.load_registry().values()]


@router.get("/workflows/{name}")
def get_workflow(name: str):
    reg = registry.load_registry()
    if name not in reg:
        raise HTTPException(404, "workflow not found")
    return reg[name]


@router.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    """Resolve workflow (promoted/champion or canary), inject prompt/seed, enqueue.

    M5: semantic cache lookup happens before this (cache.py).
    """
    reg = registry.load_registry()
    if req.workflow_id not in reg:
        raise HTTPException(404, f"unknown workflow '{req.workflow_id}'")
    try:
        version, canary_version = promotion.resolve_version(
            req.workflow_id, req.version, reg[req.workflow_id]["version"]
        )
        workflow_json, version = registry.resolve(req.workflow_id, version)
        workflow_json = registry.instantiate(workflow_json, req.prompt, req.seed or 0)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    if canary_version:
        metrics.CANARY_REQUESTS.labels(workflow=req.workflow_id, version=version).inc()
    job = jobs.create_job(
        workflow_id=f"{req.workflow_id}@{version}", prompt=req.prompt, seed=req.seed
    )
    publisher.publish(
        {
            "id": job["id"],
            "workflow_id": job["workflow_id"],
            "prompt": job["prompt"],
            "seed": job["seed"],
            "workflow_json": workflow_json,
        }
    )
    metrics.record_job("queued")
    return GenerateResponse(job_id=job["id"], status="queued", version=version)


@router.get("/workflows/{name}/promotion")
def get_promotion(name: str):
    return promotion.get_state(name)


@router.post("/workflows/{name}/promote")
def promote(name: str, body: dict):
    """Promote a version to champion (call after the gate PASSES + manual approve)."""
    version = body.get("version")
    if not version:
        raise HTTPException(400, "version required")
    reg = registry.load_registry()
    if name not in reg or version not in reg[name]["versions"]:
        raise HTTPException(404, f"workflow '{name}' has no version {version}")
    promotion.set_promoted(name, version)
    return promotion.get_state(name)


@router.get("/workflows/{name}/canary")
def get_canary(name: str):
    return promotion.get_state(name)["canary"]


@router.post("/workflows/{name}/canary")
def set_canary(name: str, body: dict):
    """Route `weight` (0..1) of unversioned /generate traffic to a challenger."""
    version = body.get("version")
    weight = float(body.get("weight", 0.0))
    if not version:
        raise HTTPException(400, "version required")
    reg = registry.load_registry()
    if name not in reg or version not in reg[name]["versions"]:
        raise HTTPException(404, f"workflow '{name}' has no version {version}")
    promotion.set_canary(name, version, weight)
    return promotion.get_state(name)


@router.delete("/workflows/{name}/canary")
def clear_canary(name: str):
    promotion.clear_canary(name)
    return promotion.get_state(name)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def job_status(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return JobStatusResponse(**jobs.to_public(job))


@router.post("/jobs/{job_id}/complete")
def job_complete(
    job_id: str,
    image_url: str | None = None,
    generation_time: float | None = None,
    body: dict | None = None,
):
    """Called by the worker (or a webhook) when images are in object storage.

    Accepts query params (worker) or a JSON body {image_url, generation_time}.
    """
    if body is not None:
        image_url = image_url or body.get("image_url")
        generation_time = generation_time if generation_time is not None else body.get("generation_time")
    if not image_url:
        raise HTTPException(400, "image_url required")
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    jobs.mark_done(job_id, image_url, generation_time)
    metrics.record_job("done")
    metrics.record_completion(job["created_at"], generation_time)
    return {"status": "ok"}
import io
import time

from fastapi import APIRouter, HTTPException, Response
from minio import Minio

from app.core import jobs, registry
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
    """Resolve workflow, inject prompt/seed, enqueue. (M5: semantic cache here.)"""
    try:
        workflow_json, version = registry.resolve(req.workflow_id, req.version)
        workflow_json = registry.instantiate(workflow_json, req.prompt, req.seed or 0)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
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
    return GenerateResponse(job_id=job["id"], status="queued")


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def job_status(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return JobStatusResponse(**jobs.to_public(job))


@router.post("/jobs/{job_id}/complete")
def job_complete(job_id: str, image_url: str):
    """Called by the worker (or a webhook) when images are in MinIO."""
    if not jobs.get_job(job_id):
        raise HTTPException(404, "job not found")
    jobs.mark_done(job_id, image_url)
    return {"status": "ok"}
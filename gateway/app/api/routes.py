import time

from fastapi import APIRouter, HTTPException

from app.core import jobs
from app.core.rabbit import JobPublisher
from app.models.schemas import GenerateRequest, GenerateResponse, JobStatusResponse

router = APIRouter()
publisher = JobPublisher()


@router.get("/health")
def health():
    return {"status": "ok", "service": "comfyops-gateway"}


@router.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    """Enqueue a generation job. (M5: semantic cache lookup goes here.)"""
    job = jobs.create_job(workflow_id=req.workflow_id, prompt=req.prompt, seed=req.seed)
    publisher.publish(
        {
            "id": job["id"],
            "workflow_id": job["workflow_id"],
            "prompt": job["prompt"],
            "seed": job["seed"],
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
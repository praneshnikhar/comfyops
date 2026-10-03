from pydantic import BaseModel


class GenerateRequest(BaseModel):
    workflow_id: str = "txt2img-sd15"
    version: str | None = None
    prompt: str
    seed: int | None = None


class GenerateResponse(BaseModel):
    job_id: str
    status: str
    version: str | None = None


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    workflow_id: str
    prompt: str
    seed: int | None = None
    cached: bool = False
    image_url: str | None = None
    generation_time: float | None = None
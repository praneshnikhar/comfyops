from pydantic import BaseModel


class GenerateRequest(BaseModel):
    workflow_id: str = "default"
    prompt: str
    seed: int | None = None


class GenerateResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    workflow_id: str
    prompt: str
    seed: int | None = None
    cached: bool = False
    image_url: str | None = None
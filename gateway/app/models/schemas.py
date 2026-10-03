from pydantic import BaseModel


class GenerateRequest(BaseModel):
    workflow_id: str
    prompt: str
    seed: int | None = None


class GenerateResponse(BaseModel):
    job_id: str
    status: str
    image_url: str | None = None
    cached: bool = False
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


# M1:
# POST /workflows      — register a workflow (JSON graph + model/node versions)
# POST /generate       — enqueue job (workflow_id, prompt, seed) w/ cache lookup
# GET  /jobs/{id}      — job status + result URL
# GET  /results/{id}   — result metadata (metrics, cache info)
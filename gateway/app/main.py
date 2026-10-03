from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import routes
from app.core import metrics
from app.core.jobs import init_db
from app.core.promotion import init_promotion
from app.core.registry import load_registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_promotion()
    registry = load_registry()
    invalid = [k for k, v in registry.items() if not v["valid"]]
    if invalid:
        raise RuntimeError(f"invalid workflows in registry: {invalid}")
    metrics.start_poller()
    yield
    routes.publisher.close()


app = FastAPI(title="ComfyOps", version="0.2.0", lifespan=lifespan)
app.include_router(routes.router)
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import routes
from app.core.jobs import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    routes.publisher.close()


app = FastAPI(title="ComfyOps", version="0.1.0", lifespan=lifespan)
app.include_router(routes.router)
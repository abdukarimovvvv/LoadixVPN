from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.logging import setup_logging
from app.db.seed import seed_plans
from app.db.session import AsyncSessionLocal
import app.models  # noqa: F401  ensure models register with Base.metadata
from app.services.scheduler import start_scheduler, stop_scheduler

setup_logging()
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with AsyncSessionLocal() as db:
        await seed_plans(db)
    start_scheduler()
    log.info("LOADIX VPN backend started")
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(title="LOADIX VPN Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_router)

from __future__ import annotations

from fastapi import APIRouter


router = APIRouter()


@router.get("/bot/health")
async def bot_webhook_health() -> dict[str, str]:
    return {"status": "polling-mode"}

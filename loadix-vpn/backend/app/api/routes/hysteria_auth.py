from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.device import Device

log = logging.getLogger(__name__)

router = APIRouter(prefix="/hysteria")


class HysteriaAuthIn(BaseModel):
    addr: str
    auth: str
    tx: int = 0


class HysteriaAuthOut(BaseModel):
    ok: bool
    id: str = ""


@router.post("/auth", response_model=HysteriaAuthOut)
async def hysteria_auth(payload: HysteriaAuthIn) -> HysteriaAuthOut:
    """Called by the standalone Hysteria2 server (auth.type: http) on every
    new connection. `payload.auth` is the password the client presented —
    we treat it as the device's raw_config password field. Not protected by
    X-Internal-Token since Hysteria2 can't send custom headers; this endpoint
    only ever reveals whether a password matches an enabled device, nothing
    else, so the exposure is equivalent to the password itself leaking.
    """
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(Device).where(Device.protocol == "hysteria2", Device.hysteria_password == payload.auth)
        )
        dev = res.scalar_one_or_none()
        if not dev:
            return HysteriaAuthOut(ok=False)
        return HysteriaAuthOut(ok=True, id=dev.xui_email or str(dev.id))

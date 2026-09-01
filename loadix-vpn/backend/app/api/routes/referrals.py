from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_internal_token
from app.db.session import get_db
from app.services.referral_service import get_referral_stats, record_referral

log = logging.getLogger(__name__)
router = APIRouter(prefix="/referrals", dependencies=[Depends(require_internal_token)])


class RecordReferralIn(BaseModel):
    referrer_telegram_id: int
    referee_telegram_id: int
    referee_username: str | None = None


@router.post("/record")
async def referrals_record(payload: RecordReferralIn, db: AsyncSession = Depends(get_db)) -> dict:
    if payload.referrer_telegram_id == payload.referee_telegram_id:
        return {"ok": False, "reason": "self_referral"}
    ref = await record_referral(
        db,
        referrer_telegram_id=payload.referrer_telegram_id,
        referee_telegram_id=payload.referee_telegram_id,
        referee_username=payload.referee_username,
    )
    if not ref:
        await db.commit()  # in case referee was created
        return {"ok": False, "reason": "already_linked_or_invalid"}
    await db.commit()
    return {"ok": True, "referral_id": str(ref.id)}


@router.get("/stats/{telegram_id}")
async def referrals_stats(telegram_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    stats = await get_referral_stats(db, telegram_id=telegram_id)
    return stats

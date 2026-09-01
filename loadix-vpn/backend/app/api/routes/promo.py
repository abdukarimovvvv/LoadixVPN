from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_telegram_id, require_internal_token
from app.db.session import get_db
from app.services.promo_service import (
    admin_create_promo,
    admin_list_promos,
    admin_set_active,
    validate_promo,
)
from app.services.subscription_service import get_or_create_user

log = logging.getLogger(__name__)
router = APIRouter()


# ── User-facing: validate promo before payment ──────────────────


class PromoValidateIn(BaseModel):
    code: str
    telegram_id: int


@router.post("/promo/validate", dependencies=[Depends(require_internal_token)])
async def promo_validate(payload: PromoValidateIn, db: AsyncSession = Depends(get_db)) -> dict:
    user = await get_or_create_user(db, payload.telegram_id, None)
    await db.flush()
    result = await validate_promo(db, code=payload.code, user_id=user.id)
    return result


# ── Admin: CRUD ──────────────────────────────────────────────────


class PromoCreateIn(BaseModel):
    code: str
    bonus_days: int
    max_uses: int | None = None
    valid_until: datetime | None = None


@router.post("/admin/promo/create", dependencies=[Depends(require_admin_telegram_id)])
async def admin_promo_create(payload: PromoCreateIn, db: AsyncSession = Depends(get_db)) -> dict:
    if payload.bonus_days <= 0:
        raise HTTPException(status_code=400, detail="bonus_days must be positive")
    if payload.max_uses is not None and payload.max_uses <= 0:
        raise HTTPException(status_code=400, detail="max_uses must be positive or null")
    try:
        promo = await admin_create_promo(
            db,
            code=payload.code,
            bonus_days=payload.bonus_days,
            max_uses=payload.max_uses,
            valid_until=payload.valid_until,
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")
    return {
        "id": str(promo.id),
        "code": promo.code,
        "bonus_days": promo.bonus_days,
        "max_uses": promo.max_uses,
        "valid_until": promo.valid_until.isoformat() if promo.valid_until else None,
    }


@router.get("/admin/promo/list", dependencies=[Depends(require_admin_telegram_id)])
async def admin_promo_list(db: AsyncSession = Depends(get_db)) -> list[dict]:
    promos = await admin_list_promos(db)
    now = datetime.now(timezone.utc)
    out = []
    for p in promos:
        expired = bool(p.valid_until and p.valid_until <= now)
        out.append({
            "id": str(p.id),
            "code": p.code,
            "bonus_days": p.bonus_days,
            "max_uses": p.max_uses,
            "used_count": p.used_count,
            "valid_until": p.valid_until.isoformat() if p.valid_until else None,
            "is_active": p.is_active,
            "expired": expired,
            "created_at": p.created_at.isoformat(),
        })
    return out


class PromoToggleIn(BaseModel):
    code: str
    active: bool


@router.post("/admin/promo/toggle", dependencies=[Depends(require_admin_telegram_id)])
async def admin_promo_toggle(payload: PromoToggleIn, db: AsyncSession = Depends(get_db)) -> dict:
    ok = await admin_set_active(db, code=payload.code, active=payload.active)
    if not ok:
        raise HTTPException(status_code=404, detail="promo not found")
    await db.commit()
    return {"ok": True}

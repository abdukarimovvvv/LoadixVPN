from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.promo import PromoCode, PromoRedemption
from app.models.subscription import Subscription
from app.models.user import User

log = logging.getLogger(__name__)


def _norm(code: str) -> str:
    return (code or "").strip().upper()


async def get_promo(db: AsyncSession, code: str) -> PromoCode | None:
    res = await db.execute(select(PromoCode).where(PromoCode.code == _norm(code)))
    return res.scalar_one_or_none()


async def validate_promo(db: AsyncSession, *, code: str, user_id) -> dict:
    """Returns {valid, reason, bonus_days, code}. user_id is internal users.id (UUID)."""
    promo = await get_promo(db, code)
    if not promo:
        return {"valid": False, "reason": "not_found"}
    if not promo.is_active:
        return {"valid": False, "reason": "inactive"}
    if promo.valid_until and promo.valid_until <= datetime.now(timezone.utc):
        return {"valid": False, "reason": "expired"}
    if promo.max_uses is not None and promo.used_count >= promo.max_uses:
        return {"valid": False, "reason": "max_uses_reached"}

    # Already redeemed by this user?
    res = await db.execute(
        select(PromoRedemption.id).where(
            PromoRedemption.promo_code_id == promo.id,
            PromoRedemption.user_id == user_id,
        )
    )
    if res.scalar_one_or_none():
        return {"valid": False, "reason": "already_used"}

    return {
        "valid": True,
        "bonus_days": promo.bonus_days,
        "code": promo.code,
    }


async def apply_promo_to_subscription(
    db: AsyncSession, *, code: str, user: User, subscription: Subscription, payment_id
) -> int:
    """Apply promo to a freshly-created/renewed subscription. Returns bonus_days applied (0 if invalid).
    Caller commits.
    """
    promo = await get_promo(db, code)
    if not promo:
        return 0
    check = await validate_promo(db, code=code, user_id=user.id)
    if not check.get("valid"):
        log.info("promo %s not applied for user %s: %s", code, user.telegram_id, check.get("reason"))
        return 0

    # Apply bonus
    subscription.expire_date = subscription.expire_date + timedelta(days=promo.bonus_days)
    promo.used_count += 1

    redemption = PromoRedemption(
        promo_code_id=promo.id,
        user_id=user.id,
        payment_id=payment_id,
        bonus_days_applied=promo.bonus_days,
    )
    db.add(redemption)
    await db.flush()
    log.info("promo %s applied for user %s: +%dd", code, user.telegram_id, promo.bonus_days)
    return promo.bonus_days


# ── Admin CRUD ──────────────────────────────────────────────────

async def admin_create_promo(
    db: AsyncSession, *,
    code: str, bonus_days: int, max_uses: int | None, valid_until: datetime | None,
    created_by_user_id=None,
) -> PromoCode:
    promo = PromoCode(
        code=_norm(code),
        bonus_days=bonus_days,
        max_uses=max_uses,
        valid_until=valid_until,
        is_active=True,
        created_by=created_by_user_id,
    )
    db.add(promo)
    await db.flush()
    return promo


async def admin_list_promos(db: AsyncSession, *, only_active: bool = False) -> list[PromoCode]:
    q = select(PromoCode).order_by(PromoCode.created_at.desc())
    if only_active:
        q = q.where(PromoCode.is_active.is_(True))
    res = await db.execute(q)
    return list(res.scalars().all())


async def admin_set_active(db: AsyncSession, *, code: str, active: bool) -> bool:
    promo = await get_promo(db, code)
    if not promo:
        return False
    promo.is_active = active
    await db.flush()
    return True

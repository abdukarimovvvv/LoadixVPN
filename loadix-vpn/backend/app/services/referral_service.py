from __future__ import annotations

import logging
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SubscriptionStatus
from app.models.payment import Payment
from app.models.referral import Referral
from app.models.subscription import Subscription
from app.models.user import User

log = logging.getLogger(__name__)

REFERRAL_BONUS_DAYS = 7


async def get_user_by_telegram(db: AsyncSession, telegram_id: int) -> User | None:
    res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    return res.scalar_one_or_none()


async def record_referral(
    db: AsyncSession, *, referrer_telegram_id: int, referee_telegram_id: int, referee_username: str | None
) -> Referral | None:
    """Called when a NEW user clicks ref-link. Creates referral if eligible."""
    if referrer_telegram_id == referee_telegram_id:
        return None  # self-referral

    referrer = await get_user_by_telegram(db, referrer_telegram_id)
    if not referrer:
        log.info("referrer %s not found, skipping", referrer_telegram_id)
        return None

    # Get or create referee
    referee = await get_user_by_telegram(db, referee_telegram_id)
    if referee:
        # Check whether referee already has a referral entry (one referrer per user, forever)
        existing = await db.execute(
            select(Referral).where(Referral.referee_id == referee.id)
        )
        if existing.scalar_one_or_none():
            return None  # already linked to someone
    else:
        referee = User(telegram_id=referee_telegram_id, username=referee_username)
        db.add(referee)
        await db.flush()

    ref = Referral(referrer_id=referrer.id, referee_id=referee.id)
    db.add(ref)
    await db.flush()
    return ref


async def try_grant_bonus_for_payment(db: AsyncSession, *, payment: Payment) -> bool:
    """Called after a successful PAID purchase by a user (the referee).
    Locks the referral to this payment; bonus_days_granted is set. If referrer has
    an active sub — extend its expiry now. Else mark as pending (bonus_granted_at=NULL),
    will be auto-applied next time referrer purchases (see apply_pending_bonuses_for_user).
    """
    res = await db.execute(
        select(Referral).where(
            Referral.referee_id == payment.user_id,
            Referral.first_payment_id.is_(None),
        )
    )
    ref = res.scalar_one_or_none()
    if not ref:
        return False

    res = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == ref.referrer_id)
        .where(Subscription.status == SubscriptionStatus.ACTIVE.value)
        .order_by(Subscription.expire_date.desc())
    )
    sub = res.scalars().first()

    now = datetime.now(timezone.utc)
    bonus = timedelta(days=REFERRAL_BONUS_DAYS)

    ref.first_payment_id = payment.id
    ref.bonus_days_granted = REFERRAL_BONUS_DAYS

    if sub:
        base = sub.expire_date if sub.expire_date > now else now
        sub.expire_date = base + bonus
        ref.bonus_granted_at = now
        log.info("referral bonus +%dd applied to active sub of referrer %s", REFERRAL_BONUS_DAYS, ref.referrer_id)
    else:
        # pending — will be applied on referrer's next purchase
        log.info("referral bonus +%dd PENDING for referrer %s (no active sub)", REFERRAL_BONUS_DAYS, ref.referrer_id)

    await db.flush()
    return True


async def apply_pending_bonuses_for_user(db: AsyncSession, *, user_id, subscription: Subscription) -> int:
    """Apply any pending referral bonuses (where this user is referrer, bonus locked but not granted yet).
    Called right after referrer themselves purchase/renew a subscription. Returns total days added.
    """
    res = await db.execute(
        select(Referral).where(
            Referral.referrer_id == user_id,
            Referral.bonus_days_granted > 0,
            Referral.bonus_granted_at.is_(None),
        )
    )
    pending = list(res.scalars().all())
    if not pending:
        return 0

    now = datetime.now(timezone.utc)
    total = 0
    for ref in pending:
        subscription.expire_date = subscription.expire_date + timedelta(days=ref.bonus_days_granted)
        ref.bonus_granted_at = now
        total += ref.bonus_days_granted
    await db.flush()
    log.info("applied %d pending referral days to user %s", total, user_id)
    return total


async def get_referral_stats(db: AsyncSession, *, telegram_id: int) -> dict:
    """Stats for ?start=ref_<telegram_id>: count of invited, count of paid, bonus days earned."""
    user = await get_user_by_telegram(db, telegram_id)
    if not user:
        return {"invited": 0, "paid": 0, "bonus_days": 0}

    invited = (
        await db.execute(select(func.count(Referral.id)).where(Referral.referrer_id == user.id))
    ).scalar_one()

    paid = (
        await db.execute(
            select(func.count(Referral.id)).where(
                Referral.referrer_id == user.id,
                Referral.first_payment_id.isnot(None),
            )
        )
    ).scalar_one()

    bonus_days_applied = (
        await db.execute(
            select(func.coalesce(func.sum(Referral.bonus_days_granted), 0)).where(
                Referral.referrer_id == user.id,
                Referral.bonus_granted_at.isnot(None),
            )
        )
    ).scalar_one()

    bonus_days_pending = (
        await db.execute(
            select(func.coalesce(func.sum(Referral.bonus_days_granted), 0)).where(
                Referral.referrer_id == user.id,
                Referral.bonus_granted_at.is_(None),
                Referral.bonus_days_granted > 0,
            )
        )
    ).scalar_one()

    return {
        "invited": int(invited),
        "paid": int(paid),
        "bonus_days": int(bonus_days_applied),
        "bonus_days_pending": int(bonus_days_pending),
        "bonus_per_friend": REFERRAL_BONUS_DAYS,
    }

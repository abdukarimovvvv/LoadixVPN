from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.enums import SubscriptionStatus
from app.models.subscription import Subscription
from app.models.user import User
from app.services.telegram import send_message
from app.services.xui_client import xui

log = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="UTC")


async def _expire_overdue() -> None:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(Subscription)
            .where(Subscription.status == SubscriptionStatus.ACTIVE.value)
            .where(Subscription.expire_date <= now)
        )
        overdue = list(res.scalars().all())
        for sub in overdue:
            for dev in sub.devices:
                if dev.protocol != "vless":
                    continue
                try:
                    await xui.disable_client(dev.client_uuid, dev.xui_email)
                except Exception as e:
                    log.warning("xui disable failed for %s: %s", dev.client_uuid, e)
            sub.status = SubscriptionStatus.EXPIRED.value
            if sub.user_id:
                user = await db.get(User, sub.user_id)
                if user:
                    await send_message(
                        user.telegram_id,
                        "Ваша подписка LOADIX VPN истекла. Используйте /renew для продления.",
                    )
        if overdue:
            await db.commit()
            log.info("expired %d subscriptions", len(overdue))


async def _notify_expiring() -> None:
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=settings.NOTIFY_BEFORE_EXPIRE_HOURS)
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(Subscription)
            .where(Subscription.status == SubscriptionStatus.ACTIVE.value)
            .where(Subscription.notified_expiring.is_(False))
            .where(Subscription.expire_date <= horizon)
            .where(Subscription.expire_date > now)
            .where(Subscription.user_id.is_not(None))
        )
        rows = list(res.scalars().all())
        for sub in rows:
            user = await db.get(User, sub.user_id)
            if not user:
                continue
            hours_left = max(0, int((sub.expire_date - now).total_seconds() // 3600))
            await send_message(
                user.telegram_id,
                f"Ваша подписка LOADIX VPN истекает через ~{hours_left} ч. "
                f"Продлите через /renew, чтобы не потерять доступ.",
            )
            sub.notified_expiring = True
        if rows:
            await db.commit()
            log.info("notified %d users about expiring subs", len(rows))


async def _check_traffic() -> None:
    if xui.stub:
        return
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(Subscription).where(Subscription.status == SubscriptionStatus.ACTIVE.value)
        )
        subs = list(res.scalars().all())
        for sub in subs:
            total_used = 0
            for dev in sub.devices:
                if dev.protocol != "vless":
                    continue  # WireGuard/OpenVPN traffic isn't tracked yet
                try:
                    used = await xui.get_client_traffic(dev.xui_email)
                    total_used += used
                except Exception as e:
                    log.warning("xui traffic check failed for %s: %s", dev.xui_email, e)
                    continue
            sub.traffic_used_bytes = total_used
            limit_bytes = sub.traffic_limit_gb * 1024 ** 3
            if limit_bytes and total_used >= limit_bytes:
                for dev in sub.devices:
                    if dev.protocol != "vless":
                        continue
                    try:
                        await xui.disable_client(dev.client_uuid, dev.xui_email)
                    except Exception:
                        pass
                sub.status = SubscriptionStatus.EXPIRED.value
                if sub.user_id:
                    user = await db.get(User, sub.user_id)
                    if user:
                        await send_message(
                            user.telegram_id,
                            "Лимит трафика исчерпан. Продлите подписку командой /renew.",
                        )
        await db.commit()


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(_expire_overdue, "interval", minutes=5, id="expire_overdue", replace_existing=True)
    scheduler.add_job(_notify_expiring, "interval", minutes=5, id="notify_expiring", replace_existing=True)
    scheduler.add_job(_check_traffic, "interval", minutes=5, id="check_traffic", replace_existing=True)
    scheduler.start()
    log.info("scheduler started")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)

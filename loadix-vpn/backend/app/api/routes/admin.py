from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_telegram_id
from app.db.session import get_db
from app.models.enums import PaymentStatus, SubscriptionStatus
from app.models.payment import Payment
from app.models.subscription import Subscription
from app.models.trial import Trial
from app.models.user import User  # noqa: F401
from app.schemas.admin import BanIn, BroadcastIn, BroadcastOut, GrantIn, StatsOut, TrafficTopItem, TrafficTopOut, UserSubscriptionItem, UserSubscriptionsPage
from app.schemas.subscription import DeviceWithQR, SubscriptionWithDevices
from app.schemas.users import UserOut
from app.services.audit import write_audit
from app.services.qr import make_qr_png_base64, make_qr_png_bytes
from app.services.subscription_service import (
    get_active_subscription,
    get_or_create_user,
    get_plan_by_code,
    provision_subscription,
    renew_subscription,
    revoke_device,
)
from app.services.telegram import send_message, send_photo_bytes

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin_telegram_id)])


@router.get("/users", response_model=list[UserOut])
async def admin_users(limit: int = 100, offset: int = 0, db: AsyncSession = Depends(get_db)) -> list[UserOut]:
    res = await db.execute(select(User).order_by(User.created_at.desc()).limit(limit).offset(offset))
    return [UserOut.model_validate(u) for u in res.scalars().all()]


@router.get("/users/subscriptions", response_model=UserSubscriptionsPage)
async def admin_users_subscriptions(
    page: int = 0, page_size: int = 10, db: AsyncSession = Depends(get_db)
) -> UserSubscriptionsPage:
    from app.models.plan import Plan

    if page < 0:
        page = 0
    if page_size < 1 or page_size > 100:
        page_size = 10

    total = (await db.execute(select(func.count(User.id)))).scalar_one()

    res = await db.execute(
        select(User)
        .order_by(User.created_at.desc())
        .limit(page_size)
        .offset(page * page_size)
    )
    users = list(res.scalars().all())

    items: list[UserSubscriptionItem] = []
    for u in users:
        res2 = await db.execute(
            select(Subscription)
            .where(Subscription.user_id == u.id)
            .order_by(
                (Subscription.status == SubscriptionStatus.ACTIVE.value).desc(),
                Subscription.start_date.desc(),
            )
            .limit(1)
        )
        sub = res2.scalar_one_or_none()
        plan_name = None
        status = None
        expire_date = None
        if sub is not None:
            status = sub.status
            expire_date = sub.expire_date.isoformat()
            plan = await db.get(Plan, sub.plan_id)
            plan_name = plan.name if plan else None
        items.append(
            UserSubscriptionItem(
                telegram_id=u.telegram_id,
                username=u.username,
                plan_name=plan_name,
                status=status,
                expire_date=expire_date,
            )
        )

    return UserSubscriptionsPage(items=items, total=int(total), page=page, page_size=page_size)


@router.get("/subscriptions/traffic-top", response_model=TrafficTopOut)
async def admin_traffic_top(db: AsyncSession = Depends(get_db)) -> TrafficTopOut:
    from app.models.plan import Plan

    res = await db.execute(
        select(Subscription)
        .where(Subscription.status == SubscriptionStatus.ACTIVE.value)
        .order_by(Subscription.traffic_used_bytes.desc())
        .limit(20)
    )
    subs = list(res.scalars().all())

    items: list[TrafficTopItem] = []
    for sub in subs:
        user = await db.get(User, sub.user_id) if sub.user_id else None
        plan = await db.get(Plan, sub.plan_id)
        items.append(
            TrafficTopItem(
                telegram_id=user.telegram_id if user else 0,
                username=user.username if user else None,
                plan_name=plan.name if plan else None,
                traffic_used_bytes=sub.traffic_used_bytes,
                traffic_limit_gb=sub.traffic_limit_gb,
            )
        )

    return TrafficTopOut(items=items)


@router.get("/users/{telegram_id}/full")
async def admin_user_card(telegram_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    """Comprehensive user info for admin lookup: profile, active sub, payments, devices."""
    from sqlalchemy.orm import selectinload
    from app.models.device import Device
    from app.models.plan import Plan

    res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="user not found")

    # All subscriptions with devices + plan
    res = await db.execute(
        select(Subscription)
        .options(selectinload(Subscription.devices))
        .where(Subscription.user_id == user.id)
        .order_by(Subscription.start_date.desc())
    )
    subs = list(res.scalars().all())

    plans_by_id: dict = {}
    for s in subs:
        if s.plan_id not in plans_by_id:
            p = await db.get(Plan, s.plan_id)
            if p:
                plans_by_id[s.plan_id] = {"code": p.code, "name": p.name}

    # Payments
    res = await db.execute(
        select(Payment).where(Payment.user_id == user.id).order_by(Payment.created_at.desc()).limit(20)
    )
    payments = list(res.scalars().all())

    # Trials count for this user (subscriptions marked is_trial=True)
    trials_count = sum(1 for s in subs if s.is_trial)

    # Active sub
    active = next((s for s in subs if s.status == SubscriptionStatus.ACTIVE.value), None)

    def _sub_dict(s: Subscription) -> dict:
        plan_info = plans_by_id.get(s.plan_id, {})
        return {
            "id": str(s.id),
            "plan_code": plan_info.get("code"),
            "plan_name": plan_info.get("name"),
            "status": s.status,
            "is_trial": s.is_trial,
            "start_date": s.start_date.isoformat(),
            "expire_date": s.expire_date.isoformat(),
            "traffic_limit_gb": s.traffic_limit_gb,
            "traffic_used_bytes": s.traffic_used_bytes,
            "device_limit": s.device_limit,
            "devices_count": len(s.devices),
            "devices": [
                {
                    "id": str(d.id),
                    "name": d.name,
                    "protocol": d.protocol,
                    "xui_email": d.xui_email,
                    "client_uuid": d.client_uuid,
                    "created_at": d.created_at.isoformat(),
                }
                for d in s.devices
            ],
        }

    return {
        "user": {
            "id": str(user.id),
            "telegram_id": user.telegram_id,
            "username": user.username,
            "role": user.role,
            "is_banned": user.is_banned,
            "created_at": user.created_at.isoformat(),
        },
        "active_subscription": _sub_dict(active) if active else None,
        "all_subscriptions": [_sub_dict(s) for s in subs],
        "payments": [
            {
                "id": str(p.id),
                "provider": p.provider,
                "amount": float(p.amount),
                "currency": p.currency,
                "status": p.status,
                "created_at": p.created_at.isoformat(),
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            }
            for p in payments
        ],
        "stats": {
            "subscriptions_count": len(subs),
            "trials_count": int(trials_count),
            "payments_count": len(payments),
            "payments_paid_count": len([p for p in payments if p.status == PaymentStatus.PAID.value]),
            "total_paid_stars": sum(float(p.amount) for p in payments if p.status == PaymentStatus.PAID.value and p.currency == "XTR"),
            "total_paid_rub": sum(float(p.amount) for p in payments if p.status == PaymentStatus.PAID.value and p.currency == "RUB"),
        },
    }


@router.post("/users/ban", response_model=UserOut)
async def admin_ban_user(
    payload: BanIn,
    db: AsyncSession = Depends(get_db),
    actor: int = Depends(require_admin_telegram_id),
) -> UserOut:
    res = await db.execute(select(User).where(User.telegram_id == payload.telegram_id))
    user = res.scalar_one_or_none()
    if not user:
        user = User(telegram_id=payload.telegram_id, is_banned=payload.ban)
        db.add(user)
        await db.flush()
    else:
        user.is_banned = payload.ban

    res = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    subs = list(res.scalars().all())
    from app.core.config import settings as _s
    from app.services.xui_client import XUIClientData, xui

    affected_devices = 0
    for sub in subs:
        for dev in sub.devices:
            if dev.protocol != "vless":
                continue
            affected_devices += 1
            try:
                if payload.ban:
                    await xui.disable_client(dev.client_uuid, dev.xui_email)
                else:
                    try:
                        await xui.add_client(
                            XUIClientData(
                                client_uuid=dev.client_uuid,
                                email=dev.xui_email,
                                total_gb=sub.traffic_limit_gb,
                                expire_ts_ms=int(sub.expire_date.timestamp() * 1000),
                                limit_ip=sub.device_limit,
                                flow=_s.REALITY_FLOW,
                            )
                        )
                    except Exception as e:
                        log.warning("re-add client failed for %s: %s", dev.client_uuid, e)
            except Exception as e:
                log.warning("xui ban/unban op failed for %s: %s", dev.client_uuid, e)
        if payload.ban and sub.status == SubscriptionStatus.ACTIVE.value:
            sub.status = SubscriptionStatus.DISABLED.value
        elif not payload.ban and sub.status == SubscriptionStatus.DISABLED.value:
            sub.status = SubscriptionStatus.ACTIVE.value

    await write_audit(
        db,
        actor_telegram_id=actor,
        action="ban" if payload.ban else "unban",
        target=str(payload.telegram_id),
        meta={"affected_subs": len(subs), "affected_devices": affected_devices},
    )
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.get("/stats", response_model=StatsOut)
async def admin_stats(db: AsyncSession = Depends(get_db)) -> StatsOut:
    users_total = (await db.execute(select(func.count(User.id)))).scalar_one()
    users_banned = (await db.execute(select(func.count(User.id)).where(User.is_banned.is_(True)))).scalar_one()
    subs_active = (
        await db.execute(
            select(func.count(Subscription.id)).where(Subscription.status == SubscriptionStatus.ACTIVE.value)
        )
    ).scalar_one()
    subs_total = (await db.execute(select(func.count(Subscription.id)))).scalar_one()
    trials_total = (await db.execute(select(func.count(Trial.id)))).scalar_one()
    payments_paid = (
        await db.execute(select(func.count(Payment.id)).where(Payment.status == PaymentStatus.PAID.value))
    ).scalar_one()
    revenue = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.status == PaymentStatus.PAID.value)
        )
    ).scalar_one()

    return StatsOut(
        users_total=int(users_total),
        users_banned=int(users_banned),
        subscriptions_active=int(subs_active),
        subscriptions_total=int(subs_total),
        trials_total=int(trials_total),
        payments_paid=int(payments_paid),
        revenue_rub=float(Decimal(revenue or 0)),
    )


@router.post("/grant", response_model=SubscriptionWithDevices)
async def admin_grant(
    payload: GrantIn,
    db: AsyncSession = Depends(get_db),
    actor: int = Depends(require_admin_telegram_id),
) -> SubscriptionWithDevices:
    plan = await get_plan_by_code(db, payload.plan_code)
    if not plan or not plan.is_active:
        raise HTTPException(status_code=400, detail="invalid plan")

    user = await get_or_create_user(db, payload.telegram_id, payload.username)

    existing = await get_active_subscription(db, user.id)
    if existing:
        sub = await renew_subscription(db, existing, plan)
        action_kind = "grant_renew"
    else:
        # No initial device — user will choose protocol themselves in the bot
        sub = await provision_subscription(db, plan=plan, user=user, is_trial=False, create_initial_device=False)
        action_kind = "grant_new"

    await write_audit(
        db,
        actor_telegram_id=actor,
        action=action_kind,
        target=str(payload.telegram_id),
        meta={"plan_code": plan.code, "subscription_id": str(sub.id)},
    )

    await db.commit()
    await db.refresh(sub)

    await send_message(
        user.telegram_id,
        f"🎉 <b>Подписка активирована!</b>\n\n"
        f"Тариф: <b>{plan.name}</b>\n"
        f"Действует до: <b>{sub.expire_date.strftime('%Y-%m-%d %H:%M UTC')}</b>\n\n"
        f"👉 Откройте бот → <b>Мой VPN</b> → <b>Добавить устройство</b>\n"
        f"Выберите протокол и получите ключ.",
    )

    return SubscriptionWithDevices(
        id=sub.id,
        plan_id=sub.plan_id,
        status=sub.status,
        is_trial=sub.is_trial,
        start_date=sub.start_date,
        expire_date=sub.expire_date,
        traffic_limit_gb=sub.traffic_limit_gb,
        traffic_used_bytes=sub.traffic_used_bytes,
        device_limit=sub.device_limit,
        devices=[
            DeviceWithQR(
                id=d.id,
                protocol=d.protocol,
                client_uuid=d.client_uuid,
                name=d.name,
                vless_uri=d.vless_uri,
                raw_config=d.raw_config,
                created_at=d.created_at,
                qr_base64=(
                    make_qr_png_base64(d.vless_uri if d.protocol == "vless" else d.raw_config)
                    if d.protocol in ("vless", "wireguard", "hysteria2")
                    else None
                ),
            )
            for d in sub.devices
        ],
    )


@router.post("/broadcast", response_model=BroadcastOut)
async def admin_broadcast(
    payload: BroadcastIn,
    db: AsyncSession = Depends(get_db),
    actor: int = Depends(require_admin_telegram_id),
) -> BroadcastOut:
    res = await db.execute(select(User.telegram_id).where(User.is_banned.is_(False)))
    chat_ids = [int(x) for x in res.scalars().all()]

    sent = 0
    failed = 0

    async def _one(chat_id: int) -> None:
        nonlocal sent, failed
        ok = await send_message(chat_id, payload.text)
        if ok:
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(0.05)

    await asyncio.gather(*[_one(cid) for cid in chat_ids])

    await write_audit(
        db,
        actor_telegram_id=actor,
        action="broadcast",
        meta={"sent": sent, "failed": failed, "recipients": len(chat_ids)},
        note=payload.text[:500],
    )
    await db.commit()


@router.post("/users/{telegram_id}/revoke")
async def admin_revoke_subscription(
    telegram_id: int,
    db: AsyncSession = Depends(get_db),
    actor: int = Depends(require_admin_telegram_id),
) -> dict:
    """Revoke (cancel) the active subscription of a user."""
    res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="user not found")

    sub = await get_active_subscription(db, user.id)
    if not sub:
        raise HTTPException(status_code=404, detail="no active subscription")

    # Revoke all devices first
    for dev in list(sub.devices):
        try:
            await revoke_device(db, dev)
        except Exception as e:
            log.warning("revoke device %s failed: %s", dev.id, e)

    sub.status = SubscriptionStatus.DISABLED.value

    await write_audit(
        db,
        actor_telegram_id=actor,
        action="revoke_subscription",
        target=str(telegram_id),
        meta={"subscription_id": str(sub.id)},
    )
    await db.commit()

    await send_message(
        user.telegram_id,
        "⚠️ Ваша подписка была аннулирована администратором.",
    )
    return {"ok": True}

    return BroadcastOut(sent=sent, failed=failed)

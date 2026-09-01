from __future__ import annotations

import logging
import secrets
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as _s
from app.models.device import Device
from app.models.enums import SubscriptionStatus
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.services.vless import generate_vless_reality_uri
from app.services.xui_client import XUIClientData, xui

log = logging.getLogger(__name__)


async def get_or_create_user(db: AsyncSession, telegram_id: int, username: str | None = None) -> User:
    res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(telegram_id=telegram_id, username=username)
        db.add(user)
        await db.flush()
    elif username and user.username != username:
        user.username = username
        await db.flush()
    return user


async def get_active_subscription(db: AsyncSession, user_id: uuidlib.UUID) -> Subscription | None:
    """Get the most recent ACTIVE subscription (paid preferred over trial).
    Falls back to the newest subscription if none are active."""
    res = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .where(Subscription.status == SubscriptionStatus.ACTIVE.value)
        .order_by(Subscription.is_trial.asc(), Subscription.expire_date.desc())
    )
    sub = res.scalars().first()
    if sub:
        return sub
    
    # If no active subscription, return the most recent one (any status)
    res = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def get_plan_by_code(db: AsyncSession, code: str) -> Plan | None:
    res = await db.execute(select(Plan).where(Plan.code == code))
    return res.scalar_one_or_none()


def _build_email(prefix: str, telegram_id: int | None = None) -> str:
    rnd = secrets.token_hex(3)
    return f"{prefix}-{telegram_id}-{rnd}" if telegram_id else f"{prefix}-{rnd}"


async def _add_xui_client(*, client_uuid: str, email: str, total_gb: int, expire_ts_ms: int, limit_ip: int) -> None:
    await xui.add_client(
        XUIClientData(
            client_uuid=client_uuid,
            email=email,
            total_gb=total_gb,
            expire_ts_ms=expire_ts_ms,
            limit_ip=limit_ip,
            flow=_s.REALITY_FLOW,
        )
    )


async def _update_xui_client(*, client_uuid: str, email: str, total_gb: int, expire_ts_ms: int, limit_ip: int) -> None:
    await xui.update_client(
        XUIClientData(
            client_uuid=client_uuid,
            email=email,
            total_gb=total_gb,
            expire_ts_ms=expire_ts_ms,
            limit_ip=limit_ip,
            flow=_s.REALITY_FLOW,
        )
    )


def _settings_hours_fallback() -> int:
    return _s.TRIAL_DURATION_HOURS


async def _create_device(
    db: AsyncSession,
    *,
    sub: Subscription,
    name: str | None,
    user: User | None,
    email_prefix: str,
) -> Device:
    client_uuid = str(uuidlib.uuid4())
    email = _build_email(email_prefix, user.telegram_id if user else None)
    vless_uri = generate_vless_reality_uri(client_uuid, email=email)

    await _add_xui_client(
        client_uuid=client_uuid,
        email=email,
        total_gb=sub.traffic_limit_gb,
        expire_ts_ms=int(sub.expire_date.timestamp() * 1000),
        limit_ip=1,
    )

    device = Device(
        subscription_id=sub.id,
        client_uuid=client_uuid,
        xui_email=email,
        name=name,
        vless_uri=vless_uri,
    )
    db.add(device)
    await db.flush()
    return device


async def provision_subscription(
    db: AsyncSession,
    *,
    plan: Plan,
    user: User | None,
    is_trial: bool,
    create_initial_device: bool = True,
) -> Subscription:
    """Create fresh subscription. Optionally creates 1 default VLESS device. Caller commits."""
    now = datetime.now(timezone.utc)
    if plan.duration_days > 0:
        expire = now + timedelta(days=plan.duration_days)
    else:
        expire = now + timedelta(hours=_settings_hours_fallback())

    sub = Subscription(
        user_id=user.id if user else None,
        plan_id=plan.id,
        status=SubscriptionStatus.ACTIVE.value,
        is_trial=is_trial,
        start_date=now,
        expire_date=expire,
        traffic_limit_gb=plan.traffic_limit_gb,
        traffic_used_bytes=0,
        device_limit=plan.device_limit,
    )
    db.add(sub)
    await db.flush()

    if create_initial_device:
        await _create_device(
            db,
            sub=sub,
            name="Устройство 1",
            user=user,
            email_prefix="trial" if is_trial else "loadix",
        )
    return sub


async def renew_subscription(db: AsyncSession, sub: Subscription, plan: Plan) -> Subscription:
    """Extend dates / refresh limits + sync all existing devices in xui."""
    now = datetime.now(timezone.utc)
    base = sub.expire_date if sub.expire_date > now and sub.status == SubscriptionStatus.ACTIVE.value else now
    sub.expire_date = base + timedelta(days=plan.duration_days)
    sub.traffic_limit_gb = plan.traffic_limit_gb
    sub.device_limit = plan.device_limit
    sub.status = SubscriptionStatus.ACTIVE.value
    sub.notified_expiring = False

    expire_ts_ms = int(sub.expire_date.timestamp() * 1000)
    for dev in sub.devices:
        try:
            await _update_xui_client(
                client_uuid=dev.client_uuid,
                email=dev.xui_email,
                total_gb=sub.traffic_limit_gb,
                expire_ts_ms=expire_ts_ms,
                limit_ip=1,
            )
        except Exception as e:
            log.warning("renew: update_client failed for %s: %s", dev.client_uuid, e)

    await db.flush()
    return sub


async def add_device(
    db: AsyncSession,
    *,
    sub: Subscription,
    name: str | None,
    user: User | None,
) -> Device:
    if len(sub.devices) >= sub.device_limit:
        raise ValueError("device_limit_reached")
    return await _create_device(
        db,
        sub=sub,
        name=name or f"Устройство {len(sub.devices) + 1}",
        user=user,
        email_prefix="trial" if sub.is_trial else "loadix",
    )


async def revoke_device(db: AsyncSession, device: Device) -> None:
    try:
        await xui.disable_client(device.client_uuid, device.xui_email)
    except Exception as e:
        log.warning("revoke: disable_client failed: %s", e)
    try:
        await xui.delete_client(device.client_uuid)
    except Exception as e:
        log.warning("revoke: delete_client failed: %s", e)
    await db.delete(device)
    await db.flush()


async def rotate_device_key(db: AsyncSession, device: Device, sub: Subscription) -> Device:
    """Generate fresh UUID for one specific device. Old key stops working."""
    try:
        await xui.disable_client(device.client_uuid, device.xui_email)
    except Exception:
        pass
    try:
        await xui.delete_client(device.client_uuid)
    except Exception:
        pass

    new_uuid = str(uuidlib.uuid4())
    user = sub.user
    new_email = _build_email("trial" if sub.is_trial else "loadix", user.telegram_id if user else None)
    new_vless = generate_vless_reality_uri(new_uuid, email=new_email)

    await _add_xui_client(
        client_uuid=new_uuid,
        email=new_email,
        total_gb=sub.traffic_limit_gb,
        expire_ts_ms=int(sub.expire_date.timestamp() * 1000),
        limit_ip=1,
    )

    device.client_uuid = new_uuid
    device.xui_email = new_email
    device.vless_uri = new_vless
    await db.flush()
    return device


async def get_device(db: AsyncSession, device_id: uuidlib.UUID) -> Device | None:
    res = await db.execute(select(Device).where(Device.id == device_id))
    return res.scalar_one_or_none()

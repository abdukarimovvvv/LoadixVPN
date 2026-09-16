from __future__ import annotations

import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_internal_token
from app.db.session import get_db
from app.models.device import Device
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.payment import BotTrialIn
from app.schemas.subscription import (
    DeviceAddIn,
    DeviceWithQR,
    SubscriptionWithDevices,
    VpnConfigIn,
    VpnRawConfigOut,
)
from app.services.qr import make_qr_png_base64, make_qr_png_bytes
from app.services.subscription_service import (
    add_device,
    get_active_subscription,
    get_device,
    get_or_create_user,
    get_plan_by_code,
    provision_subscription,
    revoke_device,
    rotate_device_key,
)
from app.services.telegram import send_message, send_photo_bytes


router = APIRouter(dependencies=[Depends(require_internal_token)])


def _device_with_qr(d: Device) -> DeviceWithQR:
    # WireGuard configs are short enough to QR; OpenVPN's embedded certs are
    # not (exceeds the QR spec's ~2.9KB cap), so it ships as a file only.
    if d.protocol == "vless":
        qr_source = d.vless_uri
    elif d.protocol == "wireguard":
        qr_source = d.raw_config
    else:
        qr_source = None
    return DeviceWithQR(
        id=d.id,
        protocol=d.protocol,
        client_uuid=d.client_uuid,
        name=d.name,
        vless_uri=d.vless_uri,
        raw_config=d.raw_config,
        created_at=d.created_at,
        qr_base64=make_qr_png_base64(qr_source) if qr_source else None,
    )


def _sub_with_devices(sub: Subscription) -> SubscriptionWithDevices:
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
        devices=[_device_with_qr(d) for d in sub.devices],
    )


@router.post("/users/register")
async def register_user(payload: BotTrialIn, db: AsyncSession = Depends(get_db)) -> dict:
    """Called on /start — creates user record if not exists. Silent, always returns ok."""
    user = await get_or_create_user(db, payload.telegram_id, payload.username)
    await db.commit()
    return {"ok": True, "user_id": str(user.id)}


@router.get("/users/{telegram_id}/banned")
async def is_user_banned(telegram_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = res.scalar_one_or_none()
    if not user:
        return {"banned": False, "known": False}
    return {"banned": bool(user.is_banned), "known": True}


@router.post("/trial/bot", response_model=SubscriptionWithDevices)
async def claim_trial_via_bot(payload: BotTrialIn, db: AsyncSession = Depends(get_db)) -> SubscriptionWithDevices:
    user = await get_or_create_user(db, payload.telegram_id, payload.username)
    if user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user is banned")

    res = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id).where(Subscription.is_trial.is_(True))
    )
    if res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Вы уже получали бесплатный Trial.",
        )

    plan = await get_plan_by_code(db, "trial")
    if not plan or not plan.is_active:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="trial plan unavailable")

    sub = await provision_subscription(db, plan=plan, user=user, is_trial=True)
    await db.commit()
    await db.refresh(sub)

    dev = sub.devices[0]
    traffic_display = "∞" if sub.traffic_limit_gb == 0 else f"{sub.traffic_limit_gb} GB"
    await send_message(
        user.telegram_id,
        "🎁 <b>Бесплатный Trial активирован</b>\n\n"
        f"Действует до: <b>{sub.expire_date.strftime('%Y-%m-%d %H:%M UTC')}</b>\n"
        f"Лимит: <b>{traffic_display}</b>, до <b>{sub.device_limit}</b> устр.\n\n"
        f"<code>{dev.vless_uri}</code>",
    )
    try:
        await send_photo_bytes(user.telegram_id, make_qr_png_bytes(dev.vless_uri), caption="VLESS Reality QR")
    except Exception:
        pass

    return _sub_with_devices(sub)


@router.get("/subscription/{telegram_id}", response_model=SubscriptionWithDevices)
async def get_my_subscription(telegram_id: int, db: AsyncSession = Depends(get_db)) -> SubscriptionWithDevices:
    res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    sub = await get_active_subscription(db, user.id)
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no active subscription")
    return _sub_with_devices(sub)


@router.get("/subscription/{telegram_id}/last", response_model=SubscriptionWithDevices)
async def get_last_subscription(telegram_id: int, db: AsyncSession = Depends(get_db)) -> SubscriptionWithDevices:
    res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    res = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    sub = res.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no subscription")
    return _sub_with_devices(sub)


@router.post("/subscription/{telegram_id}/devices", response_model=DeviceWithQR)
async def add_subscription_device(
    telegram_id: int,
    payload: DeviceAddIn,
    db: AsyncSession = Depends(get_db),
) -> DeviceWithQR:
    res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    if user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user is banned")
    sub = await get_active_subscription(db, user.id)
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no active subscription")
    try:
        dev = await add_device(db, sub=sub, name=payload.name, user=user)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Лимит устройств тарифа: {sub.device_limit}. Удалите одно или продлите тариф.",
        )
    await db.commit()
    await db.refresh(dev)
    return _device_with_qr(dev)


@router.delete("/subscription/{telegram_id}/devices/{device_id}")
async def delete_subscription_device(
    telegram_id: int,
    device_id: uuidlib.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    sub = await get_active_subscription(db, user.id)
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no active subscription")
    dev = await get_device(db, device_id)
    if not dev or dev.subscription_id != sub.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="device not found")
    if len(sub.devices) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя удалить последнее устройство.",
        )
    await revoke_device(db, dev)
    await db.commit()
    return {"ok": True}


@router.post("/subscription/{telegram_id}/wireguard", response_model=VpnRawConfigOut)
async def get_wireguard_config(
    telegram_id: int,
    payload: VpnConfigIn,
    db: AsyncSession = Depends(get_db),
) -> VpnRawConfigOut:
    from app.services.subscription_service import add_wireguard_device

    res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    if user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user is banned")
    sub = await get_active_subscription(db, user.id)
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no active subscription")
    name = (payload.name or f"user_{telegram_id}")[:64]
    try:
        _, config = await add_wireguard_device(db, sub=sub, name=name)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="device_limit_reached")
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    await db.commit()
    return VpnRawConfigOut(config=config, protocol="wireguard", qr_base64=make_qr_png_base64(config))


@router.post("/subscription/{telegram_id}/openvpn", response_model=VpnRawConfigOut)
async def get_openvpn_config(
    telegram_id: int,
    payload: VpnConfigIn,
    db: AsyncSession = Depends(get_db),
) -> VpnRawConfigOut:
    from app.services.subscription_service import add_openvpn_device

    res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    if user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user is banned")
    sub = await get_active_subscription(db, user.id)
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no active subscription")
    name = (payload.name or f"user_{telegram_id}")[:64]
    try:
        _, config = await add_openvpn_device(db, sub=sub, name=name)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="device_limit_reached")
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    await db.commit()
    # .ovpn configs embed full certs/keys and are far too large to fit in a QR
    # code (QR spec caps out at version 40, ~2.9KB); ship the file only.
    return VpnRawConfigOut(config=config, protocol="openvpn")


@router.post("/subscription/{telegram_id}/devices/{device_id}/rotate", response_model=DeviceWithQR)
async def rotate_subscription_device(
    telegram_id: int,
    device_id: uuidlib.UUID,
    db: AsyncSession = Depends(get_db),
) -> DeviceWithQR:
    from app.services.rate_limit import rotate_key_limiter

    if not rotate_key_limiter.allow(f"rotate:{telegram_id}"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Превышен лимит смены ключа: 5 раз в сутки.",
        )

    res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    if user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user is banned")
    sub = await get_active_subscription(db, user.id)
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no active subscription")
    dev = await get_device(db, device_id)
    if not dev or dev.subscription_id != sub.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="device not found")
    dev = await rotate_device_key(db, dev, sub)
    await db.commit()
    await db.refresh(dev)
    return _device_with_qr(dev)

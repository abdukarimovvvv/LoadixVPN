from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.enums import SubscriptionStatus
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.trial import Trial
from app.schemas.plans import PlanOut
from app.schemas.trial import TrialIn, TrialOut
from app.services.qr import make_qr_png_base64
from app.services.subscription_service import get_plan_by_code, provision_subscription

log = logging.getLogger(__name__)
router = APIRouter()

_STARTED_AT = time.monotonic()


@router.get("/ping")
async def ping(db: AsyncSession = Depends(get_db)) -> dict:
    """Public health/ping endpoint. Reports server status + xray reachability + uptime."""
    t0 = time.perf_counter()

    db_ok = False
    active_subs = 0
    try:
        res = await db.execute(
            select(func.count(Subscription.id)).where(Subscription.status == SubscriptionStatus.ACTIVE.value)
        )
        active_subs = int(res.scalar_one())
        db_ok = True
    except Exception:
        pass

    # TCP-check x-ui panel via docker host gateway: confirms Xray engine is alive
    # without depending on hairpin-NAT from public domain back to ourselves.
    xray_ok = False
    xray_ms: float | None = None
    for port in (2053, 2096, 54321):
        try:
            import socket

            t_xray = time.perf_counter()
            s = socket.create_connection(("host.docker.internal", port), timeout=2)
            s.close()
            xray_ms = round((time.perf_counter() - t_xray) * 1000, 1)
            xray_ok = True
            break
        except Exception:
            continue

    uptime_seconds = int(time.monotonic() - _STARTED_AT)
    total_ms = round((time.perf_counter() - t0) * 1000, 1)

    return {
        "status": "ok" if (db_ok and xray_ok) else "degraded",
        "now": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": uptime_seconds,
        "backend_ms": total_ms,
        "db_ok": db_ok,
        "vpn_endpoint": f"{settings.DOMAIN}:{settings.REALITY_PORT}",
        "vpn_ok": xray_ok,
        "vpn_tcp_ms": xray_ms,
        "active_subscriptions": active_subs,
    }


@router.get("/plans", response_model=list[PlanOut])
async def list_plans(db: AsyncSession = Depends(get_db)) -> list[PlanOut]:
    res = await db.execute(
        select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.is_trial.desc(), Plan.duration_days)
    )
    return [PlanOut.model_validate(p) for p in res.scalars().all()]


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"


@router.post("/trial", response_model=TrialOut)
async def create_trial(
    payload: TrialIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TrialOut:
    ip = _client_ip(request)

    existing = (await db.execute(select(Trial).where(Trial.ip_address == ip))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="trial already issued for this IP")

    plan = await get_plan_by_code(db, "trial")
    if plan is None or not plan.is_active:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="trial plan not configured")

    sub = await provision_subscription(db, plan=plan, user=None, is_trial=True)

    trial_row = Trial(ip_address=ip, user_agent=payload.user_agent, subscription_id=sub.id)
    db.add(trial_row)
    await db.commit()
    await db.refresh(sub)

    primary = sub.devices[0]
    qr_b64 = make_qr_png_base64(primary.vless_uri)
    bot_url = f"https://t.me/{settings.BOT_USERNAME}" if settings.BOT_USERNAME else "https://t.me"

    return TrialOut(
        vless_uri=primary.vless_uri,
        qr_base64=qr_b64,
        expire_date=sub.expire_date,
        traffic_limit_gb=sub.traffic_limit_gb,
        bot_url=bot_url,
    )

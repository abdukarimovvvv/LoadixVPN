from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_internal_token
from app.db.session import get_db
from app.models.enums import PaymentStatus
from app.models.payment import Payment
from app.models.plan import Plan
from app.models.user import User
from app.schemas.payment import InvoiceCreateIn, InvoiceOut, TelegramPaidIn, TelegramStarsPaidIn
from app.services.cryptobot import create_invoice, verify_webhook_signature
from app.services.promo_service import apply_promo_to_subscription
from app.services.qr import make_qr_png_bytes
from app.services.referral_service import apply_pending_bonuses_for_user, try_grant_bonus_for_payment
from app.services.subscription_service import (
    get_active_subscription,
    get_or_create_user,
    get_plan_by_code,
    provision_subscription,
    renew_subscription,
)
from app.services.telegram import send_message, send_photo_bytes

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/payments/invoice", response_model=InvoiceOut, dependencies=[Depends(require_internal_token)])
async def create_payment_invoice(
    payload: InvoiceCreateIn,
    db: AsyncSession = Depends(get_db),
) -> InvoiceOut:
    plan = await get_plan_by_code(db, payload.plan_code)
    if not plan or not plan.is_active or plan.is_trial:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid plan")

    user = await get_or_create_user(db, payload.telegram_id, payload.username)
    if user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user is banned")

    payment = Payment(
        user_id=user.id,
        plan_id=plan.id,
        provider="cryptobot",
        invoice_id="",
        amount=Decimal(plan.price_rub),
        currency="RUB",
        status=PaymentStatus.PENDING.value,
    )
    db.add(payment)
    await db.flush()

    invoice = await create_invoice(
        amount=Decimal(plan.price_rub),
        description=f"LOADIX VPN — {plan.name}",
        payload=str(payment.id),
    )

    payment.invoice_id = str(invoice["invoice_id"])
    payment.pay_url = invoice.get("pay_url") or invoice.get("bot_invoice_url") or invoice.get("mini_app_invoice_url")
    await db.commit()
    await db.refresh(payment)

    return InvoiceOut(
        payment_id=payment.id,
        invoice_id=payment.invoice_id,
        pay_url=payment.pay_url or "",
        amount=Decimal(plan.price_rub),
        currency="RUB",
    )


@router.post("/payments/telegram-confirmed", dependencies=[Depends(require_internal_token)])
async def telegram_payment_confirmed(
    payload: TelegramPaidIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    plan = await get_plan_by_code(db, payload.plan_code)
    if not plan or not plan.is_active or plan.is_trial:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid plan")

    user = await get_or_create_user(db, payload.telegram_id, payload.username)

    # Idempotency: skip if this telegram_payment_charge_id already processed
    res = await db.execute(select(Payment).where(Payment.invoice_id == payload.telegram_payment_charge_id))
    if res.scalar_one_or_none():
        return {"ok": True, "duplicate": True}

    from datetime import datetime, timezone

    payment = Payment(
        user_id=user.id,
        plan_id=plan.id,
        provider="telegram",
        invoice_id=payload.telegram_payment_charge_id,
        pay_url=None,
        amount=payload.amount_rub,
        currency="RUB",
        status=PaymentStatus.PAID.value,
        paid_at=datetime.now(timezone.utc),
    )
    db.add(payment)
    await db.flush()

    existing = await get_active_subscription(db, user.id)
    if existing:
        sub = await renew_subscription(db, existing, plan)
    else:
        sub = await provision_subscription(db, plan=plan, user=user, is_trial=False)

    try:
        await try_grant_bonus_for_payment(db, payment=payment)
    except Exception as e:
        log.warning("referral bonus grant failed: %s", e)

    pending_days_rub = 0
    try:
        pending_days_rub = await apply_pending_bonuses_for_user(db, user_id=user.id, subscription=sub)
    except Exception as e:
        log.warning("apply_pending_bonuses failed: %s", e)

    await db.commit()
    await db.refresh(sub)

    primary = sub.devices[0] if sub.devices else None
    bonus_line_rub = f"\n🎁 <b>+{pending_days_rub} дней бонуса</b> от приглашённых друзей применены\n" if pending_days_rub else ""
    await send_message(
        user.telegram_id,
        f"✅ Оплата получена.\n\nТариф: <b>{plan.name}</b>\n"
        f"{bonus_line_rub}"
        f"Действует до: <b>{sub.expire_date.strftime('%Y-%m-%d %H:%M UTC')}</b>\n\n"
        + (f"<code>{primary.vless_uri}</code>" if primary else ""),
    )
    if primary:
        try:
            await send_photo_bytes(
                user.telegram_id, make_qr_png_bytes(primary.vless_uri), caption="VLESS Reality QR"
            )
        except Exception as e:
            log.warning("send qr failed: %s", e)

    return {"ok": True}


@router.post("/payments/telegram-stars-confirmed", dependencies=[Depends(require_internal_token)])
async def telegram_stars_payment_confirmed(
    payload: TelegramStarsPaidIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    plan = await get_plan_by_code(db, payload.plan_code)
    if not plan or not plan.is_active or plan.is_trial:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid plan")

    user = await get_or_create_user(db, payload.telegram_id, payload.username)

    res = await db.execute(select(Payment).where(Payment.invoice_id == payload.telegram_payment_charge_id))
    if res.scalar_one_or_none():
        return {"ok": True, "duplicate": True}

    from datetime import datetime, timezone

    payment = Payment(
        user_id=user.id,
        plan_id=plan.id,
        provider="telegram-stars",
        invoice_id=payload.telegram_payment_charge_id,
        pay_url=None,
        amount=Decimal(payload.amount_stars),
        currency="XTR",
        status=PaymentStatus.PAID.value,
        paid_at=datetime.now(timezone.utc),
    )
    db.add(payment)
    await db.flush()

    existing = await get_active_subscription(db, user.id)
    if existing:
        sub = await renew_subscription(db, existing, plan)
    else:
        sub = await provision_subscription(db, plan=plan, user=user, is_trial=False)

    # Apply promo code if provided
    promo_days = 0
    if payload.promo_code:
        try:
            promo_days = await apply_promo_to_subscription(
                db, code=payload.promo_code, user=user, subscription=sub, payment_id=payment.id
            )
        except Exception as e:
            log.warning("promo apply failed: %s", e)

    # Referral bonus (granted once per invited user on their first paid purchase)
    try:
        await try_grant_bonus_for_payment(db, payment=payment)
    except Exception as e:
        log.warning("referral bonus grant failed: %s", e)

    # Apply any PENDING referral bonuses this user earned earlier without active sub
    pending_days = 0
    try:
        pending_days = await apply_pending_bonuses_for_user(db, user_id=user.id, subscription=sub)
    except Exception as e:
        log.warning("apply_pending_bonuses failed: %s", e)

    await db.commit()
    await db.refresh(sub)

    primary = sub.devices[0] if sub.devices else None
    bonus_lines = ""
    if promo_days:
        bonus_lines += f"\n🎟 <b>Промокод {payload.promo_code.upper()}: +{promo_days} дней</b>"
    if pending_days:
        bonus_lines += f"\n🎁 <b>+{pending_days} дней</b> от приглашённых друзей"
    await send_message(
        user.telegram_id,
        f"✅ Оплата получена ({payload.amount_stars} ⭐).\n\nТариф: <b>{plan.name}</b>"
        f"{bonus_lines}\n"
        f"Действует до: <b>{sub.expire_date.strftime('%Y-%m-%d %H:%M UTC')}</b>\n\n"
        + (f"<code>{primary.vless_uri}</code>" if primary else ""),
    )
    if primary:
        try:
            await send_photo_bytes(
                user.telegram_id, make_qr_png_bytes(primary.vless_uri), caption="VLESS Reality QR"
            )
        except Exception as e:
            log.warning("send qr failed: %s", e)

    return {"ok": True}


@router.post("/payments/webhook")
async def cryptobot_webhook(
    request: Request,
    crypto_pay_api_signature: str | None = Header(default=None, alias="crypto-pay-api-signature"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    body = await request.body()
    if not verify_webhook_signature(body, crypto_pay_api_signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad signature")

    data = await request.json()
    update_type = data.get("update_type")
    if update_type != "invoice_paid":
        return {"ok": True}

    invoice = data.get("payload") or {}
    payload_str = invoice.get("payload") or ""
    invoice_id = str(invoice.get("invoice_id") or "")

    payment = None
    if payload_str:
        res = await db.execute(select(Payment).where(Payment.id == payload_str))
        payment = res.scalar_one_or_none()
    if not payment and invoice_id:
        res = await db.execute(select(Payment).where(Payment.invoice_id == invoice_id))
        payment = res.scalar_one_or_none()

    if not payment:
        log.warning("webhook for unknown payment: %s", invoice)
        return {"ok": True}

    if payment.status == PaymentStatus.PAID.value:
        return {"ok": True}

    payment.status = PaymentStatus.PAID.value
    from datetime import datetime, timezone

    payment.paid_at = datetime.now(timezone.utc)

    plan = await db.get(Plan, payment.plan_id)
    user = await db.get(User, payment.user_id)
    if not plan or not user:
        await db.commit()
        return {"ok": True}

    existing = await get_active_subscription(db, user.id)
    if existing:
        sub = await renew_subscription(db, existing, plan)
    else:
        sub = await provision_subscription(db, plan=plan, user=user, is_trial=False)

    await db.commit()
    await db.refresh(sub)

    primary = sub.devices[0] if sub.devices else None
    await send_message(
        user.telegram_id,
        f"✅ Оплата получена.\n\nТариф: <b>{plan.name}</b>\n"
        f"Действует до: <b>{sub.expire_date.strftime('%Y-%m-%d %H:%M UTC')}</b>\n\n"
        + (f"<code>{primary.vless_uri}</code>" if primary else ""),
    )
    if primary:
        try:
            await send_photo_bytes(
                user.telegram_id, make_qr_png_bytes(primary.vless_uri), caption="VLESS Reality QR"
            )
        except Exception as e:
            log.warning("send qr failed: %s", e)

    return {"ok": True}

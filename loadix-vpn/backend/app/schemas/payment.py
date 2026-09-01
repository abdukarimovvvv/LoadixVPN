from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class InvoiceCreateIn(BaseModel):
    telegram_id: int
    username: str | None = None
    plan_code: str


class InvoiceOut(BaseModel):
    payment_id: UUID
    invoice_id: str
    pay_url: str
    amount: Decimal
    currency: str


class TelegramPaidIn(BaseModel):
    telegram_id: int
    username: str | None = None
    plan_code: str
    amount_rub: Decimal
    telegram_payment_charge_id: str
    provider_payment_charge_id: str | None = None


class TelegramStarsPaidIn(BaseModel):
    telegram_id: int
    username: str | None = None
    plan_code: str
    amount_stars: int
    telegram_payment_charge_id: str
    promo_code: str | None = None


class BotTrialIn(BaseModel):
    telegram_id: int
    username: str | None = None

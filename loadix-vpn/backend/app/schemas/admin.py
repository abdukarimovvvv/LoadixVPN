from __future__ import annotations

from pydantic import BaseModel


class BroadcastIn(BaseModel):
    text: str


class BroadcastOut(BaseModel):
    sent: int
    failed: int


class StatsOut(BaseModel):
    users_total: int
    users_banned: int
    subscriptions_active: int
    subscriptions_total: int
    trials_total: int
    payments_paid: int
    revenue_rub: float


class BanIn(BaseModel):
    telegram_id: int
    ban: bool = True


class GrantIn(BaseModel):
    telegram_id: int
    username: str | None = None
    plan_code: str


class UserSubscriptionItem(BaseModel):
    telegram_id: int
    username: str | None = None
    plan_name: str | None = None
    status: str | None = None
    expire_date: str | None = None


class UserSubscriptionsPage(BaseModel):
    items: list[UserSubscriptionItem]
    total: int
    page: int
    page_size: int

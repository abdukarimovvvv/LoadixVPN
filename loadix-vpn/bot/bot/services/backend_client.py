from __future__ import annotations

import logging
from typing import Any

import httpx

from bot.app_env import settings

log = logging.getLogger(__name__)


class BackendError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"{status_code}: {message}")
        self.status_code = status_code
        self.message = message


def _headers(telegram_id: int | None = None) -> dict[str, str]:
    headers = {"X-Internal-Token": settings.INTERNAL_API_TOKEN}
    if telegram_id is not None:
        headers["X-Telegram-Id"] = str(telegram_id)
    return headers


async def _request(method: str, path: str, *, telegram_id: int | None = None, **kwargs: Any) -> Any:
    url = f"{settings.BACKEND_BASE_URL.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.request(method, url, headers=_headers(telegram_id), **kwargs)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise BackendError(r.status_code, str(detail))
    if not r.content:
        return None
    ct = r.headers.get("content-type", "")
    if ct.startswith("application/json"):
        return r.json()
    return r.content


async def list_plans() -> list[dict]:
    return await _request("GET", "/api/plans")


async def ping() -> dict:
    return await _request("GET", "/api/ping")


async def get_plan(plan_code: str) -> dict | None:
    for p in await list_plans():
        if p.get("code") == plan_code:
            return p
    return None


async def create_invoice(telegram_id: int, username: str | None, plan_code: str) -> dict:
    return await _request(
        "POST",
        "/api/payments/invoice",
        telegram_id=telegram_id,
        json={"telegram_id": telegram_id, "username": username, "plan_code": plan_code},
    )


async def telegram_paid_confirm(
    telegram_id: int,
    username: str | None,
    plan_code: str,
    amount_rub: float,
    telegram_payment_charge_id: str,
    provider_payment_charge_id: str | None = None,
) -> dict:
    return await _request(
        "POST",
        "/api/payments/telegram-confirmed",
        json={
            "telegram_id": telegram_id,
            "username": username,
            "plan_code": plan_code,
            "amount_rub": amount_rub,
            "telegram_payment_charge_id": telegram_payment_charge_id,
            "provider_payment_charge_id": provider_payment_charge_id,
        },
    )


async def telegram_stars_paid_confirm(
    telegram_id: int,
    username: str | None,
    plan_code: str,
    amount_stars: int,
    telegram_payment_charge_id: str,
    promo_code: str | None = None,
) -> dict:
    return await _request(
        "POST",
        "/api/payments/telegram-stars-confirmed",
        json={
            "telegram_id": telegram_id,
            "username": username,
            "plan_code": plan_code,
            "amount_stars": amount_stars,
            "telegram_payment_charge_id": telegram_payment_charge_id,
            "promo_code": promo_code,
        },
    )


async def promo_validate(telegram_id: int, code: str) -> dict:
    return await _request(
        "POST",
        "/api/promo/validate",
        json={"telegram_id": telegram_id, "code": code},
    )


async def admin_promo_create(telegram_id: int, code: str, bonus_days: int, max_uses: int | None, valid_until: str | None) -> dict:
    return await _request(
        "POST",
        "/api/admin/promo/create",
        telegram_id=telegram_id,
        json={
            "code": code,
            "bonus_days": bonus_days,
            "max_uses": max_uses,
            "valid_until": valid_until,
        },
    )


async def admin_promo_list(telegram_id: int) -> list[dict]:
    return await _request("GET", "/api/admin/promo/list", telegram_id=telegram_id)


async def admin_promo_toggle(telegram_id: int, code: str, active: bool) -> dict:
    return await _request(
        "POST",
        "/api/admin/promo/toggle",
        telegram_id=telegram_id,
        json={"code": code, "active": active},
    )


async def get_subscription(telegram_id: int) -> dict:
    return await _request("GET", f"/api/subscription/{telegram_id}", telegram_id=telegram_id)


async def get_last_subscription(telegram_id: int) -> dict:
    return await _request("GET", f"/api/subscription/{telegram_id}/last", telegram_id=telegram_id)


async def add_device(telegram_id: int, name: str | None) -> dict:
    return await _request(
        "POST",
        f"/api/subscription/{telegram_id}/devices",
        telegram_id=telegram_id,
        json={"name": name},
    )


async def delete_device(telegram_id: int, device_id: str) -> dict:
    return await _request(
        "DELETE",
        f"/api/subscription/{telegram_id}/devices/{device_id}",
        telegram_id=telegram_id,
    )


async def get_wireguard_config(telegram_id: int, name: str | None) -> dict:
    return await _request(
        "POST",
        f"/api/subscription/{telegram_id}/wireguard",
        telegram_id=telegram_id,
        json={"name": name},
    )


async def get_openvpn_config(telegram_id: int, name: str | None) -> dict:
    return await _request(
        "POST",
        f"/api/subscription/{telegram_id}/openvpn",
        telegram_id=telegram_id,
        json={"name": name},
    )


async def rotate_device(telegram_id: int, device_id: str) -> dict:
    return await _request(
        "POST",
        f"/api/subscription/{telegram_id}/devices/{device_id}/rotate",
        telegram_id=telegram_id,
    )


async def is_user_banned(telegram_id: int) -> bool:
    try:
        r = await _request("GET", f"/api/users/{telegram_id}/banned")
        return bool(r.get("banned"))
    except BackendError:
        return False


async def register_user(telegram_id: int, username: str | None) -> None:
    """Fire-and-forget on /start — registers user in DB silently."""
    try:
        await _request(
            "POST",
            "/api/users/register",
            telegram_id=telegram_id,
            json={"telegram_id": telegram_id, "username": username},
        )
    except Exception:
        pass  # never break /start


async def claim_trial(telegram_id: int, username: str | None) -> dict:
    return await _request(
        "POST",
        "/api/trial/bot",
        telegram_id=telegram_id,
        json={"telegram_id": telegram_id, "username": username},
    )


async def admin_stats(telegram_id: int) -> dict:
    return await _request("GET", "/api/admin/stats", telegram_id=telegram_id)


async def admin_broadcast(telegram_id: int, text: str) -> dict:
    return await _request(
        "POST", "/api/admin/broadcast", telegram_id=telegram_id, json={"text": text}
    )


async def admin_users(telegram_id: int, limit: int = 20, offset: int = 0) -> list[dict]:
    return await _request(
        "GET",
        "/api/admin/users",
        telegram_id=telegram_id,
        params={"limit": limit, "offset": offset},
    )


async def admin_users_subscriptions(telegram_id: int, page: int = 0, page_size: int = 10) -> dict:
    return await _request(
        "GET",
        "/api/admin/users/subscriptions",
        telegram_id=telegram_id,
        params={"page": page, "page_size": page_size},
    )


async def admin_traffic_top(telegram_id: int) -> dict:
    return await _request(
        "GET",
        "/api/admin/subscriptions/traffic-top",
        telegram_id=telegram_id,
    )


async def admin_user_card(telegram_id: int, target_id: int) -> dict:
    return await _request(
        "GET",
        f"/api/admin/users/{target_id}/full",
        telegram_id=telegram_id,
    )


async def record_referral(referrer_telegram_id: int, referee_telegram_id: int, referee_username: str | None) -> dict:
    return await _request(
        "POST",
        "/api/referrals/record",
        json={
            "referrer_telegram_id": referrer_telegram_id,
            "referee_telegram_id": referee_telegram_id,
            "referee_username": referee_username,
        },
    )


async def referral_stats(telegram_id: int) -> dict:
    return await _request("GET", f"/api/referrals/stats/{telegram_id}")


async def admin_revoke_subscription(telegram_id: int, target_id: int) -> dict:
    return await _request(
        "POST",
        f"/api/admin/users/{target_id}/revoke",
        telegram_id=telegram_id,
    )


async def admin_ban(telegram_id: int, target_id: int, ban: bool) -> dict:
    return await _request(
        "POST",
        "/api/admin/users/ban",
        telegram_id=telegram_id,
        json={"telegram_id": target_id, "ban": ban},
    )


async def admin_grant(telegram_id: int, target_id: int, username: str | None, plan_code: str) -> dict:
    return await _request(
        "POST",
        "/api/admin/grant",
        telegram_id=telegram_id,
        json={"telegram_id": target_id, "username": username, "plan_code": plan_code},
    )

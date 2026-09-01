from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards.inline import no_subscription_kb, status_actions
from bot.services.backend_client import BackendError, get_subscription
from bot.services.screen import screen_text

log = logging.getLogger(__name__)
router = Router(name="status")


def _bar(used: float, total: float, width: int = 10) -> str:
    if total <= 0:
        return "▱" * width
    pct = min(max(used / total, 0.0), 1.0)
    filled = int(round(pct * width))
    return "▰" * filled + "▱" * (width - filled)


def _human_bytes(n: int) -> str:
    gb = n / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.2f} GB"
    return f"{n / (1024 ** 2):.1f} MB"


def _days_left(expire_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(expire_iso.replace("Z", "+00:00"))
        delta = dt - datetime.now(dt.tzinfo)
        days = max(0, delta.days)
        if days >= 1:
            return f"{days} дн."
        hours = max(0, delta.seconds // 3600)
        return f"{hours} ч."
    except Exception:
        return expire_iso


_STATUS_EMOJI = {"active": "🟢 Активна", "expired": "🔴 Истекла", "disabled": "⏸ Отключена"}


async def send_status(message: Message, telegram_id: int) -> None:
    try:
        sub = await get_subscription(telegram_id)
    except BackendError as e:
        if e.status_code == 404:
            await screen_text(
                message,
                "У вас пока нет подписок.\nВыберите тариф — это займёт минуту.",
                reply_markup=no_subscription_kb(),
            )
        else:
            log.warning("status failed: %s", e)
            await screen_text(message, "Не удалось получить статус.")
        return

    days_text = _days_left(sub["expire_date"])
    used_bytes = sub["traffic_used_bytes"]
    # Serializer converts 0 → "∞" for unlimited plans — treat as 0
    raw_limit = sub["traffic_limit_gb"]
    traffic_limit_gb = 0 if isinstance(raw_limit, str) else int(raw_limit)
    total_bytes = traffic_limit_gb * 1024 ** 3
    used_pct = (used_bytes / total_bytes * 100) if total_bytes else 0
    bar = _bar(used_bytes, total_bytes)
    state = _STATUS_EMOJI.get(sub["status"], sub["status"])
    trial_tag = "  •  🎁 Trial" if sub.get("is_trial") else ""

    if traffic_limit_gb:
        traffic_text = f"{_human_bytes(used_bytes)} / {traffic_limit_gb} GB"
    else:
        traffic_text = f"{_human_bytes(used_bytes)} / ♾ безлимит"

    text = (
        f"📊 <b>Статус подписки</b>{trial_tag}\n\n"
        f"Состояние: <b>{state}</b>\n"
        f"⏳ Осталось: <b>{days_text}</b>\n\n"
        f"📦 Трафик\n"
        f"<code>{bar}</code>  {used_pct:.0f}%\n"
        f"{traffic_text}"
    )
    devices_count = len(sub.get("devices", []))
    text += f"\n📱 Устройств: <b>{devices_count} / {sub['device_limit']}</b>"
    await screen_text(message, text, reply_markup=status_actions())


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    if message.from_user:
        await send_status(message, message.from_user.id)

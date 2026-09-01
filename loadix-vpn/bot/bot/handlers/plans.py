from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.app_env import settings
from bot.keyboards.inline import plans_keyboard
from bot.services.backend_client import BackendError, list_plans
from bot.services.screen import screen_edit, screen_text

log = logging.getLogger(__name__)
router = Router(name="plans")


def _is_admin(uid: int | None) -> bool:
    return uid is not None and uid in settings.admin_ids


def _format_plans_text(plans: list[dict], admin: bool) -> tuple[str, list[dict]]:
    paid = [p for p in plans if not p.get("is_trial")]
    lines = ["<b>🛒 Тарифы</b>", ""]
    if admin:
        lines.append("<i>Вы админ — любой тариф активируется бесплатно.</i>\n")
    for p in paid:
        stars = int(p.get("price_stars") or 0)
        if admin:
            price = "бесплатно"
        elif stars > 0:
            price = f"{stars} ⭐"
        else:
            price = f"{int(float(p.get('price_rub') or 0))} ₽"
        traffic = "♾ безлимит" if not p.get("traffic_limit_gb") else f"{p['traffic_limit_gb']} GB"
        lines.append(
            f"<b>{p['name']}</b> — {price}\n"
            f"   ⏳ {p['duration_days']} дн.  •  📦 {traffic}  •  📱 до {p['device_limit']} устр."
        )
        lines.append("")
    return "\n".join(lines), paid


async def show_plans(message: Message, *, prefix: str = "buy", admin: bool = False) -> None:
    try:
        plans = await list_plans()
    except BackendError as e:
        log.warning("plans list failed: %s", e)
        await screen_text(message, "Не удалось получить список тарифов. Попробуйте позже.")
        return
    text, paid = _format_plans_text(plans, admin)
    if not paid:
        await screen_text(message, "Тарифов пока нет.")
        return
    await screen_text(message, text, reply_markup=plans_keyboard(plans, prefix=prefix, admin=admin))


async def show_plans_via_edit(cb: CallbackQuery, *, prefix: str = "buy", admin: bool = False) -> None:
    try:
        plans = await list_plans()
    except BackendError as e:
        log.warning("plans list failed: %s", e)
        await screen_edit(cb, "Не удалось получить список тарифов.")
        return
    text, paid = _format_plans_text(plans, admin)
    if not paid:
        await screen_edit(cb, "Тарифов пока нет.")
        return
    await screen_edit(cb, text, reply_markup=plans_keyboard(plans, prefix=prefix, admin=admin))


@router.message(Command("plans"))
async def cmd_plans(message: Message) -> None:
    admin = _is_admin(message.from_user.id if message.from_user else None)
    await show_plans(message, admin=admin)

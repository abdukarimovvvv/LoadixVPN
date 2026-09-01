from __future__ import annotations

import logging
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import back_to_menu
from bot.services.backend_client import BackendError, ping
from bot.services.screen import screen_edit, screen_text

log = logging.getLogger(__name__)
router = Router(name="ping")


def _fmt(p: dict, rtt_ms: float) -> str:
    status_icon = "🟢" if p.get("status") == "ok" else "🟡"
    vpn_icon = "🟢" if p.get("vpn_ok") else "🔴"
    db_icon = "🟢" if p.get("db_ok") else "🔴"
    uptime = p.get("uptime_seconds", 0)
    if uptime > 86400:
        ut = f"{uptime // 86400} дн. {uptime % 86400 // 3600} ч."
    elif uptime > 3600:
        ut = f"{uptime // 3600} ч. {uptime % 3600 // 60} мин."
    else:
        ut = f"{uptime // 60} мин."
    vpn_ms = p.get("vpn_tcp_ms")
    vpn_ms_text = f"{vpn_ms} ms" if vpn_ms is not None else "—"

    return (
        f"📡 <b>Состояние сервиса</b>  {status_icon}\n\n"
        f"{vpn_icon} <b>VPN-сервер</b>\n"
        f"   <code>{p.get('vpn_endpoint', '—')}</code>\n"
        f"   TCP-отклик: <b>{vpn_ms_text}</b>\n\n"
        f"{db_icon} <b>База данных:</b> {'OK' if p.get('db_ok') else 'недоступна'}\n"
        f"🌐 <b>Telegram → бот RTT:</b> {rtt_ms:.0f} ms\n"
        f"⏱ <b>Uptime:</b> {ut}\n"
        f"👥 <b>Активных подписок:</b> {p.get('active_subscriptions', 0)}\n\n"
        "<i>Если статус 🟢 — значит VPN работает. "
        "Если медленно открываются сайты — проблема скорее всего на стороне вашего интернет-провайдера.</i>"
    )


async def _fetch(message_or_cb) -> tuple[dict | None, float, str | None]:
    t0 = time.perf_counter()
    try:
        p = await ping()
    except BackendError as e:
        return None, 0, e.message
    rtt = (time.perf_counter() - t0) * 1000
    return p, rtt, None


@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    p, rtt, err = await _fetch(message)
    if err:
        await screen_text(message, f"⚠️ Сервер не отвечает: {err}")
        return
    await screen_text(message, _fmt(p, rtt), reply_markup=back_to_menu())


@router.callback_query(F.data == "menu:ping")
async def cb_ping(cb: CallbackQuery) -> None:
    if not cb.message:
        await cb.answer()
        return
    await cb.answer("⏳ Проверяю...")
    p, rtt, err = await _fetch(cb.message)
    if err:
        await screen_edit(cb, f"⚠️ Сервер не отвечает: {err}", reply_markup=back_to_menu())
        return
    await screen_edit(cb, _fmt(p, rtt), reply_markup=back_to_menu())

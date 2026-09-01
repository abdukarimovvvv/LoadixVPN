from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.services.backend_client import BackendError, claim_trial
from bot.services.screen import screen_text

log = logging.getLogger(__name__)
router = Router(name="trial")


async def _claim_and_reply(message: Message, telegram_id: int, username: str | None) -> None:
    try:
        await claim_trial(telegram_id, username)
    except BackendError as e:
        if e.status_code == 409:
            await screen_text(
                message,
                "🎁 Вы уже получали Trial. Бесплатно даём только 1 раз.\n"
                "Чтобы продолжить — выберите платный тариф в «🛒 Тарифы».",
                delete_user_msg=False,
            )
        elif e.status_code == 403:
            await screen_text(message, "⛔️ Аккаунт заблокирован.", delete_user_msg=False)
        elif e.status_code == 503:
            await screen_text(message, "Trial временно недоступен.", delete_user_msg=False)
        else:
            log.warning("trial failed: %s", e)
            await screen_text(message, f"⚠️ {e.message}", delete_user_msg=False)
        return
    # backend already sent the key + QR via Telegram


@router.message(Command("trial"))
async def cmd_trial(message: Message) -> None:
    if not message.from_user:
        return
    await _claim_and_reply(message, message.from_user.id, message.from_user.username)


@router.callback_query(F.data == "trial:claim")
async def cb_trial(cb: CallbackQuery) -> None:
    if not cb.from_user or not cb.message:
        await cb.answer()
        return
    await cb.answer("⏳ Активирую…")
    await _claim_and_reply(cb.message, cb.from_user.id, cb.from_user.username)

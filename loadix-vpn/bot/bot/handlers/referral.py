from __future__ import annotations

import logging
from urllib.parse import quote

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.services.backend_client import BackendError, referral_stats
from bot.services.screen import screen_text

log = logging.getLogger(__name__)
router = Router(name="referral")


async def send_referral_screen(message: Message, telegram_id: int) -> None:
    try:
        stats = await referral_stats(telegram_id)
    except BackendError as e:
        await screen_text(message, f"⚠️ {e.message}")
        return

    bot_username = (await message.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{telegram_id}"
    bonus = stats.get("bonus_per_friend", 7)

    pending = stats.get("bonus_days_pending", 0)
    text = (
        "🤝 <b>Пригласи друга — получи бонусные дни</b>\n\n"
        f"За каждого друга, кто купит подписку — <b>+{bonus} дней</b> к твоей подписке.\n"
        "Считается с первой покупки. Trial не считается.\n\n"
        "<b>Твоя реферальная ссылка:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        "<b>📊 Статистика</b>\n"
        f"   Приглашено: <b>{stats['invited']}</b>\n"
        f"   Купили подписку: <b>{stats['paid']}</b>\n"
        f"   Применено бонусных дней: <b>{stats['bonus_days']}</b>"
        + (f"\n   ⏳ Ждёт твоей покупки: <b>+{pending} дней</b>" if pending else "")
    )

    share_text = quote(
        f"🚀 Подключайся к LoadixVPN — быстрый и стабильный VPN.\n"
        f"Безлимит. Работает в РФ. Оплата через Telegram Stars ⭐.\n\n{ref_link}"
    )
    share_url = f"https://t.me/share/url?url={quote(ref_link)}&text={share_text}"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 Поделиться ссылкой", url=share_url)],
            [InlineKeyboardButton(text="‹ Назад в меню", callback_data="back:menu")],
        ]
    )
    await screen_text(message, text, reply_markup=kb, disable_web_page_preview=True)

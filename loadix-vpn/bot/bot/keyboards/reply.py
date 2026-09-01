from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


BTN_MYVPN = "🔑 Мой VPN"
BTN_PLANS = "🛒 Тарифы"
BTN_STATUS = "📊 Статус"
BTN_TRIAL = "🎁 Trial 24ч"
BTN_PING = "📡 Пинг"
BTN_HELP = "💬 Помощь"
BTN_INVITE = "🤝 Пригласить"
BTN_ADMIN = "⚙️ Админ"


def main_reply(admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_MYVPN), KeyboardButton(text=BTN_STATUS), KeyboardButton(text=BTN_HELP)],
        [KeyboardButton(text=BTN_PLANS), KeyboardButton(text=BTN_TRIAL), KeyboardButton(text=BTN_INVITE)],
        [KeyboardButton(text=BTN_PING)],
    ]
    if admin:
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите действие из меню ниже",
    )

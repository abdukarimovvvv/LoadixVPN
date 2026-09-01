from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def plans_keyboard(plans: list[dict], *, prefix: str = "buy", admin: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for p in plans:
        if p.get("is_trial"):
            continue
        stars = int(p.get("price_stars") or 0)
        if admin:
            label = f"✨ {p['name']} · бесплатно"
        elif stars > 0:
            label = f"{p['name']} · {stars} ⭐"
        else:
            label = f"{p['name']} · {int(float(p.get('price_rub') or 0))} ₽"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"{prefix}:{p['code']}")])
    if not rows:
        rows = [[InlineKeyboardButton(text="Тарифов пока нет", callback_data="noop")]]
    rows.append([InlineKeyboardButton(text="‹ Назад в меню", callback_data="back:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pay_keyboard(pay_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=pay_url)],
            [InlineKeyboardButton(text="🔄 Я оплатил — проверить", callback_data="check_paid")],
            [InlineKeyboardButton(text="‹ Назад в меню", callback_data="back:menu")],
        ]
    )


def status_actions() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Мои устройства", callback_data="dev:list")],
            [InlineKeyboardButton(text="↻ Продлить", callback_data="open:plans")],
            [InlineKeyboardButton(text="‹ Назад в меню", callback_data="back:menu")],
        ]
    )


def help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📖 Инструкция", callback_data="help:setup"),
                InlineKeyboardButton(text="⭐ Купить Stars", callback_data="help:buy_stars"),
            ],
            [
                InlineKeyboardButton(text="🛠 Не работает", callback_data="help:troubleshoot"),
                InlineKeyboardButton(text="❓ FAQ", callback_data="help:faq"),
            ],
            [InlineKeyboardButton(text="✉️ Написать в поддержку", callback_data="help:contact")],
            [InlineKeyboardButton(text="‹ Назад в меню", callback_data="back:menu")],
        ]
    )


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="‹ Назад в меню", callback_data="back:menu")]]
    )


def back_to_help() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="‹ Назад", callback_data="back:help")]]
    )


def no_subscription_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Trial 24ч бесплатно", callback_data="trial:claim")],
            [InlineKeyboardButton(text="🛒 Выбрать тариф", callback_data="open:plans")],
            [InlineKeyboardButton(text="‹ Назад в меню", callback_data="back:menu")],
        ]
    )

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
            [
                InlineKeyboardButton(text="👥 Пользователи", callback_data="adm:users"),
                InlineKeyboardButton(text="👤 Найти юзера", callback_data="adm:find"),
            ],
            [
                InlineKeyboardButton(text="📋 Подписки", callback_data="adm:subs:0"),
                InlineKeyboardButton(text="📈 Трафик", callback_data="adm:traffic"),
            ],
            [
                InlineKeyboardButton(text="🎁 Выдать тариф", callback_data="adm:grant"),
                InlineKeyboardButton(text="🚫 Бан / Анбан", callback_data="adm:ban"),
            ],
            [
                InlineKeyboardButton(text="🎟️ Промокоды", callback_data="adm:promo"),
                InlineKeyboardButton(text="📣 Рассылка", callback_data="adm:broadcast"),
            ],
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:refresh")],
            [InlineKeyboardButton(text="‹ Назад в меню", callback_data="back:menu")],
        ]
    )


def promo_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать", callback_data="adm:promo_create")],
            [InlineKeyboardButton(text="📋 Список", callback_data="adm:promo_list")],
            [InlineKeyboardButton(text="‹ В админку", callback_data="adm:menu")],
        ]
    )


def promo_list_actions(codes: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for code in codes[:20]:  # cap to 20 buttons
        rows.append([InlineKeyboardButton(text=f"🔁 {code}", callback_data=f"adm:promo_toggle:{code}")])
    rows.append([InlineKeyboardButton(text="‹ К промокодам", callback_data="adm:promo")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_card_actions(target_id: int, is_banned: bool, has_active_sub: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🎁 Выдать тариф", callback_data=f"adm:grant_for:{target_id}")],
    ]
    if has_active_sub:
        rows.append([InlineKeyboardButton(text="❌ Аннулировать подписку", callback_data=f"adm:revoke:{target_id}")])
    if is_banned:
        rows.append([InlineKeyboardButton(text="✅ Разбанить", callback_data=f"adm:unban_now:{target_id}")])
    else:
        rows.append([InlineKeyboardButton(text="🚫 Забанить", callback_data=f"adm:ban_now:{target_id}")])
    rows.append([InlineKeyboardButton(text="🔄 Обновить карточку", callback_data=f"adm:card:{target_id}")])
    rows.append([InlineKeyboardButton(text="‹ В админку", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="‹ В админку", callback_data="adm:menu")]]
    )


def admin_subs_pagination(page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    nav_row = []
    if has_prev:
        nav_row.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"adm:subs:{page - 1}"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="Вперёд ▶", callback_data=f"adm:subs:{page + 1}"))
    rows = [nav_row] if nav_row else []
    rows.append([InlineKeyboardButton(text="‹ В админку", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_grant_plans(plans: list[dict], target_id: int) -> InlineKeyboardMarkup:
    rows = []
    for p in plans:
        if p.get("is_trial"):
            continue
        rows.append([
            InlineKeyboardButton(text=p["name"], callback_data=f"adm:grant_do:{target_id}:{p['code']}")
        ])
    rows.append([InlineKeyboardButton(text="‹ Отмена", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

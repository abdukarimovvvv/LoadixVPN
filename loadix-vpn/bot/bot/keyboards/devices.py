from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def devices_list_kb(devices: list[dict], device_limit: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for d in devices:
        name = d.get("name") or "Без имени"
        rows.append([InlineKeyboardButton(text=f"📱 {name}", callback_data=f"dev:show:{d['id']}")])
    if len(devices) < device_limit:
        rows.append([InlineKeyboardButton(text=f"🆕 Добавить устройство ({len(devices)}/{device_limit})", callback_data="dev:add")])
    else:
        rows.append([InlineKeyboardButton(text=f"⛔ Лимит: {device_limit}/{device_limit}", callback_data="noop")])
    rows.append([InlineKeyboardButton(text="‹ Назад", callback_data="back:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def device_actions_kb(device_id: str, can_delete: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📖 Как подключить", callback_data="help:setup")],
        [InlineKeyboardButton(text="🔄 Сменить ключ", callback_data=f"dev:rotate:{device_id}")],
    ]
    if can_delete:
        rows.append([InlineKeyboardButton(text="❌ Удалить устройство", callback_data=f"dev:del_confirm:{device_id}")])
    rows.append([InlineKeyboardButton(text="‹ К списку устройств", callback_data="dev:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def protocol_select_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Hysteria2", callback_data="proto:hysteria2")],
            [InlineKeyboardButton(text="🔒 WireGuard", callback_data="proto:wireguard")],
            [InlineKeyboardButton(text="⚡ VLESS / Reality", callback_data="proto:vless")],
            [InlineKeyboardButton(text="🛡 OpenVPN", callback_data="proto:openvpn")],
            [InlineKeyboardButton(text="‹ Отмена", callback_data="dev:list")],
        ]
    )


def device_delete_confirm_kb(device_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"dev:del:{device_id}")],
            [InlineKeyboardButton(text="‹ Отмена", callback_data=f"dev:show:{device_id}")],
        ]
    )

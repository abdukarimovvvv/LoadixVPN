from __future__ import annotations

import base64
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.keyboards.devices import (
    device_actions_kb,
    device_delete_confirm_kb,
    devices_list_kb,
    protocol_select_kb,
)
from bot.keyboards.inline import no_subscription_kb
from bot.services.backend_client import (
    BackendError,
    add_device,
    delete_device,
    get_hysteria2_config,
    get_openvpn_config,
    get_subscription,
    get_wireguard_config,
    rotate_device,
)
from bot.services.screen import screen_photo, screen_text

log = logging.getLogger(__name__)
router = Router(name="myvpn")


class DeviceStates(StatesGroup):
    waiting_name = State()
    waiting_protocol = State()


def _fmt_days_left(expire_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(expire_iso.replace("Z", "+00:00"))
        delta = dt - datetime.now(dt.tzinfo)
        days = delta.days
        hours = delta.seconds // 3600
        if days > 0:
            return f"{days} дн."
        if hours > 0:
            return f"{hours} ч."
        return "истекает"
    except Exception:
        return expire_iso


def _fmt_expire(expire_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(expire_iso.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M UTC")
    except Exception:
        return expire_iso


def _list_text(sub: dict) -> str:
    devices = sub.get("devices", [])
    traffic_limit = "♾ безлимит" if not sub.get("traffic_limit_gb") else f"{sub['traffic_limit_gb']} GB"
    return (
        "🔑 <b>Ваши устройства</b>\n\n"
        f"📅 Подписка до: <b>{_fmt_expire(sub['expire_date'])}</b>  •  ⏳ {_fmt_days_left(sub['expire_date'])}\n"
        f"📦 Трафик: <b>{traffic_limit}</b>\n"
        f"📱 Устройств: <b>{len(devices)} / {sub['device_limit']}</b>\n\n"
        "⚠️ <b>Правило:</b> один ключ — одно устройство. На каждое устройство нужен свой отдельный ключ.\n\n"
        + ("Нажмите на устройство — увидите ключ и QR." if devices else "Устройств пока нет.")
    )


def _device_caption(sub: dict, dev: dict) -> str:
    traffic_limit = "♾ безлимит" if not sub.get("traffic_limit_gb") else f"{sub['traffic_limit_gb']} GB"
    header = (
        f"📱 <b>{dev.get('name') or 'Устройство'}</b>\n"
        f"📅 Действует до: <b>{_fmt_expire(sub['expire_date'])}</b>\n"
        f"📦 Трафик: <b>{traffic_limit}</b>\n\n"
        "⚠️ <b>Этот ключ — только для одного устройства.</b>\n"
        "Если поставите тот же QR/файл на второе устройство — оба перестанут работать. "
        "Для второго гаджета жмите «🆕 Добавить устройство» в списке.\n\n"
    )
    protocol = dev.get("protocol", "vless")
    if protocol == "vless":
        return header + (
            "👇 Сканируй QR в v2RayTun / Amnezia / Hiddify (или скопируй ссылку):\n\n"
            f"<code>{dev['vless_uri']}</code>"
        )
    if protocol == "wireguard":
        return header + "👇 Сканируй QR в приложении WireGuard, или используй файл конфига ниже."
    if protocol == "hysteria2":
        return header + (
            "👇 Сканируй QR в приложении с поддержкой Hysteria2 (например, v2RayTun, NekoBox), "
            "или скопируй ссылку:\n\n"
            f"<code>{dev.get('raw_config', '')}</code>"
        )
    return header + "👇 Импортируйте файл конфига ниже в OpenVPN Connect."


async def _send_device_card(message: Message, sub: dict, dev: dict, *, can_delete: bool, prefix: str = "") -> None:
    caption = prefix + _device_caption(sub, dev)
    kb = device_actions_kb(dev["id"], can_delete=can_delete)
    if dev.get("qr_base64"):
        png = base64.b64decode(dev["qr_base64"])
        await screen_photo(message, BufferedInputFile(png, filename="loadix-key.png"), caption, reply_markup=kb, delete_user_msg=False)
    else:
        await screen_text(message, caption, reply_markup=kb, delete_user_msg=False)
    if dev.get("protocol") in ("wireguard", "openvpn") and dev.get("raw_config"):
        ext = "conf" if dev["protocol"] == "wireguard" else "ovpn"
        file_name = f"loadix-{dev['protocol']}-{(dev.get('name') or 'vpn').replace(' ', '_')}.{ext}"
        await message.answer_document(BufferedInputFile(dev["raw_config"].encode(), filename=file_name))


async def send_myvpn(message: Message, telegram_id: int) -> None:
    try:
        sub = await get_subscription(telegram_id)
    except BackendError as e:
        if e.status_code == 404:
            await screen_text(
                message,
                "У вас пока нет активной подписки.\nВыберите тариф или получите Trial — это бесплатно.",
                reply_markup=no_subscription_kb(),
            )
        else:
            log.warning("get sub failed: %s", e)
            await screen_text(message, "Не удалось получить данные. Попробуйте позже.")
        return
    await screen_text(
        message,
        _list_text(sub),
        reply_markup=devices_list_kb(sub["devices"], sub["device_limit"]),
    )


@router.message(Command("myvpn"))
async def cmd_myvpn(message: Message) -> None:
    if message.from_user:
        await send_myvpn(message, message.from_user.id)


@router.callback_query(F.data == "dev:list")
async def cb_list(cb: CallbackQuery) -> None:
    if cb.from_user and cb.message:
        await send_myvpn(cb.message, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data.startswith("dev:show:"))
async def cb_show(cb: CallbackQuery) -> None:
    if not cb.from_user or not cb.message:
        await cb.answer()
        return
    device_id = cb.data.split(":", 2)[2]
    try:
        sub = await get_subscription(cb.from_user.id)
    except BackendError as e:
        await cb.message.answer(f"⚠️ {e.message}")
        await cb.answer()
        return
    devices = sub["devices"]
    dev = next((d for d in devices if d["id"] == device_id), None)
    if not dev:
        await cb.answer("Устройство не найдено", show_alert=True)
        return
    await _send_device_card(cb.message, sub, dev, can_delete=len(devices) > 1)
    await cb.answer()


@router.callback_query(F.data == "dev:add")
async def cb_add_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not cb.from_user or not cb.message:
        await cb.answer()
        return
    await state.set_state(DeviceStates.waiting_name)
    await screen_text(
        cb.message,
        "🆕 <b>Добавить устройство</b>\n\n"
        "Напишите название (например, «iPhone», «MacBook», «Работа»). "
        "Или отправьте «-» чтобы пропустить.",
        delete_user_msg=False,
    )
    await cb.answer()


@router.message(DeviceStates.waiting_name, F.text)
async def add_device_got_name(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    raw = (message.text or "").strip()
    name = None if raw in {"-", ""} else raw[:64]
    await state.update_data(device_name=name)
    await state.set_state(DeviceStates.waiting_protocol)
    await screen_text(
        message,
        "📡 <b>Выберите протокол</b>\n\n"
        "• <b>Hysteria2</b> — новый и быстрый, хорошо обходит блокировки. Рекомендуем попробовать первым.\n"
        "• <b>WireGuard</b> — стабильный, отличный выбор если что-то не работает.\n"
        "• <b>VLESS / Reality</b> — быстрый, работает на порту 443.\n"
        "• <b>OpenVPN</b> — классика, совместим с большинством устройств.\n\n"
        "⚠️ Если один протокол не работает — попробуйте другой.",
        reply_markup=protocol_select_kb(),
        delete_user_msg=False,
    )


@router.callback_query(DeviceStates.waiting_protocol, F.data.startswith("proto:"))
async def cb_protocol_selected(cb: CallbackQuery, state: FSMContext) -> None:
    if not cb.from_user or not cb.message:
        await cb.answer()
        return

    protocol = cb.data.split(":", 1)[1]  # vless / wireguard / openvpn
    data = await state.get_data()
    name = data.get("device_name")
    await state.clear()

    await cb.answer("⏳ Генерирую ключ…")

    if protocol == "vless":
        try:
            dev = await add_device(cb.from_user.id, name)
        except BackendError as e:
            if e.status_code == 409:
                await screen_text(cb.message, f"⚠️ {e.message}", delete_user_msg=False)
            elif e.status_code == 404:
                await screen_text(cb.message, "Сначала оформите подписку.", reply_markup=no_subscription_kb())
            else:
                log.warning("add device failed: %s", e)
                await screen_text(cb.message, f"⚠️ {e.message}", delete_user_msg=False)
            return
        try:
            sub = await get_subscription(cb.from_user.id)
        except BackendError:
            await screen_text(cb.message, "Устройство создано. Откройте /myvpn.", delete_user_msg=False)
            return
        png = base64.b64decode(dev["qr_base64"])
        await screen_photo(
            cb.message,
            BufferedInputFile(png, filename="loadix-vless.png"),
            "✨ <b>VLESS ключ готов</b>\n\n"
            + _device_caption(sub, dev)
            + "\n\n💡 Не работает? Попробуйте WireGuard или OpenVPN — нажмите /myvpn → Добавить устройство.",
            reply_markup=device_actions_kb(dev["id"], can_delete=len(sub["devices"]) > 1),
            delete_user_msg=False,
        )

    elif protocol == "hysteria2":
        try:
            result = await get_hysteria2_config(cb.from_user.id, name)
        except BackendError as e:
            if e.status_code == 404:
                await screen_text(cb.message, "Сначала оформите подписку.", reply_markup=no_subscription_kb())
            elif e.status_code == 409:
                await screen_text(cb.message, "⚠️ Достигнут лимит устройств для вашей подписки.", delete_user_msg=False)
            else:
                log.warning("hysteria2 config failed: %s", e)
                await screen_text(cb.message, f"⚠️ {e.message}\n\nПопробуйте другой протокол.", delete_user_msg=False)
            return
        config_text = result["config"]
        png = base64.b64decode(result["qr_base64"])
        await cb.message.answer_photo(
            BufferedInputFile(png, filename="loadix-hy2.png"),
            caption=(
                "🚀 <b>Hysteria2 ключ готов</b>\n\n"
                "📲 Как использовать:\n"
                "• <b>Android/iOS</b>: приложение <b>v2RayTun</b> / <b>NekoBox</b> → Сканировать QR-код\n"
                "• Или скопируйте ссылку ниже\n\n"
                f"<code>{config_text}</code>\n\n"
                "⚠️ Не работает? Попробуйте WireGuard или VLESS — /myvpn → Добавить устройство."
            ),
            parse_mode="HTML",
        )

    elif protocol == "wireguard":
        try:
            result = await get_wireguard_config(cb.from_user.id, name)
        except BackendError as e:
            if e.status_code == 404:
                await screen_text(cb.message, "Сначала оформите подписку.", reply_markup=no_subscription_kb())
            elif e.status_code == 409:
                await screen_text(cb.message, "⚠️ Достигнут лимит устройств для вашей подписки.", delete_user_msg=False)
            else:
                log.warning("wireguard config failed: %s", e)
                await screen_text(cb.message, f"⚠️ {e.message}\n\nПопробуйте другой протокол.", delete_user_msg=False)
            return
        config_text = result["config"]
        file_name = f"loadix-wg-{(name or 'vpn').replace(' ', '_')}.conf"
        png = base64.b64decode(result["qr_base64"])
        await cb.message.answer_photo(
            BufferedInputFile(png, filename="loadix-wg.png"),
            caption=(
                "✅ <b>WireGuard конфиг готов</b>\n\n"
                "📲 Как использовать:\n"
                "• <b>Android/iOS</b>: приложение <b>WireGuard</b> → «+» → Сканировать QR-код\n"
                "• Или импортируйте файл конфига ниже\n\n"
                "⚠️ Не работает? Попробуйте VLESS или OpenVPN — /myvpn → Добавить устройство."
            ),
            parse_mode="HTML",
        )
        await cb.message.answer_document(
            BufferedInputFile(config_text.encode(), filename=file_name),
        )

    elif protocol == "openvpn":
        try:
            result = await get_openvpn_config(cb.from_user.id, name)
        except BackendError as e:
            if e.status_code == 404:
                await screen_text(cb.message, "Сначала оформите подписку.", reply_markup=no_subscription_kb())
            elif e.status_code == 409:
                await screen_text(cb.message, "⚠️ Достигнут лимит устройств для вашей подписки.", delete_user_msg=False)
            else:
                log.warning("openvpn config failed: %s", e)
                await screen_text(cb.message, f"⚠️ {e.message}\n\nПопробуйте другой протокол.", delete_user_msg=False)
            return
        config_text = result["config"]
        file_name = f"loadix-ovpn-{(name or 'vpn').replace(' ', '_')}.ovpn"
        await cb.message.answer_document(
            BufferedInputFile(config_text.encode(), filename=file_name),
            caption=(
                "✅ <b>OpenVPN конфиг готов</b>\n\n"
                "📲 Как использовать:\n"
                "• <b>Android/iOS</b>: приложение <b>OpenVPN Connect</b> → импортировать .ovpn\n"
                "• <b>Amnezia VPN</b>: импортировать конфиг\n"
                "• <b>Windows/Mac</b>: OpenVPN GUI → Import file\n\n"
                "⚠️ Не работает? Попробуйте VLESS или WireGuard — /myvpn → Добавить устройство."
            ),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("dev:rotate:"))
async def cb_rotate(cb: CallbackQuery) -> None:
    if not cb.from_user or not cb.message:
        await cb.answer()
        return
    device_id = cb.data.split(":", 2)[2]
    await cb.answer("⏳ Меняю ключ…")
    try:
        dev = await rotate_device(cb.from_user.id, device_id)
    except BackendError as e:
        if e.status_code == 429:
            await screen_text(cb.message, f"⏳ {e.message}", delete_user_msg=False)
        else:
            await screen_text(cb.message, f"⚠️ {e.message}", delete_user_msg=False)
        return
    try:
        sub = await get_subscription(cb.from_user.id)
    except BackendError:
        return
    await _send_device_card(
        cb.message, sub, dev,
        can_delete=len(sub["devices"]) > 1,
        prefix="✨ <b>Новый ключ</b> — старый перестал работать.\n\n",
    )


@router.callback_query(F.data.startswith("dev:del_confirm:"))
async def cb_del_confirm(cb: CallbackQuery) -> None:
    if not cb.from_user or not cb.message:
        await cb.answer()
        return
    device_id = cb.data.split(":", 2)[2]
    await screen_text(
        cb.message,
        "❗️ <b>Удалить устройство?</b>\n\nПосле удаления ключ перестанет работать.\nСлот освободится — можно будет добавить новое устройство.",
        reply_markup=device_delete_confirm_kb(device_id),
        delete_user_msg=False,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("dev:del:"))
async def cb_del(cb: CallbackQuery) -> None:
    if not cb.from_user or not cb.message:
        await cb.answer()
        return
    device_id = cb.data.split(":", 2)[2]
    try:
        await delete_device(cb.from_user.id, device_id)
    except BackendError as e:
        await screen_text(cb.message, f"⚠️ {e.message}", delete_user_msg=False)
        await cb.answer()
        return
    await cb.answer("Удалено")
    await send_myvpn(cb.message, cb.from_user.id)

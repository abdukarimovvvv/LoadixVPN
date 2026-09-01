from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.app_env import settings
from bot.keyboards.reply import (
    BTN_ADMIN,
    BTN_HELP,
    BTN_INVITE,
    BTN_MYVPN,
    BTN_PING,
    BTN_PLANS,
    BTN_STATUS,
    BTN_TRIAL,
    main_reply,
)
from bot.services.backend_client import BackendError, record_referral, register_user
from bot.services.screen import remember, screen_edit, screen_text

router = Router(name="start")


def _is_admin(uid: int | None) -> bool:
    return uid is not None and uid in settings.admin_ids


WELCOME = (
    "⚡️ <b>LOADIX VPN</b>\n"
    "Быстрый VPN на технологии VLESS Reality.\n"
    "Работает там, где блокируют всё остальное.\n\n"
    "Управление — кнопками снизу 👇"
)


@router.message(CommandStart(deep_link=True))
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    await state.clear()

    # Parse "ref_<inviter_telegram_id>" deeplink payload
    payload = ""
    if message.text and " " in message.text:
        payload = message.text.split(" ", 1)[1].strip()
    if payload.startswith("ref_"):
        try:
            inviter_id = int(payload[4:])
            if inviter_id != message.from_user.id:
                await record_referral(
                    referrer_telegram_id=inviter_id,
                    referee_telegram_id=message.from_user.id,
                    referee_username=message.from_user.username,
                )
        except (ValueError, BackendError):
            pass  # silent fail — referral is optional

    # Register user in DB (silent — never breaks /start)
    await register_user(message.from_user.id, message.from_user.username)

    await screen_text(
        message,
        WELCOME,
        reply_markup=main_reply(admin=_is_admin(message.from_user.id)),
    )


# === Reply-keyboard buttons (text → handler) ===


@router.message(StateFilter("*"), F.text == BTN_MYVPN)
async def on_btn_myvpn(message: Message, state: FSMContext) -> None:
    await state.clear()
    from bot.handlers.myvpn import send_myvpn

    if message.from_user:
        await send_myvpn(message, message.from_user.id)


@router.message(StateFilter("*"), F.text == BTN_PLANS)
async def on_btn_plans(message: Message, state: FSMContext) -> None:
    await state.clear()
    from bot.handlers.plans import show_plans

    if message.from_user:
        await show_plans(message, admin=_is_admin(message.from_user.id))


@router.message(StateFilter("*"), F.text == BTN_STATUS)
async def on_btn_status(message: Message, state: FSMContext) -> None:
    await state.clear()
    from bot.handlers.status import send_status

    if message.from_user:
        await send_status(message, message.from_user.id)


@router.message(StateFilter("*"), F.text == BTN_TRIAL)
async def on_btn_trial(message: Message, state: FSMContext) -> None:
    await state.clear()
    from bot.handlers.trial import _claim_and_reply

    if message.from_user:
        await _claim_and_reply(message, message.from_user.id, message.from_user.username)


@router.message(StateFilter("*"), F.text == BTN_PING)
async def on_btn_ping(message: Message, state: FSMContext) -> None:
    await state.clear()
    from bot.handlers.ping import cmd_ping

    await cmd_ping(message)


@router.message(StateFilter("*"), F.text == BTN_HELP)
async def on_btn_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    from bot.handlers.support import send_help

    await send_help(message)


@router.message(StateFilter("*"), F.text == BTN_INVITE)
async def on_btn_invite(message: Message, state: FSMContext) -> None:
    await state.clear()
    from bot.handlers.referral import send_referral_screen

    if message.from_user:
        await send_referral_screen(message, message.from_user.id)


@router.message(StateFilter("*"), F.text == BTN_ADMIN)
async def on_btn_admin(message: Message, state: FSMContext) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    await state.clear()
    from bot.handlers.admin import open_admin_panel

    await open_admin_panel(message)


# === Inline navigation callbacks ===


@router.callback_query(F.data == "back:menu")
async def cb_back_menu(cb: CallbackQuery) -> None:
    if not cb.from_user or not cb.message:
        await cb.answer()
        return
    # Delete the inline screen, send fresh welcome so the reply keyboard re-appears
    chat_id = cb.message.chat.id
    try:
        await cb.message.delete()
    except Exception:
        pass
    sent = await cb.bot.send_message(
        chat_id,
        WELCOME,
        reply_markup=main_reply(admin=_is_admin(cb.from_user.id)),
    )
    remember(chat_id, sent.message_id)
    await cb.answer()


@router.callback_query(F.data == "open:plans")
async def cb_open_plans(cb: CallbackQuery) -> None:
    from bot.handlers.plans import show_plans_via_edit

    if not cb.message or not cb.from_user:
        await cb.answer()
        return
    await show_plans_via_edit(cb, admin=_is_admin(cb.from_user.id))
    await cb.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery) -> None:
    await cb.answer()

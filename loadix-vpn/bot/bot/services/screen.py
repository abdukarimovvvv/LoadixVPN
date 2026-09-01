from __future__ import annotations

import logging
from typing import Optional

from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

log = logging.getLogger(__name__)

# chat_id -> message_id of the last bot "screen" message
_last_screen: dict[int, int] = {}


async def _delete_safe(bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        log.debug("delete failed: %s", e)


async def _delete_user(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        pass


def remember(chat_id: int, message_id: int) -> None:
    _last_screen[chat_id] = message_id


def forget(chat_id: int) -> None:
    _last_screen.pop(chat_id, None)


async def screen_text(
    message: Message,
    text: str,
    *,
    reply_markup: Optional[InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove] = None,
    disable_web_page_preview: bool = False,
    delete_user_msg: bool = True,
) -> Message:
    """Replace last screen with text. Deletes user msg + previous bot screen."""
    chat_id = message.chat.id
    if delete_user_msg:
        await _delete_user(message)
    prev = _last_screen.get(chat_id)
    if prev:
        await _delete_safe(message.bot, chat_id, prev)
    new = await message.bot.send_message(
        chat_id,
        text,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )
    _last_screen[chat_id] = new.message_id
    return new


async def screen_photo(
    message: Message,
    photo: BufferedInputFile,
    caption: str,
    *,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    delete_user_msg: bool = True,
) -> Message:
    chat_id = message.chat.id
    if delete_user_msg:
        await _delete_user(message)
    prev = _last_screen.get(chat_id)
    if prev:
        await _delete_safe(message.bot, chat_id, prev)
    new = await message.bot.send_photo(
        chat_id,
        photo,
        caption=caption,
        reply_markup=reply_markup,
    )
    _last_screen[chat_id] = new.message_id
    return new


async def screen_edit(
    cb: CallbackQuery,
    text: str,
    *,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    disable_web_page_preview: bool = False,
) -> None:
    """For inline callbacks: edit current message in place, falling back to delete+send."""
    if not cb.message:
        return
    chat_id = cb.message.chat.id
    try:
        await cb.message.edit_text(
            text,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
        _last_screen[chat_id] = cb.message.message_id
        return
    except Exception as e:
        log.debug("edit failed, falling back to delete+send: %s", e)
    await _delete_safe(cb.bot, chat_id, cb.message.message_id)
    new = await cb.bot.send_message(
        chat_id,
        text,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )
    _last_screen[chat_id] = new.message_id

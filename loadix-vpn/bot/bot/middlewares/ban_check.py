from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.app_env import settings
from bot.services.backend_client import is_user_banned

log = logging.getLogger(__name__)


class BanCheckMiddleware(BaseMiddleware):
    """Blocks all updates from banned users (per backend `is_banned` flag).

    Result is cached per Telegram ID for a short TTL to avoid hitting backend on every event.
    Admins are always allowed through.
    """

    def __init__(self, ttl_seconds: float = 5.0) -> None:
        self._ttl = ttl_seconds
        self._cache: dict[int, tuple[float, bool]] = {}

    def invalidate(self, telegram_id: int) -> None:
        self._cache.pop(telegram_id, None)

    async def _check(self, telegram_id: int) -> bool:
        ts, banned = self._cache.get(telegram_id, (0.0, False))
        if time.time() - ts < self._ttl:
            return banned
        try:
            banned = await is_user_banned(telegram_id)
        except Exception as e:
            log.debug("ban check failed (fail-open): %s", e)
            banned = False
        self._cache[telegram_id] = (time.time(), banned)
        return banned

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)
        if user.id in settings.admin_ids:
            return await handler(event, data)

        if not await self._check(user.id):
            return await handler(event, data)

        text = (
            "⛔️ Ваш аккаунт заблокирован.\n"
            f"Свяжитесь с поддержкой: @{settings.SUPPORT_USERNAME}"
        )
        if isinstance(event, Message):
            try:
                await event.answer(text)
            except Exception:
                pass
        elif isinstance(event, CallbackQuery):
            try:
                await event.answer(text, show_alert=True)
            except Exception:
                pass
        return None

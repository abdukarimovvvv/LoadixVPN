from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

log = logging.getLogger(__name__)


class ThrottleMiddleware(BaseMiddleware):
    """Per-user simple-token throttle. Drops events arriving faster than `rate` per second."""

    def __init__(self, min_interval: float = 0.6) -> None:
        self._min = min_interval
        self._last: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)
        now = time.monotonic()
        prev = self._last.get(user.id, 0.0)
        if now - prev < self._min:
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer("⏳ Слишком часто — подождите секунду.", show_alert=False)
                except Exception:
                    pass
            return None
        self._last[user.id] = now
        return await handler(event, data)

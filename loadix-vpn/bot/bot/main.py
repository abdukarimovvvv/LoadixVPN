from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from bot.app_env import settings
from bot.handlers import build_router
from bot.middlewares.ban_check import BanCheckMiddleware
from bot.middlewares.throttle import ThrottleMiddleware


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bot")


PUBLIC_COMMANDS = [
    BotCommand(command="start", description="🏠 Главное меню"),
]

ADMIN_COMMANDS = PUBLIC_COMMANDS + [
    BotCommand(command="admin", description="⚙️ Админ-панель"),
]


async def setup_commands(bot: Bot) -> None:
    await bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeDefault())
    for admin_id in settings.admin_ids:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as e:
            log.warning("set admin commands for %s failed: %s", admin_id, e)


async def main() -> None:
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    throttle = ThrottleMiddleware()
    ban_middleware = BanCheckMiddleware()
    dp.message.middleware(throttle)
    dp.callback_query.middleware(throttle)
    dp.message.middleware(ban_middleware)
    dp.callback_query.middleware(ban_middleware)
    dp.pre_checkout_query.middleware(ban_middleware)
    dp.include_router(build_router())

    me = await bot.get_me()
    log.info("Bot started: @%s (%s)", me.username, me.id)

    await bot.delete_webhook(drop_pending_updates=True)
    await setup_commands(bot)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())

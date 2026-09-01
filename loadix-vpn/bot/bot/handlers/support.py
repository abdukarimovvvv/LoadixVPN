from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.app_env import settings
from bot.keyboards.inline import back_to_help, back_to_menu, help_keyboard
from bot.services.screen import screen_edit, screen_text

router = Router(name="support")


HELP_TEXT = (
    "💬 <b>Помощь</b>\n\n"
    "Выберите, что нужно:"
)


SETUP_GUIDE = (
    "📖 <b>Как подключить за 2 минуты</b>\n\n"
    "<b>1.</b> Установите приложение под своё устройство:\n\n"
    "<i>📱 Телефон — Hiddify (рекомендуем):</i>\n"
    "• <a href='https://hiddify.com/'>Hiddify</a> — iOS / Android\n\n"
    "<i>💻 Компьютер — WireGuard (рекомендуем):</i>\n"
    "• Windows / Mac / Linux: <a href='https://www.wireguard.com/install/'>wireguard.com</a>\n\n"
    "<i>Альтернативы (на любом устройстве):</i>\n"
    "• <a href='https://amnezia.org/downloads'>Amnezia VPN</a> — iOS / Android / Windows / Mac / Linux\n"
    "• v2RayTun — iOS / macOS: <a href='https://apps.apple.com/app/v2raytun/id6476628951'>App Store</a>, Android: <a href='https://play.google.com/store/apps/details?id=com.v2raytun.android'>Google Play</a>\n\n"
    "<b>2.</b> Получите ключ в <b>🔑 Мой VPN</b>:\n"
    "• Для <b>Hiddify</b>, <b>v2RayTun</b> — скопируйте VLESS-ссылку или отсканируйте QR.\n"
    "• Для <b>WireGuard</b>, <b>Amnezia</b> — скачайте файл конфигурации (.conf) или отсканируйте отдельный QR.\n\n"
    "<b>3.</b> Импортируйте ключ в приложение:\n"
    "• <b>Hiddify / v2RayTun:</b> нажмите <b>+</b> → <b>Импорт из буфера</b>, либо сканируйте QR-код.\n"
    "• <b>WireGuard / Amnezia:</b> нажмите <b>+</b> → <b>Импортировать из файла</b> и выберите скачанный .conf, либо сканируйте QR через <b>+</b> → <b>Сканировать QR-код</b>.\n\n"
    "<b>4.</b> Включите соединение — иконка/переключатель станет цветным(-ой). Готово.\n\n"
    "⚠️ Не работает? — нажмите «🛠 Не работает» в /help."
)


BUY_STARS_GUIDE = (
    "⭐ <b>Как купить Telegram Stars</b>\n\n"
    "Stars — это внутренняя валюта Telegram, оплата идёт в самом приложении (без браузеров и карт сайтов).\n\n"
    "<b>Способ 1 — через Telegram (самый простой):</b>\n"
    "1. Открой Telegram → <b>Настройки</b> ⚙️\n"
    "2. Найди раздел <b>Мой профиль</b> → <b>⭐ Stars</b> (или <i>«My Stars»</i>)\n"
    "3. Нажми <b>Buy more</b> / <b>Купить ещё</b>\n"
    "4. Выбери пакет (минимум 50 ⭐ ≈ 75 ₽, удобнее 100 ⭐ ≈ 150 ₽)\n"
    "5. Оплати через Apple Pay / Google Pay / банковскую карту\n\n"
    "<b>Способ 2 — через @PremiumBot:</b>\n"
    "1. Открой <a href='https://t.me/PremiumBot'>@PremiumBot</a> в Telegram\n"
    "2. Команда <code>/buy_stars</code>\n"
    "3. Выбери количество и оплати\n\n"
    "<b>Сколько надо для тарифов LoadixVPN:</b>\n"
    "• 30 дней = 100 ⭐\n"
    "• 45 дней = 150 ⭐\n"
    "• 90 дней = 300 ⭐\n\n"
    "<b>После покупки</b> вернись в бот → 🛒 <b>Тарифы</b> → выбери план → жми <b>Pay</b>. "
    "Списание моментальное, ключ придёт сразу.\n\n"
    "💡 Stars можно вернуть в течение 21 дня через @PremiumBot если передумал."
)


TROUBLESHOOT_TEXT = (
    "🛠 <b>Если VPN не работает</b>\n\n"
    "По порядку — обычно помогает один из шагов:\n\n"
    "<b>1.</b> Выключите и снова включите соединение в приложении.\n\n"
    "<b>2.</b> Проверьте дату и время на устройстве — должны быть точными (TLS не работает при сильном расхождении).\n\n"
    "<b>3.</b> Попробуйте другой Wi-Fi или мобильный интернет — некоторые сети режут VPN-трафик.\n\n"
    "<b>4.</b> Попробуйте другое приложение — у нас работает <b>Hiddify</b>, <b>WireGuard</b>, <b>Amnezia</b>, <b>v2RayTun</b>. Если в одном не работает — переключись на другое (учтите: для WireGuard/Amnezia нужен свой ключ, см. «📖 Инструкция»).\n\n"
    "<b>5.</b> Удалите старый профиль и заново импортируйте ключ (через QR или из буфера).\n\n"
    "<b>6.</b> Подключаетесь с двух устройств одним ключом? У нас правило: <b>один ключ = одно устройство</b>. Для второго устройства создайте отдельный ключ через <b>🔑 Мой VPN → 🆕 Добавить устройство</b> (если позволяет тариф).\n\n"
    "<b>7.</b> <b>Сменить ключ.</b> В <b>🔑 Мой VPN</b> → ваше устройство → «🔄 Сменить ключ» — создастся новый UUID. Старый сразу перестанет работать.\n\n"
    "Не помогло — напишите в поддержку (см. ниже)."
)


FAQ_TEXT = (
    "❓ <b>Частые вопросы</b>\n\n"
    "<b>Что такое Trial?</b>\n"
    "Бесплатная демо-подписка на 24 часа / 5 GB / 1 устройство. Выдаётся 1 раз. "
    "Чтобы пользоваться постоянно — нужен платный тариф.\n\n"
    "<b>Какие тарифы есть?</b>\n"
    "• 30 дней — 100 ⭐ — 3 устройства\n"
    "• 45 дней — 150 ⭐ — 4 устройства\n"
    "• 90 дней — 300 ⭐ — 5 устройств\n"
    "Все тарифы — <b>безлимитный трафик</b>.\n\n"
    "<b>Сколько устройств одновременно?</b>\n"
    "Зависит от тарифа (3, 4 или 5). <b>Каждое устройство — отдельный ключ</b> с собственным UUID. Один ключ работает только на одном устройстве (для второго одного и того же ключа — выкинет первое подключение).\n\n"
    "<b>Как добавить второе устройство?</b>\n"
    "В <b>🔑 Мой VPN</b> → «🆕 Добавить устройство». Будет создан отдельный ключ — импортируй его в приложение на нужном устройстве.\n\n"
    "<b>На сколько хватает одного ключа?</b>\n"
    "На весь срок тарифа (30 / 45 / 90 дней). Точная дата в карточке «🔑 Мой VPN».\n\n"
    "<b>Что если ключ перестал работать?</b>\n"
    "В большинстве случаев помогает «🔄 Сменить ключ» в карточке (создаст новый UUID), либо переустановка профиля в приложении.\n\n"
    "<b>Подписка истекает — что делать?</b>\n"
    "За 24 ч придёт уведомление. Нажми <b>🛒 Тарифы</b> и выбери любой — старый ключ останется тем же, продлится срок.\n\n"
    "<b>В какой валюте оплата?</b>\n"
    "<b>Только Telegram Stars (⭐)</b> — внутренняя валюта Telegram. Покупаются прямо в Telegram (см. «⭐ Как купить Telegram Stars» в меню Помощь). Оплата идёт в самом приложении — без сайтов, карт и кошельков.\n\n"
    "<b>В каких приложениях работает ключ?</b>\n"
    "VLESS-ключ — в любом клиенте с поддержкой VLESS Reality: Hiddify, v2RayTun, v2rayN и прочие. Для WireGuard или Amnezia нужен отдельный ключ (.conf-файл) — открывается в приложении WireGuard или Amnezia VPN. Полный список с ссылками — в «📖 Инструкция по подключению»."
)


async def send_help(message: Message) -> None:
    await screen_text(message, HELP_TEXT, reply_markup=help_keyboard())


@router.message(Command("support"))
async def cmd_support(message: Message) -> None:
    await send_help(message)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await send_help(message)


@router.callback_query(F.data == "help:setup")
async def cb_setup(cb: CallbackQuery) -> None:
    await screen_edit(cb, SETUP_GUIDE, reply_markup=back_to_help(), disable_web_page_preview=True)
    await cb.answer()


@router.callback_query(F.data == "help:buy_stars")
async def cb_buy_stars(cb: CallbackQuery) -> None:
    await screen_edit(cb, BUY_STARS_GUIDE, reply_markup=back_to_help(), disable_web_page_preview=True)
    await cb.answer()


@router.callback_query(F.data == "help:troubleshoot")
async def cb_trouble(cb: CallbackQuery) -> None:
    await screen_edit(cb, TROUBLESHOOT_TEXT, reply_markup=back_to_help())
    await cb.answer()


@router.callback_query(F.data == "help:faq")
async def cb_faq(cb: CallbackQuery) -> None:
    await screen_edit(cb, FAQ_TEXT, reply_markup=back_to_help())
    await cb.answer()


@router.callback_query(F.data == "help:contact")
async def cb_contact(cb: CallbackQuery) -> None:
    await screen_edit(
        cb,
        f"✉️ Напишите в поддержку: @{settings.SUPPORT_USERNAME}\n\n"
        "Опишите проблему как можно подробнее. Если ошибка в клиенте — приложите скриншот логов v2RayTun.",
        reply_markup=back_to_help(),
    )


@router.callback_query(F.data == "back:help")
async def cb_back_help(cb: CallbackQuery) -> None:
    await screen_edit(cb, HELP_TEXT, reply_markup=help_keyboard())
    await cb.answer()

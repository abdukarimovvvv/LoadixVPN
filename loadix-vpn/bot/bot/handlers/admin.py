from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.app_env import settings
from bot.keyboards.admin import admin_back, admin_grant_plans, admin_menu, admin_subs_pagination, promo_list_actions, promo_menu, user_card_actions
from bot.services.backend_client import (
    BackendError,
    admin_ban,
    admin_broadcast,
    admin_grant,
    admin_promo_create,
    admin_promo_list,
    admin_promo_toggle,
    admin_revoke_subscription,
    admin_stats,
    admin_traffic_top,
    admin_user_card,
    admin_users,
    admin_users_subscriptions,
    list_plans,
)
from bot.services.screen import screen_text

log = logging.getLogger(__name__)
router = Router(name="admin")


class AdminStates(StatesGroup):
    waiting_broadcast = State()
    waiting_grant_target = State()
    waiting_ban_id = State()
    waiting_unban_id = State()
    waiting_find_id = State()
    waiting_promo_create = State()


def _is_admin(uid: int | None) -> bool:
    return uid is not None and uid in settings.admin_ids


async def _render(msg: Message, text: str, kb, edit: bool) -> None:
    if edit:
        try:
            await msg.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await msg.answer(text, reply_markup=kb)


async def _render_stats(message: Message, telegram_id: int, edit: bool = False) -> None:
    try:
        s = await admin_stats(telegram_id)
    except BackendError as e:
        await _render(message, f"⚠️ Ошибка: {e.message}", admin_back(), edit)
        return
    active_pct = (s["subscriptions_active"] / s["users_total"] * 100) if s["users_total"] else 0
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{s['users_total']}</b>"
        + (f" (🚫 бан: {s['users_banned']})" if s["users_banned"] else "")
        + "\n"
        f"✅ Активных подписок: <b>{s['subscriptions_active']}</b> / {s['subscriptions_total']} ({active_pct:.0f}%)\n"
        f"🎁 Trial выдано: <b>{s['trials_total']}</b>\n"
        f"💳 Оплат: <b>{s['payments_paid']}</b>\n"
        f"💰 Доход: <b>{s['revenue_rub']:.2f} ₽</b>"
    )
    await _render(message, text, admin_menu(), edit)


async def _render_users(message: Message, telegram_id: int, edit: bool = False) -> None:
    try:
        users = await admin_users(telegram_id, limit=20)
    except BackendError as e:
        await _render(message, f"⚠️ Ошибка: {e.message}", admin_back(), edit)
        return
    if not users:
        await _render(message, "Пользователей нет.", admin_back(), edit)
        return
    lines = ["👥 <b>Последние 20 пользователей</b>\n"]
    for u in users:
        flag = "🚫" if u["is_banned"] else ("👑" if u["role"] == "admin" else "✅")
        raw_username = u.get("username") or ""
        username = f"@{html.escape(raw_username)}" if raw_username else "—"
        lines.append(f"{flag} <code>{u['telegram_id']}</code> {username}")
    await _render(message, "\n".join(lines), admin_back(), edit)


_STATUS_LABEL = {"active": "✅ активна", "expired": "⏳ истекла", "disabled": "⛔ отключена"}


async def _render_subs(message: Message, telegram_id: int, page: int = 0, edit: bool = False) -> None:
    try:
        data = await admin_users_subscriptions(telegram_id, page=page, page_size=10)
    except BackendError as e:
        await _render(message, f"⚠️ Ошибка: {e.message}", admin_back(), edit)
        return
    items = data.get("items", [])
    total = data.get("total", 0)
    page_size = data.get("page_size", 10)
    if not items:
        if page > 0 and total:
            await _render(
                message, "Эта страница пуста.",
                admin_subs_pagination(page, has_prev=True, has_next=False), edit,
            )
        else:
            await _render(message, "Пользователей нет.", admin_back(), edit)
        return
    total_pages = max(1, (total + page_size - 1) // page_size)
    lines = [f"📋 <b>Подписки пользователей</b> (стр. {page + 1}/{total_pages}, всего {total})\n"]
    for it in items:
        raw_username = it.get("username") or ""
        username = f"@{html.escape(raw_username)}" if raw_username else "—"
        lines.append(f"🆔 <code>{it['telegram_id']}</code> {username}")
        if it.get("plan_name"):
            status = _STATUS_LABEL.get(it.get("status") or "", it.get("status") or "—")
            expire = (it.get("expire_date") or "")[:10] or "—"
            lines.append(f"   📦 {html.escape(it['plan_name'])} · {status} · до {expire}")
        else:
            lines.append("   — нет подписки")
    kb = admin_subs_pagination(page, has_prev=page > 0, has_next=(page + 1) * page_size < total)
    await _render(message, "\n".join(lines), kb, edit)


async def _render_traffic(message: Message, telegram_id: int, edit: bool = False) -> None:
    try:
        data = await admin_traffic_top(telegram_id)
    except BackendError as e:
        await _render(message, f"⚠️ Ошибка: {e.message}", admin_back(), edit)
        return
    items = data.get("items", [])
    if not items:
        await _render(message, "Активных подписок с трафиком нет.", admin_back(), edit)
        return
    lines = ["📈 <b>Топ по расходу трафика</b> (среди активных)\n"]
    for i, it in enumerate(items, start=1):
        raw_username = it.get("username") or ""
        username = f"@{html.escape(raw_username)}" if raw_username else "—"
        used_gb = (it.get("traffic_used_bytes") or 0) / (1024 ** 3)
        limit_gb = it.get("traffic_limit_gb") or 0
        limit_label = "∞" if limit_gb == 0 else f"{limit_gb}"
        pct = f" ({used_gb / limit_gb * 100:.0f}%)" if limit_gb else ""
        plan_name = html.escape(it["plan_name"]) if it.get("plan_name") else "—"
        lines.append(f"#{i} 🆔 <code>{it['telegram_id']}</code> {username}")
        lines.append(f"   📦 {plan_name} · {used_gb:.2f} GB / {limit_label} GB{pct}")
    await _render(message, "\n".join(lines), admin_back(), edit)


def _fmt_user_card(card: dict) -> str:
    u = card["user"]
    s = card.get("active_subscription")
    pays = card.get("payments", [])
    stats = card.get("stats", {})
    all_subs = card.get("all_subscriptions", [])

    def _esc(x):
        return html.escape(str(x)) if x else "—"

    banned = "🚫 ЗАБАНЕН" if u.get("is_banned") else "✅ не забанен"
    role_icon = "👑" if u.get("role") == "admin" else "👤"

    lines = [
        f"{role_icon} <b>{_esc(u['telegram_id'])}</b>  @{_esc(u['username'])}",
        f"   Зарегистрирован: <code>{u['created_at'][:10]}</code>",
        f"   Роль: <b>{_esc(u['role'])}</b> | {banned}",
        "",
    ]

    if s:
        used_gb = (s.get("traffic_used_bytes") or 0) / (1024 ** 3)
        traffic_limit = "♾ безлимит" if not s.get("traffic_limit_gb") else f"{s['traffic_limit_gb']} GB"
        lines.append(f"📊 <b>Активная подписка</b>")
        lines.append(f"   Тариф: <b>{_esc(s.get('plan_name'))}</b> ({_esc(s.get('plan_code'))})")
        lines.append(f"   Действует до: <b>{s['expire_date'][:10]}</b>")
        lines.append(f"   Устройств: <b>{s['devices_count']}/{s['device_limit']}</b>")
        lines.append(f"   Трафик: <b>{used_gb:.2f} GB</b> / {traffic_limit}")
        if s.get("devices"):
            lines.append("")
            lines.append("📱 <b>Устройства:</b>")
            for d in s["devices"]:
                lines.append(f"   • {_esc(d.get('name'))}  <code>{d['client_uuid'][:8]}</code>")
        lines.append("")
    else:
        lines.append("📊 <b>Подписка:</b> нет активной")
        lines.append("")

    lines.append(f"💳 <b>Платежи</b> (всего {stats.get('payments_count', 0)})")
    if stats.get("total_paid_stars", 0):
        lines.append(f"   Звёзд: <b>{int(stats['total_paid_stars'])} ⭐</b>")
    if stats.get("total_paid_rub", 0):
        lines.append(f"   Рублей: <b>{stats['total_paid_rub']:.0f} ₽</b>")
    for p in pays[:5]:
        amt = f"{int(p['amount'])} ⭐" if p["currency"] == "XTR" else f"{p['amount']:.0f} {p['currency']}"
        status_icon = "✅" if p["status"] == "paid" else "⏳"
        lines.append(f"   {status_icon} {p['created_at'][:10]} — <b>{amt}</b> — {_esc(p['provider'])}")
    if len(pays) > 5:
        lines.append(f"   <i>… и ещё {len(pays) - 5}</i>")

    lines.append("")
    lines.append(f"📦 Всего подписок: <b>{stats.get('subscriptions_count', 0)}</b>"
                 f" | 🎁 Trials: <b>{stats.get('trials_count', 0)}</b>")

    return "\n".join(lines)


async def _show_user_card(message: Message, target_id: int, actor_id: int, *, edit: bool = False) -> None:
    """Render or update user card. If edit=True, edits message in place (for callback flows)."""
    try:
        card = await admin_user_card(actor_id, target_id)
    except BackendError as e:
        err_text = (
            f"⚠️ Юзер с tg_id <code>{target_id}</code> не найден."
            if e.status_code == 404
            else f"⚠️ {e.message}"
        )
        if edit:
            try:
                await message.edit_text(err_text, reply_markup=admin_back())
            except Exception:
                await message.answer(err_text, reply_markup=admin_back())
        else:
            await message.answer(err_text, reply_markup=admin_back())
        return
    text = _fmt_user_card(card)
    is_banned = bool(card["user"].get("is_banned"))
    has_active_sub = card.get("active_subscription") is not None
    kb = user_card_actions(target_id, is_banned, has_active_sub=has_active_sub)
    if edit:
        try:
            await message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass  # fall through to send new
    await message.answer(text, reply_markup=kb)


async def open_admin_panel(message: Message) -> None:
    await screen_text(
        message,
        "⚙️ <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=admin_menu(),
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    await open_admin_panel(message)
    

@router.callback_query(F.data == "adm:menu")
async def cb_admin_menu(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    text = "⚙️ <b>Админ-панель</b>\n\nВыберите действие:"
    try:
        await cb.message.edit_text(text, reply_markup=admin_menu())
    except Exception:
        await cb.message.answer(text, reply_markup=admin_menu())
    await cb.answer()
    

@router.callback_query(F.data == "adm:stats")
async def cb_stats(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    await _render_stats(cb.message, cb.from_user.id, edit=True)
    await cb.answer()


@router.callback_query(F.data == "adm:refresh")
async def cb_refresh(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    await _render_stats(cb.message, cb.from_user.id, edit=True)
    await cb.answer("Обновлено")


@router.callback_query(F.data == "adm:users")
async def cb_users(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    await _render_users(cb.message, cb.from_user.id, edit=True)
    await cb.answer()


@router.callback_query(F.data.startswith("adm:subs:"))
async def cb_subs(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    try:
        page = int(cb.data.split(":", 2)[2])
    except ValueError:
        page = 0
    await _render_subs(cb.message, cb.from_user.id, page=page, edit=True)
    await cb.answer()


@router.callback_query(F.data == "adm:traffic")
async def cb_traffic(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    await _render_traffic(cb.message, cb.from_user.id, edit=True)
    await cb.answer()


@router.callback_query(F.data == "adm:grant")
async def cb_grant_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    await state.set_state(AdminStates.waiting_grant_target)
    await cb.message.answer(
        "🎁 <b>Выдать подписку</b>\n\n"
        "Пришлите telegram_id пользователя (числом).\n"
        "Или /cancel.",
        reply_markup=admin_back(),
    )
    await cb.answer()


@router.message(AdminStates.waiting_grant_target, F.text)
async def grant_pick_plan(message: Message, state: FSMContext) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        await state.clear()
        return
    text = (message.text or "").strip()
    if not text.lstrip("-").isdigit():
        await message.answer("Это не похоже на ID. Пришлите число.")
        return
    target_id = int(text)
    try:
        plans = await list_plans()
    except BackendError as e:
        await state.clear()
        await message.answer(f"⚠️ {e.message}")
        return
    await state.clear()
    await message.answer(
        f"Выберите тариф для <code>{target_id}</code>:",
        reply_markup=admin_grant_plans(plans, target_id),
    )


@router.callback_query(F.data.startswith("adm:grant_do:"))
async def cb_grant_do(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    _, _, target_str, plan_code = cb.data.split(":", 3)
    target = int(target_str)
    try:
        await admin_grant(cb.from_user.id, target, username=None, plan_code=plan_code)
    except BackendError as e:
        await cb.message.answer(f"⚠️ {e.message}", reply_markup=admin_back())
        await cb.answer()
        return
    await cb.message.answer(
        f"✨ Тариф <b>{plan_code}</b> выдан пользователю <code>{target}</code>.\n"
        "Ключ отправлен ему в Telegram.",
        reply_markup=admin_back(),
    )
    await cb.answer("Готово")


@router.callback_query(F.data == "adm:broadcast")
async def cb_broadcast_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    await state.set_state(AdminStates.waiting_broadcast)
    await cb.message.answer(
        "📣 <b>Рассылка</b>\n\n"
        "Пришлите текст одним сообщением — он уйдёт всем не-забаненным.\n"
        "/cancel — отменить.",
        reply_markup=admin_back(),
    )
    await cb.answer()


@router.message(AdminStates.waiting_broadcast, F.text)
async def do_broadcast(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not message.from_user or not message.text:
        return
    await message.answer("⏳ Рассылка запущена…")
    try:
        r = await admin_broadcast(message.from_user.id, message.text)
    except BackendError as e:
        await message.answer(f"⚠️ {e.message}", reply_markup=admin_back())
        return
    await message.answer(
        f"✅ Отправлено: <b>{r['sent']}</b>\n❌ Неуспешно: <b>{r['failed']}</b>",
        reply_markup=admin_back(),
    )


@router.callback_query(F.data == "adm:ban")
async def cb_ban_menu(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Забанить", callback_data="adm:ban_start")],
        [InlineKeyboardButton(text="✅ Разбанить", callback_data="adm:unban_start")],
        [InlineKeyboardButton(text="‹ В админку", callback_data="adm:menu")],
    ])
    await cb.message.answer("Выберите действие:", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "adm:ban_start")
async def cb_ban_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    await state.set_state(AdminStates.waiting_ban_id)
    await cb.message.answer("Пришлите telegram_id для бана. /cancel — отмена.", reply_markup=admin_back())
    await cb.answer()


@router.callback_query(F.data == "adm:unban_start")
async def cb_unban_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    await state.set_state(AdminStates.waiting_unban_id)
    await cb.message.answer("Пришлите telegram_id для разбана. /cancel — отмена.", reply_markup=admin_back())
    await cb.answer()


@router.message(AdminStates.waiting_ban_id, F.text)
async def do_ban(message: Message, state: FSMContext) -> None:
    await _ban_with(message, state, ban=True)


@router.message(AdminStates.waiting_unban_id, F.text)
async def do_unban(message: Message, state: FSMContext) -> None:
    await _ban_with(message, state, ban=False)


async def _ban_with(message: Message, state: FSMContext, *, ban: bool) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        await state.clear()
        return
    text = (message.text or "").strip()
    if not text.lstrip("-").isdigit():
        await message.answer("Это не похоже на ID. Пришлите число.")
        return
    await state.clear()
    target = int(text)
    try:
        await admin_ban(message.from_user.id, target, ban=ban)
    except BackendError as e:
        await message.answer(f"⚠️ {e.message}", reply_markup=admin_back())
        return
    verb = "забанен" if ban else "разбанен"
    await message.answer(f"✅ Пользователь <code>{target}</code> {verb}.", reply_markup=admin_back())


@router.callback_query(F.data == "adm:find")
async def cb_find_user(cb: CallbackQuery, state: FSMContext) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    await state.set_state(AdminStates.waiting_find_id)
    await cb.message.answer(
        "👤 <b>Найти юзера</b>\n\n"
        "Пришлите <b>telegram_id</b> числом (например <code>1263887908</code>) или <b>@username</b>.\n"
        "/cancel — отмена.",
        reply_markup=admin_back(),
    )
    await cb.answer()


@router.message(AdminStates.waiting_find_id, F.text)
async def find_user_input(message: Message, state: FSMContext) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        await state.clear()
        return
    text = (message.text or "").strip().lstrip("@")
    await state.clear()
    if text.lstrip("-").isdigit():
        target_id = int(text)
    else:
        # username search — try via /api/admin/users list (lightweight scan)
        try:
            users = await admin_users(message.from_user.id, limit=500, offset=0)
        except BackendError as e:
            await message.answer(f"⚠️ {e.message}", reply_markup=admin_back())
            return
        match = next((u for u in users if (u.get("username") or "").lower() == text.lower()), None)
        if not match:
            await message.answer(
                f"⚠️ Юзер @{html.escape(text)} не найден. Попробуй tg_id числом.",
                reply_markup=admin_back(),
            )
            return
        target_id = int(match["telegram_id"])
    await _show_user_card(message, target_id, message.from_user.id)


@router.callback_query(F.data.startswith("adm:card:"))
async def cb_card_refresh(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    target_id = int(cb.data.split(":", 2)[2])
    await _show_user_card(cb.message, target_id, cb.from_user.id, edit=True)
    await cb.answer("Обновлено")


@router.callback_query(F.data.startswith("adm:ban_now:"))
async def cb_ban_now(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    target_id = int(cb.data.split(":", 2)[2])
    try:
        await admin_ban(cb.from_user.id, target_id, ban=True)
    except BackendError as e:
        await cb.answer(f"⚠️ {e.message}", show_alert=True)
        return
    await cb.answer("🚫 Забанен")
    await _show_user_card(cb.message, target_id, cb.from_user.id, edit=True)


@router.callback_query(F.data.startswith("adm:unban_now:"))
async def cb_unban_now(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    target_id = int(cb.data.split(":", 2)[2])
    try:
        await admin_ban(cb.from_user.id, target_id, ban=False)
    except BackendError as e:
        await cb.answer(f"⚠️ {e.message}", show_alert=True)
        return
    await cb.answer("✅ Разбанен")
    await _show_user_card(cb.message, target_id, cb.from_user.id, edit=True)


@router.callback_query(F.data.startswith("adm:revoke:"))
async def cb_revoke_sub(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    target_id = int(cb.data.split(":", 2)[2])
    try:
        await admin_revoke_subscription(cb.from_user.id, target_id)
    except BackendError as e:
        await cb.answer(f"⚠️ {e.message}", show_alert=True)
        return
    await cb.answer("✅ Подписка аннулирована")
    await _show_user_card(cb.message, target_id, cb.from_user.id, edit=True)


@router.callback_query(F.data.startswith("adm:grant_for:"))
async def cb_grant_for(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    target_id = int(cb.data.split(":", 2)[2])
    try:
        plans = await list_plans()
    except BackendError as e:
        await cb.answer(f"⚠️ {e.message}", show_alert=True)
        return
    try:
        await cb.message.edit_text(
            f"Выберите тариф для <code>{target_id}</code>:",
            reply_markup=admin_grant_plans(plans, target_id),
        )
    except Exception:
        await cb.message.answer(
            f"Выберите тариф для <code>{target_id}</code>:",
            reply_markup=admin_grant_plans(plans, target_id),
        )
    await cb.answer()


@router.callback_query(F.data == "adm:promo")
async def cb_promo_menu(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    text = (
        "🎟️ <b>Промокоды</b>\n\n"
        "• <b>Создать</b> — добавить новый код\n"
        "• <b>Список</b> — посмотреть существующие + включить/выключить\n\n"
        "Юзер при покупке тарифа сможет ввести код и получит +N бонусных дней."
    )
    try:
        await cb.message.edit_text(text, reply_markup=promo_menu())
    except Exception:
        await cb.message.answer(text, reply_markup=promo_menu())
    await cb.answer()


@router.callback_query(F.data == "adm:promo_create")
async def cb_promo_create_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    await state.set_state(AdminStates.waiting_promo_create)
    text = (
        "➕ <b>Создать промокод</b>\n\n"
        "Пришли строку в формате:\n"
        "<code>CODE BONUS_DAYS [MAX_USES] [VALID_UNTIL]</code>\n\n"
        "Примеры:\n"
        "<code>LAUNCH7 7</code> — код LAUNCH7, +7 дней, без лимитов\n"
        "<code>FRIDAY 14 100</code> — +14 дней, макс 100 использований\n"
        "<code>SUMMER 30 50 2026-08-31</code> — +30 дней, 50 раз, до 31 авг 2026\n\n"
        "/cancel — отмена."
    )
    await cb.message.answer(text, reply_markup=admin_back())
    await cb.answer()


@router.message(AdminStates.waiting_promo_create, F.text)
async def do_promo_create(message: Message, state: FSMContext) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        await state.clear()
        return
    text = (message.text or "").strip()
    if text.startswith("/"):
        await state.clear()
        return
    await state.clear()

    parts = text.split()
    if len(parts) < 2:
        await message.answer("⚠️ Нужно минимум: <code>CODE BONUS_DAYS</code>", reply_markup=admin_back())
        return
    code = parts[0].upper()
    try:
        bonus_days = int(parts[1])
    except ValueError:
        await message.answer("⚠️ BONUS_DAYS должно быть числом", reply_markup=admin_back())
        return
    max_uses = None
    valid_until = None
    if len(parts) >= 3:
        try:
            max_uses = int(parts[2])
        except ValueError:
            await message.answer("⚠️ MAX_USES должно быть числом", reply_markup=admin_back())
            return
    if len(parts) >= 4:
        # YYYY-MM-DD → ISO date at midnight UTC
        try:
            from datetime import datetime
            d = datetime.fromisoformat(parts[3])
            valid_until = d.isoformat()
        except ValueError:
            await message.answer("⚠️ VALID_UNTIL должно быть YYYY-MM-DD", reply_markup=admin_back())
            return

    try:
        result = await admin_promo_create(message.from_user.id, code, bonus_days, max_uses, valid_until)
    except BackendError as e:
        await message.answer(f"⚠️ {e.message}", reply_markup=admin_back())
        return

    lines = [
        f"✅ Промокод <b>{result['code']}</b> создан",
        f"   +{result['bonus_days']} дней",
        f"   Макс. использований: {result.get('max_uses') or '∞'}",
    ]
    if result.get("valid_until"):
        lines.append(f"   До: {result['valid_until'][:10]}")
    await message.answer("\n".join(lines), reply_markup=promo_menu())


@router.callback_query(F.data == "adm:promo_list")
async def cb_promo_list(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    try:
        promos = await admin_promo_list(cb.from_user.id)
    except BackendError as e:
        await cb.answer(f"⚠️ {e.message}", show_alert=True)
        return
    if not promos:
        await _render(cb.message, "Промокодов пока нет.", promo_menu(), True)
        await cb.answer()
        return
    lines = ["🎟️ <b>Все промокоды</b>\n"]
    codes_for_toggle: list[str] = []
    for p in promos:
        flag = "🟢" if p["is_active"] and not p.get("expired") else ("⏳" if p.get("expired") else "🔴")
        used = f"{p['used_count']}/{p['max_uses'] or '∞'}"
        until = f" до {p['valid_until'][:10]}" if p.get("valid_until") else ""
        lines.append(f"{flag} <code>{p['code']}</code> · +{p['bonus_days']}д · {used}{until}")
        if p["is_active"] or not p.get("expired"):
            codes_for_toggle.append(p["code"])
    text = "\n".join(lines) + "\n\n🔁 — переключить активность"
    try:
        await cb.message.edit_text(text, reply_markup=promo_list_actions(codes_for_toggle))
    except Exception:
        await cb.message.answer(text, reply_markup=promo_list_actions(codes_for_toggle))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:promo_toggle:"))
async def cb_promo_toggle(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    code = cb.data.split(":", 2)[2]
    try:
        promos = await admin_promo_list(cb.from_user.id)
        current = next((p for p in promos if p["code"] == code), None)
        if not current:
            await cb.answer("Не найдено", show_alert=True)
            return
        await admin_promo_toggle(cb.from_user.id, code, not current["is_active"])
    except BackendError as e:
        await cb.answer(f"⚠️ {e.message}", show_alert=True)
        return
    await cb.answer(f"{'✅ Активирован' if not current['is_active'] else '🔴 Отключён'}")
    # Refresh list
    await cb_promo_list(cb)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.")


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if message.from_user and _is_admin(message.from_user.id):
        await _render_stats(message, message.from_user.id)


@router.message(Command("grant"))
async def cmd_grant(message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 3 or not parts[1].lstrip("-").isdigit():
        await message.answer("Использование: /grant &lt;telegram_id&gt; &lt;plan_code&gt;")
        return
    target, plan_code = int(parts[1]), parts[2].strip()
    try:
        await admin_grant(message.from_user.id, target, username=None, plan_code=plan_code)
    except BackendError as e:
        await message.answer(f"⚠️ {e.message}")
        return
    await message.answer(f"✨ Тариф <b>{plan_code}</b> выдан <code>{target}</code>.")


@router.message(Command("users"))
async def cmd_users(message: Message) -> None:
    if message.from_user and _is_admin(message.from_user.id):
        await _render_users(message, message.from_user.id)

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from bot.app_env import settings
from bot.handlers.plans import show_plans
from bot.services.backend_client import (
    BackendError,
    admin_grant,
    get_plan,
    promo_validate,
    telegram_paid_confirm,
    telegram_stars_paid_confirm,
)
from bot.services.screen import screen_text

log = logging.getLogger(__name__)
router = Router(name="buy")


class PromoStates(StatesGroup):
    waiting_code = State()


def _is_admin(uid: int | None) -> bool:
    return uid is not None and uid in settings.admin_ids


def _prebuy_kb(plan_code: str, promo: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    if promo:
        rows.append([InlineKeyboardButton(text=f"💳 Оплатить (с промо: {promo})", callback_data=f"pay:{plan_code}:{promo}")])
        rows.append([InlineKeyboardButton(text="❌ Убрать промокод", callback_data=f"prebuy:{plan_code}:nopromo")])
    else:
        rows.append([InlineKeyboardButton(text="💳 Оплатить", callback_data=f"pay:{plan_code}:")])
        rows.append([InlineKeyboardButton(text="🎟️ Ввести промокод", callback_data=f"prebuy:{plan_code}:promo")])
    rows.append([InlineKeyboardButton(text="‹ Назад в меню", callback_data="back:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_prebuy_text(plan: dict, promo_days: int = 0, promo_code: str | None = None) -> str:
    traffic = "♾ безлимит" if not plan.get("traffic_limit_gb") else f"{plan['traffic_limit_gb']} GB"
    stars = int(plan.get("price_stars") or 0)
    days = int(plan.get("duration_days", 0))
    total_days = days + promo_days
    lines = [
        f"🛒 <b>{plan['name']}</b>",
        f"   💰 Цена: <b>{stars} ⭐</b>",
        f"   📦 Трафик: {traffic}",
        f"   📱 Устройств: до {plan['device_limit']}",
        f"   ⏳ Длительность: <b>{days} дней</b>",
    ]
    if promo_code:
        lines.append("")
        lines.append(f"🎟 Промокод <b>{promo_code}</b>: <b>+{promo_days} дней</b>")
        lines.append(f"   Итого: <b>{total_days} дней</b>")
    lines.append("")
    lines.append("Нажми <b>Оплатить</b> — Telegram запросит подтверждение Stars.")
    return "\n".join(lines)


@router.message(Command("buy"))
async def cmd_buy(message: Message) -> None:
    await show_plans(message, prefix="buy", admin=_is_admin(message.from_user.id if message.from_user else None))


@router.message(Command("renew"))
async def cmd_renew(message: Message) -> None:
    await show_plans(message, prefix="renew", admin=_is_admin(message.from_user.id if message.from_user else None))


@router.callback_query(F.data.startswith("buy:") | F.data.startswith("renew:"))
async def on_buy(cb: CallbackQuery, state: FSMContext) -> None:
    if not cb.from_user or not cb.message:
        await cb.answer()
        return
    plan_code = cb.data.split(":", 1)[1]

    # admin → бесплатная активация (минуя оплату и промокоды)
    if _is_admin(cb.from_user.id):
        try:
            await admin_grant(
                telegram_id=cb.from_user.id,
                target_id=cb.from_user.id,
                username=cb.from_user.username,
                plan_code=plan_code,
            )
        except BackendError as e:
            await screen_text(cb.message, f"⚠️ Не удалось активировать: {e.message}", delete_user_msg=False)
            await cb.answer()
            return
        await screen_text(cb.message, "✨ Подписка активирована.", delete_user_msg=False)
        await cb.answer("Готово")
        return

    plan = await get_plan(plan_code)
    if not plan or plan.get("is_trial"):
        await cb.answer("Тариф недоступен", show_alert=True)
        return

    await state.clear()
    text = _format_prebuy_text(plan)
    try:
        await cb.message.edit_text(text, reply_markup=_prebuy_kb(plan_code))
    except Exception:
        await cb.message.answer(text, reply_markup=_prebuy_kb(plan_code))
    await cb.answer()


@router.callback_query(F.data.startswith("prebuy:"))
async def on_prebuy(cb: CallbackQuery, state: FSMContext) -> None:
    if not cb.from_user or not cb.message:
        await cb.answer()
        return
    parts = cb.data.split(":", 2)
    plan_code = parts[1]
    action = parts[2] if len(parts) > 2 else ""

    plan = await get_plan(plan_code)
    if not plan:
        await cb.answer("Тариф недоступен", show_alert=True)
        return

    if action == "promo":
        await state.set_state(PromoStates.waiting_code)
        await state.update_data(plan_code=plan_code, prebuy_msg_id=cb.message.message_id)
        await cb.message.answer(
            "🎟️ <b>Введи промокод</b>\n\nНапиши его одним сообщением. /cancel — отмена."
        )
        await cb.answer()
    elif action == "nopromo":
        text = _format_prebuy_text(plan)
        try:
            await cb.message.edit_text(text, reply_markup=_prebuy_kb(plan_code))
        except Exception:
            pass
        await cb.answer("Промокод убран")


@router.message(PromoStates.waiting_code, F.text)
async def on_promo_input(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        await state.clear()
        return
    code = (message.text or "").strip().upper()
    data = await state.get_data()
    plan_code = data.get("plan_code")
    await state.clear()

    if not plan_code or code.startswith("/"):
        return  # /cancel etc

    plan = await get_plan(plan_code)
    if not plan:
        return

    try:
        result = await promo_validate(message.from_user.id, code)
    except BackendError as e:
        await message.answer(f"⚠️ {e.message}")
        return

    if not result.get("valid"):
        reasons = {
            "not_found": "Промокод не найден",
            "inactive": "Промокод отключён",
            "expired": "Срок промокода истёк",
            "max_uses_reached": "Лимит использований промокода исчерпан",
            "already_used": "Ты уже использовал этот промокод",
        }
        msg = reasons.get(result.get("reason"), "Промокод недействителен")
        await message.answer(
            f"⚠️ {msg}.\n\nВернись к выбору тарифа — кнопка <b>🛒 Тарифы</b>."
        )
        return

    bonus = int(result.get("bonus_days", 0))
    code_norm = result.get("code", code)
    text = _format_prebuy_text(plan, promo_days=bonus, promo_code=code_norm)
    await message.answer(text, reply_markup=_prebuy_kb(plan_code, promo=code_norm))


@router.callback_query(F.data.startswith("pay:"))
async def on_pay(cb: CallbackQuery) -> None:
    if not cb.from_user or not cb.message:
        await cb.answer()
        return
    parts = cb.data.split(":", 2)
    plan_code = parts[1]
    promo = parts[2] if len(parts) > 2 and parts[2] else None

    plan = await get_plan(plan_code)
    if not plan or plan.get("is_trial"):
        await cb.answer("Тариф недоступен", show_alert=True)
        return
    stars = int(plan.get("price_stars") or 0)
    if stars <= 0:
        await cb.answer("Цена не настроена", show_alert=True)
        return

    traffic = "♾ безлимит" if not plan.get("traffic_limit_gb") else f"{plan['traffic_limit_gb']} GB"
    description = f"{plan['duration_days']} дн. · {traffic} · до {plan['device_limit']} устр."
    if promo:
        description += f" · промо {promo}"

    payload = f"plan:{plan_code}" + (f":promo:{promo}" if promo else "")

    try:
        await cb.message.answer_invoice(
            title=f"LOADIX VPN — {plan['name']}",
            description=description,
            payload=payload,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=plan["name"], amount=stars)],
            need_email=False,
            need_phone_number=False,
            need_shipping_address=False,
        )
    except Exception as e:
        log.exception("send_invoice (XTR) failed: %s", e)
        await screen_text(cb.message, f"⚠️ Не удалось создать счёт: {e}", delete_user_msg=False)
    await cb.answer()


# === Telegram Payments callbacks ===


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    sp = message.successful_payment
    if not sp or not message.from_user:
        return
    payload = sp.invoice_payload or ""
    if not payload.startswith("plan:"):
        log.warning("unknown payment payload: %s", payload)
        return

    parts = payload.split(":")
    plan_code = parts[1]
    promo_code = parts[3] if len(parts) >= 4 and parts[2] == "promo" else None

    try:
        if sp.currency == "XTR":
            await telegram_stars_paid_confirm(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                plan_code=plan_code,
                amount_stars=int(sp.total_amount),
                telegram_payment_charge_id=sp.telegram_payment_charge_id,
                promo_code=promo_code,
            )
        else:
            amount_rub = sp.total_amount / 100.0
            await telegram_paid_confirm(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                plan_code=plan_code,
                amount_rub=amount_rub,
                telegram_payment_charge_id=sp.telegram_payment_charge_id,
                provider_payment_charge_id=sp.provider_payment_charge_id,
            )
    except BackendError as e:
        log.exception("payment confirm failed: %s", e)
        await message.answer(
            f"⚠️ Оплата получена, но активация не удалась. Свяжитесь со @{settings.SUPPORT_USERNAME}.\n"
            f"ID платежа: <code>{sp.telegram_payment_charge_id}</code>"
        )
        return

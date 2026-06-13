import secrets
import string
import aiosqlite
import os
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from ..database.db import Database
from ..keyboards.inline import (
    promo_select_bot_keyboard, promo_list_keyboard,
    promo_info_keyboard, promo_confirm_keyboard, cancel_keyboard,
)
from ..utils.premium_emoji import pe

router = Router()


class PromoStates(StatesGroup):
    waiting_code = State()
    waiting_duration = State()
    waiting_max_uses = State()


def _gen_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(8))


@router.callback_query(F.data == "promo_menu")
async def cb_promo_menu(callback: CallbackQuery, db: Database):
    user = await db.get_or_create_user(callback.from_user.id, callback.from_user.username)
    franchises = await db.get_user_franchises(user.id)
    if not franchises:
        await callback.answer("У вас нет ботов", show_alert=True)
        return
    if len(franchises) == 1:
        await _show_franchise_promos(callback, db, franchises[0].id)
        return
    await callback.message.edit_text(
        pe("🎟️ <b>Промокоды</b>\n\nВыберите бота:"),
        parse_mode="HTML",
        reply_markup=promo_select_bot_keyboard(franchises),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("franchise_promos:"))
async def cb_franchise_promos(callback: CallbackQuery, db: Database):
    franchise_id = int(callback.data.split(":")[1])
    await _show_franchise_promos(callback, db, franchise_id)


async def _show_franchise_promos(callback: CallbackQuery, db: Database, franchise_id: int):
    franchise = await db.get_franchise(franchise_id)
    if not franchise:
        await callback.answer("Бот не найден", show_alert=True)
        return
    promos = await db.get_franchise_promos(franchise_id)
    price_7d = float(await db.get_setting("base_price_7d", "1.0"))
    text = pe(
        f"🎟️ <b>Промокоды — {franchise.display_name}</b>\n\n"
        f"Всего промокодов: <b>{len(promos)}</b>\n"
        f"💰 Цена промокода = кол-во дней × ${price_7d:.2f}/7д\n"
    )
    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=promo_list_keyboard(franchise_id, promos),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("promo_info:"))
async def cb_promo_info(callback: CallbackQuery, db: Database):
    promo_id = int(callback.data.split(":")[1])
    row = await db.get_promo_by_id(promo_id)
    if not row:
        await callback.answer("Промокод не найден", show_alert=True)
        return
    expires = row["expires_at"] or "Бессрочно"
    text = pe(
        f"🎟️ <b>Промокод: <code>{row['code']}</code></b>\n\n"
        f"📅 Дней подписки: <b>{row['duration_days']}</b>\n"
        f"Использований: <b>{row['uses_count']}/{row['max_uses']}</b>\n"
        f"Истекает: <b>{expires}</b>\n"
        f"💰 Стоимость: <b>${row['cost']:.2f}</b>"
    )
    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=promo_info_keyboard(promo_id, row["franchise_id"]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delete_promo:"))
async def cb_delete_promo(callback: CallbackQuery, db: Database):
    parts = callback.data.split(":")
    promo_id = int(parts[1])
    franchise_id = int(parts[2])
    await db.delete_promo(promo_id)
    await callback.answer("✅ Промокод удалён")
    await _show_franchise_promos(callback, db, franchise_id)


@router.callback_query(F.data.startswith("create_promo:"))
async def cb_create_promo(callback: CallbackQuery, state: FSMContext, db: Database):
    franchise_id = int(callback.data.split(":")[1])
    user = await db.get_or_create_user(callback.from_user.id, callback.from_user.username)
    await state.set_state(PromoStates.waiting_code)
    await state.update_data(franchise_id=franchise_id, user_id=user.id)
    code = _gen_code()
    await state.update_data(suggested_code=code)
    await callback.message.edit_text(
        f"🎟️ <b>Создание промокода</b>\n\n"
        f"Введите код или отправьте «+» чтобы использовать авто-генерацию:\n"
        f"Предложенный код: <code>{code}</code>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(PromoStates.waiting_code)
async def process_promo_code(message: Message, state: FSMContext):
    data = await state.get_data()
    if (message.text or "").strip() == "+":
        code = data["suggested_code"]
    else:
        code = (message.text or "").strip().upper()
        if len(code) < 3 or len(code) > 20:
            await message.answer("❌ Код должен быть от 3 до 20 символов.", reply_markup=cancel_keyboard())
            return
    await state.update_data(code=code)
    await state.set_state(PromoStates.waiting_duration)
    await message.answer(
        f"✅ Код: <code>{code}</code>\n\n"
        f"Введите количество дней подписки (например: <code>30</code>):",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@router.message(PromoStates.waiting_duration)
async def process_promo_duration(message: Message, state: FSMContext):
    try:
        days = int((message.text or "").strip())
        if days < 1 or days > 365:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите число от 1 до 365.", reply_markup=cancel_keyboard())
        return
    await state.update_data(duration_days=days)
    await state.set_state(PromoStates.waiting_max_uses)
    await message.answer(
        f"✅ Дней подписки: <b>{days}</b>\n\n"
        f"Введите максимальное количество использований:",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@router.message(PromoStates.waiting_max_uses)
async def process_promo_max_uses(message: Message, state: FSMContext, db: Database):
    try:
        max_uses = int((message.text or "").strip())
        if max_uses < 1:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите число >= 1.", reply_markup=cancel_keyboard())
        return

    data = await state.get_data()
    user = await db.get_or_create_user(message.from_user.id, message.from_user.username)

    price_7d = float(await db.get_setting("base_price_7d", "1.0"))
    duration_days = data["duration_days"]
    cost_per_use = round(price_7d / 7 * duration_days, 2)
    total_cost = round(cost_per_use * max_uses, 2)

    if user.balance < total_cost:
        await state.clear()
        await message.answer(
            f"❌ Недостаточно средств.\n"
            f"Нужно: <b>${total_cost:.2f}</b>, у вас: <b>${user.balance:.2f}</b>",
            parse_mode="HTML",
        )
        return

    await state.update_data(max_uses=max_uses, total_cost=total_cost)
    await message.answer(
        f"🎟️ <b>Подтверждение</b>\n\n"
        f"Код: <code>{data['code']}</code>\n"
        f"Дней подписки: <b>{data['duration_days']}</b>\n"
        f"Макс. использований: <b>{max_uses}</b>\n"
        f"Цена 1 использования: <b>${cost_per_use:.2f}</b> ({duration_days}д × ${price_7d:.2f}/7д)\n"
        f"Итого: <b>${total_cost:.2f}</b> будет списано с баланса\n\n"
        f"Ваш баланс после: <b>${user.balance - total_cost:.2f}</b>",
        parse_mode="HTML",
        reply_markup=promo_confirm_keyboard(data["franchise_id"]),
    )


@router.callback_query(F.data.startswith("confirm_promo:"))
async def cb_confirm_promo(callback: CallbackQuery, state: FSMContext, db: Database):
    data = await state.get_data()
    if not data:
        await callback.answer("Сессия устарела", show_alert=True)
        return

    franchise_id = int(callback.data.split(":")[1])
    franchise = await db.get_franchise(franchise_id)
    user = await db.get_or_create_user(callback.from_user.id, callback.from_user.username)
    total_cost = data["total_cost"]

    if user.balance < total_cost:
        await callback.answer("❌ Недостаточно средств", show_alert=True)
        await state.clear()
        return

    promo = await db.create_promo(
        franchise_id=franchise_id,
        code=data["code"],
        duration_days=data["duration_days"],
        max_uses=data["max_uses"],
        cost=total_cost,
        expires_at=None,
    )
    await db.update_balance(user.id, -total_cost, "promo_cost", f"Промокод {data['code']}")
    await state.clear()

    await _sync_promo_to_instance(franchise, promo.code, promo.duration_days, promo.max_uses)

    await callback.message.edit_text(
        f"✅ Промокод <code>{promo.code}</code> создан!\n"
        f"Списано с баланса: <b>${total_cost:.2f}</b>",
        parse_mode="HTML",
    )
    await _show_franchise_promos(callback, db, franchise_id)


async def _sync_promo_to_instance(franchise, code: str, duration_days: int, max_uses: int):
    if not franchise.instance_dir:
        return
    db_path = os.path.join(franchise.instance_dir, "data", "bot.db")
    if not os.path.exists(db_path):
        return
    try:
        async with aiosqlite.connect(db_path) as conn:
            await conn.execute(
                """INSERT OR IGNORE INTO promocodes
                   (code, duration_days, max_uses, uses_count, is_subscription)
                   VALUES (?, ?, ?, 0, 1)""",
                (code, duration_days, max_uses)
            )
            await conn.commit()
    except Exception:
        pass

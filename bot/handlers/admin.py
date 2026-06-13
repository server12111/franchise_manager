from aiogram import Router, F
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from ..database.db import Database
from ..keyboards.inline import (
    admin_keyboard, admin_settings_keyboard,
    admin_user_keyboard, admin_withdrawals_keyboard,
)
from ..services.stats_reader import StatsReader
from ..config import config
from ..utils.premium_emoji import pe

router = Router()


class IsAdmin(Filter):
    async def __call__(self, event) -> bool:
        uid = getattr(event.from_user, "id", None)
        return uid == config.ADMIN_ID


class AdminSettingStates(StatesGroup):
    waiting_value = State()


class AdminBalanceStates(StatesGroup):
    waiting_amount = State()


router.callback_query.filter(IsAdmin())
router.message.filter(IsAdmin())


@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    await callback.message.edit_text(
        pe("👑 <b>Админ-панель</b>\n\nВыберите раздел:"),
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_all_bots")
async def cb_admin_all_bots(callback: CallbackQuery, db: Database):
    franchises = await db.get_all_franchises()
    if not franchises:
        await callback.answer("Нет ботов", show_alert=True)
        return
    text = pe("🤖 <b>Все боты</b>\n\n")
    for f in franchises:
        status = "🟢" if f.status == "running" else "🔴"
        text += pe(f"{status} {f.display_name} | наценка {f.markup_percent:.0f}%\n")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_back_to_admin_kb())
    await callback.answer()


@router.callback_query(F.data == "admin_global_stats")
async def cb_admin_global_stats(callback: CallbackQuery, db: Database):
    franchises = await db.get_all_franchises()
    total_users = total_revenue = total_blocked = 0
    for f in franchises:
        s = await StatsReader.read(f.instance_dir)
        total_users += s.get("users_total", 0)
        total_revenue += s.get("revenue_total", 0)
        total_blocked += s.get("users_blocked", 0)
    text = pe(
        f"📊 <b>Общая статистика</b>\n\n"
        f"🤖 Всего ботов: <b>{len(franchises)}</b>\n"
        f"👥 Пользователей (суммарно): <b>{total_users}</b>\n"
        f"🚫 Заблокировали (суммарно): <b>{total_blocked}</b>\n"
        f"💰 Заработано (суммарно): <b>${total_revenue:.2f}</b>\n"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_back_to_admin_kb())
    await callback.answer()


@router.callback_query(F.data == "admin_users")
async def cb_admin_users(callback: CallbackQuery, db: Database):
    users = await db.get_all_users()
    if not users:
        await callback.answer("Нет пользователей", show_alert=True)
        return
    text = pe("👥 <b>Пользователи</b>\n\n")
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    for u in users[:20]:
        label = f"@{u.username}" if u.username else f"ID {u.telegram_id}"
        builder.row(InlineKeyboardButton(
            text=f"{label} | ${u.balance:.2f}",
            callback_data=f"admin_user:{u.telegram_id}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel"))
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("admin_user:"))
async def cb_admin_user(callback: CallbackQuery, db: Database):
    target_tid = int(callback.data.split(":")[1])
    user = await db.get_user(target_tid)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    label = f"@{user.username}" if user.username else f"ID {user.telegram_id}"
    text = pe(
        f"👤 <b>{label}</b>\n\n"
        f"ID: <code>{user.telegram_id}</code>\n"
        f"💰 Баланс: <b>${user.balance:.2f}</b>\n"
        f"Регистрация: {user.created_at.strftime('%d.%m.%Y') if user.created_at else '—'}"
    )
    await callback.message.edit_text(text, parse_mode="HTML",
                                     reply_markup=admin_user_keyboard(user.telegram_id))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_add_balance:"))
async def cb_admin_add_balance(callback: CallbackQuery, state: FSMContext):
    target_tid = int(callback.data.split(":")[1])
    await state.set_state(AdminBalanceStates.waiting_amount)
    await state.update_data(target_tid=target_tid, operation="add")
    await callback.message.edit_text(
        pe("➕ Введите сумму для начисления (в долларах):\nПример: <code>10.00</code>"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_sub_balance:"))
async def cb_admin_sub_balance(callback: CallbackQuery, state: FSMContext):
    target_tid = int(callback.data.split(":")[1])
    await state.set_state(AdminBalanceStates.waiting_amount)
    await state.update_data(target_tid=target_tid, operation="sub")
    await callback.message.edit_text(
        pe("➖ Введите сумму для списания (в долларах):\nПример: <code>5.00</code>"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminBalanceStates.waiting_amount)
async def process_admin_balance(message: Message, state: FSMContext, db: Database):
    try:
        amount = float((message.text or "").strip().replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer(pe("❌ Введите положительное число."), parse_mode="HTML")
        return

    data = await state.get_data()
    target_tid = data["target_tid"]
    operation = data["operation"]
    user = await db.get_user(target_tid)
    if not user:
        await state.clear()
        await message.answer(pe("❌ Пользователь не найден."), parse_mode="HTML")
        return

    if operation == "add":
        await db.update_balance(user.id, amount, "admin_deposit", "Начисление от администратора")
        await message.answer(pe(f"✅ Начислено <b>${amount:.2f}</b>"), parse_mode="HTML")
    else:
        if user.balance < amount:
            await state.clear()
            await message.answer(pe(f"❌ У пользователя только ${user.balance:.2f}"), parse_mode="HTML")
            return
        await db.update_balance(user.id, -amount, "admin_deduct", "Списание администратором")
        await message.answer(pe(f"✅ Списано <b>${amount:.2f}</b>"), parse_mode="HTML")

    try:
        from aiogram import Bot
        bot_instance = Bot(token=message.bot.token)
        direction = "начислено" if operation == "add" else "списано"
        await bot_instance.send_message(
            user.telegram_id,
            pe(f"💰 Администратор {direction} <b>${amount:.2f}</b> на ваш баланс."),
            parse_mode="HTML"
        )
        await bot_instance.session.close()
    except Exception:
        pass

    await state.clear()


@router.callback_query(F.data == "admin_settings")
async def cb_admin_settings(callback: CallbackQuery, db: Database):
    s = await db.get_all_settings()
    text = pe(
        f"⚙️ <b>Настройки системы</b>\n\n"
        f"📅 Цена 7 дней (база): <b>${float(s.get('base_price_7d', 1.0)):.2f}</b>\n"
        f"📅 Цена 30 дней (база): <b>${float(s.get('base_price_30d', 3.0)):.2f}</b>\n"
        f"💵 Мин. наценка (MIN): <b>${float(s.get('min_subscription_price', 3.0)):.2f}</b>\n"
        f"🎟️ Цена промокода (за исп.): <b>${float(s.get('promo_cost_per_use', 0.5)):.2f}</b>\n"
        f"💸 Комиссия вывода: <b>{float(s.get('withdrawal_commission', 0.07))*100:.0f}%</b>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_settings_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("admin_set:"))
async def cb_admin_set_value(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[1]
    labels = {
        "base_price_7d": "базовую цену за 7 дней подписки (в $)",
        "base_price_30d": "базовую цену за 30 дней подписки (в $)",
        "min_subscription_price": "минимальный порог наценки (в $)",
        "promo_cost_per_use": "стоимость одного использования промокода (в $)",
        "withdrawal_commission": "комиссию вывода (например: 0.07 = 7%)",
    }
    await state.set_state(AdminSettingStates.waiting_value)
    await state.update_data(setting_key=key)
    await callback.message.edit_text(
        pe(f"⚙️ Введите новое значение для «{labels.get(key, key)}»:"),
        parse_mode="HTML",
        reply_markup=_back_to_admin_kb(),
    )
    await callback.answer()


@router.message(AdminSettingStates.waiting_value)
async def process_admin_setting(message: Message, state: FSMContext, db: Database):
    try:
        val = float((message.text or "").strip().replace(",", "."))
        if val < 0:
            raise ValueError
    except ValueError:
        await message.answer(pe("❌ Введите положительное число."), parse_mode="HTML")
        return

    data = await state.get_data()
    key = data["setting_key"]
    await db.set_setting(key, str(val))
    await state.clear()
    await message.answer(
        pe(f"✅ Настройка обновлена: <b>{val}</b>"),
        parse_mode="HTML",
        reply_markup=_back_to_admin_kb()
    )


@router.callback_query(F.data == "admin_withdrawals")
async def cb_admin_withdrawals(callback: CallbackQuery, db: Database):
    requests = await db.get_pending_withdrawals()
    if not requests:
        await callback.answer("Нет заявок на вывод", show_alert=True)
        return
    await callback.message.edit_text(
        pe(f"💸 <b>Заявки на вывод ({len(requests)})</b>"),
        parse_mode="HTML",
        reply_markup=admin_withdrawals_keyboard(requests),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_withdrawal:"))
async def cb_admin_withdrawal_detail(callback: CallbackQuery, db: Database):
    request_id = int(callback.data.split(":")[1])
    req = await db.get_withdrawal(request_id)
    if not req:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    user = await db.get_user_by_id(req.user_id)
    method_name = "TON" if req.method == "ton" else "CryptoBot"
    username_str = f"@{user.username}" if (user and user.username) else f"ID {user.telegram_id if user else '?'}"
    text = pe(
        f"💸 <b>Заявка на вывод #{req.id}</b>\n\n"
        f"От: {username_str}\n"
        f"Сумма: <b>${req.amount:.2f}</b>\n"
        f"Комиссия: <b>${req.commission:.2f}</b>\n"
        f"К выплате: <b>${req.net_amount:.2f}</b>\n"
        f"Способ: <b>{method_name}</b>\n"
        f"Кошелёк: <code>{req.wallet}</code>\n"
        f"Статус: <b>{req.status}</b>"
    )
    from ..keyboards.inline import admin_withdrawal_keyboard
    await callback.message.edit_text(text, parse_mode="HTML",
                                     reply_markup=admin_withdrawal_keyboard(request_id))
    await callback.answer()


@router.callback_query(F.data.startswith("approve_withdraw:"))
async def cb_approve_withdraw(callback: CallbackQuery, db: Database):
    request_id = int(callback.data.split(":")[1])
    req = await db.get_withdrawal(request_id)
    if not req or req.status != "pending":
        await callback.answer("Заявка уже обработана", show_alert=True)
        return
    await db.process_withdrawal(request_id, "approved")
    await callback.answer("✅ Одобрено")
    await callback.message.edit_text(
        pe(f"✅ Заявка #{request_id} одобрена. Выплатите <b>${req.net_amount:.2f}</b> на {req.wallet}"),
        parse_mode="HTML", reply_markup=_back_to_admin_kb()
    )
    user = await db.get_user_by_id(req.user_id)
    if user:
        try:
            from aiogram import Bot
            bot_instance = Bot(token=callback.bot.token)
            method_name = "TON" if req.method == "ton" else "CryptoBot"
            await bot_instance.send_message(
                user.telegram_id,
                pe(
                    f"✅ Ваша заявка на вывод <b>${req.amount:.2f}</b> одобрена!\n"
                    f"Средства (<b>${req.net_amount:.2f}</b>) отправлены на ваш {method_name}-кошелёк."
                ),
                parse_mode="HTML"
            )
            await bot_instance.session.close()
        except Exception:
            pass


@router.callback_query(F.data.startswith("reject_withdraw:"))
async def cb_reject_withdraw(callback: CallbackQuery, db: Database):
    request_id = int(callback.data.split(":")[1])
    req = await db.get_withdrawal(request_id)
    if not req or req.status != "pending":
        await callback.answer("Заявка уже обработана", show_alert=True)
        return
    await db.process_withdrawal(request_id, "rejected")
    user = await db.get_user_by_id(req.user_id)
    if user:
        await db.update_balance(user.id, req.amount, "withdrawal_return", f"Возврат по заявке #{request_id}")
    await callback.answer("❌ Отклонено")
    await callback.message.edit_text(
        pe(f"❌ Заявка #{request_id} отклонена. Средства возвращены пользователю."),
        parse_mode="HTML",
        reply_markup=_back_to_admin_kb()
    )
    if user:
        try:
            from aiogram import Bot
            bot_instance = Bot(token=callback.bot.token)
            await bot_instance.send_message(
                user.telegram_id,
                pe(
                    f"❌ Ваша заявка на вывод <b>${req.amount:.2f}</b> отклонена.\n"
                    "Средства возвращены на ваш баланс."
                ),
                parse_mode="HTML"
            )
            await bot_instance.session.close()
        except Exception:
            pass


def _back_to_admin_kb():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel"))
    return builder.as_markup()

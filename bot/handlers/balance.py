from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from ..database.db import Database
from ..keyboards.inline import (
    balance_keyboard, withdrawal_method_keyboard,
    withdrawal_confirm_keyboard, back_to_menu, cancel_keyboard,
)
from ..config import config
from ..utils.premium_emoji import pe

router = Router()


class WithdrawStates(StatesGroup):
    waiting_amount = State()
    waiting_wallet = State()


# === Баланс ===

@router.callback_query(F.data == "balance")
async def cb_balance(callback: CallbackQuery, db: Database):
    user = await db.get_or_create_user(callback.from_user.id, callback.from_user.username)
    commission = float(await db.get_setting("withdrawal_commission", str(config.WITHDRAWAL_COMMISSION)))
    text = pe(
        f"💰 <b>Баланс</b>\n\n"
        f"Доступно: <b>${user.balance:.2f}</b>\n\n"
        f"💸 Комиссия на вывод: {int(commission * 100)}%"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=balance_keyboard())
    await callback.answer()


@router.callback_query(F.data == "tx_history")
async def cb_tx_history(callback: CallbackQuery, db: Database):
    user = await db.get_or_create_user(callback.from_user.id, callback.from_user.username)
    txs = await db.get_user_transactions(user.id)
    if not txs:
        text = "📋 <b>История транзакций</b>\n\nПока нет операций."
    else:
        text = "📋 <b>История транзакций</b>\n\n"
        for tx in txs:
            sign = "+" if tx.amount >= 0 else ""
            dt = tx.created_at.strftime("%d.%m %H:%M") if tx.created_at else ""
            text += f"{sign}${tx.amount:.2f} — {tx.description or tx.type} <i>{dt}</i>\n"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=balance_keyboard())
    await callback.answer()


# === Вывод ===

@router.callback_query(F.data == "withdraw")
async def cb_withdraw(callback: CallbackQuery, state: FSMContext, db: Database):
    user = await db.get_or_create_user(callback.from_user.id, callback.from_user.username)
    if user.balance < 1.0:
        await callback.answer("❌ Минимальная сумма вывода $1.00", show_alert=True)
        return
    commission = float(await db.get_setting("withdrawal_commission", str(config.WITHDRAWAL_COMMISSION)))
    await state.set_state(WithdrawStates.waiting_amount)
    await state.update_data(commission_rate=commission)
    await callback.message.edit_text(
        pe(
            f"💸 <b>Вывод средств</b>\n\n"
            f"Доступно: <b>${user.balance:.2f}</b>\n"
            f"Комиссия: <b>{int(commission * 100)}%</b>\n\n"
            f"Введите сумму для вывода (мин. $1.00):"
        ),
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(WithdrawStates.waiting_amount)
async def process_withdraw_amount(message: Message, state: FSMContext, db: Database):
    try:
        amount = float((message.text or "").strip().replace(",", "."))
        if amount < 1.0:
            raise ValueError
    except ValueError:
        await message.answer(pe("❌ Введите сумму от $1.00"), parse_mode="HTML", reply_markup=cancel_keyboard())
        return

    user = await db.get_or_create_user(message.from_user.id, message.from_user.username)
    if amount > user.balance:
        await message.answer(
            pe(f"❌ Недостаточно средств. Доступно: <b>${user.balance:.2f}</b>"),
            parse_mode="HTML", reply_markup=cancel_keyboard()
        )
        return

    data = await state.get_data()
    commission_rate = data.get("commission_rate", config.WITHDRAWAL_COMMISSION)
    commission = round(amount * commission_rate, 4)
    net = round(amount - commission, 4)
    await state.update_data(amount=amount, commission=commission, net=net)
    await state.set_state(WithdrawStates.waiting_wallet)
    await message.answer(
        pe(
            f"💸 Сумма к выводу: <b>${amount:.2f}</b>\n"
            f"Комиссия ({int(commission_rate*100)}%): <b>-${commission:.2f}</b>\n"
            f"Вы получите: <b>${net:.2f}</b>\n\n"
            f"Выберите способ вывода:"
        ),
        parse_mode="HTML",
        reply_markup=withdrawal_method_keyboard(),
    )


@router.callback_query(F.data.startswith("withdraw_method:"), WithdrawStates.waiting_wallet)
async def process_withdraw_method(callback: CallbackQuery, state: FSMContext):
    method = callback.data.split(":")[1]
    await state.update_data(method=method)
    method_name = "TON-кошелёк" if method == "ton" else "CryptoBot username/кошелёк"
    await callback.message.edit_text(
        f"📝 Введите ваш {method_name} для получения средств:",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(WithdrawStates.waiting_wallet)
async def process_withdraw_wallet(message: Message, state: FSMContext, db: Database):
    wallet = (message.text or "").strip()
    if not wallet:
        await message.answer("❌ Введите адрес кошелька.", reply_markup=cancel_keyboard())
        return

    data = await state.get_data()
    amount = data["amount"]
    commission = data["commission"]
    net = data["net"]
    method = data.get("method", "ton")
    commission_rate = data.get("commission_rate", config.WITHDRAWAL_COMMISSION)

    user = await db.get_or_create_user(message.from_user.id, message.from_user.username)
    if amount > user.balance:
        await state.clear()
        await message.answer("❌ Недостаточно средств.", reply_markup=back_to_menu())
        return

    request = await db.create_withdrawal(user.id, amount, commission, net, method, wallet)

    await db.update_balance(user.id, -amount, "withdrawal", f"Заявка на вывод #{request.id}")
    await state.clear()

    method_name = "TON" if method == "ton" else "CryptoBot"
    await message.answer(
        pe(
            f"✅ <b>Заявка на вывод создана!</b>\n\n"
            f"Сумма: <b>${amount:.2f}</b>\n"
            f"К получению: <b>${net:.2f}</b>\n"
            f"Способ: <b>{method_name}</b>\n"
            f"Кошелёк: <code>{wallet}</code>\n\n"
            f"⏳ Ожидайте подтверждения от администратора."
        ),
        parse_mode="HTML",
        reply_markup=back_to_menu(),
    )

    try:
        from aiogram import Bot
        bot = Bot(token=message.bot.token)
        username = f"@{message.from_user.username}" if message.from_user.username else f"ID {message.from_user.id}"
        await bot.send_message(
            config.ADMIN_ID,
            f"💸 <b>Новая заявка на вывод #{request.id}</b>\n\n"
            f"От: {username}\n"
            f"Сумма: <b>${amount:.2f}</b>\n"
            f"К выплате: <b>${net:.2f}</b> (за вычетом {int(commission_rate*100)}%)\n"
            f"Способ: <b>{method_name}</b>\n"
            f"Кошелёк: <code>{wallet}</code>",
            parse_mode="HTML",
            reply_markup=_admin_withdrawal_kb(request.id),
        )
        await bot.session.close()
    except Exception:
        pass


def _admin_withdrawal_kb(request_id: int):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_withdraw:{request_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_withdraw:{request_id}"),
    )
    return builder.as_markup()

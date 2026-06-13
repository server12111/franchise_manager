from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from ..database.db import Database
from ..keyboards.inline import main_menu_keyboard, back_to_menu
from ..config import config
from ..utils.premium_emoji import pe

router = Router()


def is_admin(telegram_id: int) -> bool:
    return telegram_id == config.ADMIN_ID


async def show_main_menu(message: Message, db: Database):
    user = await db.get_or_create_user(message.from_user.id, message.from_user.username)
    admin = is_admin(message.from_user.id)
    text = pe(
        f"👋 Добро пожаловать, <b>{message.from_user.first_name}</b>!\n\n"
        f"💰 Баланс: <b>${user.balance:.2f}</b>\n\n"
        "Выберите раздел:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_keyboard(admin))


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database):
    await db.get_or_create_user(message.from_user.id, message.from_user.username)
    await show_main_menu(message, db)


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, db: Database):
    user = await db.get_or_create_user(callback.from_user.id, callback.from_user.username)
    admin = is_admin(callback.from_user.id)
    text = pe(
        f"💰 Баланс: <b>${user.balance:.2f}</b>\n\n"
        "Выберите раздел:"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard(admin))
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    user = await db.get_or_create_user(callback.from_user.id, callback.from_user.username)
    admin = is_admin(callback.from_user.id)
    text = pe(
        f"💰 Баланс: <b>${user.balance:.2f}</b>\n\n"
        "Выберите раздел:"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard(admin))
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=main_menu_keyboard(admin))
    await callback.answer()

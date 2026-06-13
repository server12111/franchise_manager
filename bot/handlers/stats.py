from aiogram import Router, F
from aiogram.types import CallbackQuery

from ..database.db import Database
from ..keyboards.inline import stats_select_bot_keyboard, back_to_franchise_keyboard, back_to_menu
from ..services.stats_reader import StatsReader
from ..utils.premium_emoji import pe

router = Router()


@router.callback_query(F.data == "stats_menu")
async def cb_stats_menu(callback: CallbackQuery, db: Database):
    user = await db.get_or_create_user(callback.from_user.id, callback.from_user.username)
    franchises = await db.get_user_franchises(user.id)
    if not franchises:
        await callback.answer("У вас нет ботов", show_alert=True)
        return
    if len(franchises) == 1:
        await _show_franchise_stats(callback, db, franchises[0].id)
        return
    await callback.message.edit_text(
        "📊 <b>Статистика</b>\n\nВыберите бота:",
        parse_mode="HTML",
        reply_markup=stats_select_bot_keyboard(franchises),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("franchise_stats:"))
async def cb_franchise_stats(callback: CallbackQuery, db: Database):
    franchise_id = int(callback.data.split(":")[1])
    await _show_franchise_stats(callback, db, franchise_id)


async def _show_franchise_stats(callback: CallbackQuery, db: Database, franchise_id: int):
    franchise = await db.get_franchise(franchise_id)
    if not franchise:
        await callback.answer("Бот не найден", show_alert=True)
        return

    stats = await StatsReader.read(franchise.instance_dir) if franchise.instance_dir else {}

    text = pe(
        f"📊 <b>Статистика — {franchise.display_name}</b>\n\n"
        f"👥 Всего пользователей: <b>{stats.get('users_total', 0)}</b>\n"
        f"🚫 Заблокировали бота: <b>{stats.get('users_blocked', 0)}</b>\n"
        f"💎 Активных подписчиков: <b>{stats.get('subscribers_active', 0)}</b>\n"
        f"💰 Заработано (всего): <b>${stats.get('revenue_total', 0):.2f}</b>\n"
        f"📱 Аккаунтов Telegram: <b>{stats.get('accounts_count', 0)}</b>\n"
        f"📤 Активных рассылок: <b>{stats.get('mailings_active', 0)}</b>\n"
    )
    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=back_to_franchise_keyboard(franchise_id),
    )
    await callback.answer()

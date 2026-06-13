import os
import aiohttp
import aiosqlite
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from ..database.db import Database
from ..keyboards.inline import (
    my_bots_keyboard, franchise_menu_keyboard,
    confirm_delete_bot_keyboard, cancel_keyboard, back_to_menu,
)
from ..services.process_manager import ProcessManager
from ..config import config
from ..utils.premium_emoji import pe

router = Router()


class BotCreationStates(StatesGroup):
    waiting_token = State()


class MarkupStates(StatesGroup):
    waiting_markup = State()


async def _validate_token(token: str) -> tuple[bool, str, str]:
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                if data.get("ok"):
                    bot = data["result"]
                    return True, bot.get("username", ""), bot.get("first_name", "")
                return False, "", ""
    except Exception:
        return False, "", ""


async def _sync_prices_to_instance_db(instance_dir: str, price_7d: float, price_30d: float):
    """Записывает цены подписки в SQLite экземпляра — текст в боте обновится сразу."""
    db_path = os.path.join(instance_dir, "data", "bot.db")
    if not os.path.exists(db_path):
        return
    try:
        async with aiosqlite.connect(db_path) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('price_7d', ?)", (str(price_7d),)
            )
            await conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('price_30d', ?)", (str(price_30d),)
            )
            await conn.commit()
    except Exception:
        pass


# === Список ботов ===

@router.callback_query(F.data == "my_bots")
async def cb_my_bots(callback: CallbackQuery, db: Database):
    user = await db.get_or_create_user(callback.from_user.id, callback.from_user.username)
    franchises = await db.get_user_franchises(user.id)
    text = pe("🤖 <b>Мои боты</b>\n\n")
    if franchises:
        text += f"Ваш бот:"
    else:
        text += "У вас пока нет бота.\nНажмите «➕ Создать бота» чтобы начать."
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=my_bots_keyboard(franchises))
    await callback.answer()


# === Открыть меню конкретного бота ===

@router.callback_query(F.data.startswith("franchise:"))
async def cb_franchise_menu(callback: CallbackQuery, db: Database):
    franchise_id = int(callback.data.split(":")[1])
    franchise = await db.get_franchise(franchise_id)
    if not franchise:
        await callback.answer("Бот не найден", show_alert=True)
        return
    status_text = "🟢 Запущен" if franchise.status == "running" else "🔴 Остановлен"
    text = pe(
        f"🤖 <b>{franchise.display_name}</b>\n\n"
        f"Статус: <b>{status_text}</b>\n"
        f"💰 Наценка: <b>{franchise.markup_percent:.1f}%</b>\n"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=franchise_menu_keyboard(franchise))
    await callback.answer()


# === Создание бота ===

@router.callback_query(F.data == "create_bot")
async def cb_create_bot(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BotCreationStates.waiting_token)
    await callback.message.edit_text(
        pe(
            "🤖 <b>Создание бота</b>\n\n"
            "Отправьте токен вашего бота.\n"
            "Получить токен можно у @BotFather → /newbot\n\n"
            "<i>Пример: 1234567890:ABCdef...</i>"
        ),
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(BotCreationStates.waiting_token)
async def process_bot_token(message: Message, state: FSMContext, db: Database, pm: ProcessManager):
    token = (message.text or "").strip()
    if ":" not in token or len(token) < 30:
        await message.answer(
            pe("❌ Неверный формат токена. Попробуйте ещё раз или нажмите Отмена."),
            parse_mode="HTML",
            reply_markup=cancel_keyboard()
        )
        return

    user = await db.get_or_create_user(message.from_user.id, message.from_user.username)

    existing = await db.get_user_franchises(user.id)
    if existing:
        await state.clear()
        await message.answer(
            pe("❌ У вас уже есть бот. Один аккаунт — один бот.\n\nУправляйте им через меню «🤖 Мои боты»."),
            parse_mode="HTML",
            reply_markup=back_to_menu(),
        )
        return

    if await db.get_franchise_by_token(token):
        await message.answer(pe("❌ Этот токен уже используется."), parse_mode="HTML", reply_markup=cancel_keyboard())
        return

    status_msg = await message.answer(pe("⏳ Проверяю токен..."), parse_mode="HTML")
    ok, username, name = await _validate_token(token)
    if not ok:
        await status_msg.edit_text(
            pe("❌ Токен недействителен. Проверьте и попробуйте снова."),
            parse_mode="HTML", reply_markup=cancel_keyboard()
        )
        return

    await status_msg.edit_text(pe(f"✅ Бот @{username} найден. Создаю экземпляр..."), parse_mode="HTML")

    instance_dir = os.path.join("instances", str(user.id) + "_" + username)
    os.makedirs(os.path.join(instance_dir, "data"), exist_ok=True)
    os.makedirs(os.path.join(instance_dir, "sessions"), exist_ok=True)

    min_price = await db.get_setting("min_subscription_price", "3.0")
    _write_instance_env(instance_dir, token, message.from_user.id, float(min_price), float(min_price))

    franchise = await db.create_franchise(user.id, token, username, name, instance_dir)
    await state.clear()

    ok_start = pm.start(franchise.id, token, instance_dir, message.from_user.id, float(min_price))
    if ok_start:
        await db.update_franchise_status(franchise.id, "running", pm.get_pid(franchise.id))
        await status_msg.edit_text(
            pe(
                f"✅ Бот <b>@{username}</b> создан и запущен!\n\n"
                "Теперь вы можете управлять им через меню."
            ),
            parse_mode="HTML",
        )
    else:
        await status_msg.edit_text(
            pe(
                f"⚠️ Бот <b>@{username}</b> создан, но не удалось запустить.\n"
                "Попробуйте запустить вручную из меню."
            ),
            parse_mode="HTML",
        )

    franchises = await db.get_user_franchises(user.id)
    await message.answer(pe("🤖 Ваши боты:"), parse_mode="HTML", reply_markup=my_bots_keyboard(franchises))


# === Запуск / Остановка / Перезапуск ===

@router.callback_query(F.data.startswith("start_bot:"))
async def cb_start_bot(callback: CallbackQuery, db: Database, pm: ProcessManager):
    franchise_id = int(callback.data.split(":")[1])
    franchise = await db.get_franchise(franchise_id)
    if not franchise:
        await callback.answer("Бот не найден", show_alert=True)
        return
    base_30d = float(await db.get_setting("base_price_30d", "3.0"))
    price = round(base_30d * (1 + franchise.markup_percent / 100), 2)
    owner = await db.get_user_by_id(franchise.user_id)
    owner_id = owner.telegram_id if owner else callback.from_user.id
    ok = pm.start(franchise.id, franchise.bot_token, franchise.instance_dir,
                  owner_id, price, franchise.markup_percent)
    if ok:
        await db.update_franchise_status(franchise.id, "running", pm.get_pid(franchise.id))
        await callback.answer("✅ Бот запущен")
    else:
        await callback.answer("❌ Не удалось запустить бота", show_alert=True)
    franchise = await db.get_franchise(franchise_id)
    await callback.message.edit_reply_markup(reply_markup=franchise_menu_keyboard(franchise))


@router.callback_query(F.data.startswith("stop_bot:"))
async def cb_stop_bot(callback: CallbackQuery, db: Database, pm: ProcessManager):
    franchise_id = int(callback.data.split(":")[1])
    franchise = await db.get_franchise(franchise_id)
    if not franchise:
        await callback.answer("Бот не найден", show_alert=True)
        return
    pm.stop(franchise.id, franchise.pid)
    await db.update_franchise_status(franchise.id, "stopped", None)
    await callback.answer("⏹️ Бот остановлен")
    franchise = await db.get_franchise(franchise_id)
    await callback.message.edit_reply_markup(reply_markup=franchise_menu_keyboard(franchise))


@router.callback_query(F.data.startswith("restart_bot:"))
async def cb_restart_bot(callback: CallbackQuery, db: Database, pm: ProcessManager):
    franchise_id = int(callback.data.split(":")[1])
    franchise = await db.get_franchise(franchise_id)
    if not franchise:
        await callback.answer("Бот не найден", show_alert=True)
        return
    pm.stop(franchise.id, franchise.pid)
    base_30d = float(await db.get_setting("base_price_30d", "3.0"))
    price = round(base_30d * (1 + franchise.markup_percent / 100), 2)
    owner = await db.get_user_by_id(franchise.user_id)
    owner_id = owner.telegram_id if owner else callback.from_user.id
    pm.start(franchise.id, franchise.bot_token, franchise.instance_dir,
             owner_id, price, franchise.markup_percent)
    await db.update_franchise_status(franchise.id, "running", pm.get_pid(franchise.id))
    await callback.answer("🔄 Бот перезапущен")
    franchise = await db.get_franchise(franchise_id)
    await callback.message.edit_reply_markup(reply_markup=franchise_menu_keyboard(franchise))


# === Наценка ===

@router.callback_query(F.data.startswith("set_markup:"))
async def cb_set_markup(callback: CallbackQuery, state: FSMContext, db: Database):
    franchise_id = int(callback.data.split(":")[1])
    franchise = await db.get_franchise(franchise_id)
    base_7d = float(await db.get_setting("base_price_7d", "1.0"))
    base_30d = float(await db.get_setting("base_price_30d", "3.0"))
    await state.set_state(MarkupStates.waiting_markup)
    await state.update_data(franchise_id=franchise_id)
    example_7d = round(base_7d * 1.3, 2)
    example_30d = round(base_30d * 1.3, 2)
    await callback.message.edit_text(
        pe(
            f"💰 <b>Настройка наценки</b>\n\n"
            f"Текущая наценка: <b>{franchise.markup_percent:.1f}%</b>\n"
            f"Базовые цены: <b>7д = ${base_7d:.2f}</b> | <b>30д = ${base_30d:.2f}</b>\n\n"
            f"Введите наценку в процентах (0 = без наценки).\n"
            f"Например: <code>30</code> → 7д = <b>${example_7d}</b>, 30д = <b>${example_30d}</b>"
        ),
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(MarkupStates.waiting_markup)
async def process_markup(message: Message, state: FSMContext, db: Database, pm: ProcessManager):
    try:
        markup = float((message.text or "").strip().replace(",", "."))
        if markup < 0:
            raise ValueError
    except ValueError:
        await message.answer(pe("❌ Введите число >= 0. Например: <code>50</code>"), parse_mode="HTML")
        return

    data = await state.get_data()
    franchise_id = data["franchise_id"]
    franchise = await db.get_franchise(franchise_id)
    await db.update_franchise_markup(franchise_id, markup)
    await state.clear()

    base_7d = float(await db.get_setting("base_price_7d", "1.0"))
    base_30d = float(await db.get_setting("base_price_30d", "3.0"))
    factor = 1 + markup / 100
    price_7d = round(base_7d * factor, 2)
    price_30d = round(base_30d * factor, 2)

    _write_instance_env(franchise.instance_dir, franchise.bot_token,
                        message.from_user.id, price_30d, base_30d, markup, price_7d)

    # Обновляем цены в БД экземпляра — текст в боте обновится сразу
    await _sync_prices_to_instance_db(franchise.instance_dir, price_7d, price_30d)

    if franchise.status == "running":
        pm.stop(franchise.id, franchise.pid)
        pm.start(franchise.id, franchise.bot_token, franchise.instance_dir,
                 message.from_user.id, price_30d, markup)
        await db.update_franchise_status(franchise.id, "running", pm.get_pid(franchise.id))

    franchise = await db.get_franchise(franchise_id)
    await message.answer(
        pe(
            f"✅ Наценка установлена: <b>{markup:.1f}%</b>\n"
            f"💰 7 дней: <b>${price_7d:.2f}</b>\n"
            f"💰 30 дней: <b>${price_30d:.2f}</b>"
        ),
        parse_mode="HTML",
        reply_markup=franchise_menu_keyboard(franchise),
    )


# === Удаление бота ===

@router.callback_query(F.data.startswith("delete_bot:"))
async def cb_delete_bot(callback: CallbackQuery, db: Database):
    franchise_id = int(callback.data.split(":")[1])
    franchise = await db.get_franchise(franchise_id)
    if not franchise:
        await callback.answer("Бот не найден", show_alert=True)
        return
    await callback.message.edit_text(
        pe(
            f"⚠️ Вы уверены, что хотите удалить бота <b>{franchise.display_name}</b>?\n\n"
            "Это действие нельзя отменить. Все данные бота будут удалены."
        ),
        parse_mode="HTML",
        reply_markup=confirm_delete_bot_keyboard(franchise_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_delete_bot:"))
async def cb_confirm_delete_bot(callback: CallbackQuery, db: Database, pm: ProcessManager):
    franchise_id = int(callback.data.split(":")[1])
    franchise = await db.get_franchise(franchise_id)
    if not franchise:
        await callback.answer("Бот не найден", show_alert=True)
        return
    pm.stop(franchise.id, franchise.pid)
    await db.delete_franchise(franchise_id)
    user = await db.get_or_create_user(callback.from_user.id, callback.from_user.username)
    franchises = await db.get_user_franchises(user.id)
    await callback.message.edit_text(
        pe("✅ Бот удалён."),
        parse_mode="HTML",
        reply_markup=my_bots_keyboard(franchises),
    )
    await callback.answer()


def _write_instance_env(instance_dir: str, token: str, owner_id: int,
                         price: float, min_price: float, markup: float = 0.0,
                         price_7d: float = None):
    env_path = os.path.join(instance_dir, ".env")
    db_path = os.path.join(instance_dir, "data", "bot.db")
    sessions_path = os.path.join(instance_dir, "sessions")
    if price_7d is None:
        price_7d = round(price / 3, 2)  # sensible default: ~1/3 of 30d price
    lines = [
        f"BOT_TOKEN={token}",
        f"ADMIN_IDS={owner_id}",
        f"DATABASE_PATH={db_path}",
        f"SESSIONS_PATH={sessions_path}",
        f"SUBSCRIPTION_PRICE={price:.2f}",
        f"SUBSCRIPTION_PRICE_7D={price_7d:.2f}",
        f"MIN_SUBSCRIPTION_PRICE={min_price:.2f}",
        f"FRANCHISE_MARKUP={markup:.2f}",
        f"SUPPORT_USERNAME=@febashsupportbot",
        f"FRANCHISE_OWNER_ID={owner_id}",
    ]
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

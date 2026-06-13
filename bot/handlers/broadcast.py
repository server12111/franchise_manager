import os
import re
import asyncio
import aiosqlite
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.utils.text_decorations import html_decoration

from ..database.db import Database
from ..keyboards.inline import (
    broadcast_select_bot_keyboard, broadcast_confirm_keyboard,
    back_to_franchise_keyboard, cancel_keyboard,
)
from ..utils.premium_emoji import pe

router = Router()

PHOTOS_DIR = "data/broadcast_photos"


class BroadcastStates(StatesGroup):
    waiting_message = State()


@router.callback_query(F.data == "broadcast_menu")
async def cb_broadcast_menu(callback: CallbackQuery, state: FSMContext, db: Database):
    user = await db.get_or_create_user(callback.from_user.id, callback.from_user.username)
    franchises = await db.get_user_franchises(user.id)
    if not franchises:
        await callback.answer("У вас нет ботов", show_alert=True)
        return
    if len(franchises) == 1:
        await _start_broadcast(callback, state=state, franchise_id=franchises[0].id)
        return
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\nВыберите бота:",
        parse_mode="HTML",
        reply_markup=broadcast_select_bot_keyboard(franchises),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("franchise_broadcast:"))
async def cb_franchise_broadcast(callback: CallbackQuery, state: FSMContext, db: Database):
    franchise_id = int(callback.data.split(":")[1])
    await _start_broadcast(callback, state, franchise_id)


async def _start_broadcast(callback: CallbackQuery, state, franchise_id: int):
    if state:
        await state.set_state(BroadcastStates.waiting_message)
        await state.update_data(franchise_id=franchise_id)
    await callback.message.edit_text(
        pe(
            "📢 <b>Рассылка по пользователям бота</b>\n\n"
            "Отправьте сообщение для рассылки.\n"
            "Поддерживается: текст, фото, видео."
        ),
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(BroadcastStates.waiting_message)
async def process_broadcast_message(message: Message, state: FSMContext, db: Database):
    data = await state.get_data()
    franchise_id = data.get("franchise_id")
    if not franchise_id:
        await state.clear()
        return

    # Preserve formatting as HTML
    if message.text:
        text = message.html_text
    elif message.caption:
        text = html_decoration.unparse(message.caption, message.caption_entities or [])
    else:
        text = ""

    photo_path = None
    video_path = None

    if message.photo:
        os.makedirs(PHOTOS_DIR, exist_ok=True)
        photo_path = os.path.join(PHOTOS_DIR, f"bc_{message.message_id}.jpg")
        await message.bot.download(message.photo[-1], destination=photo_path)
    elif message.video:
        os.makedirs(PHOTOS_DIR, exist_ok=True)
        video_path = os.path.join(PHOTOS_DIR, f"bc_{message.message_id}.mp4")
        await message.bot.download(message.video, destination=video_path)

    broadcast = await db.create_broadcast(franchise_id, text, photo_path, video_path)
    franchise = await db.get_franchise(franchise_id)
    user_count = await _count_franchise_users(franchise.instance_dir)

    await state.clear()
    await state.update_data(broadcast_id=broadcast.id, franchise_id=franchise_id)

    preview = re.sub(r"<[^>]+>", "", text)[:200] if text else ""
    await message.answer(
        pe(
            f"📢 <b>Подтверждение рассылки</b>\n\n"
            f"🤖 Бот: <b>{franchise.display_name}</b>\n"
            f"👥 Получателей: <b>{user_count}</b>\n\n"
            f"{'📝 ' + preview if preview else ''}"
        ),
        parse_mode="HTML",
        reply_markup=broadcast_confirm_keyboard(franchise_id),
    )


@router.callback_query(F.data.startswith("confirm_broadcast:"))
async def cb_confirm_broadcast(callback: CallbackQuery, state: FSMContext, db: Database):
    data = await state.get_data()
    broadcast_id = data.get("broadcast_id")
    franchise_id = int(callback.data.split(":")[1])

    franchise = await db.get_franchise(franchise_id)
    if not franchise:
        await callback.answer("Бот не найден", show_alert=True)
        return

    bc_row = await db.get_broadcast_by_id(broadcast_id)
    if not bc_row:
        await callback.answer("Рассылка не найдена", show_alert=True)
        return

    await state.clear()
    status_msg = await callback.message.edit_text("⏳ Рассылка запущена...")
    await callback.answer()

    user_ids = await _get_franchise_user_ids(franchise.instance_dir)
    sent = failed = blocked = 0

    franchise_bot = Bot(token=franchise.bot_token)
    try:
        for uid in user_ids:
            try:
                msg_text = bc_row["text"] or None
                parse_mode = "HTML" if msg_text else None
                if bc_row["video_path"] and os.path.exists(bc_row["video_path"]):
                    await franchise_bot.send_video(uid, FSInputFile(bc_row["video_path"]),
                                                   caption=msg_text, parse_mode=parse_mode)
                elif bc_row["photo_path"] and os.path.exists(bc_row["photo_path"]):
                    await franchise_bot.send_photo(uid, FSInputFile(bc_row["photo_path"]),
                                                   caption=msg_text, parse_mode=parse_mode)
                else:
                    await franchise_bot.send_message(uid, msg_text or ".", parse_mode=parse_mode)
                sent += 1
            except Exception as e:
                err = str(e).lower()
                if "blocked" in err or "forbidden" in err or "deactivated" in err:
                    blocked += 1
                else:
                    failed += 1
            await asyncio.sleep(0.05)
    finally:
        await franchise_bot.session.close()

    await db.update_broadcast_stats(broadcast_id, sent, failed, blocked)
    await status_msg.edit_text(
        pe(
            f"✅ <b>Рассылка завершена</b>\n\n"
            f"✅ Отправлено: <b>{sent}</b>\n"
            f"🚫 Заблокировали: <b>{blocked}</b>\n"
            f"❌ Ошибок: <b>{failed}</b>"
        ),
        parse_mode="HTML",
        reply_markup=back_to_franchise_keyboard(franchise_id),
    )


async def _count_franchise_users(instance_dir: str) -> int:
    if not instance_dir:
        return 0
    db_path = os.path.join(instance_dir, "data", "bot.db")
    if not os.path.exists(db_path):
        return 0
    try:
        async with aiosqlite.connect(db_path) as conn:
            async with conn.execute("SELECT COUNT(*) FROM users") as cur:
                row = await cur.fetchone()
                return row[0] if row else 0
    except Exception:
        return 0


async def _get_franchise_user_ids(instance_dir: str) -> list[int]:
    if not instance_dir:
        return []
    db_path = os.path.join(instance_dir, "data", "bot.db")
    if not os.path.exists(db_path):
        return []
    try:
        async with aiosqlite.connect(db_path) as conn:
            async with conn.execute("SELECT telegram_id FROM users") as cur:
                rows = await cur.fetchall()
                return [r[0] for r in rows]
    except Exception:
        return []

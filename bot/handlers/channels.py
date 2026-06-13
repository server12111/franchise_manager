import os
import aiohttp
import aiosqlite
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from ..database.db import Database
from ..keyboards.inline import (
    channels_keyboard, channel_info_keyboard,
    cancel_keyboard, back_to_franchise_keyboard,
)
from ..utils.premium_emoji import pe

router = Router()

CHANNEL_PRICE = 1.0  # $1 за каждый канал после первого


class ChannelStates(StatesGroup):
    waiting_channel = State()


async def _get_channel_info(bot_token: str, identifier: str):
    """Validate channel and return (channel_id, username, title) or None."""
    if identifier.startswith("https://t.me/"):
        identifier = "@" + identifier.split("t.me/")[1].strip("/").split("?")[0]
    elif not identifier.startswith("@") and not identifier.lstrip("-").isdigit():
        identifier = "@" + identifier

    url = f"https://api.telegram.org/bot{bot_token}/getChat"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params={"chat_id": identifier},
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                if data.get("ok"):
                    chat = data["result"]
                    if chat.get("type") not in ("channel", "supergroup", "group"):
                        return None
                    return (
                        chat["id"],
                        chat.get("username"),
                        chat.get("title", chat.get("username", "Unknown")),
                    )
    except Exception:
        pass
    return None


async def _sync_channels_to_instance(instance_dir: str, channels: list[dict]):
    """Replaces required_channels in the instance SQLite DB."""
    if not instance_dir:
        return
    db_path = os.path.join(instance_dir, "data", "bot.db")
    if not os.path.exists(db_path):
        return
    try:
        async with aiosqlite.connect(db_path) as conn:
            await conn.execute("DELETE FROM required_channels")
            for ch in channels:
                await conn.execute(
                    """INSERT OR REPLACE INTO required_channels
                       (channel_id, channel_username, channel_title)
                       VALUES (?, ?, ?)""",
                    (ch["channel_id"], ch.get("channel_username"), ch["channel_title"])
                )
            await conn.commit()
    except Exception:
        pass


async def _show_channels(callback: CallbackQuery, db: Database, franchise_id: int):
    franchise = await db.get_franchise(franchise_id)
    if not franchise:
        await callback.answer("Бот не найден", show_alert=True)
        return
    channels = await db.get_franchise_channels(franchise_id)
    count = len(channels)
    free_used = min(count, 1)
    paid_used = max(count - 1, 0)
    text = pe(
        f"📋 <b>Обязательные каналы — {franchise.display_name}</b>\n\n"
        f"Каналов: <b>{count}</b>\n"
        f"1-й канал — бесплатно, каждый следующий — <b>${CHANNEL_PRICE:.0f}</b>\n\n"
        "Пользователи смогут пользоваться ботом только после подписки на все каналы."
    )
    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=channels_keyboard(franchise_id, channels),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("franchise_channels:"))
async def cb_franchise_channels(callback: CallbackQuery, db: Database):
    franchise_id = int(callback.data.split(":")[1])
    await _show_channels(callback, db, franchise_id)


@router.callback_query(F.data.startswith("channel_info:"))
async def cb_channel_info(callback: CallbackQuery, db: Database):
    parts = callback.data.split(":")
    franchise_id = int(parts[1])
    channel_id = int(parts[2])

    channels = await db.get_franchise_channels(franchise_id)
    ch = next((c for c in channels if c["channel_id"] == channel_id), None)
    if not ch:
        await callback.answer("Канал не найден", show_alert=True)
        return

    name = f"@{ch['channel_username']}" if ch.get("channel_username") else ch["channel_title"]
    text = pe(
        f"📢 <b>{ch['channel_title']}</b>\n\n"
        f"Юзернейм: {name}\n"
        f"ID: <code>{ch['channel_id']}</code>"
    )
    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=channel_info_keyboard(franchise_id, channel_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("add_channel:"))
async def cb_add_channel(callback: CallbackQuery, state: FSMContext, db: Database):
    franchise_id = int(callback.data.split(":")[1])
    franchise = await db.get_franchise(franchise_id)
    if not franchise:
        await callback.answer("Бот не найден", show_alert=True)
        return

    count = await db.count_franchise_channels(franchise_id)
    price = CHANNEL_PRICE if count >= 1 else 0.0

    user = await db.get_or_create_user(callback.from_user.id, callback.from_user.username)

    if price > 0 and user.balance < price:
        await callback.answer(
            f"❌ Недостаточно средств. Нужно ${price:.2f}, у вас ${user.balance:.2f}",
            show_alert=True
        )
        return

    await state.set_state(ChannelStates.waiting_channel)
    await state.update_data(franchise_id=franchise_id, price=price, bot_token=franchise.bot_token)

    cost_note = f"\n💰 Спишется <b>${price:.2f}</b> с баланса." if price > 0 else "\n✅ Первый канал — бесплатно."
    await callback.message.edit_text(
        pe(
            f"📋 <b>Добавление канала</b>\n\n"
            f"Отправьте @юзернейм или ссылку на канал.\n"
            f"Пример: <code>@mychannel</code> или <code>https://t.me/mychannel</code>\n\n"
            f"⚠️ Бот <b>@{franchise.bot_username}</b> должен быть участником (или админом для приватных каналов)."
            f"{cost_note}"
        ),
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(ChannelStates.waiting_channel)
async def process_channel_input(message: Message, state: FSMContext, db: Database):
    data = await state.get_data()
    franchise_id = data["franchise_id"]
    price = data["price"]
    bot_token = data["bot_token"]

    identifier = (message.text or "").strip()
    if not identifier:
        await message.answer(pe("❌ Введите юзернейм или ссылку на канал."), parse_mode="HTML",
                             reply_markup=cancel_keyboard())
        return

    status_msg = await message.answer(pe("⏳ Проверяю канал..."), parse_mode="HTML")
    result = await _get_channel_info(bot_token, identifier)

    if not result:
        await status_msg.edit_text(
            pe(
                "❌ Канал не найден или бот не имеет доступа.\n\n"
                "Убедитесь что:\n"
                "• Для публичного канала — укажите @юзернейм\n"
                "• Для приватного — добавьте бота как администратора"
            ),
            parse_mode="HTML",
            reply_markup=cancel_keyboard(),
        )
        return

    channel_id, username, title = result

    # Check duplicate
    channels = await db.get_franchise_channels(franchise_id)
    if any(c["channel_id"] == channel_id for c in channels):
        await status_msg.edit_text(
            pe("❌ Этот канал уже добавлен."),
            parse_mode="HTML",
            reply_markup=cancel_keyboard(),
        )
        return

    # Charge if needed
    if price > 0:
        user = await db.get_or_create_user(message.from_user.id, message.from_user.username)
        if user.balance < price:
            await state.clear()
            await status_msg.edit_text(
                pe(f"❌ Недостаточно средств. Нужно ${price:.2f}, у вас ${user.balance:.2f}"),
                parse_mode="HTML",
            )
            return
        await db.update_balance(user.id, -price, "channel_add", f"Добавление канала {title}")

    await db.add_franchise_channel(franchise_id, channel_id, username, title)
    franchise = await db.get_franchise(franchise_id)
    channels = await db.get_franchise_channels(franchise_id)
    await _sync_channels_to_instance(franchise.instance_dir, channels)
    await state.clear()

    name = f"@{username}" if username else title
    await status_msg.edit_text(
        pe(f"✅ Канал <b>{name}</b> добавлен!\n\nПользователи должны будут подписаться на него."),
        parse_mode="HTML",
        reply_markup=back_to_franchise_keyboard(franchise_id),
    )


@router.callback_query(F.data.startswith("remove_channel:"))
async def cb_remove_channel(callback: CallbackQuery, db: Database):
    parts = callback.data.split(":")
    franchise_id = int(parts[1])
    channel_id = int(parts[2])

    franchise = await db.get_franchise(franchise_id)
    await db.remove_franchise_channel(franchise_id, channel_id)
    if franchise:
        channels = await db.get_franchise_channels(franchise_id)
        await _sync_channels_to_instance(franchise.instance_dir, channels)

    await callback.answer("✅ Канал удалён")
    await _show_channels(callback, db, franchise_id)

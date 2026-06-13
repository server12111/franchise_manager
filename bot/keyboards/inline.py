from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..database.db import Franchise, PromoCode, WithdrawalRequest


def btn(text: str, **kwargs) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, **kwargs)


# === Главное меню ===

def main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("🤖 Мои боты", callback_data="my_bots"),
        btn("📊 Статистика", callback_data="stats_menu"),
    )
    builder.row(
        btn("💰 Баланс", callback_data="balance"),
        btn("🆘 Поддержка", url="https://t.me/febashsupportbot"),
    )
    if is_admin:
        builder.row(btn("👑 Админ-панель", callback_data="admin_panel"))
    return builder.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("◀️ Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("❌ Отмена", callback_data="cancel"))
    return builder.as_markup()


# === Мои боты ===

def my_bots_keyboard(franchises: list[Franchise]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for f in franchises:
        status = "🟢" if f.status == "running" else "🔴"
        builder.row(btn(
            f"{status} {f.display_name}",
            callback_data=f"franchise:{f.id}"
        ))
    if not franchises:
        builder.row(btn("➕ Создать бота", callback_data="create_bot"))
    builder.row(btn("◀️ Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def franchise_menu_keyboard(franchise: Franchise) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if franchise.status == "running":
        builder.row(
            btn("⏹️ Остановить", callback_data=f"stop_bot:{franchise.id}"),
            btn("🔄 Перезапустить", callback_data=f"restart_bot:{franchise.id}"),
        )
    else:
        builder.row(btn("▶️ Запустить", callback_data=f"start_bot:{franchise.id}"))
    builder.row(
        btn("📊 Статистика", callback_data=f"franchise_stats:{franchise.id}"),
        btn("💰 Наценка", callback_data=f"set_markup:{franchise.id}"),
    )
    builder.row(
        btn("🎟️ Промокоды", callback_data=f"franchise_promos:{franchise.id}"),
        btn("📢 Рассылка", callback_data=f"franchise_broadcast:{franchise.id}"),
    )
    builder.row(
        btn("📋 Каналы", callback_data=f"franchise_channels:{franchise.id}"),
        btn("🗑️ Удалить бота", callback_data=f"delete_bot:{franchise.id}"),
    )
    builder.row(btn("◀️ Назад", callback_data="my_bots"))
    return builder.as_markup()


def confirm_delete_bot_keyboard(franchise_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("✅ Да, удалить", callback_data=f"confirm_delete_bot:{franchise_id}"),
        btn("◀️ Отмена", callback_data=f"franchise:{franchise_id}"),
    )
    return builder.as_markup()


# === Статистика ===

def stats_select_bot_keyboard(franchises: list[Franchise]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for f in franchises:
        status = "🟢" if f.status == "running" else "🔴"
        builder.row(btn(f"{status} {f.display_name}", callback_data=f"franchise_stats:{f.id}"))
    builder.row(btn("◀️ Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def back_to_franchise_keyboard(franchise_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("◀️ Назад", callback_data=f"franchise:{franchise_id}"))
    return builder.as_markup()


# === Баланс / Вывод ===

def balance_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("💸 Вывести средства", callback_data="withdraw"))
    builder.row(btn("📋 История транзакций", callback_data="tx_history"))
    builder.row(btn("◀️ Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def withdrawal_method_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("💎 TON", callback_data="withdraw_method:ton"),
        btn("🤖 CryptoBot", callback_data="withdraw_method:cryptobot"),
    )
    builder.row(btn("❌ Отмена", callback_data="balance"))
    return builder.as_markup()


def withdrawal_confirm_keyboard(request_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("✅ Подтвердить", callback_data=f"confirm_withdraw:{request_id}"),
        btn("❌ Отмена", callback_data="balance"),
    )
    return builder.as_markup()


def admin_withdrawal_keyboard(request_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("✅ Одобрить", callback_data=f"approve_withdraw:{request_id}"),
        btn("❌ Отклонить", callback_data=f"reject_withdraw:{request_id}"),
    )
    return builder.as_markup()


# === Промокоды ===

def promo_select_bot_keyboard(franchises: list[Franchise]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for f in franchises:
        status = "🟢" if f.status == "running" else "🔴"
        builder.row(btn(f"{status} {f.display_name}", callback_data=f"franchise_promos:{f.id}"))
    builder.row(btn("◀️ Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def promo_list_keyboard(franchise_id: int, promos: list[PromoCode]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in promos:
        label = f"🎟️ {p.code} | {p.duration_days}д | {p.uses_count}/{p.max_uses}"
        builder.row(btn(label, callback_data=f"promo_info:{p.id}"))
    builder.row(btn("➕ Создать промокод", callback_data=f"create_promo:{franchise_id}"))
    builder.row(btn("◀️ Назад", callback_data=f"franchise:{franchise_id}"))
    return builder.as_markup()


def promo_info_keyboard(promo_id: int, franchise_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("🗑️ Удалить", callback_data=f"delete_promo:{promo_id}:{franchise_id}"))
    builder.row(btn("◀️ Назад", callback_data=f"franchise_promos:{franchise_id}"))
    return builder.as_markup()


def promo_confirm_keyboard(franchise_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("✅ Создать и списать", callback_data=f"confirm_promo:{franchise_id}"),
        btn("❌ Отмена", callback_data=f"franchise_promos:{franchise_id}"),
    )
    return builder.as_markup()


# === Рассылка ===

def broadcast_select_bot_keyboard(franchises: list[Franchise]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for f in franchises:
        status = "🟢" if f.status == "running" else "🔴"
        builder.row(btn(f"{status} {f.display_name}", callback_data=f"franchise_broadcast:{f.id}"))
    builder.row(btn("◀️ Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def broadcast_confirm_keyboard(franchise_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("✅ Отправить всем", callback_data=f"confirm_broadcast:{franchise_id}"),
        btn("❌ Отмена", callback_data=f"franchise:{franchise_id}"),
    )
    return builder.as_markup()


# === Каналы ===

def channels_keyboard(franchise_id: int, channels: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ch in channels:
        name = ch["channel_username"] and f"@{ch['channel_username']}" or ch["channel_title"]
        builder.row(btn(
            f"📢 {name}",
            callback_data=f"channel_info:{franchise_id}:{ch['channel_id']}"
        ))
    builder.row(btn("➕ Добавить канал", callback_data=f"add_channel:{franchise_id}"))
    builder.row(btn("◀️ Назад", callback_data=f"franchise:{franchise_id}"))
    return builder.as_markup()


def channel_info_keyboard(franchise_id: int, channel_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("🗑️ Удалить", callback_data=f"remove_channel:{franchise_id}:{channel_id}"))
    builder.row(btn("◀️ Назад", callback_data=f"franchise_channels:{franchise_id}"))
    return builder.as_markup()


# === Админ-панель ===

def admin_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("👥 Все пользователи", callback_data="admin_users"),
        btn("🤖 Все боты", callback_data="admin_all_bots"),
    )
    builder.row(
        btn("⚙️ Настройки системы", callback_data="admin_settings"),
        btn("📊 Общая статистика", callback_data="admin_global_stats"),
    )
    builder.row(btn("💸 Заявки на вывод", callback_data="admin_withdrawals"))
    builder.row(btn("◀️ Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def admin_settings_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("📅 Цена 7 дней", callback_data="admin_set:base_price_7d"),
        btn("📅 Цена 30 дней", callback_data="admin_set:base_price_30d"),
    )
    builder.row(btn("💵 Мин. цена подписки", callback_data="admin_set:min_subscription_price"))
    builder.row(btn("💸 Комиссия вывода (%)", callback_data="admin_set:withdrawal_commission"))
    builder.row(btn("◀️ Назад", callback_data="admin_panel"))
    return builder.as_markup()


def admin_user_keyboard(target_user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("➕ Начислить баланс", callback_data=f"admin_add_balance:{target_user_id}"),
        btn("➖ Снять баланс", callback_data=f"admin_sub_balance:{target_user_id}"),
    )
    builder.row(btn("◀️ Назад", callback_data="admin_users"))
    return builder.as_markup()


def admin_withdrawals_keyboard(requests: list[WithdrawalRequest]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for r in requests:
        method = "TON" if r.method == "ton" else "CryptoBot"
        builder.row(btn(
            f"💸 #{r.id} | ${r.amount:.2f} → ${r.net_amount:.2f} | {method}",
            callback_data=f"admin_withdrawal:{r.id}"
        ))
    builder.row(btn("◀️ Назад", callback_data="admin_panel"))
    return builder.as_markup()

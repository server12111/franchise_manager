from datetime import datetime
from typing import Callable, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from aiogram.fsm.context import FSMContext

from ..database.db import Database
from ..config import Config, config as _global_config
from ..handlers.subscription import SubscriptionStates
from ..handlers.referral import ReferralStates


class SubscriptionMiddleware(BaseMiddleware):
    EXEMPT_CALLBACKS = {
        "main_menu",
        "subscription",
        "buy_subscription",
        "help",
        "pay_cryptobot",
        "pay_ton",
        "pay_card",
        "pay_platega",
        "pay_account_cryptobot",
        "pay_account_ton",
        "pay_account_card",
        "enter_promocode",
        "referral",
        "withdraw_ref_balance",
        "check_channels",
        "activate_free_tier",
        "activate_free_tier_confirm",
        "dm_mailing_info",
    }

    EXEMPT_CALLBACK_PREFIXES = (
        "check_payment:",
        "check_ton_payment:",
        "check_ton_account:",
        "check_account_payment:",
        "check_platega:",
        "sub_plan:",
    )

    EXEMPT_FSM_STATES = {
        SubscriptionStates.waiting_promocode,
        ReferralStates.waiting_wallet,
    }

    def __init__(self, db: Database):
        self.db = db

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        state: FSMContext = data.get("state")
        if state:
            current_state = await state.get_state()
            for exempt_state in self.EXEMPT_FSM_STATES:
                if current_state == exempt_state.state:
                    return await handler(event, data)

        user_id = None
        if isinstance(event, Message):
            if event.text and event.text.startswith("/start"):
                return await handler(event, data)
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            callback_data = event.data or ""
            if callback_data in self.EXEMPT_CALLBACKS:
                return await handler(event, data)
            if callback_data.startswith(self.EXEMPT_CALLBACK_PREFIXES):
                return await handler(event, data)
            user_id = event.from_user.id

        if user_id:
            db: Database = data.get("db") or self.db
            if not db:
                return await handler(event, data)
            user = await db.get_user(user_id)
            cfg: Config = data.get("config") or _global_config

            if user and (user.is_admin or user_id in cfg.ADMIN_IDS):
                return await handler(event, data)

            if user and user.subscription_type == "free_ad":
                return await handler(event, data)

            if not user or not user.subscription_end:
                await self._show_subscription_required(event)
                return

            if user.subscription_end < datetime.now():
                await self._show_subscription_expired(event)
                return

        return await handler(event, data)

    async def _show_subscription_required(self, event: TelegramObject):
        text = (
            "⚠️ Для использования этой функции требуется подписка.\n\n"
            "Нажмите «Подписка» в главном меню, чтобы приобрести доступ."
        )
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)

    async def _show_subscription_expired(self, event: TelegramObject):
        text = (
            "⚠️ Ваша подписка истекла.\n\n"
            "Нажмите «Подписка» в главном меню, чтобы продлить доступ."
        )
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)

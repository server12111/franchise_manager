"""
SharedDispatcherManager — запускає всі franchise-інстанси в одному процесі.
Один dispatcher + aiogram + telethon на всі боти. Кожен новий інстанс додає
лише ~15-20MB замість ~80MB окремого subprocess.

Архітектура:
  - ONE Dispatcher з хендлерами feAutoSender (роутери завантажуються раз)
  - ONE polling task на кожен Bot об'єкт
  - InstanceContextMiddleware інжектує per-bot: db, config, userbot_manager,
    mailing_service, autoresponder_service, cryptobot, ton_service, platega_service
"""

import asyncio
import logging
import os
import sys
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Middleware для ін'єкції per-instance контексту
# ---------------------------------------------------------------------------

class _InstanceContextMiddleware:
    """Injects per-bot DI data from registry before each handler call."""

    def __init__(self, registry: dict):
        self._registry = registry  # bot_id → dict

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        bot = data.get("bot")
        if bot:
            ctx = self._registry.get(bot.id, {})
            data.update(ctx)
            # Set per-task config so handlers that use the global `config` proxy
            # transparently receive the correct per-franchise Config object.
            cfg = ctx.get("config")
            if cfg:
                try:
                    from feas.config import _config_var
                    _config_var.set(cfg)
                except ImportError:
                    pass
        return await handler(event, data)


# ---------------------------------------------------------------------------
# Shared Dispatcher Manager
# ---------------------------------------------------------------------------

class SharedDispatcherManager:
    """Runs all franchise instances in one process via aiogram multibot."""

    def __init__(self, fe_path: str):
        self.fe_path = fe_path
        self._registry: dict[int, dict] = {}      # bot_id → instance context
        self._tasks: dict[int, asyncio.Task] = {}  # franchise_id → polling task
        self._bots: dict[int, object] = {}          # franchise_id → Bot
        self._dispatcher = None
        self._feas = None

    def _load_feas(self):
        """Import feAutoSender's feas package (done once)."""
        if self._feas is not None:
            return self._feas
        if self.fe_path and self.fe_path not in sys.path:
            sys.path.insert(0, self.fe_path)
        import feas
        import feas.main as feas_main
        self._feas = feas_main
        return feas_main

    async def _ensure_dispatcher(self):
        if self._dispatcher is not None:
            return

        self._load_feas()

        # Mark process as franchise so setup_routers() skips admin router
        os.environ.setdefault("FRANCHISE_OWNER_ID", "__shared__")

        from aiogram import Dispatcher
        from aiogram.fsm.storage.memory import MemoryStorage
        from feas.handlers import setup_routers
        from feas.middlewares.subscription import SubscriptionMiddleware
        from feas.middlewares.album import AlbumMiddleware
        from feas.main import ActivityMiddleware

        ctx_mw = _InstanceContextMiddleware(self._registry)

        dp = Dispatcher(storage=MemoryStorage())
        # InstanceContextMiddleware FIRST — injects db/config before other middleware
        dp.message.outer_middleware(ctx_mw)
        dp.callback_query.outer_middleware(ctx_mw)

        dp.message.middleware(AlbumMiddleware())
        dp.message.middleware(ActivityMiddleware())
        # SubscriptionMiddleware gets db from data (already updated)
        dp.message.middleware(SubscriptionMiddleware(None))
        dp.callback_query.middleware(ActivityMiddleware())
        dp.callback_query.middleware(SubscriptionMiddleware(None))

        dp.include_router(setup_routers())
        self._dispatcher = dp

    async def start(self, franchise_id: int, token: str, instance_dir: str,
                    owner_id: int, price: float, markup: float = 0.0) -> bool:
        if not self.fe_path or not os.path.isdir(self.fe_path):
            logger.error(f"feAutoSender path not found: {self.fe_path}")
            return False

        await self.stop(franchise_id)

        try:
            await self._ensure_dispatcher()
        except Exception as e:
            logger.error(f"Failed to init shared dispatcher: {e}", exc_info=True)
            return False

        abs_instance = os.path.abspath(instance_dir)
        db_path = os.path.join(abs_instance, "data", "bot.db")
        sessions_path = os.path.join(abs_instance, "sessions")

        extra = _read_instance_env(abs_instance)

        try:
            from aiogram import Bot
            from aiogram.client.default import DefaultBotProperties
            from aiogram.enums import ParseMode
            from feas.config import Config
            from feas.database.db import Database
            from feas.userbot.manager import UserbotManager
            from feas.services import (
                CryptoBotService, TonPaymentService, PlategaService,
                AutoresponderService, MailingService, SubscriptionCheckerService,
            )

            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
            os.makedirs(sessions_path, exist_ok=True)

            cfg = Config(
                BOT_TOKEN=token,
                ADMIN_IDS=[owner_id],
                DATABASE_PATH=db_path,
                SESSIONS_PATH=sessions_path,
                SUBSCRIPTION_PRICE=price,
                SUBSCRIPTION_PRICE_7D=float(extra.get("SUBSCRIPTION_PRICE_7D",
                                                       round(price / 30 * 7, 2))),
                FRANCHISE_OWNER_ID=str(owner_id),
                CRYPTOBOT_TOKEN=extra.get("CRYPTOBOT_TOKEN", ""),
                TON_WALLET_ADDRESS=extra.get("TON_WALLET_ADDRESS", ""),
                TONCENTER_API_KEY=extra.get("TONCENTER_API_KEY", ""),
                PLATEGA_MERCHANT_ID=extra.get("PLATEGA_MERCHANT_ID", ""),
                PLATEGA_SECRET=extra.get("PLATEGA_SECRET", ""),
                SUPPORT_USERNAME=extra.get("SUPPORT_USERNAME", "febashsupportbot"),
            )

            db = Database(db_path)
            await db.connect()

            bot = Bot(token=token,
                      default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            bot_info = await bot.get_me()
            bot_id = bot_info.id

            cryptobot = CryptoBotService(cfg.CRYPTOBOT_TOKEN, testnet=cfg.CRYPTOBOT_TESTNET)
            ton_service = (TonPaymentService(cfg.TON_WALLET_ADDRESS, cfg.TONCENTER_API_KEY)
                           if cfg.TON_WALLET_ADDRESS else None)
            platega_service = (PlategaService(cfg.PLATEGA_MERCHANT_ID, cfg.PLATEGA_SECRET)
                               if cfg.PLATEGA_MERCHANT_ID and cfg.PLATEGA_SECRET else None)

            userbot_mgr = UserbotManager(db, sessions_path)
            autoresponder_svc = AutoresponderService(db)
            mailing_svc = MailingService(db, userbot_mgr)
            sub_checker = SubscriptionCheckerService(db, mailing_svc)

            async def _notify(uid: int, text: str):
                try:
                    await bot.send_message(uid, text)
                except Exception:
                    pass

            userbot_mgr.set_message_handler(autoresponder_svc.handle_message)
            userbot_mgr.set_group_reply_handler(autoresponder_svc.handle_group_reply)
            userbot_mgr.set_sponsor_check_handler(autoresponder_svc.handle_sponsor_check)
            userbot_mgr.set_bot_notify_callback(_notify)

            await userbot_mgr.start_all_clients(background=True)
            userbot_mgr.start_monitor()
            await mailing_svc.start()
            sub_checker.start(bot)

            self._registry[bot_id] = {
                "db": db,
                "config": cfg,
                "userbot_manager": userbot_mgr,
                "mailing_service": mailing_svc,
                "autoresponder_service": autoresponder_svc,
                "cryptobot": cryptobot,
                "ton_service": ton_service,
                "platega_service": platega_service,
                "_bot": bot,
                "_db": db,
                "_userbot_mgr": userbot_mgr,
                "_mailing_svc": mailing_svc,
                "_sub_checker": sub_checker,
            }
            self._bots[franchise_id] = (bot, bot_id)

            task = asyncio.create_task(
                self._dispatcher.start_polling(bot),
                name=f"feas_{franchise_id}",
            )
            task.add_done_callback(lambda t: self._on_done(franchise_id, bot_id, t))
            self._tasks[franchise_id] = task

            logger.info(f"Started franchise {franchise_id} in-process (@{bot_info.username})")
            return True

        except Exception as e:
            logger.error(f"Failed to start franchise {franchise_id}: {e}", exc_info=True)
            return False

    def _on_done(self, franchise_id: int, bot_id: int, task: asyncio.Task):
        self._tasks.pop(franchise_id, None)
        self._bots.pop(franchise_id, None)
        self._registry.pop(bot_id, None)
        try:
            exc = task.exception()
            if exc:
                logger.warning(f"Franchise {franchise_id} polling ended with: {exc}")
        except (asyncio.CancelledError, Exception):
            pass

    async def stop(self, franchise_id: int, _pid=None):
        task = self._tasks.pop(franchise_id, None)
        bot_entry = self._bots.pop(franchise_id, None)

        if bot_entry:
            bot, bot_id = bot_entry
            ctx = self._registry.pop(bot_id, {})

            # Cleanup services
            for cleanup_fn in [
                lambda: ctx.get("_sub_checker") and ctx["_sub_checker"]._task and ctx["_sub_checker"]._task.cancel(),
                lambda: ctx.get("_mailing_svc") and ctx["_mailing_svc"].stop(),
                lambda: ctx.get("_userbot_mgr") and ctx["_userbot_mgr"].stop_all_clients(),
                lambda: ctx.get("_db") and ctx["_db"].close(),
                lambda: bot.session.close(),
            ]:
                try:
                    result = cleanup_fn()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass

        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        logger.info(f"Stopped franchise {franchise_id}")

    def get_pid(self, franchise_id: int) -> Optional[int]:
        return os.getpid() if franchise_id in self._tasks else None

    def is_running(self, franchise_id: int) -> bool:
        task = self._tasks.get(franchise_id)
        return task is not None and not task.done()

    def check_and_cleanup(self) -> list[int]:
        dead = []
        for fid, task in list(self._tasks.items()):
            if task.done():
                dead.append(fid)
                del self._tasks[fid]
        return dead

    async def restore_running(self, franchises: list) -> None:
        for f in franchises:
            if f.status == "running" and f.instance_dir:
                try:
                    extra = _read_instance_env(f.instance_dir)
                    price = float(extra.get("SUBSCRIPTION_PRICE", "3.0"))
                    raw_owner = extra.get("FRANCHISE_OWNER_ID", "")
                    owner_id = int(raw_owner) if raw_owner.strip().lstrip("-").isdigit() else 0
                    await self.start(f.id, f.bot_token, f.instance_dir, owner_id, price, f.markup_percent)
                    logger.info(f"Restored franchise {f.id} ({f.display_name})")
                except Exception as e:
                    logger.error(f"Failed to restore franchise {f.id}: {e}", exc_info=True)


# Alias
ProcessManager = SharedDispatcherManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_instance_env(instance_dir: str) -> dict:
    result = {}
    env_path = os.path.join(instance_dir, ".env")
    try:
        with open(env_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    result[k.strip()] = v.strip()
    except Exception:
        pass
    return result

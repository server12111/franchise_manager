import asyncio
import logging
import os
import sys

# Allow running as `python bot/main.py` directly (bothost.ru style)
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "bot"

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from .config import config
from .database.db import Database
from .services.process_manager import ProcessManager
from .handlers import start, bots, balance, stats, promo, broadcast, admin, channels

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)),
        logging.FileHandler("manager.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


async def run_bot():
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    db = Database(config.DATABASE_PATH)
    await db.connect()
    logger.info("БД подключена")

    pm = ProcessManager(config.FE_AUTO_SENDER_PATH)

    franchises = await db.get_all_franchises()
    running = [f for f in franchises if f.status == "running"]
    if running:
        logger.info(f"Восстанавливаем {len(running)} запущенных ботов...")
        await pm.restore_running(running)

    @dp.errors()
    async def error_handler(event: ErrorEvent):
        logger.exception(f"Необработанная ошибка в хендлере: {event.exception}", exc_info=event.exception)

    async def monitor_processes():
        while True:
            await asyncio.sleep(60)
            dead = pm.check_and_cleanup()
            for fid in dead:
                await db.update_franchise_status(fid, "stopped", None)
                logger.warning(f"Franchise {fid} помечена как stopped (процесс упал)")

    dp.include_router(start.router)
    dp.include_router(bots.router)
    dp.include_router(channels.router)
    dp.include_router(balance.router)
    dp.include_router(stats.router)
    dp.include_router(promo.router)
    dp.include_router(broadcast.router)
    dp.include_router(admin.router)

    logger.info("Franchise Manager запущен")
    monitor_task = asyncio.create_task(monitor_processes())
    try:
        await dp.start_polling(bot, db=db, pm=pm)
    finally:
        monitor_task.cancel()
        await db.close()
        await bot.session.close()
        logger.info("Бот остановлен")


async def main():
    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN не задан в .env")
        sys.exit(1)
    if not config.ADMIN_ID:
        logger.error("ADMIN_ID не задан в .env")
        sys.exit(1)

    retry_delay = 5
    while True:
        try:
            await run_bot()
            break  # Чистый выход (Ctrl+C)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Остановка по сигналу")
            break
        except Exception as e:
            logger.error(f"Бот упал: {e}. Перезапуск через {retry_delay}с...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)  # экспоненциальный backoff до 60с


if __name__ == "__main__":
    asyncio.run(main())

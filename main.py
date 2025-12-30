import asyncio
import uvicorn
import threading
import logging
import structlog
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from config.settings import settings
from database.connection import db_manager
from database.models import Base
from handlers import start_router, wallet_router, send_router, receive_router, swap_router, p2p_router, history_router, settings_router
from api.server import app as fastapi_app

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = structlog.get_logger(__name__)

async def start_bot_async():
    """Асинхронная функция для запуска бота."""
    await db_manager.initialize()
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("DB tables checked/created.")

    bot = Bot(token=settings.BOT_TOKEN.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    
    dp.include_router(start_router); dp.include_router(wallet_router); dp.include_router(send_router)
    dp.include_router(receive_router); dp.include_router(swap_router); dp.include_router(p2p_router)
    dp.include_router(history_router); dp.include_router(settings_router)

    logger.info("Bot is starting polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), drop_pending_updates=True)

def run_bot_in_thread():
    """Запускает асинхронного бота в отдельном потоке."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(start_bot_async())
    finally:
        loop.close()

if __name__ == "__main__":
    logger.info("Starting application...")

    bot_thread = threading.Thread(target=run_bot_in_thread, daemon=True)
    bot_thread.start()
    logger.info("Bot thread has been started.")

    port = int(os.getenv("PORT", 8000))
    logger.info(f"Starting web server on http://0.0.0.0:{port}")
    try:
        uvicorn.run(fastapi_app, host="0.0.0.0", port=port)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Web server stopped.")
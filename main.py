import asyncio
import sys
import os
import uvicorn
import threading
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
import structlog

from config.settings import settings
from database.connection import db_manager
from database.models import Base
from handlers import start_router, wallet_router, send_router, receive_router, swap_router, p2p_router, history_router, settings_router
from services import price_service, swap_service
from api.server import app as fastapi_app

logger = structlog.get_logger()

async def start_bot_async():
    """Асинхронная функция для запуска бота"""
    await db_manager.initialize()
    await create_tables()
    bot = Bot(token=settings.BOT_TOKEN.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    
    # Регистрация роутеров
    dp.include_router(start_router); dp.include_router(wallet_router); dp.include_router(send_router)
    dp.include_router(receive_router); dp.include_router(swap_router); dp.include_router(p2p_router)
    dp.include_router(history_router); dp.include_router(settings_router)

    logger.info("Bot is starting polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), drop_pending_updates=True)

def run_bot_in_thread():
    """Функция для запуска асинхронного бота в отдельном потоке"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_bot_async())

async def create_tables():
    """Создает таблицы в БД"""
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("DB tables checked/created")


if __name__ == "__main__":
    # Настраиваем логирование
    import logging
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting application...")

    # 1. Запускаем бота в отдельном фоновом потоке
    bot_thread = threading.Thread(target=run_bot_in_thread, daemon=True)
    bot_thread.start()
    logger.info("Bot thread started.")

    # 2. Основной поток запускает веб-сервер (то, что видит Render)
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Starting web server on port {port}...")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port)
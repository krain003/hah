import asyncio
import sys
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
import structlog

from config.settings import settings
from database.connection import dbmanager
from database.models import Base

from handlers.start import router as start_router
from handlers.wallet import router as wallet_router

logger = structlog.get_logger()

async def on_startup(bot: Bot):
    logger.info("Bot started", bot_username=(await bot.get_me()).username)
    logger.info("NEXUS WALLET is ready!")

async def on_shutdown(bot: Bot):
    logger.info("Shutting down NEXUS WALLET...")
    await dbmanager.close()

async def create_tables():
    async with dbmanager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")

async def main():
    await dbmanager.initialize()
    await create_tables()
    
    bot = Bot(token=settings.BOT_TOKEN.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    
    dp.include_router(start_router)
    dp.include_router(wallet_router)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

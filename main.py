import asyncio, sys, os, uvicorn
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
import structlog
from config.settings import settings
from database.connection import db_manager
from database.models import Base
from handlers.start import router as start_router
from handlers.wallet import router as wallet_router
from handlers.send import router as send_router
from handlers.receive import router as receive_router
from handlers.swap import router as swap_router
from handlers.p2p import router as p2p_router
from handlers.history import router as history_router
from handlers.settings import router as settings_router
from services.price_service import price_service
from services.swap_service import swap_service
from api.server import app as fastapi_app

logger = structlog.get_logger()

async def on_startup(bot: Bot):
    bot_info = await bot.get_me()
    logger.info("Bot started", bot_username=f"@{bot_info.username}")

async def on_shutdown(bot: Bot):
    await price_service.close()
    await swap_service.close()
    await db_manager.close()

async def create_tables():
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("DB tables checked/created")

async def start_bot():
    await db_manager.initialize()
    await create_tables()
    bot = Bot(token=settings.BOT_TOKEN.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(start_router); dp.include_router(wallet_router); dp.include_router(send_router)
    dp.include_router(receive_router); dp.include_router(swap_router); dp.include_router(p2p_router)
    dp.include_router(history_router); dp.include_router(settings_router)
    dp.startup.register(on_startup); dp.shutdown.register(on_shutdown)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), drop_pending_updates=True)

async def start_web_server():
    port = int(os.getenv("PORT", 8000))
    config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    await asyncio.gather(start_bot(), start_web_server())

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

"""
NEXUS WALLET - Main Entry Point
Advanced Telegram Crypto Wallet with Real Blockchain Integration
"""

import asyncio
import sys
import os
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
import structlog

# Ensure we can import from project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import settings
from database.connection import db_manager
from database.models import Base

# Import ALL handlers
from handlers.start import router as start_router
from handlers.wallet import router as wallet_router
from handlers.send import router as send_router
from handlers.receive import router as receive_router
from handlers.swap import router as swap_router
from handlers.p2p import router as p2p_router
from handlers.history import router as history_router
from handlers.settings import router as settings_router

# Import services
from services.price_service import price_service
from services.swap_service import swap_service

logger = structlog.get_logger()


async def on_startup(bot: Bot):
    """Startup actions"""
    try:
        bot_info = await bot.get_me()
        logger.info("Bot started", bot_username=f"@{bot_info.username}")
        logger.info("=" * 50)
        logger.info("NEXUS WALLET is ready! (REAL MODE)")
        logger.info("=" * 50)

        # Optional: Notify admin (if configured)
        # admin_ids = [123456789]
        # for admin_id in admin_ids:
        #     await bot.send_message(admin_id, "🚀 Bot Started")
    except Exception as e:
        logger.error(f"Startup error: {e}")


async def on_shutdown(bot: Bot):
    """Shutdown actions"""
    logger.info("Shutting down NEXUS WALLET Bot...")

    try:
        # Close services
        await price_service.close()
        await swap_service.close()
        # Note: Database is managed by FastAPI app lifespan usually, 
        # but we can close it here if running standalone
        
        logger.info("Services stopped")
    except Exception as e:
        logger.error(f"Shutdown error: {e}")


async def create_tables():
    """Create database tables"""
    try:
        async with db_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables verified/created")
        return True
    except Exception as e:
        logger.error("Failed to create tables", error=str(e))
        return False


async def main():
    """Main entry point for Bot"""
    logger.info("Initializing Bot...")

    # Initialize database (safe to call multiple times)
    await db_manager.initialize()
    
    # Create tables if not exist
    if not await create_tables():
        logger.error("Database initialization failed")
        return

    # Initialize bot
    bot = Bot(
        token=settings.BOT_TOKEN.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # Initialize dispatcher
    dp = Dispatcher(storage=MemoryStorage())

    # Register routers
    dp.include_router(start_router)
    dp.include_router(wallet_router)
    dp.include_router(send_router)
    dp.include_router(receive_router)
    dp.include_router(swap_router)
    dp.include_router(p2p_router)
    dp.include_router(history_router)
    dp.include_router(settings_router)

    # Register hooks
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Start polling
    try:
        # Remove any existing webhook to ensure polling works
        await bot.delete_webhook(drop_pending_updates=True)
        
        logger.info("🚀 Starting polling...")
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types()
        )
    except asyncio.CancelledError:
        logger.info("Polling cancelled (Service stopping)")
    except Exception as e:
        logger.error(f"Polling critical error: {e}")
    finally:
        await bot.session.close()
        logger.info("Bot session closed")


if __name__ == "__main__":
    # Logging configuration
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    # Reduce noise
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user")
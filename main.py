"""
NEXUS WALLET - Main Entry Point
Advanced Telegram Crypto Wallet with Real Blockchain Integration
"""

import asyncio
import sys
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
import structlog

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

# Import services to initialize
from services.price_service import price_service
from services.transaction_service import transaction_service
from services.p2p_service import p2p_service
from services.swap_service import swap_service

logger = structlog.get_logger()


async def on_startup(bot: Bot):
    """Startup actions"""
    bot_info = await bot.get_me()
    logger.info("Bot started", bot_username=f"@{bot_info.username}")
    logger.info("=" * 50)
    logger.info("NEXUS WALLET is ready! (REAL MODE)")
    logger.info("=" * 50)
    
    # Notify admin
    admin_ids = [8405499025]  # Add your ID
    for admin_id in admin_ids:
        try:
            await bot.send_message(
                admin_id,
                "🚀 <b>NEXUS WALLET Started!</b>\n\n"
                f"Bot: @{bot_info.username}\n"
                f"Mode: Real Blockchain & Database\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode="HTML"
            )
        except Exception:
            pass


async def on_shutdown(bot: Bot):
    """Shutdown actions"""
    logger.info("Shutting down NEXUS WALLET...")
    
    # Close services
    await price_service.close()
    await swap_service.close()
    await db_manager.close()
    
    logger.info("Services stopped")
    logger.info("Goodbye!")


async def create_tables():
    """Create database tables"""
    try:
        async with db_manager.engine.begin() as conn:
            # Uncomment to force recreate tables (WARNING: DATA LOSS)
            # await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created")
        return True
    except Exception as e:
        logger.error("Failed to create tables", error=str(e))
        return False


async def main():
    """Main function"""
    logger.info("Starting bot polling...")
    logger.info("=" * 50)
    logger.info("Starting NEXUS WALLET...")
    logger.info("=" * 50)

    # Initialize database
    await db_manager.initialize()

    # Create tables
    if not await create_tables():
        logger.error("Failed to initialize database, exiting...")
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
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=True
        )
    except Exception as e:
        logger.error(f"Polling failed: {e}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    
    try:
        if sys.version_info[:2] < (3, 8):
            print("ERROR: Python 3.8+ required!")
            sys.exit(1)
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)
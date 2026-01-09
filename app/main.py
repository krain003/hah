"""
NEXUS WALLET - Main Application Entry Point
"""

import asyncio
import sys
import structlog
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from redis.asyncio import Redis as AsyncRedis
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Project Imports
from config.settings import settings
from database.connection import db_manager
from database.migrations import run_migrations
from database.models import Base
from middlewares.maintenance import MaintenanceMiddleware

# Handlers
from handlers.admin import router as admin_router
from handlers.admin_test import router as admin_test_router
from handlers.start import router as start_router
from handlers.wallet import router as wallet_router
from handlers.send import router as send_router
from handlers.receive import router as receive_router
from handlers.p2p import router as p2p_router
from handlers.shop import router as shop_router
from handlers.direct_buy import router as direct_buy_router
from handlers.staking import router as staking_router
from handlers.settings import router as settings_router
from handlers.inline_transfer import router as inline_transfer_router  # NEW!
from handlers.exchange import router as exchange_router
from handlers.checks import router as checks_router
from handlers.giveaway import router as giveaway_router
from handlers.real_swap import router as real_swap_router

# Services
from services.price_service import price_service
from services.deposit_watcher import deposit_watcher

# Logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer()
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)
logger = structlog.get_logger()

# Global State Container
class NexusApp:
    bot: Bot = None
    dp: Dispatcher = None
    scheduler: AsyncIOScheduler = None
    redis: AsyncRedis = None

nexus = NexusApp()

# --- INITIALIZATION ---

# 1. Setup Storage (Global)
try:
    redis = AsyncRedis.from_url(settings.REDIS_URL, decode_responses=False)
    storage = RedisStorage(redis, key_builder=DefaultKeyBuilder(with_destiny=True))
    nexus.redis = redis
except Exception:
    storage = MemoryStorage()
    logger.warning("Redis failed, using MemoryStorage")

# 2. Setup Bot & Dispatcher (Global)
session = AiohttpSession(timeout=60)
nexus.bot = Bot(
    token=settings.BOT_TOKEN.get_secret_value(), 
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
nexus.dp = Dispatcher(storage=storage)

# 3. Register Middlewares & Routers
nexus.dp.update.outer_middleware(MaintenanceMiddleware())
nexus.dp.include_routers(
    admin_test_router, 
    admin_router, 
    start_router, 
    wallet_router, 
    send_router, 
    receive_router, 
    real_swap_router, 
    p2p_router, 
    shop_router, 
    direct_buy_router, 
    staking_router, 
    settings_router,
    inline_transfer_router,
    exchange_router,      # <-- ДОБАВЛЕНО!
    checks_router,        # <-- ДОБАВЛЕНО!
    giveaway_router,      # <-- ДОБАВЛЕНО!
)

async def on_startup():
    """Startup sequence"""
    logger.info("system.startup", status="initiating")

    # DB Sync
    await db_manager.initialize()
    async with db_manager.session() as session:
        await run_migrations(session)
    
    logger.info("Migrations completed")
    # Services
    await price_service.initialize()
    
    # Scheduler
    nexus.scheduler = AsyncIOScheduler()
    nexus.scheduler.add_job(price_service._background_update_loop, 'interval', minutes=1)

    nexus.scheduler.add_job(deposit_watcher.check_deposits, 'interval', seconds=30)

    nexus.scheduler.start()

    # Start Polling
    asyncio.create_task(nexus.dp.start_polling(nexus.bot))
    logger.info("bot.started")

async def on_shutdown():
    """Shutdown sequence"""
    if nexus.scheduler: nexus.scheduler.shutdown()
    if nexus.bot: await nexus.bot.session.close()
    await price_service.close()
    await db_manager.close()
    if nexus.redis: await nexus.redis.close()
    logger.info("system.offline")

# FastAPI App
@asynccontextmanager
async def lifespan(app: FastAPI):
    await on_startup()
    yield
    await on_shutdown()

app = FastAPI(title="Nexus Wallet", lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok", "bot": "polling"}

def main():
    print("""
    💎 NEXUS WALLET v3.0
    🤖 Bot + API Mode
    """)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

if __name__ == "__main__":
    main()
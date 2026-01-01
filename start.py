"""
NEXUS WALLET - Production Starter
Runs Web App and Telegram Bot correctly
"""

import os
import sys
import asyncio
import uvicorn
import structlog
from contextlib import asynccontextmanager

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web.app import app as web_app
from main import main as start_bot_logic

logger = structlog.get_logger()

def get_port() -> int:
    return int(os.environ.get("PORT", 8000))

# Эта функция запустит бота как фоновую задачу при старте веб-сервера
@asynccontextmanager
async def lifespan(app):
    # --- STARTUP ---
    logger.info("🚀 Starting NEXUS WALLET Services...")
    
    # Запускаем бота в отдельной задаче (чтобы не блокировать веб)
    bot_task = asyncio.create_task(start_bot_logic())
    
    yield
    
    # --- SHUTDOWN ---
    logger.info("🛑 Shutting down...")
    bot_task.cancel()
    try:
        await bot_task
    except asyncio.CancelledError:
        logger.info("Bot stopped cleanly")

# Подключаем lifespan к нашему веб-приложению
web_app.router.lifespan_context = lifespan

if __name__ == "__main__":
    port = get_port()
    logger.info(f"🌍 Starting Web Server on port {port}")
    
    # Запускаем только Uvicorn. Бот запустится внутри него через lifespan.
    uvicorn.run(
        "web.app:app",  # Путь к приложению (не меняем)
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=True,
        workers=1  # Важно: 1 воркер, чтобы бот не дублировался!
    )
"""
NEXUS WALLET - Production Starter
Runs BOTH Web App and Telegram Bot
"""

import os
import sys
import asyncio
import uvicorn
import structlog

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web.app import app
from main import main as start_bot_polling

logger = structlog.get_logger()

def get_port() -> int:
    return int(os.environ.get("PORT", 8000))

async def start_web_server():
    """Start FastAPI Web Server"""
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=get_port(),
        log_level="info",
        access_log=True
    )
    server = uvicorn.Server(config)
    logger.info("🚀 Starting Web Server...")
    await server.serve()

async def start_services():
    """Run both Bot and Web App concurrently"""
    try:
        # Запускаем и бота, и веб-сервер параллельно
        await asyncio.gather(
            start_bot_polling(),
            start_web_server()
        )
    except Exception as e:
        logger.error(f"Critical error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(start_services())
    except KeyboardInterrupt:
        print("Stopped by user")
"""
NEXUS WALLET - Main FastAPI Application
Includes Telegram Bot runner
"""

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import asyncio
import structlog

# Импортируем функцию запуска бота из корня
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Импорт main функции бота. ВАЖНО: убедись, что путь верный
from main import main as start_bot

from web.database import init_db
from web.routes import auth, wallet, api, tg_app

logger = structlog.get_logger()

# Environment
IS_PRODUCTION = os.environ.get("RAILWAY_ENVIRONMENT") is not None
RAILWAY_PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    
    # 1. Start Database (FORCE INIT)
    logger.info("🛠️ Initializing Web Database...")
    await init_db()
    logger.info("✅ Web Database initialized")
    
    if RAILWAY_PUBLIC_DOMAIN:
        logger.info(f"🌐 URL: https://{RAILWAY_PUBLIC_DOMAIN}")

    # 2. Start Telegram Bot in background
    bot_task = asyncio.create_task(start_bot())
    logger.info("🤖 Telegram Bot started in background")
    
    yield
    
    # Shutdown logic
    logger.info("🛑 Shutting down...")
    bot_task.cancel()
    try:
        await bot_task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title="NEXUS WALLET",
    description="Multi-Chain Crypto Wallet",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files and templates
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(BASE_DIR, "static")
templates_dir = os.path.join(BASE_DIR, "templates")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=templates_dir)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(wallet.router, prefix="/wallet", tags=["Wallet"])
app.include_router(api.router, prefix="/api", tags=["API"])
app.include_router(tg_app.router, prefix="/tg", tags=["Telegram Mini App"])

@app.get("/")
async def home(request: Request):
    """Home page"""
    return templates.TemplateResponse("index.html", {
        "request": request,
        "railway_domain": RAILWAY_PUBLIC_DOMAIN
    })

@app.get("/health")
async def health():
    """Health check"""
    return {"status": "ok", "service": "nexus-wallet"}

@app.get("/info")
async def info():
    """App info"""
    return {
        "name": "NEXUS WALLET",
        "version": "1.0.0",
        "status": "running"
    }
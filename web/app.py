"""
NEXUS WALLET - Main FastAPI Application
Production-ready for Railway.app
"""

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from contextlib import asynccontextmanager
import os

from web.database import init_db
from web.routes import auth, wallet, api, tg_app


# Environment
IS_PRODUCTION = os.environ.get("RAILWAY_ENVIRONMENT") is not None
RAILWAY_PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    await init_db()
    
    if RAILWAY_PUBLIC_DOMAIN:
        print(f"🌐 Public URL: https://{RAILWAY_PUBLIC_DOMAIN}")
        print(f"💎 Telegram Mini App: https://{RAILWAY_PUBLIC_DOMAIN}/tg/")
    
    print("✅ NEXUS WALLET started successfully!")
    
    yield
    
    # Shutdown
    print("👋 Shutting down NEXUS WALLET...")


app = FastAPI(
    title="NEXUS WALLET",
    description="Multi-Chain Crypto Wallet",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if not IS_PRODUCTION else None,  # Disable docs in production
    redoc_url="/redoc" if not IS_PRODUCTION else None
)

# Security middleware for production
if IS_PRODUCTION and RAILWAY_PUBLIC_DOMAIN:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[RAILWAY_PUBLIC_DOMAIN, "localhost", "127.0.0.1"]
    )

# CORS - allow Telegram
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*",
        "https://web.telegram.org",
        "https://telegram.org",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files and templates
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

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
    """Health check endpoint for Railway"""
    return {
        "status": "healthy",
        "service": "nexus-wallet",
        "version": "1.0.0"
    }


@app.get("/info")
async def info():
    """App info"""
    return {
        "name": "NEXUS WALLET",
        "version": "1.0.0",
        "telegram_mini_app": f"https://{RAILWAY_PUBLIC_DOMAIN}/tg/" if RAILWAY_PUBLIC_DOMAIN else "/tg/",
        "environment": "production" if IS_PRODUCTION else "development"
    }
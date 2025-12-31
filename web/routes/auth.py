"""
NEXUS WALLET - Main FastAPI Application
"""

from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

from web.database import init_db
from web.routes import auth, wallet, api, tg_app  # ADD tg_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    await init_db()
    print("✅ Database initialized")
    yield
    print("👋 Shutting down...")


app = FastAPI(
    title="NEXUS WALLET",
    description="Multi-Chain Crypto Wallet",
    version="1.0.0",
    lifespan=lifespan
)

# CORS - allow Telegram
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "https://web.telegram.org"],
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
app.include_router(tg_app.router, prefix="/tg", tags=["Telegram Mini App"])  # ADD THIS


@app.get("/")
async def home(request: Request):
    """Home page"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health():
    """Health check"""
    return {"status": "healthy", "service": "nexus-wallet-web"}
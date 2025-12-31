"""
NEXUS WALLET - Main FastAPI Application
"""

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

from web.database import init_db

IS_PRODUCTION = os.environ.get("RAILWAY_ENVIRONMENT") is not None
RAILWAY_PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting NEXUS WALLET...")
    try:
        await init_db()
        print("Database ready")
    except Exception as e:
        print(f"Database warning: {e}")
    
    if RAILWAY_PUBLIC_DOMAIN:
        print(f"URL: https://{RAILWAY_PUBLIC_DOMAIN}")
    
    yield
    print("Shutting down...")


app = FastAPI(
    title="NEXUS WALLET",
    description="Multi-Chain Crypto Wallet",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(BASE_DIR, "static")
templates_dir = os.path.join(BASE_DIR, "templates")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

if os.path.exists(templates_dir):
    templates = Jinja2Templates(directory=templates_dir)
else:
    templates = None

# Import and include routers
from web.routes import auth, wallet, api, tg_app

app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(wallet.router, prefix="/wallet", tags=["Wallet"])
app.include_router(api.router, prefix="/api", tags=["API"])
app.include_router(tg_app.router, prefix="/tg", tags=["Telegram Mini App"])


@app.get("/")
async def home(request: Request):
    if templates:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "railway_domain": RAILWAY_PUBLIC_DOMAIN
        })
    return {"message": "NEXUS WALLET", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/info")
async def info():
    return {
        "name": "NEXUS WALLET",
        "version": "1.0.0",
        "status": "running"
    }

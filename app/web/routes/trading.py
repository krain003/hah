from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import os

from services.trading_service import trading_service
from database.connection import db_manager
from web.routes.tg_app import get_or_create_user

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

@router.get("/trade", response_class=HTMLResponse)
async def trading_interface(request: Request):
    """Trading Dashboard"""
    # В реальном приложении бери tg_id из initData
    user = await get_or_create_user(tg_id=1) 
    
    return templates.TemplateResponse("tg/trading.html", {
        "request": request,
        "user": user,
        "symbol": "BTCUSDT"
    })

@router.post("/api/trade/open")
async def open_trade(
    user_id: int = Form(...),
    symbol: str = Form(...),
    direction: str = Form(...),
    amount: float = Form(...),
    leverage: int = Form(...)
):
    try:
        pos = await trading_service.open_position(user_id, symbol, direction, amount, leverage)
        return JSONResponse({"status": "success", "id": pos.id, "entry": pos.entry_price})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})

@router.get("/api/price/{symbol}")
async def get_price(symbol: str):
    price = await trading_service.get_current_price(symbol)
    return {"symbol": symbol, "price": price}
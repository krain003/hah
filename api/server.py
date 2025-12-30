from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from decimal import Decimal
import structlog
from database.connection import db_manager
from database.repositories.user_repository import UserRepository
from database.repositories.wallet_repository import WalletRepository
from blockchain.wallet_manager import wallet_manager, NETWORKS
from services.price_service import price_service
from services.transaction_service import transaction_service
from services.p2p_service import p2p_service
from security.encryption_manager import encryption_manager

app = FastAPI(title="NEXUS REAL WEB")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
templates = Jinja2Templates(directory="webapp")

class SendRequest(BaseModel):
    user_id: int; pin: str; network: str; to_address: str; amount: float; token: str
class SettingsRequest(BaseModel):
    user_id: int; field: str; value: str

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/user/{telegram_id}")
async def get_user_data(telegram_id: int):
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, telegram_id)
        if not user: return {"error": "User not found"}
        wallets = await WalletRepository().get_user_wallets(session, user.id)
        total_usd, wallets_data = 0.0, []
        for w in wallets:
            balance = await wallet_manager.get_balance(w.network, w.address)
            price = await price_service.get_price(NETWORKS[w.network].symbol) or 0
            usd_val = float(balance) * float(price); total_usd += usd_val
            wallets_data.append({"network": w.network, "symbol": NETWORKS[w.network].symbol, "icon": NETWORKS[w.network].icon, "address": w.address, "balance": f"{balance:.6f}", "usd_value": f"{usd_val:.2f}"})
        return {"username": user.username, "total_balance": f"${total_usd:,.2f}", "wallets": wallets_data, "currency": user.default_currency, "lang": user.language_code, "id": user.telegram_id}

@app.get("/api/history/{telegram_id}")
async def get_history(telegram_id: int):
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, telegram_id)
        txs = await transaction_service.get_user_transactions(session, user.id, limit=25)
        return [{"type": t.tx_type, "amount": f"{t.amount:.4f}", "symbol": t.token_symbol, "status": t.status, "date": t.created_at.strftime("%d.%m %H:%M")} for t in txs]

@app.get("/api/p2p/orders")
async def get_p2p_orders(type: str = "sell"):
    async with db_manager.session() as session:
        orders = await p2p_service.get_active_orders(session, order_type=type, limit=10)
        return [{"id": o.id, "price": f"{o.price_per_unit:,.2f}", "fiat": o.fiat_currency, "min": f"{o.min_trade_amount:.0f}", "max": f"{o.max_trade_amount:.0f}", "token": o.token_symbol} for o in orders]

@app.post("/api/settings/update")
async def update_settings(req: SettingsRequest):
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, req.user_id)
        await UserRepository().update(session, user.id, **{req.field: req.value})
        await session.commit()
        return {"success": True}

@app.post("/api/send")
async def send_crypto(req: SendRequest):
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, req.user_id)
        if not encryption_manager.verify_pin(req.pin, user.pin_hash): raise HTTPException(403, "Wrong PIN")
        wallet = await WalletRepository().get_user_wallet_by_network(session, user.id, req.network)
        pk = encryption_manager.decrypt_private_key(wallet.encrypted_private_key)
        tx_hash = await wallet_manager.send_transaction(req.network, pk, req.to_address, Decimal(str(req.amount)))
        await transaction_service.create_transaction(session, user.id, "send", req.network, req.token, Decimal(str(req.amount)), tx_hash=tx_hash, status="completed")
        await session.commit()
        return {"success": True, "tx_hash": tx_hash}
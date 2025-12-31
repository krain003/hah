"""
NEXUS WALLET - Telegram Mini App Routes
"""

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from decimal import Decimal
import os
import sys
import secrets
import hashlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from blockchain.wallet_manager import wallet_manager, NETWORKS
from security.encryption_manager import encryption_manager
from web.database import WalletDB, TransactionDB, UserDB

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates", "tg"))


def simple_hash(password: str) -> str:
    """Simple password hash using SHA256 (for internal use only)"""
    salt = secrets.token_hex(16)
    hash_obj = hashlib.sha256((salt + password).encode())
    return salt + ":" + hash_obj.hexdigest()


async def get_or_create_user(tg_id: int = 1, username: str = None, first_name: str = None) -> dict:
    """Get or create user from Telegram ID"""
    user = await UserDB.get_user_by_username(f"tg_{tg_id}")
    
    if not user:
        random_pass = secrets.token_urlsafe(16)
        password_hash = simple_hash(random_pass)
        
        user_id = await UserDB.create_user(
            username=f"tg_{tg_id}",
            password_hash=password_hash,
            email=None
        )
        user = await UserDB.get_user_by_id(user_id)
    
    if user:
        user["tg_id"] = tg_id
        user["tg_username"] = username
        user["tg_first_name"] = first_name or "User"
    
    return user


@router.get("/", response_class=HTMLResponse)
async def tg_app_home(request: Request):
    """Main Telegram Mini App page"""
    user = await get_or_create_user(tg_id=1, username="dev", first_name="Developer")
    
    if not user:
        return templates.TemplateResponse("app.html", {
            "request": request,
            "user": {"tg_first_name": "Guest", "id": 0},
            "wallets": [],
            "networks": NETWORKS,
            "error": "Could not create user"
        })
    
    wallets = await WalletDB.get_user_wallets(user["id"])
    
    wallet_data = []
    for w in wallets:
        try:
            balance = await wallet_manager.get_balance(w["network"], w["address"])
            network_config = NETWORKS.get(w["network"])
            
            wallet_data.append({
                "id": w["id"],
                "network": w["network"],
                "address": w["address"],
                "name": w["name"] or f"{network_config.name} Wallet",
                "balance": str(balance),
                "symbol": network_config.symbol,
                "icon": network_config.icon,
                "is_primary": w["is_primary"]
            })
        except Exception as e:
            network_config = NETWORKS.get(w["network"])
            wallet_data.append({
                "id": w["id"],
                "network": w["network"],
                "address": w["address"],
                "name": w["name"] or w["network"].upper(),
                "balance": "0",
                "symbol": network_config.symbol if network_config else "???",
                "icon": network_config.icon if network_config else "🔗",
                "is_primary": w["is_primary"]
            })
    
    return templates.TemplateResponse("app.html", {
        "request": request,
        "user": user,
        "wallets": wallet_data,
        "networks": NETWORKS,
        "error": None
    })


@router.get("/create", response_class=HTMLResponse)
async def tg_create_wallet_page(request: Request):
    """Create wallet page"""
    return templates.TemplateResponse("wallet_create.html", {
        "request": request,
        "networks": NETWORKS,
        "action": "select"
    })


@router.post("/create", response_class=HTMLResponse)
async def tg_create_wallet(request: Request):
    """Create new wallet"""
    form = await request.form()
    network = form.get("network")
    name = form.get("name")
    
    user = await get_or_create_user(tg_id=1)
    
    if not user:
        return templates.TemplateResponse("wallet_create.html", {
            "request": request,
            "networks": NETWORKS,
            "action": "select",
            "error": "User not found"
        })
    
    if network not in NETWORKS:
        return templates.TemplateResponse("wallet_create.html", {
            "request": request,
            "networks": NETWORKS,
            "action": "select",
            "error": "Invalid network"
        })
    
    try:
        wallet_data = await wallet_manager.create_wallet(network)
        
        encrypted_pk = encryption_manager.encrypt_private_key(wallet_data.private_key)
        encrypted_mnemonic = None
        if wallet_data.mnemonic:
            encrypted_mnemonic = encryption_manager.encrypt_private_key(wallet_data.mnemonic)
        
        existing_wallets = await WalletDB.get_user_wallets(user["id"])
        is_primary = len(existing_wallets) == 0
        
        await WalletDB.create_wallet(
            user_id=user["id"],
            network=network,
            address=wallet_data.address,
            encrypted_private_key=encrypted_pk,
            encrypted_mnemonic=encrypted_mnemonic,
            name=name or f"{NETWORKS[network].name} Wallet",
            is_primary=is_primary
        )
        
        return templates.TemplateResponse("wallet_create.html", {
            "request": request,
            "networks": NETWORKS,
            "action": "success",
            "wallet": {
                "network": network,
                "address": wallet_data.address,
                "mnemonic": wallet_data.mnemonic,
                "name": name or f"{NETWORKS[network].name} Wallet",
                "icon": NETWORKS[network].icon,
                "symbol": NETWORKS[network].symbol
            }
        })
        
    except Exception as e:
        return templates.TemplateResponse("wallet_create.html", {
            "request": request,
            "networks": NETWORKS,
            "action": "select",
            "error": str(e)
        })


@router.get("/wallet/{wallet_id}", response_class=HTMLResponse)
async def tg_wallet_detail(request: Request, wallet_id: int):
    """Wallet detail page"""
    user = await get_or_create_user(tg_id=1)
    
    if not user:
        return RedirectResponse(url="/tg/", status_code=302)
    
    wallet = await WalletDB.get_wallet_by_id(wallet_id, user["id"])
    
    if not wallet:
        return RedirectResponse(url="/tg/", status_code=302)
    
    balance = await wallet_manager.get_balance(wallet["network"], wallet["address"])
    network_config = NETWORKS.get(wallet["network"])
    transactions = await TransactionDB.get_user_transactions(user["id"], limit=20)
    wallet_transactions = [t for t in transactions if t["wallet_id"] == wallet_id]
    
    return templates.TemplateResponse("wallet_detail.html", {
        "request": request,
        "user": user,
        "wallet": wallet,
        "balance": str(balance),
        "network": network_config,
        "transactions": wallet_transactions
    })


@router.get("/send/{wallet_id}", response_class=HTMLResponse)
async def tg_send_page(request: Request, wallet_id: int):
    """Send crypto page"""
    user = await get_or_create_user(tg_id=1)
    
    if not user:
        return RedirectResponse(url="/tg/", status_code=302)
    
    wallet = await WalletDB.get_wallet_by_id(wallet_id, user["id"])
    
    if not wallet:
        return RedirectResponse(url="/tg/", status_code=302)
    
    balance = await wallet_manager.get_balance(wallet["network"], wallet["address"])
    network_config = NETWORKS.get(wallet["network"])
    
    return templates.TemplateResponse("send.html", {
        "request": request,
        "user": user,
        "wallet": wallet,
        "balance": str(balance),
        "network": network_config
    })


@router.post("/send/{wallet_id}", response_class=HTMLResponse)
async def tg_send_transaction(request: Request, wallet_id: int):
    """Process send transaction"""
    form = await request.form()
    to_address = form.get("to_address")
    amount = form.get("amount")
    
    user = await get_or_create_user(tg_id=1)
    
    if not user:
        return RedirectResponse(url="/tg/", status_code=302)
    
    wallet = await WalletDB.get_wallet_by_id(wallet_id, user["id"])
    
    if not wallet:
        return RedirectResponse(url="/tg/", status_code=302)
    
    network_config = NETWORKS.get(wallet["network"])
    
    try:
        private_key = encryption_manager.decrypt_private_key(wallet["encrypted_private_key"])
        
        tx_hash = await wallet_manager.send_transaction(
            network=wallet["network"],
            private_key=private_key,
            to_address=to_address,
            amount=Decimal(amount)
        )
        
        await TransactionDB.create_transaction(
            user_id=user["id"],
            wallet_id=wallet_id,
            network=wallet["network"],
            tx_type="send",
            amount=amount,
            to_address=to_address,
            from_address=wallet["address"],
            tx_hash=tx_hash,
            status="pending"
        )
        
        return templates.TemplateResponse("send.html", {
            "request": request,
            "user": user,
            "wallet": wallet,
            "network": network_config,
            "success": True,
            "tx_hash": tx_hash
        })
        
    except Exception as e:
        balance = await wallet_manager.get_balance(wallet["network"], wallet["address"])
        return templates.TemplateResponse("send.html", {
            "request": request,
            "user": user,
            "wallet": wallet,
            "balance": str(balance),
            "network": network_config,
            "error": str(e)
        })


@router.get("/receive/{wallet_id}", response_class=HTMLResponse)
async def tg_receive_page(request: Request, wallet_id: int):
    """Receive crypto page"""
    user = await get_or_create_user(tg_id=1)
    
    if not user:
        return RedirectResponse(url="/tg/", status_code=302)
    
    wallet = await WalletDB.get_wallet_by_id(wallet_id, user["id"])
    
    if not wallet:
        return RedirectResponse(url="/tg/", status_code=302)
    
    network_config = NETWORKS.get(wallet["network"])
    
    return templates.TemplateResponse("receive.html", {
        "request": request,
        "user": user,
        "wallet": wallet,
        "network": network_config
    })


@router.post("/delete/{wallet_id}")
async def tg_delete_wallet(request: Request, wallet_id: int):
    """Delete wallet"""
    user = await get_or_create_user(tg_id=1)
    
    if user:
        await WalletDB.delete_wallet(wallet_id, user["id"])
    
    return RedirectResponse(url="/tg/", status_code=302)

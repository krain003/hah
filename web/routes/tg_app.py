"""
NEXUS WALLET - Telegram Mini App Routes
No separate auth needed - uses Telegram auth
"""

from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from decimal import Decimal
from typing import Optional
import hashlib
import hmac
import json
import os
import sys
from urllib.parse import parse_qsl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from blockchain.wallet_manager import wallet_manager, NETWORKS
from security.encryption_manager import encryption_manager
from web.database import WalletDB, TransactionDB, UserDB

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates", "tg"))

# Bot token for validation (set in environment)
BOT_TOKEN = os.getenv("BOT_TOKEN", "")


def validate_telegram_data(init_data: str) -> Optional[dict]:
    """
    Validate Telegram Mini App init data
    Returns user data if valid, None otherwise
    """
    if not BOT_TOKEN:
        # If no token set, skip validation (for development)
        return {"id": 0, "first_name": "Dev", "username": "developer"}
    
    try:
        parsed_data = dict(parse_qsl(init_data, keep_blank_values=True))
        
        if "hash" not in parsed_data:
            return None
        
        received_hash = parsed_data.pop("hash")
        
        # Create data check string
        data_check_arr = sorted([f"{k}={v}" for k, v in parsed_data.items()])
        data_check_string = "\n".join(data_check_arr)
        
        # Create secret key
        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()
        
        # Calculate hash
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if calculated_hash != received_hash:
            return None
        
        # Parse user data
        if "user" in parsed_data:
            return json.loads(parsed_data["user"])
        
        return None
        
    except Exception as e:
        print(f"Telegram validation error: {e}")
        return None


async def get_or_create_user(tg_user: dict) -> dict:
    """Get existing user or create new one from Telegram data"""
    tg_id = tg_user.get("id")
    username = tg_user.get("username", f"user_{tg_id}")
    
    # Try to find existing user
    user = await UserDB.get_user_by_username(f"tg_{tg_id}")
    
    if not user:
        # Create new user
        import secrets
        from passlib.hash import bcrypt
        
        # Generate random password (user won't need it - uses Telegram auth)
        random_pass = secrets.token_urlsafe(32)
        password_hash = bcrypt.hash(random_pass)
        
        user_id = await UserDB.create_user(
            username=f"tg_{tg_id}",
            password_hash=password_hash,
            email=None
        )
        
        user = await UserDB.get_user_by_id(user_id)
    
    # Add Telegram info
    user["tg_id"] = tg_id
    user["tg_username"] = tg_user.get("username")
    user["tg_first_name"] = tg_user.get("first_name", "User")
    
    return user


# ============== PAGES ==============

@router.get("/", response_class=HTMLResponse)
async def tg_app_home(request: Request, tgWebAppData: str = Query(default="")):
    """Main Telegram Mini App page"""
    
    # Validate Telegram data
    tg_user = validate_telegram_data(tgWebAppData)
    
    if not tg_user and BOT_TOKEN:
        return templates.TemplateResponse("app.html", {
            "request": request,
            "error": "Invalid Telegram authorization",
            "user": None,
            "wallets": [],
            "networks": NETWORKS
        })
    
    # Get or create user
    if tg_user:
        user = await get_or_create_user(tg_user)
    else:
        # Development mode
        user = {"id": 1, "username": "dev_user", "tg_first_name": "Developer"}
    
    # Get user wallets
    wallets = await WalletDB.get_user_wallets(user["id"])
    
    # Enrich wallet data with balances and network info
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
                "is_primary": w["is_primary"],
                "error": str(e)
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
async def tg_create_wallet(
    request: Request,
    tgWebAppData: str = Query(default="")
):
    """Create new wallet"""
    form = await request.form()
    network = form.get("network")
    name = form.get("name")
    
    tg_user = validate_telegram_data(tgWebAppData)
    if not tg_user and BOT_TOKEN:
        return templates.TemplateResponse("wallet_create.html", {
            "request": request,
            "networks": NETWORKS,
            "action": "select",
            "error": "Authorization failed"
        })
    
    if tg_user:
        user = await get_or_create_user(tg_user)
    else:
        user = {"id": 1}
    
    if network not in NETWORKS:
        return templates.TemplateResponse("wallet_create.html", {
            "request": request,
            "networks": NETWORKS,
            "action": "select",
            "error": "Invalid network"
        })
    
    try:
        # Create wallet
        wallet_data = await wallet_manager.create_wallet(network)
        
        # Encrypt sensitive data
        encrypted_pk = encryption_manager.encrypt_private_key(wallet_data.private_key)
        encrypted_mnemonic = None
        if wallet_data.mnemonic:
            encrypted_mnemonic = encryption_manager.encrypt_private_key(wallet_data.mnemonic)
        
        # Check if first wallet
        existing_wallets = await WalletDB.get_user_wallets(user["id"])
        is_primary = len(existing_wallets) == 0
        
        # Save to database
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
async def tg_wallet_detail(
    request: Request,
    wallet_id: int,
    tgWebAppData: str = Query(default="")
):
    """Wallet detail page"""
    tg_user = validate_telegram_data(tgWebAppData)
    if tg_user:
        user = await get_or_create_user(tg_user)
    else:
        user = {"id": 1}
    
    wallet = await WalletDB.get_wallet_by_id(wallet_id, user["id"])
    
    if not wallet:
        return templates.TemplateResponse("app.html", {
            "request": request,
            "error": "Wallet not found",
            "user": user,
            "wallets": [],
            "networks": NETWORKS
        })
    
    # Get balance
    balance = await wallet_manager.get_balance(wallet["network"], wallet["address"])
    network_config = NETWORKS.get(wallet["network"])
    
    # Get transactions
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
async def tg_send_page(
    request: Request,
    wallet_id: int,
    tgWebAppData: str = Query(default="")
):
    """Send crypto page"""
    tg_user = validate_telegram_data(tgWebAppData)
    if tg_user:
        user = await get_or_create_user(tg_user)
    else:
        user = {"id": 1}
    
    wallet = await WalletDB.get_wallet_by_id(wallet_id, user["id"])
    
    if not wallet:
        return templates.TemplateResponse("send.html", {
            "request": request,
            "error": "Wallet not found"
        })
    
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
async def tg_send_transaction(
    request: Request,
    wallet_id: int,
    tgWebAppData: str = Query(default="")
):
    """Process send transaction"""
    form = await request.form()
    to_address = form.get("to_address")
    amount = form.get("amount")
    
    tg_user = validate_telegram_data(tgWebAppData)
    if tg_user:
        user = await get_or_create_user(tg_user)
    else:
        user = {"id": 1}
    
    wallet = await WalletDB.get_wallet_by_id(wallet_id, user["id"])
    
    if not wallet:
        return templates.TemplateResponse("send.html", {
            "request": request,
            "error": "Wallet not found"
        })
    
    network_config = NETWORKS.get(wallet["network"])
    
    try:
        # Decrypt private key
        private_key = encryption_manager.decrypt_private_key(wallet["encrypted_private_key"])
        
        # Send transaction
        tx_hash = await wallet_manager.send_transaction(
            network=wallet["network"],
            private_key=private_key,
            to_address=to_address,
            amount=Decimal(amount)
        )
        
        # Save transaction
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
async def tg_receive_page(
    request: Request,
    wallet_id: int,
    tgWebAppData: str = Query(default="")
):
    """Receive crypto page"""
    tg_user = validate_telegram_data(tgWebAppData)
    if tg_user:
        user = await get_or_create_user(tg_user)
    else:
        user = {"id": 1}
    
    wallet = await WalletDB.get_wallet_by_id(wallet_id, user["id"])
    
    if not wallet:
        return templates.TemplateResponse("receive.html", {
            "request": request,
            "error": "Wallet not found"
        })
    
    network_config = NETWORKS.get(wallet["network"])
    
    return templates.TemplateResponse("receive.html", {
        "request": request,
        "user": user,
        "wallet": wallet,
        "network": network_config
    })


@router.post("/delete/{wallet_id}")
async def tg_delete_wallet(
    request: Request,
    wallet_id: int,
    tgWebAppData: str = Query(default="")
):
    """Delete wallet"""
    from fastapi.responses import RedirectResponse
    
    tg_user = validate_telegram_data(tgWebAppData)
    if tg_user:
        user = await get_or_create_user(tg_user)
    else:
        user = {"id": 1}
    
    await WalletDB.delete_wallet(wallet_id, user["id"])
    
    return RedirectResponse(url="/tg/", status_code=302)
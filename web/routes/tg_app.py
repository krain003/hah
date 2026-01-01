"""
NEXUS WALLET - Telegram Mini App Routes
Full-featured wallet with all bot functions
"""

from fastapi import APIRouter, Request, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from decimal import Decimal, InvalidOperation
import os
import sys
import secrets
import hashlib
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from blockchain.wallet_manager import wallet_manager, NETWORKS
from security.encryption_manager import encryption_manager
from web.database import WalletDB, TransactionDB, UserDB

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


# ==================== HELPERS ====================

def simple_hash(password: str) -> str:
    """Simple password hash"""
    salt = secrets.token_hex(16)
    hash_obj = hashlib.sha256((salt + password).encode())
    return salt + ":" + hash_obj.hexdigest()


def verify_simple_hash(password: str, stored_hash: str) -> bool:
    """Verify simple hash"""
    try:
        salt, hash_value = stored_hash.split(":")
        hash_obj = hashlib.sha256((salt + password).encode())
        return hash_obj.hexdigest() == hash_value
    except:
        return False


async def get_or_create_user(tg_id: int = 1, username: str = None, first_name: str = None) -> dict:
    """Get or create user"""
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


def format_balance(balance: Decimal, decimals: int = 6) -> str:
    """Format balance for display"""
    if balance == 0:
        return "0"
    formatted = f"{balance:.{decimals}f}".rstrip('0').rstrip('.')
    return formatted


def format_address(address: str, start: int = 8, end: int = 6) -> str:
    """Format address for display"""
    if len(address) <= start + end:
        return address
    return f"{address[:start]}...{address[-end:]}"


# ==================== MAIN PAGES ====================

@router.get("/", response_class=HTMLResponse)
async def tg_app_home(request: Request):
    """Main page - Dashboard"""
    user = await get_or_create_user(tg_id=1, username="dev", first_name="Developer")
    
    if not user:
        return templates.TemplateResponse("tg/app.html", {
            "request": request,
            "user": {"tg_first_name": "Guest", "id": 0},
            "wallets": [],
            "networks": NETWORKS,
            "total_usd": 0,
            "error": "Could not create user"
        })
    
    wallets = await WalletDB.get_user_wallets(user["id"])
    
    wallet_data = []
    total_usd = Decimal("0")
    
    for w in wallets:
        try:
            balance = await wallet_manager.get_balance(w["network"], w["address"])
            network_config = NETWORKS.get(w["network"])
            
            wallet_data.append({
                "id": w["id"],
                "network": w["network"],
                "address": w["address"],
                "short_address": format_address(w["address"]),
                "name": w["name"] or f"{network_config.name} Wallet",
                "balance": format_balance(balance),
                "balance_raw": balance,
                "symbol": network_config.symbol,
                "icon": network_config.icon,
                "is_primary": w["is_primary"],
                "explorer_url": network_config.explorer_url
            })
        except Exception:
            network_config = NETWORKS.get(w["network"])
            wallet_data.append({
                "id": w["id"],
                "network": w["network"],
                "address": w["address"],
                "short_address": format_address(w["address"]),
                "name": w["name"] or w["network"].upper(),
                "balance": "0",
                "balance_raw": Decimal("0"),
                "symbol": network_config.symbol if network_config else "???",
                "icon": network_config.icon if network_config else "🔗",
                "is_primary": w["is_primary"],
                "explorer_url": network_config.explorer_url if network_config else "#"
            })
    
    # Get recent transactions
    transactions = await TransactionDB.get_user_transactions(user["id"], limit=5)
    
    return templates.TemplateResponse("tg/app.html", {
        "request": request,
        "user": user,
        "wallets": wallet_data,
        "networks": NETWORKS,
        "total_usd": float(total_usd),
        "transactions": transactions,
        "error": None
    })


# ==================== WALLET MANAGEMENT ====================

@router.get("/wallet", response_class=HTMLResponse)
async def wallet_menu(request: Request):
    """Wallet management menu"""
    user = await get_or_create_user(tg_id=1)
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
                "short_address": format_address(w["address"]),
                "name": w["name"] or f"{network_config.name} Wallet",
                "balance": format_balance(balance),
                "symbol": network_config.symbol,
                "icon": network_config.icon,
            })
        except:
            pass
    
    return templates.TemplateResponse("tg/wallet_menu.html", {
        "request": request,
        "user": user,
        "wallets": wallet_data,
        "networks": NETWORKS
    })


@router.get("/create", response_class=HTMLResponse)
async def create_wallet_page(request: Request):
    """Create wallet page"""
    return templates.TemplateResponse("tg/wallet_create.html", {
        "request": request,
        "networks": NETWORKS,
        "action": "select"
    })


@router.post("/create", response_class=HTMLResponse)
async def create_wallet(request: Request):
    """Create new wallet"""
    form = await request.form()
    network = form.get("network")
    name = form.get("name")
    create_all = form.get("create_all") == "true"
    
    user = await get_or_create_user(tg_id=1)
    
    if not user:
        return templates.TemplateResponse("tg/wallet_create.html", {
            "request": request,
            "networks": NETWORKS,
            "action": "select",
            "error": "User not found"
        })
    
    try:
        if create_all:
            # Create wallets for all networks
            mnemonic = wallet_manager.generate_mnemonic()
            created_wallets = []
            
            for net_id in NETWORKS.keys():
                try:
                    existing = await WalletDB.get_user_wallet_by_network(user["id"], net_id)
                    if existing:
                        continue
                    
                    wallet_data = await wallet_manager.create_wallet(net_id, mnemonic)
                    encrypted_pk = encryption_manager.encrypt_private_key(wallet_data.private_key)
                    encrypted_mnemonic = encryption_manager.encrypt_private_key(mnemonic)
                    
                    await WalletDB.create_wallet(
                        user_id=user["id"],
                        network=net_id,
                        address=wallet_data.address,
                        encrypted_private_key=encrypted_pk,
                        encrypted_mnemonic=encrypted_mnemonic,
                        name=f"{NETWORKS[net_id].name} Wallet",
                        is_primary=len(created_wallets) == 0
                    )
                    created_wallets.append(net_id)
                except Exception as e:
                    continue
            
            return templates.TemplateResponse("tg/wallet_create.html", {
                "request": request,
                "networks": NETWORKS,
                "action": "success_all",
                "created_count": len(created_wallets),
                "mnemonic": mnemonic
            })
        
        else:
            # Create single network wallet
            if network not in NETWORKS:
                return templates.TemplateResponse("tg/wallet_create.html", {
                    "request": request,
                    "networks": NETWORKS,
                    "action": "select",
                    "error": "Invalid network"
                })
            
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
            
            return templates.TemplateResponse("tg/wallet_create.html", {
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
        return templates.TemplateResponse("tg/wallet_create.html", {
            "request": request,
            "networks": NETWORKS,
            "action": "select",
            "error": str(e)
        })


@router.get("/import", response_class=HTMLResponse)
async def import_wallet_page(request: Request):
    """Import wallet page"""
    return templates.TemplateResponse("tg/wallet_import.html", {
        "request": request,
        "networks": NETWORKS
    })


@router.post("/import", response_class=HTMLResponse)
async def import_wallet(request: Request):
    """Import wallet from mnemonic or private key"""
    form = await request.form()
    import_type = form.get("import_type")
    mnemonic = form.get("mnemonic", "").strip()
    private_key = form.get("private_key", "").strip()
    network = form.get("network")
    
    user = await get_or_create_user(tg_id=1)
    
    try:
        if import_type == "mnemonic" and mnemonic:
            if not wallet_manager.validate_mnemonic(mnemonic):
                return templates.TemplateResponse("tg/wallet_import.html", {
                    "request": request,
                    "networks": NETWORKS,
                    "error": "Invalid mnemonic phrase"
                })
            
            # Import for all networks
            created_count = 0
            for net_id in NETWORKS.keys():
                try:
                    wallet_data = await wallet_manager.create_wallet(net_id, mnemonic)
                    
                    # Check if already exists
                    existing = await WalletDB.get_wallet_by_address(wallet_data.address)
                    if existing:
                        continue
                    
                    encrypted_pk = encryption_manager.encrypt_private_key(wallet_data.private_key)
                    encrypted_mnemonic = encryption_manager.encrypt_private_key(mnemonic)
                    
                    await WalletDB.create_wallet(
                        user_id=user["id"],
                        network=net_id,
                        address=wallet_data.address,
                        encrypted_private_key=encrypted_pk,
                        encrypted_mnemonic=encrypted_mnemonic,
                        name=f"{NETWORKS[net_id].name} (Imported)",
                        is_primary=False
                    )
                    created_count += 1
                except:
                    continue
            
            return templates.TemplateResponse("tg/wallet_import.html", {
                "request": request,
                "networks": NETWORKS,
                "success": True,
                "message": f"Successfully imported {created_count} wallets"
            })
        
        elif import_type == "private_key" and private_key and network:
            wallet_data = wallet_manager.import_from_private_key(network, private_key)
            
            encrypted_pk = encryption_manager.encrypt_private_key(private_key)
            
            await WalletDB.create_wallet(
                user_id=user["id"],
                network=network,
                address=wallet_data.address,
                encrypted_private_key=encrypted_pk,
                name=f"{NETWORKS[network].name} (Imported)",
                is_primary=False
            )
            
            return templates.TemplateResponse("tg/wallet_import.html", {
                "request": request,
                "networks": NETWORKS,
                "success": True,
                "message": f"Successfully imported {NETWORKS[network].name} wallet"
            })
        
        else:
            return templates.TemplateResponse("tg/wallet_import.html", {
                "request": request,
                "networks": NETWORKS,
                "error": "Please provide mnemonic or private key"
            })
    
    except Exception as e:
        return templates.TemplateResponse("tg/wallet_import.html", {
            "request": request,
            "networks": NETWORKS,
            "error": str(e)
        })


@router.get("/wallet/{wallet_id}", response_class=HTMLResponse)
async def wallet_detail(request: Request, wallet_id: int):
    """Wallet detail page"""
    user = await get_or_create_user(tg_id=1)
    wallet = await WalletDB.get_wallet_by_id(wallet_id, user["id"])
    
    if not wallet:
        return RedirectResponse(url="/tg/", status_code=302)
    
    balance = await wallet_manager.get_balance(wallet["network"], wallet["address"])
    network_config = NETWORKS.get(wallet["network"])
    
    transactions = await TransactionDB.get_user_transactions(user["id"], limit=20)
    wallet_transactions = [t for t in transactions if t["wallet_id"] == wallet_id]
    
    return templates.TemplateResponse("tg/wallet_detail.html", {
        "request": request,
        "user": user,
        "wallet": wallet,
        "balance": format_balance(balance),
        "balance_raw": balance,
        "network": network_config,
        "transactions": wallet_transactions
    })


# ==================== SEND ====================

@router.get("/send", response_class=HTMLResponse)
async def send_select_network(request: Request):
    """Send - select network"""
    user = await get_or_create_user(tg_id=1)
    wallets = await WalletDB.get_user_wallets(user["id"])
    
    if not wallets:
        return templates.TemplateResponse("tg/send.html", {
            "request": request,
            "step": "no_wallets"
        })
    
    wallet_data = []
    for w in wallets:
        try:
            balance = await wallet_manager.get_balance(w["network"], w["address"])
            network_config = NETWORKS.get(w["network"])
            wallet_data.append({
                "id": w["id"],
                "network": w["network"],
                "balance": format_balance(balance),
                "symbol": network_config.symbol,
                "icon": network_config.icon,
                "name": network_config.name
            })
        except:
            pass
    
    return templates.TemplateResponse("tg/send.html", {
        "request": request,
        "step": "select_network",
        "wallets": wallet_data
    })


@router.get("/send/{wallet_id}", response_class=HTMLResponse)
async def send_page(request: Request, wallet_id: int):
    """Send crypto page"""
    user = await get_or_create_user(tg_id=1)
    wallet = await WalletDB.get_wallet_by_id(wallet_id, user["id"])
    
    if not wallet:
        return RedirectResponse(url="/tg/send", status_code=302)
    
    balance = await wallet_manager.get_balance(wallet["network"], wallet["address"])
    network_config = NETWORKS.get(wallet["network"])
    
    return templates.TemplateResponse("tg/send.html", {
        "request": request,
        "step": "enter_details",
        "user": user,
        "wallet": wallet,
        "balance": format_balance(balance),
        "balance_raw": float(balance),
        "network": network_config
    })


@router.post("/send/{wallet_id}", response_class=HTMLResponse)
async def send_transaction(request: Request, wallet_id: int):
    """Process send transaction"""
    form = await request.form()
    to_address = form.get("to_address", "").strip()
    amount = form.get("amount", "").strip()
    
    user = await get_or_create_user(tg_id=1)
    wallet = await WalletDB.get_wallet_by_id(wallet_id, user["id"])
    
    if not wallet:
        return RedirectResponse(url="/tg/send", status_code=302)
    
    network_config = NETWORKS.get(wallet["network"])
    balance = await wallet_manager.get_balance(wallet["network"], wallet["address"])
    
    # Validate
    try:
        amount_decimal = Decimal(amount)
        if amount_decimal <= 0:
            raise ValueError("Amount must be positive")
        if amount_decimal > balance:
            raise ValueError("Insufficient balance")
    except (InvalidOperation, ValueError) as e:
        return templates.TemplateResponse("tg/send.html", {
            "request": request,
            "step": "enter_details",
            "wallet": wallet,
            "balance": format_balance(balance),
            "balance_raw": float(balance),
            "network": network_config,
            "error": str(e) if str(e) else "Invalid amount"
        })
    
    try:
        # Decrypt private key
        private_key = encryption_manager.decrypt_private_key(wallet["encrypted_private_key"])
        
        # Send transaction
        tx_hash = await wallet_manager.send_transaction(
            network=wallet["network"],
            private_key=private_key,
            to_address=to_address,
            amount=amount_decimal
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
        
        return templates.TemplateResponse("tg/send.html", {
            "request": request,
            "step": "success",
            "wallet": wallet,
            "network": network_config,
            "tx_hash": tx_hash,
            "amount": amount,
            "to_address": to_address,
            "explorer_url": f"{network_config.explorer_url}/tx/{tx_hash}"
        })
        
    except Exception as e:
        return templates.TemplateResponse("tg/send.html", {
            "request": request,
            "step": "enter_details",
            "wallet": wallet,
            "balance": format_balance(balance),
            "balance_raw": float(balance),
            "network": network_config,
            "error": str(e)
        })


# ==================== RECEIVE ====================

@router.get("/receive", response_class=HTMLResponse)
async def receive_select_network(request: Request):
    """Receive - select network"""
    user = await get_or_create_user(tg_id=1)
    wallets = await WalletDB.get_user_wallets(user["id"])
    
    if not wallets:
        return templates.TemplateResponse("tg/receive.html", {
            "request": request,
            "step": "no_wallets"
        })
    
    wallet_data = []
    for w in wallets:
        network_config = NETWORKS.get(w["network"])
        wallet_data.append({
            "id": w["id"],
            "network": w["network"],
            "address": w["address"],
            "symbol": network_config.symbol if network_config else "???",
            "icon": network_config.icon if network_config else "🔗",
            "name": network_config.name if network_config else w["network"]
        })
    
    return templates.TemplateResponse("tg/receive.html", {
        "request": request,
        "step": "select_network",
        "wallets": wallet_data
    })


@router.get("/receive/{wallet_id}", response_class=HTMLResponse)
async def receive_page(request: Request, wallet_id: int):
    """Receive crypto page with QR"""
    user = await get_or_create_user(tg_id=1)
    wallet = await WalletDB.get_wallet_by_id(wallet_id, user["id"])
    
    if not wallet:
        return RedirectResponse(url="/tg/receive", status_code=302)
    
    network_config = NETWORKS.get(wallet["network"])
    
    return templates.TemplateResponse("tg/receive.html", {
        "request": request,
        "step": "show_address",
        "user": user,
        "wallet": wallet,
        "network": network_config
    })


# ==================== HISTORY ====================

@router.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, filter: str = "all"):
    """Transaction history"""
    user = await get_or_create_user(tg_id=1)
    
    tx_type = None if filter == "all" else filter
    transactions = await TransactionDB.get_user_transactions(user["id"], limit=50)
    
    # Filter if needed
    if tx_type:
        transactions = [t for t in transactions if t.get("tx_type") == tx_type]
    
    return templates.TemplateResponse("tg/history.html", {
        "request": request,
        "user": user,
        "transactions": transactions,
        "current_filter": filter,
        "networks": NETWORKS
    })


# ==================== SETTINGS ====================

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings page"""
    user = await get_or_create_user(tg_id=1)
    
    return templates.TemplateResponse("tg/settings.html", {
        "request": request,
        "user": user,
        "languages": {
            "en": "🇬🇧 English",
            "ru": "🇷🇺 Русский",
            "zh": "🇨🇳 中文",
            "es": "🇪🇸 Español"
        },
        "currencies": {
            "USD": "🇺🇸 US Dollar",
            "EUR": "🇪🇺 Euro",
            "RUB": "🇷🇺 Russian Ruble"
        }
    })


# ==================== SWAP ====================

@router.get("/swap", response_class=HTMLResponse)
async def swap_page(request: Request):
    """Swap page"""
    user = await get_or_create_user(tg_id=1)
    wallets = await WalletDB.get_user_wallets(user["id"])
    
    # Filter to EVM networks (swap supported)
    evm_wallets = []
    for w in wallets:
        network_config = NETWORKS.get(w["network"])
        if network_config and network_config.network_type.value == "evm":
            try:
                balance = await wallet_manager.get_balance(w["network"], w["address"])
                evm_wallets.append({
                    "id": w["id"],
                    "network": w["network"],
                    "balance": format_balance(balance),
                    "symbol": network_config.symbol,
                    "icon": network_config.icon,
                    "name": network_config.name
                })
            except:
                pass
    
    return templates.TemplateResponse("tg/swap.html", {
        "request": request,
        "user": user,
        "wallets": evm_wallets,
        "networks": NETWORKS
    })


# ==================== P2P ====================

@router.get("/p2p", response_class=HTMLResponse)
async def p2p_page(request: Request):
    """P2P trading page"""
    user = await get_or_create_user(tg_id=1)
    
    return templates.TemplateResponse("tg/p2p.html", {
        "request": request,
        "user": user
    })


# ==================== DELETE WALLET ====================

@router.post("/delete/{wallet_id}")
async def delete_wallet(request: Request, wallet_id: int):
    """Delete wallet"""
    user = await get_or_create_user(tg_id=1)
    
    if user:
        await WalletDB.delete_wallet(wallet_id, user["id"])
    
    return RedirectResponse(url="/tg/", status_code=302)


# ==================== API ENDPOINTS ====================

@router.get("/api/balance/{wallet_id}")
async def api_get_balance(wallet_id: int):
    """API: Get wallet balance"""
    user = await get_or_create_user(tg_id=1)
    wallet = await WalletDB.get_wallet_by_id(wallet_id, user["id"])
    
    if not wallet:
        return JSONResponse({"error": "Wallet not found"}, status_code=404)
    
    try:
        balance = await wallet_manager.get_balance(wallet["network"], wallet["address"])
        return JSONResponse({
            "balance": str(balance),
            "network": wallet["network"],
            "symbol": NETWORKS[wallet["network"]].symbol
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
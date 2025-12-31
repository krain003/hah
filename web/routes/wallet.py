"""
NEXUS WALLET - Wallet Routes
"""

from fastapi import APIRouter, Request, Form, HTTPException, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from decimal import Decimal
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from web.database import WalletDB, TransactionDB
from web.routes.auth import get_current_user, require_auth, sessions
from blockchain.wallet_manager import wallet_manager, NETWORKS
from security.encryption_manager import encryption_manager

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


async def get_user_or_redirect(request: Request):
    """Get user or redirect to login"""
    session = get_current_user(request)
    if not session:
        return None
    from web.database import UserDB
    return await UserDB.get_user_by_id(session["user_id"])


@router.get("/dashboard")
async def dashboard(request: Request):
    """Main dashboard"""
    user = await get_user_or_redirect(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)
    
    # Get user wallets
    wallets = await WalletDB.get_user_wallets(user["id"])
    
    # Get balances for each wallet
    wallet_data = []
    total_usd = Decimal("0")
    
    for w in wallets:
        try:
            balance = await wallet_manager.get_balance(w["network"], w["address"])
            network_config = NETWORKS.get(w["network"], {})
            
            wallet_data.append({
                "id": w["id"],
                "network": w["network"],
                "address": w["address"],
                "name": w["name"] or f"{network_config.name if hasattr(network_config, 'name') else w['network'].upper()} Wallet",
                "balance": str(balance),
                "symbol": network_config.symbol if hasattr(network_config, 'symbol') else w["network"].upper(),
                "icon": network_config.icon if hasattr(network_config, 'icon') else "🔗",
                "is_primary": w["is_primary"]
            })
        except Exception as e:
            wallet_data.append({
                "id": w["id"],
                "network": w["network"],
                "address": w["address"],
                "name": w["name"] or w["network"].upper(),
                "balance": "0",
                "symbol": w["network"].upper(),
                "icon": "🔗",
                "is_primary": w["is_primary"],
                "error": str(e)
            })
    
    # Get recent transactions
    transactions = await TransactionDB.get_user_transactions(user["id"], limit=10)
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "wallets": wallet_data,
        "transactions": transactions,
        "networks": NETWORKS,
        "total_usd": str(total_usd)
    })


@router.get("/create")
async def create_wallet_page(request: Request):
    """Create wallet page"""
    user = await get_user_or_redirect(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)
    
    return templates.TemplateResponse("wallet.html", {
        "request": request,
        "user": user,
        "networks": NETWORKS,
        "action": "create"
    })


@router.post("/create")
async def create_wallet(
    request: Request,
    network: str = Form(...),
    name: str = Form(None)
):
    """Create new wallet"""
    user = await get_user_or_redirect(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)
    
    if network not in NETWORKS:
        return templates.TemplateResponse("wallet.html", {
            "request": request,
            "user": user,
            "networks": NETWORKS,
            "action": "create",
            "error": "Invalid network"
        })
    
    try:
        # Create wallet
        wallet_data = await wallet_manager.create_wallet(network)
        
        # Encrypt private key and mnemonic
        encrypted_pk = encryption_manager.encrypt_private_key(wallet_data.private_key)
        encrypted_mnemonic = None
        if wallet_data.mnemonic:
            encrypted_mnemonic = encryption_manager.encrypt_private_key(wallet_data.mnemonic)
        
        # Check if first wallet (make it primary)
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
        
        return templates.TemplateResponse("wallet.html", {
            "request": request,
            "user": user,
            "networks": NETWORKS,
            "action": "created",
            "wallet": {
                "network": network,
                "address": wallet_data.address,
                "mnemonic": wallet_data.mnemonic,
                "name": name or f"{NETWORKS[network].name} Wallet"
            },
            "success": True
        })
        
    except Exception as e:
        return templates.TemplateResponse("wallet.html", {
            "request": request,
            "user": user,
            "networks": NETWORKS,
            "action": "create",
            "error": str(e)
        })


@router.get("/import")
async def import_wallet_page(request: Request):
    """Import wallet page"""
    user = await get_user_or_redirect(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)
    
    return templates.TemplateResponse("wallet.html", {
        "request": request,
        "user": user,
        "networks": NETWORKS,
        "action": "import"
    })


@router.post("/import")
async def import_wallet(
    request: Request,
    network: str = Form(...),
    import_type: str = Form(...),
    private_key: str = Form(None),
    mnemonic: str = Form(None),
    name: str = Form(None)
):
    """Import existing wallet"""
    user = await get_user_or_redirect(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)
    
    try:
        if import_type == "private_key" and private_key:
            wallet_data = wallet_manager.import_from_private_key(network, private_key.strip())
        elif import_type == "mnemonic" and mnemonic:
            wallet_data = await wallet_manager.create_wallet(network, mnemonic.strip())
        else:
            raise ValueError("Please provide private key or mnemonic")
        
        # Encrypt
        encrypted_pk = encryption_manager.encrypt_private_key(wallet_data.private_key)
        encrypted_mnemonic = None
        if wallet_data.mnemonic:
            encrypted_mnemonic = encryption_manager.encrypt_private_key(wallet_data.mnemonic)
        
        # Save
        existing_wallets = await WalletDB.get_user_wallets(user["id"])
        is_primary = len(existing_wallets) == 0
        
        await WalletDB.create_wallet(
            user_id=user["id"],
            network=network,
            address=wallet_data.address,
            encrypted_private_key=encrypted_pk,
            encrypted_mnemonic=encrypted_mnemonic,
            name=name or f"{NETWORKS[network].name} Wallet (Imported)",
            is_primary=is_primary
        )
        
        return RedirectResponse(url="/wallet/dashboard", status_code=302)
        
    except Exception as e:
        return templates.TemplateResponse("wallet.html", {
            "request": request,
            "user": user,
            "networks": NETWORKS,
            "action": "import",
            "error": str(e)
        })


@router.get("/send/{wallet_id}")
async def send_page(request: Request, wallet_id: int):
    """Send transaction page"""
    user = await get_user_or_redirect(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)
    
    wallet = await WalletDB.get_wallet_by_id(wallet_id, user["id"])
    if not wallet:
        return RedirectResponse(url="/wallet/dashboard", status_code=302)
    
    # Get balance
    balance = await wallet_manager.get_balance(wallet["network"], wallet["address"])
    network_config = NETWORKS.get(wallet["network"])
    
    return templates.TemplateResponse("send.html", {
        "request": request,
        "user": user,
        "wallet": wallet,
        "balance": str(balance),
        "network": network_config
    })


@router.post("/send/{wallet_id}")
async def send_transaction(
    request: Request,
    wallet_id: int,
    to_address: str = Form(...),
    amount: str = Form(...)
):
    """Send transaction"""
    user = await get_user_or_redirect(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)
    
    wallet = await WalletDB.get_wallet_by_id(wallet_id, user["id"])
    if not wallet:
        return RedirectResponse(url="/wallet/dashboard", status_code=302)
    
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


@router.get("/receive/{wallet_id}")
async def receive_page(request: Request, wallet_id: int):
    """Receive page with QR code"""
    user = await get_user_or_redirect(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)
    
    wallet = await WalletDB.get_wallet_by_id(wallet_id, user["id"])
    if not wallet:
        return RedirectResponse(url="/wallet/dashboard", status_code=302)
    
    network_config = NETWORKS.get(wallet["network"])
    
    return templates.TemplateResponse("receive.html", {
        "request": request,
        "user": user,
        "wallet": wallet,
        "network": network_config
    })


@router.post("/delete/{wallet_id}")
async def delete_wallet(request: Request, wallet_id: int):
    """Delete wallet"""
    user = await get_user_or_redirect(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)
    
    await WalletDB.delete_wallet(wallet_id, user["id"])
    return RedirectResponse(url="/wallet/dashboard", status_code=302)
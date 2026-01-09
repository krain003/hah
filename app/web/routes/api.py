"""
NEXUS WALLET - REST API Routes
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional, List
from decimal import Decimal
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from blockchain.wallet_manager import wallet_manager, NETWORKS
from web.routes.auth import require_auth

router = APIRouter()


class WalletCreate(BaseModel):
    network: str
    mnemonic: Optional[str] = None


class BalanceResponse(BaseModel):
    network: str
    address: str
    balance: str
    symbol: str


class NetworkInfo(BaseModel):
    name: str
    symbol: str
    chain_id: Optional[int]
    icon: str


@router.get("/networks")
async def get_networks():
    """Get all supported networks"""
    return {
        network_id: {
            "name": config.name,
            "symbol": config.symbol,
            "chain_id": config.chain_id,
            "icon": config.icon,
            "network_type": config.network_type.value,
            "explorer_url": config.explorer_url
        }
        for network_id, config in NETWORKS.items()
    }


@router.get("/balance/{network}/{address}")
async def get_balance(network: str, address: str):
    """Get wallet balance"""
    if network not in NETWORKS:
        raise HTTPException(status_code=400, detail="Invalid network")
    
    try:
        balance = await wallet_manager.get_balance(network, address)
        return {
            "network": network,
            "address": address,
            "balance": str(balance),
            "symbol": NETWORKS[network].symbol
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/wallet/create")
async def create_wallet_api(data: WalletCreate):
    """Create new wallet via API"""
    if data.network not in NETWORKS:
        raise HTTPException(status_code=400, detail="Invalid network")
    
    try:
        wallet = await wallet_manager.create_wallet(data.network, data.mnemonic)
        return {
            "network": data.network,
            "address": wallet.address,
            "mnemonic": wallet.mnemonic,
            "derivation_path": wallet.derivation_path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gas/{network}")
async def estimate_gas(network: str, from_addr: str, to_addr: str, amount: str):
    """Estimate gas for transaction"""
    if network not in NETWORKS:
        raise HTTPException(status_code=400, detail="Invalid network")
    
    try:
        gas_info = await wallet_manager.estimate_gas(
            network=network,
            from_address=from_addr,
            to_address=to_addr,
            amount=Decimal(amount)
        )
        return {
            "gas": gas_info["gas"],
            "gas_price_gwei": gas_info["gas_price_gwei"],
            "total_fee": str(gas_info["total_fee"]),
            "symbol": NETWORKS[network].symbol
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tx/{network}/{tx_hash}")
async def get_transaction_status(network: str, tx_hash: str):
    """Get transaction status"""
    if network not in NETWORKS:
        raise HTTPException(status_code=400, detail="Invalid network")
    
    try:
        status = await wallet_manager.wait_for_transaction(network, tx_hash, timeout=5)
        return {
            "network": network,
            "tx_hash": tx_hash,
            "status": status["status"],
            "explorer_url": f"{NETWORKS[network].explorer_url}/tx/{tx_hash}"
        }
    except Exception as e:
        return {
            "network": network,
            "tx_hash": tx_hash,
            "status": "pending",
            "explorer_url": f"{NETWORKS[network].explorer_url}/tx/{tx_hash}"
        }
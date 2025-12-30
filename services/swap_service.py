"""
NEXUS WALLET - Swap Service
Real token swaps via 1inch API and other DEX aggregators
"""

import asyncio
from decimal import Decimal
from typing import Optional, Dict, List, Any
from datetime import datetime
import httpx
import structlog

from database.connection import db_manager
from database.models import Swap
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blockchain.wallet_manager import NETWORKS, wallet_manager
from services.price_service import price_service
from services.transaction_service import transaction_service
from security.encryption_manager import encryption_manager

logger = structlog.get_logger()


# Token addresses on different networks
TOKEN_ADDRESSES = {
    "ethereum": {
        "ETH": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",  # Native
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "DAI": "0x6B175474E89094C44Da98b954EescdeCB5BE1e",
        "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    },
    "bsc": {
        "BNB": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "USDT": "0x55d398326f99059fF775485246999027B3197955",
        "USDC": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
        "BUSD": "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
        "WBNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
    },
    "polygon": {
        "MATIC": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "USDT": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
        "USDC": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
        "WMATIC": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
        "WETH": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
    },
    "arbitrum": {
        "ETH": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
        "USDC": "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8",
        "ARB": "0x912CE59144191C1204E64559FE8253a0e49E6548",
    },
    "avalanche": {
        "AVAX": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "USDT": "0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7",
        "USDC": "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E",
        "WAVAX": "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",
    },
}

# Chain IDs for 1inch
CHAIN_IDS = {
    "ethereum": 1,
    "bsc": 56,
    "polygon": 137,
    "arbitrum": 42161,
    "avalanche": 43114,
}

# Token decimals
TOKEN_DECIMALS = {
    "ETH": 18, "WETH": 18, "BNB": 18, "WBNB": 18,
    "MATIC": 18, "WMATIC": 18, "AVAX": 18, "WAVAX": 18,
    "USDT": 6, "USDC": 6, "BUSD": 18, "DAI": 18,
    "WBTC": 8, "ARB": 18,
}


class SwapService:
    """Service for token swaps via DEX aggregators"""
    
    ONEINCH_BASE_URL = "https://api.1inch.dev/swap/v6.0"
    
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        # Get API key from environment (optional for basic quotes)
        import os
        self._api_key = os.getenv("ONEINCH_API_KEY", "")
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get HTTP client"""
        if self._client is None or self._client.is_closed:
            headers = {"Accept": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers=headers
            )
        return self._client
    
    def get_token_address(self, network: str, symbol: str) -> Optional[str]:
        """Get token contract address"""
        network_tokens = TOKEN_ADDRESSES.get(network, {})
        return network_tokens.get(symbol.upper())
    
    def get_token_decimals(self, symbol: str) -> int:
        """Get token decimals"""
        return TOKEN_DECIMALS.get(symbol.upper(), 18)
    
    def to_wei(self, amount: Decimal, symbol: str) -> int:
        """Convert to smallest unit"""
        decimals = self.get_token_decimals(symbol)
        return int(amount * Decimal(10 ** decimals))
    
    def from_wei(self, amount: int, symbol: str) -> Decimal:
        """Convert from smallest unit"""
        decimals = self.get_token_decimals(symbol)
        return Decimal(str(amount)) / Decimal(10 ** decimals)
    
    async def get_quote(
        self,
        network: str,
        from_token: str,
        to_token: str,
        amount: Decimal,
        slippage: float = 0.5
    ) -> Optional[Dict]:
        """Get swap quote from 1inch"""
        
        chain_id = CHAIN_IDS.get(network)
        if not chain_id:
            logger.error(f"Unsupported network for swap: {network}")
            return None
        
        from_address = self.get_token_address(network, from_token)
        to_address = self.get_token_address(network, to_token)
        
        if not from_address or not to_address:
            logger.error(f"Token not found: {from_token} or {to_token}")
            return None
        
        amount_wei = self.to_wei(amount, from_token)
        
        try:
            client = await self._get_client()
            
            # Get quote
            response = await client.get(
                f"{self.ONEINCH_BASE_URL}/{chain_id}/quote",
                params={
                    "src": from_address,
                    "dst": to_address,
                    "amount": str(amount_wei),
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                
                to_amount_wei = int(data.get("dstAmount", 0))
                to_amount = self.from_wei(to_amount_wei, to_token)
                
                # Get USD values
                from_price = await price_service.get_price(from_token)
                to_price = await price_service.get_price(to_token)
                
                from_usd = float(amount) * float(from_price) if from_price else 0
                to_usd = float(to_amount) * float(to_price) if to_price else 0
                
                # Calculate rate
                rate = to_amount / amount if amount > 0 else Decimal("0")
                
                # Estimate gas
                gas_estimate = int(data.get("gas", 150000))
                gas_price = await self._get_gas_price(network)
                fee_wei = gas_estimate * gas_price
                
                native_symbol = NETWORKS[network].symbol
                fee_amount = self.from_wei(fee_wei, native_symbol)
                fee_price = await price_service.get_price(native_symbol)
                fee_usd = float(fee_amount) * float(fee_price) if fee_price else 0
                
                return {
                    "network": network,
                    "from_token": from_token,
                    "from_address": from_address,
                    "from_amount": amount,
                    "from_amount_wei": amount_wei,
                    "from_usd": from_usd,
                    "to_token": to_token,
                    "to_address": to_address,
                    "to_amount": to_amount,
                    "to_amount_wei": to_amount_wei,
                    "to_usd": to_usd,
                    "rate": rate,
                    "slippage": slippage,
                    "gas_estimate": gas_estimate,
                    "fee_amount": fee_amount,
                    "fee_token": native_symbol,
                    "fee_usd": fee_usd,
                    "price_impact": abs(from_usd - to_usd) / from_usd * 100 if from_usd > 0 else 0,
                }
            else:
                logger.error(f"1inch quote failed: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to get swap quote", error=str(e))
            return None
    
    async def _get_gas_price(self, network: str) -> int:
        """Get current gas price in wei"""
        try:
            w3 = wallet_manager.get_web3(network)
            return w3.eth.gas_price
        except Exception:
            # Default gas prices (gwei)
            defaults = {
                "ethereum": 30,
                "bsc": 5,
                "polygon": 50,
                "arbitrum": 0.1,
                "avalanche": 30,
            }
            gwei = defaults.get(network, 20)
            return int(gwei * 10**9)
    
    async def build_swap_transaction(
        self,
        network: str,
        from_token: str,
        to_token: str,
        amount: Decimal,
        from_address: str,
        slippage: float = 0.5
    ) -> Optional[Dict]:
        """Build swap transaction data"""
        
        chain_id = CHAIN_IDS.get(network)
        if not chain_id:
            return None
        
        from_token_address = self.get_token_address(network, from_token)
        to_token_address = self.get_token_address(network, to_token)
        
        if not from_token_address or not to_token_address:
            return None
        
        amount_wei = self.to_wei(amount, from_token)
        
        try:
            client = await self._get_client()
            
            response = await client.get(
                f"{self.ONEINCH_BASE_URL}/{chain_id}/swap",
                params={
                    "src": from_token_address,
                    "dst": to_token_address,
                    "amount": str(amount_wei),
                    "from": from_address,
                    "slippage": slippage,
                    "disableEstimate": "true",
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "to": data["tx"]["to"],
                    "data": data["tx"]["data"],
                    "value": int(data["tx"]["value"]),
                    "gas": int(data["tx"].get("gas", 300000)),
                    "to_amount": self.from_wei(int(data["dstAmount"]), to_token),
                }
            else:
                logger.error(f"1inch swap build failed: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to build swap tx", error=str(e))
            return None
    
    async def execute_swap(
        self,
        session: AsyncSession,
        user_id: int,
        wallet_id: str,
        network: str,
        from_token: str,
        to_token: str,
        amount: Decimal,
        slippage: float = 0.5,
        encrypted_private_key: str = None,
    ) -> Dict:
        """Execute real swap transaction"""
        
        # Get quote first
        quote = await self.get_quote(network, from_token, to_token, amount, slippage)
        if not quote:
            return {"success": False, "error": "Failed to get quote"}
        
        # Get wallet
        from database.repositories.wallet_repository import WalletRepository
        wallet_repo = WalletRepository()
        wallet = await wallet_repo.get_by_id(session, wallet_id)
        
        if not wallet:
            return {"success": False, "error": "Wallet not found"}
        
        # Check balance
        balance = await wallet_manager.get_balance(network, wallet.address)
        if balance < amount:
            return {"success": False, "error": f"Insufficient balance. Have: {balance}, need: {amount}"}
        
        # Create swap record
        swap = Swap(
            user_id=user_id,
            wallet_id=wallet_id,
            network=network,
            from_token=from_token,
            from_token_address=quote["from_address"],
            from_amount=amount,
            to_token=to_token,
            to_token_address=quote["to_address"],
            to_amount_expected=quote["to_amount"],
            slippage=slippage,
            dex_name="1inch",
            status="pending",
            fee_amount=quote["fee_amount"],
            fee_usd=Decimal(str(quote["fee_usd"])),
        )
        session.add(swap)
        await session.flush()
        
        try:
            # Build transaction
            swap_tx = await self.build_swap_transaction(
                network, from_token, to_token, amount,
                wallet.address, slippage
            )
            
            if not swap_tx:
                swap.status = "failed"
                swap.error_message = "Failed to build transaction"
                return {"success": False, "error": "Failed to build swap transaction"}
            
            # Decrypt private key
            if encrypted_private_key:
                private_key = encryption_manager.decrypt_private_key(encrypted_private_key)
            else:
                private_key = encryption_manager.decrypt_private_key(wallet.encrypted_private_key)
            
            # Get web3 and sign transaction
            w3 = wallet_manager.get_web3(network)
            
            from eth_account import Account
            account = Account.from_key(private_key)
            
            # Build full transaction
            tx = {
                'from': wallet.address,
                'to': w3.to_checksum_address(swap_tx["to"]),
                'value': swap_tx["value"],
                'gas': swap_tx["gas"],
                'gasPrice': w3.eth.gas_price,
                'nonce': w3.eth.get_transaction_count(wallet.address),
                'data': swap_tx["data"],
                'chainId': CHAIN_IDS[network],
            }
            
            # Sign and send
            signed = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
            tx_hash_hex = tx_hash.hex()
            
            # Update swap record
            swap.tx_hash = tx_hash_hex
            swap.status = "confirming"
            
            # Wait for confirmation (with timeout)
            try:
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                
                if receipt["status"] == 1:
                    swap.status = "completed"
                    swap.to_amount = swap_tx["to_amount"]
                    swap.completed_at = datetime.utcnow()
                    
                    # Record transaction
                    await transaction_service.create_transaction(
                        session,
                        user_id=user_id,
                        wallet_id=wallet_id,
                        tx_type="swap",
                        network=network,
                        token_symbol=from_token,
                        amount=amount,
                        tx_hash=tx_hash_hex,
                        status="completed",
                        swap_to_token=to_token,
                        swap_to_amount=swap_tx["to_amount"],
                        fee_amount=quote["fee_amount"],
                        fee_token=quote["fee_token"],
                    )
                    
                    await session.flush()
                    
                    return {
                        "success": True,
                        "tx_hash": tx_hash_hex,
                        "from_amount": amount,
                        "from_token": from_token,
                        "to_amount": swap_tx["to_amount"],
                        "to_token": to_token,
                        "explorer_url": f"{NETWORKS[network].explorer_url}/tx/{tx_hash_hex}",
                    }
                else:
                    swap.status = "failed"
                    swap.error_message = "Transaction reverted"
                    return {"success": False, "error": "Transaction reverted", "tx_hash": tx_hash_hex}
                    
            except Exception as e:
                swap.status = "failed"
                swap.error_message = str(e)
                return {"success": False, "error": f"Transaction failed: {str(e)}", "tx_hash": tx_hash_hex}
            
        except Exception as e:
            swap.status = "failed"
            swap.error_message = str(e)
            logger.error("Swap execution failed", error=str(e))
            return {"success": False, "error": str(e)}
    
    async def get_supported_tokens(self, network: str) -> List[str]:
        """Get list of supported tokens for network"""
        return list(TOKEN_ADDRESSES.get(network, {}).keys())
    
    async def get_user_swaps(
        self,
        session: AsyncSession,
        user_id: int,
        limit: int = 50
    ) -> List[Swap]:
        """Get user's swap history"""
        result = await session.execute(
            select(Swap)
            .where(Swap.user_id == user_id)
            .order_by(Swap.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
    
    async def close(self):
        """Close HTTP client"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Global instance
swap_service = SwapService()
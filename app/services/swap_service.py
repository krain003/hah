"""
NEXUS WALLET - Real Cross-Chain Swap Service
Using ChangeNOW API for real crypto exchanges
"""

import uuid
import aiohttp
import structlog
from decimal import Decimal
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from config.settings import settings

logger = structlog.get_logger(__name__)


@dataclass
class SwapQuote:
    """Swap quote from exchange service"""
    id: str
    from_currency: str
    to_currency: str
    from_amount: Decimal
    to_amount: Decimal
    rate: Decimal
    fee: Decimal
    deposit_address: str
    deposit_extra_id: Optional[str]  # For XRP, XLM, etc.
    expires_at: datetime
    provider: str


@dataclass
class SwapStatus:
    """Swap transaction status"""
    id: str
    status: str  # waiting, confirming, exchanging, sending, finished, failed
    from_currency: str
    to_currency: str
    from_amount: Decimal
    to_amount: Optional[Decimal]
    deposit_address: str
    payout_address: str
    tx_from: Optional[str]
    tx_to: Optional[str]
    created_at: datetime


class SwapService:
    """
    Real crypto swap service using ChangeNOW API
    Docs: https://changenow.io/api/docs
    """
    
    def __init__(self):
        self.api_key = getattr(settings, 'CHANGENOW_API_KEY', None)
        self.base_url = "https://api.changenow.io/v2"
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={"x-changenow-api-key": self.api_key or ""}
            )
        return self.session
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    # ==================== CURRENCIES ====================
    
    async def get_available_currencies(self) -> List[Dict]:
        """Get list of available currencies for swap"""
        try:
            session = await self._get_session()
            
            async with session.get(
                f"{self.base_url}/exchange/currencies",
                params={"active": "true", "flow": "standard"}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data
                else:
                    logger.error("Failed to get currencies", status=resp.status)
                    return []
        except Exception as e:
            logger.error("get_currencies error", error=str(e))
            return []
    
    async def get_currency_info(self, currency: str, network: str = None) -> Optional[Dict]:
        """Get info about specific currency"""
        currencies = await self.get_available_currencies()
        
        for c in currencies:
            if c.get('ticker', '').upper() == currency.upper():
                if network:
                    if c.get('network', '').lower() == network.lower():
                        return c
                else:
                    return c
        
        return None
    
    # ==================== ESTIMATES ====================
    
    async def get_estimated_amount(
        self,
        from_currency: str,
        to_currency: str,
        from_amount: Decimal,
        from_network: str = None,
        to_network: str = None
    ) -> Optional[Dict]:
        """
        Get estimated exchange amount
        Returns: {"estimatedAmount": 0.123, "transactionSpeedForecast": "10-60", ...}
        """
        try:
            session = await self._get_session()
            
            # Build currency tickers with network
            from_ticker = from_currency.lower()
            to_ticker = to_currency.lower()
            
            if from_network:
                from_ticker = f"{from_currency.lower()}{from_network.lower()}"
            if to_network:
                to_ticker = f"{to_currency.lower()}{to_network.lower()}"
            
            params = {
                "fromCurrency": from_ticker,
                "toCurrency": to_ticker,
                "fromAmount": str(from_amount),
                "flow": "standard"
            }
            
            async with session.get(
                f"{self.base_url}/exchange/estimated-amount",
                params=params
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data
                else:
                    error = await resp.text()
                    logger.error("Estimate failed", status=resp.status, error=error)
                    return None
                    
        except Exception as e:
            logger.error("get_estimated_amount error", error=str(e))
            return None
    
    async def get_min_amount(
        self,
        from_currency: str,
        to_currency: str,
        from_network: str = None,
        to_network: str = None
    ) -> Optional[Decimal]:
        """Get minimum exchange amount"""
        try:
            session = await self._get_session()
            
            from_ticker = from_currency.lower()
            to_ticker = to_currency.lower()
            
            params = {
                "fromCurrency": from_ticker,
                "toCurrency": to_ticker,
                "flow": "standard"
            }
            
            async with session.get(
                f"{self.base_url}/exchange/min-amount",
                params=params
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return Decimal(str(data.get('minAmount', 0)))
                else:
                    return None
                    
        except Exception as e:
            logger.error("get_min_amount error", error=str(e))
            return None
    
    # ==================== CREATE EXCHANGE ====================
    
    async def create_exchange(
        self,
        from_currency: str,
        to_currency: str,
        from_amount: Decimal,
        to_address: str,
        from_network: str = None,
        to_network: str = None,
        refund_address: str = None,
        extra_id: str = None  # For XRP, XLM memo
    ) -> Optional[Dict]:
        """
        Create real exchange transaction
        
        Returns:
        {
            "id": "abc123",
            "payinAddress": "address_to_send_funds",
            "payoutAddress": "user_receiving_address",
            "fromCurrency": "btc",
            "toCurrency": "eth",
            "amount": 0.1,
            "status": "waiting"
        }
        """
        if not self.api_key:
            logger.error("ChangeNOW API key not configured!")
            return None
        
        try:
            session = await self._get_session()
            
            from_ticker = from_currency.lower()
            to_ticker = to_currency.lower()
            
            payload = {
                "fromCurrency": from_ticker,
                "toCurrency": to_ticker,
                "fromAmount": str(from_amount),
                "address": to_address,
                "flow": "standard"
            }
            
            if refund_address:
                payload["refundAddress"] = refund_address
            
            if extra_id:
                payload["extraId"] = extra_id
            
            async with session.post(
                f"{self.base_url}/exchange",
                json=payload
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info(
                        "Exchange created",
                        exchange_id=data.get('id'),
                        from_amount=str(from_amount),
                        from_currency=from_currency,
                        to_currency=to_currency
                    )
                    return data
                else:
                    error = await resp.text()
                    logger.error("Create exchange failed", status=resp.status, error=error)
                    return None
                    
        except Exception as e:
            logger.error("create_exchange error", error=str(e))
            return None
    
    # ==================== CHECK STATUS ====================
    
    async def get_exchange_status(self, exchange_id: str) -> Optional[SwapStatus]:
        """
        Get exchange transaction status
        
        Statuses:
        - waiting: Waiting for deposit
        - confirming: Deposit received, waiting confirmations
        - exchanging: Exchanging
        - sending: Sending to user
        - finished: Done!
        - failed: Failed
        - refunded: Refunded
        """
        try:
            session = await self._get_session()
            
            async with session.get(
                f"{self.base_url}/exchange/by-id",
                params={"id": exchange_id}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    return SwapStatus(
                        id=data.get('id'),
                        status=data.get('status'),
                        from_currency=data.get('fromCurrency'),
                        to_currency=data.get('toCurrency'),
                        from_amount=Decimal(str(data.get('expectedAmountFrom', 0))),
                        to_amount=Decimal(str(data.get('amountTo', 0))) if data.get('amountTo') else None,
                        deposit_address=data.get('payinAddress'),
                        payout_address=data.get('payoutAddress'),
                        tx_from=data.get('payinHash'),
                        tx_to=data.get('payoutHash'),
                        created_at=datetime.fromisoformat(data.get('createdAt', '').replace('Z', '+00:00'))
                    )
                else:
                    return None
                    
        except Exception as e:
            logger.error("get_exchange_status error", error=str(e))
            return None


# Singleton
swap_service = SwapService()
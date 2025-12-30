import asyncio
from decimal import Decimal
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import httpx
import structlog

logger = structlog.get_logger(__name__)

COINGECKO_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin", "MATIC": "matic-network",
    "AVAX": "avalanche-2", "SOL": "solana", "TON": "the-open-network", "TRX": "tron",
    "USDT": "tether", "USDC": "usd-coin", "BUSD": "binance-usd", "DAI": "dai", "ARB": "arbitrum"
}
_price_cache: Dict[str, Dict] = {}
_cache_ttl = 60  # seconds

class PriceService:
    BASE_URL = "https://api.coingecko.com/api/v3"
    
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0, headers={"Accept": "application/json"})
        return self._client
    
    async def get_price(self, symbol: str, currency: str = "USD") -> Optional[Decimal]:
        symbol = symbol.upper()
        currency = currency.lower()
        cache_key = f"{symbol}_{currency}"
        
        if cache_key in _price_cache and datetime.now() - _price_cache[cache_key]["time"] < timedelta(seconds=_cache_ttl):
            return _price_cache[cache_key]["price"]
        
        coingecko_id = COINGECKO_IDS.get(symbol)
        if not coingecko_id: return None
        
        try:
            client = await self._get_client()
            response = await client.get(f"{self.BASE_URL}/simple/price", params={"ids": coingecko_id, "vs_currencies": currency})
            
            if response.status_code == 200:
                data = response.json()
                if coingecko_id in data and currency in data[coingecko_id]:
                    price = Decimal(str(data[coingecko_id][currency]))
                    _price_cache[cache_key] = {"price": price, "time": datetime.now()}
                    return price
            return None
        except Exception as e:
            logger.error(f"Failed to fetch price for {symbol}", error=str(e))
            return None
            
    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

price_service = PriceService()
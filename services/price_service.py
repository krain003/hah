"""
NEXUS WALLET - Price Service
Real-time crypto prices from CoinGecko API (free, no key required)
"""

import asyncio
from decimal import Decimal
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import httpx
import structlog

from database.connection import db_manager

logger = structlog.get_logger()

# CoinGecko token IDs mapping
COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "MATIC": "matic-network",
    "AVAX": "avalanche-2",
    "SOL": "solana",
    "TON": "the-open-network",
    "TRX": "tron",
    "USDT": "tether",
    "USDC": "usd-coin",
    "BUSD": "binance-usd",
    "DAI": "dai",
    "ARB": "arbitrum",
    "OP": "optimism",
}

# Price cache (in-memory)
_price_cache: Dict[str, Dict] = {}
_cache_ttl = 60  # seconds


class PriceService:
    """Service for fetching real crypto prices"""
    
    BASE_URL = "https://api.coingecko.com/api/v3"
    
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._last_request = datetime.min
        self._rate_limit_delay = 1.5  # CoinGecko rate limit: 10-30 calls/min
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={"Accept": "application/json"}
            )
        return self._client
    
    async def _rate_limit(self):
        """Respect rate limits"""
        now = datetime.now()
        elapsed = (now - self._last_request).total_seconds()
        if elapsed < self._rate_limit_delay:
            await asyncio.sleep(self._rate_limit_delay - elapsed)
        self._last_request = datetime.now()
    
    async def get_price(
        self, 
        symbol: str, 
        currency: str = "USD"
    ) -> Optional[Decimal]:
        """Get current price for a token"""
        symbol = symbol.upper()
        currency = currency.lower()
        
        # Check cache first
        cache_key = f"{symbol}_{currency}"
        if cache_key in _price_cache:
            cached = _price_cache[cache_key]
            if datetime.now() - cached["time"] < timedelta(seconds=_cache_ttl):
                return cached["price"]
        
        # Get from API
        coingecko_id = COINGECKO_IDS.get(symbol)
        if not coingecko_id:
            # Try direct symbol lookup
            coingecko_id = symbol.lower()
        
        try:
            await self._rate_limit()
            client = await self._get_client()
            
            response = await client.get(
                f"{self.BASE_URL}/simple/price",
                params={
                    "ids": coingecko_id,
                    "vs_currencies": currency,
                    "include_24hr_change": "true"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                if coingecko_id in data and currency in data[coingecko_id]:
                    price = Decimal(str(data[coingecko_id][currency]))
                    change_24h = data[coingecko_id].get(f"{currency}_24h_change")
                    
                    # Cache it
                    _price_cache[cache_key] = {
                        "price": price,
                        "change_24h": change_24h,
                        "time": datetime.now()
                    }
                    
                    return price
            
            logger.warning(f"Price not found for {symbol}", status=response.status_code)
            return None
            
        except Exception as e:
            logger.error(f"Failed to fetch price for {symbol}", error=str(e))
            return None
    
    async def get_prices(
        self, 
        symbols: List[str], 
        currency: str = "USD"
    ) -> Dict[str, Decimal]:
        """Get prices for multiple tokens at once"""
        currency = currency.lower()
        results = {}
        
        # Filter symbols that need fetching
        to_fetch = []
        for symbol in symbols:
            symbol = symbol.upper()
            cache_key = f"{symbol}_{currency}"
            
            if cache_key in _price_cache:
                cached = _price_cache[cache_key]
                if datetime.now() - cached["time"] < timedelta(seconds=_cache_ttl):
                    results[symbol] = cached["price"]
                    continue
            
            coingecko_id = COINGECKO_IDS.get(symbol)
            if coingecko_id:
                to_fetch.append((symbol, coingecko_id))
        
        if not to_fetch:
            return results
        
        # Fetch from API
        try:
            await self._rate_limit()
            client = await self._get_client()
            
            ids_str = ",".join([cg_id for _, cg_id in to_fetch])
            
            response = await client.get(
                f"{self.BASE_URL}/simple/price",
                params={
                    "ids": ids_str,
                    "vs_currencies": currency,
                    "include_24hr_change": "true"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                
                for symbol, coingecko_id in to_fetch:
                    if coingecko_id in data and currency in data[coingecko_id]:
                        price = Decimal(str(data[coingecko_id][currency]))
                        change_24h = data[coingecko_id].get(f"{currency}_24h_change")
                        
                        cache_key = f"{symbol}_{currency}"
                        _price_cache[cache_key] = {
                            "price": price,
                            "change_24h": change_24h,
                            "time": datetime.now()
                        }
                        
                        results[symbol] = price
            
        except Exception as e:
            logger.error("Failed to fetch prices", error=str(e))
        
        return results
    
    async def get_price_change_24h(self, symbol: str, currency: str = "USD") -> Optional[float]:
        """Get 24h price change percentage"""
        symbol = symbol.upper()
        currency = currency.lower()
        cache_key = f"{symbol}_{currency}"
        
        # Ensure price is fetched (which also caches change)
        await self.get_price(symbol, currency)
        
        if cache_key in _price_cache:
            return _price_cache[cache_key].get("change_24h")
        
        return None
    
    async def convert(
        self, 
        amount: Decimal, 
        from_symbol: str, 
        to_symbol: str
    ) -> Optional[Decimal]:
        """Convert between two tokens"""
        from_price = await self.get_price(from_symbol)
        to_price = await self.get_price(to_symbol)
        
        if from_price and to_price and to_price > 0:
            # Convert to USD first, then to target
            usd_value = amount * from_price
            return usd_value / to_price
        
        return None
    
    async def get_token_info(self, symbol: str) -> Optional[Dict]:
        """Get detailed token info"""
        coingecko_id = COINGECKO_IDS.get(symbol.upper())
        if not coingecko_id:
            return None
        
        try:
            await self._rate_limit()
            client = await self._get_client()
            
            response = await client.get(
                f"{self.BASE_URL}/coins/{coingecko_id}",
                params={
                    "localization": "false",
                    "tickers": "false",
                    "community_data": "false",
                    "developer_data": "false"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "id": data.get("id"),
                    "symbol": data.get("symbol", "").upper(),
                    "name": data.get("name"),
                    "price_usd": data.get("market_data", {}).get("current_price", {}).get("usd"),
                    "market_cap": data.get("market_data", {}).get("market_cap", {}).get("usd"),
                    "volume_24h": data.get("market_data", {}).get("total_volume", {}).get("usd"),
                    "change_24h": data.get("market_data", {}).get("price_change_percentage_24h"),
                    "image": data.get("image", {}).get("small"),
                }
            
        except Exception as e:
            logger.error(f"Failed to get token info for {symbol}", error=str(e))
        
        return None
    
    async def close(self):
        """Close HTTP client"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Global instance
price_service = PriceService()
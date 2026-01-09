"""
NEXUS WALLET - Price Service
Real-time crypto price fetching from multiple sources
"""

import asyncio
import httpx
from decimal import Decimal
from datetime import datetime
from typing import Dict, Optional, List, Tuple
import structlog

logger = structlog.get_logger(__name__)


class PriceService:
    """
    Multi-source price service with caching and fallbacks.
    Sources: Binance (primary), CoinGecko (fallback), CryptoCompare (fallback)
    """
    
    def __init__(self):
        self._cache: Dict[str, Tuple[Decimal, datetime]] = {}
        self._cache_ttl = 30  # seconds
        self._http_client: Optional[httpx.AsyncClient] = None
        self._background_task = None
        
        # Symbol mappings for different APIs
        self.binance_symbols = {
            "BTC": "BTCUSDT",
            "ETH": "ETHUSDT",
            "BNB": "BNBUSDT",
            "SOL": "SOLUSDT",
            "TON": "TONUSDT",
            "TRX": "TRXUSDT",
            "MATIC": "MATICUSDT",
            "AVAX": "AVAXUSDT",
            "ARB": "ARBUSDT",
            "OP": "OPUSDT",
        }
        
        self.coingecko_ids = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "BNB": "binancecoin",
            "SOL": "solana",
            "TON": "the-open-network",
            "TRX": "tron",
            "MATIC": "matic-network",
            "AVAX": "avalanche-2",
            "ARB": "arbitrum",
            "OP": "optimism",
            "USDT": "tether",
            "USDC": "usd-coin",
        }
        
        # Stablecoins always return 1.0
        self.stablecoins = {"USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP"}
    
    async def initialize(self):
        """Initialize the price service (preload prices)"""
        try:
            symbols = ["BTC", "ETH", "BNB", "SOL", "TON"]
            for symbol in symbols:
                try:
                    await self.get_price(symbol)
                except Exception:
                    pass
            logger.info("Price service initialized")
        except Exception as e:
            logger.warning(f"Price service init warning: {e}")
    
    async def _background_update_loop(self):
        """Background task to update prices periodically"""
        try:
            symbols = ["BTC", "ETH", "BNB", "SOL", "TON", "TRX", "MATIC", "AVAX"]
            for symbol in symbols:
                try:
                    if symbol in self._cache:
                        del self._cache[symbol]
                    await self.get_price(symbol)
                except Exception as e:
                    logger.debug(f"Background price update failed for {symbol}: {e}")
            
            logger.debug("Background price update completed")
        except Exception as e:
            logger.warning(f"Background update loop error: {e}")
    
    async def start_background_updates(self, interval_seconds: int = 60):
        """Start background price updates"""
        while True:
            await self._background_update_loop()
            await asyncio.sleep(interval_seconds)
    
    async def shutdown(self):
        """Shutdown the price service"""
        if self._background_task:
            self._background_task.cancel()
        await self.close()
        logger.info("Price service shutdown")
    
    def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=10.0,
                headers={"User-Agent": "NexusWallet/1.0"}
            )
        return self._http_client
    
    async def get_price(self, symbol: str) -> Decimal:
        """
        Get current USD price for a token.
        Uses cache and multiple fallback sources.
        """
        symbol = symbol.upper().strip()
        
        # Stablecoins
        if symbol in self.stablecoins:
            return Decimal("1.0")
        
        # Check cache
        cached = self._get_from_cache(symbol)
        if cached is not None:
            return cached
        
        # Try sources in order
        price = await self._fetch_binance_price(symbol)
        
        if price <= 0:
            price = await self._fetch_coingecko_price(symbol)
        
        if price <= 0:
            price = await self._fetch_cryptocompare_price(symbol)
        
        # Cache result
        if price > 0:
            self._set_cache(symbol, price)
        
        return price
    
    async def get_prices(self, symbols: List[str]) -> Dict[str, Decimal]:
        """Get prices for multiple symbols"""
        results = {}
        tasks = [self.get_price(s) for s in symbols]
        prices = await asyncio.gather(*tasks, return_exceptions=True)
        
        for symbol, price in zip(symbols, prices):
            if isinstance(price, Exception):
                results[symbol] = Decimal("0")
            else:
                results[symbol] = price
        
        return results
    
    async def get_price_with_change(self, symbol: str) -> Dict:
        """Get price with 24h change percentage"""
        symbol = symbol.upper()
        
        if symbol in self.stablecoins:
            return {"price": Decimal("1.0"), "change_24h": 0.0}
        
        price = await self.get_price(symbol)
        change = await self._fetch_24h_change(symbol)
        
        return {
            "price": price,
            "change_24h": change,
            "symbol": symbol
        }
    
    def _get_from_cache(self, symbol: str) -> Optional[Decimal]:
        """Get price from cache if not expired"""
        if symbol in self._cache:
            price, timestamp = self._cache[symbol]
            if (datetime.utcnow() - timestamp).total_seconds() < self._cache_ttl:
                return price
        return None
    
    def _set_cache(self, symbol: str, price: Decimal):
        """Set price in cache"""
        self._cache[symbol] = (price, datetime.utcnow())
    
    async def _fetch_binance_price(self, symbol: str) -> Decimal:
        """Fetch price from Binance API"""
        try:
            pair = self.binance_symbols.get(symbol, f"{symbol}USDT")
            client = self._get_client()
            
            response = await client.get(
                f"https://api.binance.com/api/v3/ticker/price",
                params={"symbol": pair}
            )
            
            if response.status_code == 200:
                data = response.json()
                return Decimal(str(data.get("price", 0)))
            
            return Decimal("0")
            
        except Exception as e:
            logger.debug("Binance price fetch failed", symbol=symbol, error=str(e))
            return Decimal("0")
    
    async def _fetch_coingecko_price(self, symbol: str) -> Decimal:
        """Fetch price from CoinGecko API"""
        try:
            coin_id = self.coingecko_ids.get(symbol, symbol.lower())
            client = self._get_client()
            
            response = await client.get(
                f"https://api.coingecko.com/api/v3/simple/price",
                params={
                    "ids": coin_id,
                    "vs_currencies": "usd"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                if coin_id in data:
                    return Decimal(str(data[coin_id].get("usd", 0)))
            
            return Decimal("0")
            
        except Exception as e:
            logger.debug("CoinGecko price fetch failed", symbol=symbol, error=str(e))
            return Decimal("0")
    
    async def _fetch_cryptocompare_price(self, symbol: str) -> Decimal:
        """Fetch price from CryptoCompare API"""
        try:
            client = self._get_client()
            
            response = await client.get(
                f"https://min-api.cryptocompare.com/data/price",
                params={
                    "fsym": symbol,
                    "tsyms": "USD"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return Decimal(str(data.get("USD", 0)))
            
            return Decimal("0")
            
        except Exception as e:
            logger.debug("CryptoCompare price fetch failed", symbol=symbol, error=str(e))
            return Decimal("0")
    
    async def _fetch_24h_change(self, symbol: str) -> float:
        """Fetch 24h price change percentage"""
        try:
            pair = self.binance_symbols.get(symbol, f"{symbol}USDT")
            client = self._get_client()
            
            response = await client.get(
                f"https://api.binance.com/api/v3/ticker/24hr",
                params={"symbol": pair}
            )
            
            if response.status_code == 200:
                data = response.json()
                return float(data.get("priceChangePercent", 0))
            
            return 0.0
            
        except Exception:
            return 0.0
    
    async def get_market_data(self, symbol: str) -> Dict:
        """Get comprehensive market data for a symbol"""
        symbol = symbol.upper()
        
        try:
            coin_id = self.coingecko_ids.get(symbol, symbol.lower())
            client = self._get_client()
            
            response = await client.get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}",
                params={
                    "localization": "false",
                    "tickers": "false",
                    "community_data": "false",
                    "developer_data": "false"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                market = data.get("market_data", {})
                
                return {
                    "symbol": symbol,
                    "name": data.get("name", symbol),
                    "price": Decimal(str(market.get("current_price", {}).get("usd", 0))),
                    "market_cap": market.get("market_cap", {}).get("usd", 0),
                    "volume_24h": market.get("total_volume", {}).get("usd", 0),
                    "change_24h": market.get("price_change_percentage_24h", 0),
                    "change_7d": market.get("price_change_percentage_7d", 0),
                    "high_24h": market.get("high_24h", {}).get("usd", 0),
                    "low_24h": market.get("low_24h", {}).get("usd", 0),
                    "ath": market.get("ath", {}).get("usd", 0),
                    "ath_change": market.get("ath_change_percentage", {}).get("usd", 0),
                }
            
            return {"symbol": symbol, "price": await self.get_price(symbol)}
            
        except Exception as e:
            logger.error("Market data fetch failed", symbol=symbol, error=str(e))
            return {"symbol": symbol, "price": await self.get_price(symbol)}
    
    async def convert(
        self,
        amount: Decimal,
        from_symbol: str,
        to_symbol: str
    ) -> Decimal:
        """Convert amount between two currencies"""
        from_symbol = from_symbol.upper()
        to_symbol = to_symbol.upper()
        
        if from_symbol == to_symbol:
            return amount
        
        from_price = await self.get_price(from_symbol)
        to_price = await self.get_price(to_symbol)
        
        if from_price <= 0 or to_price <= 0:
            return Decimal("0")
        
        usd_value = amount * from_price
        return usd_value / to_price
    
    async def get_fiat_rates(self) -> Dict[str, float]:
        """Get USD to fiat exchange rates"""
        try:
            client = self._get_client()
            
            response = await client.get(
                "https://api.exchangerate-api.com/v4/latest/USD"
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get("rates", {})
            
            return {}
            
        except Exception as e:
            logger.error("Fiat rates fetch failed", error=str(e))
            return {}
    
    async def close(self):
        """Close HTTP client"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
    
    def clear_cache(self):
        """Clear price cache"""
        self._cache.clear()


# Global instance
price_service = PriceService()
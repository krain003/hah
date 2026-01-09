"""
NEXUS WALLET - Direct Purchase Service (Aggregator)
Buy/Sell crypto through official exchange APIs
Supports: MoonPay, Transak, Banxa, Simplex integration
"""

import asyncio
import hashlib
import hmac
import time
import httpx
from decimal import Decimal
from datetime import datetime
from typing import Dict, Optional, List, Tuple, Any
from enum import Enum
import structlog

from config.settings import settings
from database.models import DirectPurchase, User
from services.price_service import price_service

logger = structlog.get_logger(__name__)


class PurchaseProvider(str, Enum):
    """Supported purchase providers"""
    MOONPAY = "moonpay"
    TRANSAK = "transak"
    BANXA = "banxa"
    SIMPLEX = "simplex"
    ONRAMPER = "onramper"  # Aggregator of aggregators


class PaymentMethod(str, Enum):
    """Supported payment methods"""
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    APPLE_PAY = "apple_pay"
    GOOGLE_PAY = "google_pay"
    SEPA = "sepa"
    PIX = "pix"


# Provider configurations
PROVIDER_CONFIGS = {
    PurchaseProvider.MOONPAY: {
        "name": "MoonPay",
        "icon": "🌙",
        "base_url": "https://api.moonpay.com/v3",
        "widget_url": "https://buy.moonpay.com",
        "supported_cryptos": ["BTC", "ETH", "BNB", "SOL", "MATIC", "AVAX"],
        "supported_fiats": ["USD", "EUR", "GBP", "RUB"],
        "min_usd": 30,
        "max_usd": 10000,
        "fee_percent": 4.5,
    },
    PurchaseProvider.TRANSAK: {
        "name": "Transak",
        "icon": "🔷",
        "base_url": "https://api.transak.com/api/v2",
        "widget_url": "https://global.transak.com",
        "supported_cryptos": ["BTC", "ETH", "BNB", "SOL", "MATIC", "TRX", "TON"],
        "supported_fiats": ["USD", "EUR", "GBP", "INR", "RUB"],
        "min_usd": 15,
        "max_usd": 15000,
        "fee_percent": 3.5,
    },
    PurchaseProvider.BANXA: {
        "name": "Banxa",
        "icon": "💳",
        "base_url": "https://api.banxa.com",
        "widget_url": "https://checkout.banxa.com",
        "supported_cryptos": ["BTC", "ETH", "BNB", "SOL"],
        "supported_fiats": ["USD", "EUR", "AUD", "GBP"],
        "min_usd": 20,
        "max_usd": 50000,
        "fee_percent": 3.0,
    },
    PurchaseProvider.ONRAMPER: {
        "name": "Onramper",
        "icon": "🚀",
        "base_url": "https://api.onramper.com",
        "widget_url": "https://widget.onramper.com",
        "supported_cryptos": ["BTC", "ETH", "BNB", "SOL", "MATIC", "AVAX", "TRX", "TON"],
        "supported_fiats": ["USD", "EUR", "GBP", "RUB", "UAH", "KZT", "TRY", "INR"],
        "min_usd": 10,
        "max_usd": 20000,
        "fee_percent": 2.5,  # Varies by sub-provider
    },
}

# Network to crypto symbol mapping
NETWORK_TO_SYMBOL = {
    "ethereum": "ETH",
    "bsc": "BNB",
    "polygon": "MATIC",
    "arbitrum": "ETH",
    "avalanche": "AVAX",
    "optimism": "ETH",
    "base": "ETH",
    "bitcoin": "BTC",
    "solana": "SOL",
    "tron": "TRX",
    "ton": "TON",
}


class DirectPurchaseService:
    """
    Aggregator service for buying/selling crypto directly.
    Compares rates across multiple providers and routes to best option.
    """
    
    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        
        # Platform fees (configurable by admin)
        self.platform_fee_buy_percent = Decimal("1.0")  # 1% on buys
        self.platform_fee_sell_percent = Decimal("1.0")  # 1% on sells
        
        # Limits (configurable by admin)
        self.min_purchase_usd = Decimal("10")
        self.max_purchase_usd = Decimal("50000")
        self.min_sale_usd = Decimal("10")
        self.max_sale_usd = Decimal("50000")
        
        # API keys (from settings)
        self.moonpay_api_key = getattr(settings, 'MOONPAY_API_KEY', None)
        self.moonpay_secret_key = getattr(settings, 'MOONPAY_SECRET_KEY', None)
        self.transak_api_key = getattr(settings, 'TRANSAK_API_KEY', None)
        self.onramper_api_key = getattr(settings, 'ONRAMPER_API_KEY', None)
    
    def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client
    
    # ==================== GET QUOTES ====================
    
    async def get_buy_quotes(
        self,
        crypto_symbol: str,
        fiat_amount: Decimal,
        fiat_currency: str,
        payment_method: str = "card"
    ) -> List[Dict]:
        """
        Get buy quotes from all available providers.
        Returns list of quotes sorted by best rate.
        """
        crypto_symbol = crypto_symbol.upper()
        fiat_currency = fiat_currency.upper()
        
        quotes = []
        
        # Check limits
        usd_amount = await self._convert_to_usd(fiat_amount, fiat_currency)
        if usd_amount < self.min_purchase_usd or usd_amount > self.max_purchase_usd:
            return []
        
        # Get current crypto price
        crypto_price = await price_service.get_price(crypto_symbol)
        if crypto_price <= 0:
            return []
        
        # Query each provider
        for provider, config in PROVIDER_CONFIGS.items():
            if crypto_symbol not in config["supported_cryptos"]:
                continue
            if fiat_currency not in config["supported_fiats"]:
                continue
            
            try:
                quote = await self._get_provider_quote(
                    provider=provider,
                    crypto_symbol=crypto_symbol,
                    fiat_amount=fiat_amount,
                    fiat_currency=fiat_currency,
                    is_buy=True,
                    payment_method=payment_method
                )
                
                if quote:
                    quotes.append(quote)
                    
            except Exception as e:
                logger.warning("Quote fetch failed", provider=provider.value, error=str(e))
        
        # Sort by crypto amount received (descending - more is better)
        quotes.sort(key=lambda x: x.get("crypto_amount", 0), reverse=True)
        
        return quotes
    
    async def get_sell_quotes(
        self,
        crypto_symbol: str,
        crypto_amount: Decimal,
        fiat_currency: str,
        payout_method: str = "bank_transfer"
    ) -> List[Dict]:
        """
        Get sell quotes from all available providers.
        Returns list of quotes sorted by best rate.
        """
        crypto_symbol = crypto_symbol.upper()
        fiat_currency = fiat_currency.upper()
        
        quotes = []
        
        # Get USD value
        crypto_price = await price_service.get_price(crypto_symbol)
        usd_value = crypto_amount * crypto_price
        
        if usd_value < self.min_sale_usd or usd_value > self.max_sale_usd:
            return []
        
        # Query each provider
        for provider, config in PROVIDER_CONFIGS.items():
            if crypto_symbol not in config["supported_cryptos"]:
                continue
            if fiat_currency not in config["supported_fiats"]:
                continue
            
            try:
                quote = await self._get_provider_quote(
                    provider=provider,
                    crypto_symbol=crypto_symbol,
                    crypto_amount=crypto_amount,
                    fiat_currency=fiat_currency,
                    is_buy=False,
                    payment_method=payout_method
                )
                
                if quote:
                    quotes.append(quote)
                    
            except Exception as e:
                logger.warning("Sell quote failed", provider=provider.value, error=str(e))
        
        # Sort by fiat amount received (descending - more is better)
        quotes.sort(key=lambda x: x.get("fiat_amount", 0), reverse=True)
        
        return quotes
    
    async def _get_provider_quote(
        self,
        provider: PurchaseProvider,
        crypto_symbol: str,
        fiat_currency: str,
        is_buy: bool,
        payment_method: str,
        fiat_amount: Optional[Decimal] = None,
        crypto_amount: Optional[Decimal] = None
    ) -> Optional[Dict]:
        """Get quote from a specific provider"""
        
        config = PROVIDER_CONFIGS[provider]
        
        # Get market price as baseline
        crypto_price = await price_service.get_price(crypto_symbol)
        
        if is_buy:
            # Buying crypto with fiat
            provider_fee_percent = Decimal(str(config["fee_percent"]))
            total_fee_percent = provider_fee_percent + self.platform_fee_buy_percent
            
            # Calculate crypto amount after fees
            effective_fiat = fiat_amount * (1 - total_fee_percent / 100)
            crypto_received = effective_fiat / crypto_price
            
            # Add spread (providers usually have ~1% spread)
            crypto_received = crypto_received * Decimal("0.99")
            
            return {
                "provider": provider.value,
                "provider_name": config["name"],
                "provider_icon": config["icon"],
                "type": "buy",
                "crypto_symbol": crypto_symbol,
                "crypto_amount": float(crypto_received),
                "fiat_currency": fiat_currency,
                "fiat_amount": float(fiat_amount),
                "rate": float(fiat_amount / crypto_received) if crypto_received > 0 else 0,
                "market_rate": float(crypto_price),
                "provider_fee_percent": float(provider_fee_percent),
                "platform_fee_percent": float(self.platform_fee_buy_percent),
                "total_fee_percent": float(total_fee_percent),
                "payment_method": payment_method,
                "estimated_time": "5-30 min",
            }
        else:
            # Selling crypto for fiat
            provider_fee_percent = Decimal(str(config["fee_percent"]))
            total_fee_percent = provider_fee_percent + self.platform_fee_sell_percent
            
            # Calculate fiat amount after fees
            gross_fiat = crypto_amount * crypto_price
            # Add spread
            gross_fiat = gross_fiat * Decimal("0.99")
            net_fiat = gross_fiat * (1 - total_fee_percent / 100)
            
            return {
                "provider": provider.value,
                "provider_name": config["name"],
                "provider_icon": config["icon"],
                "type": "sell",
                "crypto_symbol": crypto_symbol,
                "crypto_amount": float(crypto_amount),
                "fiat_currency": fiat_currency,
                "fiat_amount": float(net_fiat),
                "rate": float(net_fiat / crypto_amount) if crypto_amount > 0 else 0,
                "market_rate": float(crypto_price),
                "provider_fee_percent": float(provider_fee_percent),
                "platform_fee_percent": float(self.platform_fee_sell_percent),
                "total_fee_percent": float(total_fee_percent),
                "payout_method": payment_method,
                "estimated_time": "1-3 business days",
            }
    
    # ==================== CREATE PURCHASE ====================
    
    async def create_buy_order(
        self,
        session,
        user_id: int,
        provider: str,
        crypto_symbol: str,
        fiat_amount: Decimal,
        fiat_currency: str,
        receiving_address: str,
        payment_method: str = "card"
    ) -> Tuple[Optional[str], Optional[DirectPurchase], str]:
        """
        Create a buy order and get widget URL.
        Returns: (widget_url, purchase_record, error_message)
        """
        provider_enum = PurchaseProvider(provider)
        config = PROVIDER_CONFIGS[provider_enum]
        
        # Validate
        if crypto_symbol not in config["supported_cryptos"]:
            return None, None, f"{provider} doesn't support {crypto_symbol}"
        
        if fiat_currency not in config["supported_fiats"]:
            return None, None, f"{provider} doesn't support {fiat_currency}"
        
        # Get quote
        quote = await self._get_provider_quote(
            provider=provider_enum,
            crypto_symbol=crypto_symbol,
            fiat_amount=fiat_amount,
            fiat_currency=fiat_currency,
            is_buy=True,
            payment_method=payment_method
        )
        
        if not quote:
            return None, None, "Failed to get quote"
        
        # Create database record
        platform_fee = fiat_amount * (self.platform_fee_buy_percent / 100)
        
        purchase = DirectPurchase(
            user_id=user_id,
            network=self._symbol_to_network(crypto_symbol),
            token_symbol=crypto_symbol,
            amount=Decimal(str(quote["crypto_amount"])),
            price_usd=fiat_amount if fiat_currency == "USD" else await self._convert_to_usd(fiat_amount, fiat_currency),
            platform_fee_usd=platform_fee,
            total_usd=fiat_amount + platform_fee,
            payment_provider=provider,
            payment_method=payment_method,
            receiving_address=receiving_address,
            status="pending"
        )
        
        session.add(purchase)
        await session.flush()
        
        # Generate widget URL
        widget_url = await self._generate_widget_url(
            provider=provider_enum,
            crypto_symbol=crypto_symbol,
            fiat_amount=fiat_amount,
            fiat_currency=fiat_currency,
            wallet_address=receiving_address,
            order_id=purchase.id
        )
        
        return widget_url, purchase, ""
    
    async def _generate_widget_url(
        self,
        provider: PurchaseProvider,
        crypto_symbol: str,
        fiat_amount: Decimal,
        fiat_currency: str,
        wallet_address: str,
        order_id: str
    ) -> str:
        """Generate provider widget URL with parameters"""
        
        config = PROVIDER_CONFIGS[provider]
        base_url = config["widget_url"]
        
        if provider == PurchaseProvider.MOONPAY:
            params = {
                "apiKey": self.moonpay_api_key or "pk_test_key",
                "currencyCode": crypto_symbol.lower(),
                "baseCurrencyCode": fiat_currency.lower(),
                "baseCurrencyAmount": str(fiat_amount),
                "walletAddress": wallet_address,
                "externalTransactionId": order_id[:16],
                "colorCode": "#7C3AED",  # Purple theme
            }
            
            query = "&".join(f"{k}={v}" for k, v in params.items())
            
            # Sign URL if secret key available
            if self.moonpay_secret_key:
                signature = hmac.new(
                    self.moonpay_secret_key.encode(),
                    f"?{query}".encode(),
                    hashlib.sha256
                ).hexdigest()
                query += f"&signature={signature}"
            
            return f"{base_url}?{query}"
        
        elif provider == PurchaseProvider.TRANSAK:
            params = {
                "apiKey": self.transak_api_key or "test_api_key",
                "cryptoCurrencyCode": crypto_symbol,
                "fiatCurrency": fiat_currency,
                "fiatAmount": str(fiat_amount),
                "walletAddress": wallet_address,
                "partnerOrderId": order_id[:16],
                "themeColor": "7C3AED",
            }
            
            query = "&".join(f"{k}={v}" for k, v in params.items())
            return f"{base_url}?{query}"
        
        elif provider == PurchaseProvider.ONRAMPER:
            params = {
                "apiKey": self.onramper_api_key or "pk_test",
                "defaultCrypto": crypto_symbol.lower(),
                "defaultFiat": fiat_currency.lower(),
                "defaultAmount": str(fiat_amount),
                "wallets": f"{crypto_symbol}:{wallet_address}",
                "partnerContext": order_id[:16],
                "themeName": "dark",
            }
            
            query = "&".join(f"{k}={v}" for k, v in params.items())
            return f"{base_url}?{query}"
        
        # Default fallback
        return f"{base_url}?crypto={crypto_symbol}&fiat={fiat_currency}&amount={fiat_amount}&address={wallet_address}"
    
    # ==================== SELL ====================
    
    async def create_sell_order(
        self,
        session,
        user_id: int,
        provider: str,
        crypto_symbol: str,
        crypto_amount: Decimal,
        fiat_currency: str,
        payout_details: Dict
    ) -> Tuple[Optional[Dict], str]:
        """
        Create a sell order.
        Returns: (order_details, error_message)
        
        Note: Sell flow is more complex as it requires:
        1. User sends crypto to provider's address
        2. Provider verifies and processes
        3. Fiat is sent to user's bank/card
        """
        provider_enum = PurchaseProvider(provider)
        
        # Get quote
        quote = await self._get_provider_quote(
            provider=provider_enum,
            crypto_symbol=crypto_symbol,
            crypto_amount=crypto_amount,
            fiat_currency=fiat_currency,
            is_buy=False,
            payment_method="bank_transfer"
        )
        
        if not quote:
            return None, "Failed to get sell quote"
        
        # In production, you would:
        # 1. Get deposit address from provider API
        # 2. Create transaction to send crypto there
        # 3. Monitor for confirmation
        # 4. Provider processes and sends fiat
        
        # For now, return instructions
        return {
            "quote": quote,
            "instructions": f"Sell {crypto_amount} {crypto_symbol} via {provider}",
            "deposit_address": "PROVIDER_DEPOSIT_ADDRESS",  # Get from API
            "status": "awaiting_crypto"
        }, ""
    
    # ==================== SUPPORTED OPTIONS ====================
    
    def get_supported_cryptos(self) -> List[Dict]:
        """Get list of cryptos supported for direct purchase"""
        all_cryptos = set()
        
        for config in PROVIDER_CONFIGS.values():
            all_cryptos.update(config["supported_cryptos"])
        
        return [
            {"symbol": s, "network": self._symbol_to_network(s)}
            for s in sorted(all_cryptos)
        ]
    
    def get_supported_fiats(self) -> List[str]:
        """Get list of fiat currencies supported"""
        all_fiats = set()
        
        for config in PROVIDER_CONFIGS.values():
            all_fiats.update(config["supported_fiats"])
        
        return sorted(all_fiats)
    
    def get_supported_payment_methods(self, fiat_currency: str) -> List[Dict]:
        """Get payment methods for a fiat currency"""
        methods = [
            {"id": "card", "name": "Credit/Debit Card", "icon": "💳", "time": "Instant"},
            {"id": "bank_transfer", "name": "Bank Transfer", "icon": "🏦", "time": "1-3 days"},
        ]
        
        if fiat_currency in ["USD", "EUR"]:
            methods.append({"id": "apple_pay", "name": "Apple Pay", "icon": "🍎", "time": "Instant"})
            methods.append({"id": "google_pay", "name": "Google Pay", "icon": "🤖", "time": "Instant"})
        
        if fiat_currency == "EUR":
            methods.append({"id": "sepa", "name": "SEPA Transfer", "icon": "🇪🇺", "time": "1-2 days"})
        
        if fiat_currency == "BRL":
            methods.append({"id": "pix", "name": "PIX", "icon": "⚡", "time": "Instant"})
        
        return methods
    
    def get_limits(self) -> Dict:
        """Get current purchase/sale limits"""
        return {
            "buy": {
                "min_usd": float(self.min_purchase_usd),
                "max_usd": float(self.max_purchase_usd),
            },
            "sell": {
                "min_usd": float(self.min_sale_usd),
                "max_usd": float(self.max_sale_usd),
            },
            "platform_fee_buy_percent": float(self.platform_fee_buy_percent),
            "platform_fee_sell_percent": float(self.platform_fee_sell_percent),
        }
    
    def update_limits(
        self,
        min_buy: Optional[Decimal] = None,
        max_buy: Optional[Decimal] = None,
        min_sell: Optional[Decimal] = None,
        max_sell: Optional[Decimal] = None,
        fee_buy: Optional[Decimal] = None,
        fee_sell: Optional[Decimal] = None
    ):
        """Update limits (admin only)"""
        if min_buy is not None:
            self.min_purchase_usd = min_buy
        if max_buy is not None:
            self.max_purchase_usd = max_buy
        if min_sell is not None:
            self.min_sale_usd = min_sell
        if max_sell is not None:
            self.max_sale_usd = max_sell
        if fee_buy is not None:
            self.platform_fee_buy_percent = fee_buy
        if fee_sell is not None:
            self.platform_fee_sell_percent = fee_sell
    
    # ==================== HELPERS ====================
    
    async def _convert_to_usd(self, amount: Decimal, currency: str) -> Decimal:
        """Convert fiat amount to USD"""
        if currency == "USD":
            return amount
        
        rates = await price_service.get_fiat_rates()
        rate = rates.get(currency, 1)
        
        return amount / Decimal(str(rate)) if rate > 0 else amount
    
    def _symbol_to_network(self, symbol: str) -> str:
        """Convert crypto symbol to network name"""
        symbol_to_network = {v: k for k, v in NETWORK_TO_SYMBOL.items()}
        return symbol_to_network.get(symbol, symbol.lower())
    
    async def close(self):
        """Close HTTP client"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()


# Global instance
direct_purchase_service = DirectPurchaseService()
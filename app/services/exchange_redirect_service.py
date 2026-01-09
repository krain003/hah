"""
NEXUS WALLET - Exchange Redirect Service
Зарабатывай на реферальных ссылках без лицензий!
"""

from typing import Dict, List, Optional
from decimal import Decimal
import structlog

logger = structlog.get_logger(__name__)


# ==================== ТВОИ РЕФЕРАЛЬНЫЕ КОДЫ ====================

EXCHANGES = {
    "binance": {
        "name": "Binance",
        "icon": "🟡",
        "rating": 4.8,
        "users": "150M+",
        "fee": "0.1%",
        "min_deposit": 10,
        "fiat_methods": ["Card", "Bank", "P2P"],
        "supported_cryptos": ["BTC", "ETH", "BNB", "SOL", "TON", "TRX", "MATIC", "AVAX"],
        "supported_fiats": ["USD", "EUR", "RUB", "UAH", "KZT", "TRY", "GBP"],
        "ref_link": "https://accounts.binance.com/register?ref=CPA_00POQB4F5U",
        "buy_link": "https://www.binance.com/en/buy-sell-crypto?ref=CPA_00POQB4F5U",
        "p2p_link": "https://p2p.binance.com/?ref=CPA_00POQB4F5U",
    },
    "bybit": {
        "name": "Bybit",
        "icon": "🟠",
        "rating": 4.7,
        "users": "20M+",
        "fee": "0.1%",
        "min_deposit": 10,
        "fiat_methods": ["Card", "Bank", "P2P"],
        "supported_cryptos": ["BTC", "ETH", "SOL", "MATIC", "AVAX"],
        "supported_fiats": ["USD", "EUR", "RUB", "UAH", "GBP"],
        "ref_link": "https://www.bybit.com/invite?ref=3VYE7G1",
        "buy_link": "https://www.bybit.com/fiat/trade/otc?ref=3VYE7G1",
        "p2p_link": "https://www.bybit.com/fiat/trade/otc?ref=3VYE7G1",
    },
    "okx": {
        "name": "OKX",
        "icon": "⚫",
        "rating": 4.6,
        "users": "50M+",
        "fee": "0.08%",
        "min_deposit": 10,
        "fiat_methods": ["Card", "Bank", "P2P"],
        "supported_cryptos": ["BTC", "ETH", "SOL", "TON", "TRX"],
        "supported_fiats": ["USD", "EUR", "RUB", "UAH", "TRY"],
        "ref_link": "https://www.okx.com/join/42235472",
        "buy_link": "https://www.okx.com/buy-crypto?ref=42235472",
        "p2p_link": "https://www.okx.com/p2p-markets?ref=42235472",
    },
    "kucoin": {
        "name": "KuCoin",
        "icon": "🟢",
        "rating": 4.5,
        "users": "30M+",
        "fee": "0.1%",
        "min_deposit": 5,
        "fiat_methods": ["Card", "Bank", "P2P"],
        "supported_cryptos": ["BTC", "ETH", "SOL", "TRX", "TON"],
        "supported_fiats": ["USD", "EUR", "RUB"],
        "ref_link": "https://www.kucoin.com/r/rf/CXEVD5G1",
        "buy_link": "https://www.kucoin.com/buy-crypto?rcode=CXEVD5G1",
        "p2p_link": "https://www.kucoin.com/p2p?rcode=CXEVD5G1",
    },
    "mexc": {
        "name": "MEXC",
        "icon": "🔵",
        "rating": 4.4,
        "users": "10M+",
        "fee": "0%",
        "min_deposit": 1,
        "fiat_methods": ["Card", "P2P"],
        "supported_cryptos": ["BTC", "ETH", "SOL", "TON", "TRX"],
        "supported_fiats": ["USD", "EUR", "RUB"],
        "ref_link": "https://www.mexc.com/register?inviteCode=3jTfF",
        "buy_link": "https://www.mexc.com/buy-crypto?inviteCode=3jTfF",
        "p2p_link": "https://www.mexc.com/p2p?inviteCode=3jTfF",
    },
}


class ExchangeRedirectService:
    """
    Сервис редиректа на биржи с реферальными ссылками.
    Не требует лицензий, зарабатываешь на рефералках!
    """
    
    def __init__(self):
        self.exchanges = EXCHANGES
    
    def get_best_exchanges_for_buy(
        self,
        crypto: str,
        fiat: str,
        amount_usd: float
    ) -> List[Dict]:
        """Получить лучшие биржи для покупки"""
        
        suitable = []
        
        for key, exchange in self.exchanges.items():
            if crypto not in exchange["supported_cryptos"]:
                continue
            if fiat not in exchange["supported_fiats"]:
                continue
            if amount_usd < exchange["min_deposit"]:
                continue
            
            suitable.append({
                "id": key,
                "name": exchange["name"],
                "icon": exchange["icon"],
                "rating": exchange["rating"],
                "users": exchange["users"],
                "fee": exchange["fee"],
                "methods": exchange["fiat_methods"],
                "buy_link": exchange["buy_link"],
                "p2p_link": exchange["p2p_link"],
            })
        
        suitable.sort(key=lambda x: x["rating"], reverse=True)
        
        return suitable
    
    def get_best_exchanges_for_sell(
        self,
        crypto: str,
        fiat: str
    ) -> List[Dict]:
        """Получить лучшие биржи для продажи"""
        
        suitable = []
        
        for key, exchange in self.exchanges.items():
            if crypto not in exchange["supported_cryptos"]:
                continue
            if fiat not in exchange["supported_fiats"]:
                continue
            
            suitable.append({
                "id": key,
                "name": exchange["name"],
                "icon": exchange["icon"],
                "rating": exchange["rating"],
                "p2p_link": exchange["p2p_link"],
                "ref_link": exchange["ref_link"],
            })
        
        suitable.sort(key=lambda x: x["rating"], reverse=True)
        
        return suitable
    
    def get_all_exchanges(self) -> List[Dict]:
        """Получить все биржи"""
        return [
            {
                "id": key,
                "name": ex["name"],
                "icon": ex["icon"],
                "rating": ex["rating"],
                "ref_link": ex["ref_link"],
            }
            for key, ex in self.exchanges.items()
        ]
    
    def get_exchange_link(self, exchange_id: str, link_type: str = "buy") -> Optional[str]:
        """Получить ссылку на биржу"""
        exchange = self.exchanges.get(exchange_id)
        if not exchange:
            return None
        
        if link_type == "buy":
            return exchange["buy_link"]
        elif link_type == "p2p":
            return exchange["p2p_link"]
        else:
            return exchange["ref_link"]


# Global instance
exchange_service = ExchangeRedirectService()
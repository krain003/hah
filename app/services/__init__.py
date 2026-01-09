"""
NEXUS WALLET - Services
"""

from .wallet_service import wallet_service, WalletService
from .p2p_service import p2p_service, P2PService, SUPPORTED_CRYPTOS, SUPPORTED_FIATS, PAYMENT_METHOD_TYPES
from .price_service import price_service, PriceService

# Для обратной совместимости
PAYMENT_METHODS = list(PAYMENT_METHOD_TYPES.keys())

__all__ = [
    "wallet_service",
    "WalletService",
    "p2p_service", 
    "P2PService",
    "price_service",
    "PriceService",
    "SUPPORTED_CRYPTOS",
    "SUPPORTED_FIATS",
    "PAYMENT_METHOD_TYPES",
    "PAYMENT_METHODS",
]
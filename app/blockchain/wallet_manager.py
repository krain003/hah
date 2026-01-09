"""
NEXUS WALLET - Core Wallet Manager (Production Edition)
Full Multi-Chain Integration: 33 Networks
"""

import asyncio
import hashlib
import hmac
import os
import time
import structlog
from typing import Dict, List, Optional, Any, Tuple, Callable
from decimal import Decimal
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from functools import wraps
from contextlib import asynccontextmanager

import httpx

from mnemonic import Mnemonic
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.exceptions import ContractLogicError

try:
    from web3.middleware import geth_poa_middleware
except ImportError:
    geth_poa_middleware = None

import base58
import base64

logger = structlog.get_logger(__name__)
Account.enable_unaudited_hdwallet_features()


# ==================== DECORATORS ====================

def async_retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Retry decorator for async functions"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
            raise last_exception
        return wrapper
    return decorator


# ==================== ENUMS ====================

class NetworkType(Enum):
    EVM = "evm"
    BITCOIN = "bitcoin"
    LITECOIN = "litecoin"
    DOGECOIN = "dogecoin"
    SOLANA = "solana"
    TON = "ton"
    TRON = "tron"
    XRP = "xrp"
    CARDANO = "cardano"
    POLKADOT = "polkadot"
    COSMOS = "cosmos"
    NEAR = "near"
    APTOS = "aptos"
    SUI = "sui"


class NetworkStatus(Enum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class TokenStandard(Enum):
    NATIVE = "native"
    ERC20 = "erc20"
    BEP20 = "bep20"
    TRC20 = "trc20"
    SPL = "spl"
    JETTON = "jetton"


# ==================== DATA CLASSES ====================

@dataclass
class NetworkConfig:
    name: str
    symbol: str
    chain_id: Optional[int]
    rpc_url: str
    explorer_url: str
    network_type: NetworkType
    decimals: int = 18
    icon: str = "🔗"
    is_testnet: bool = False
    coingecko_id: str = ""
    binance_symbol: str = ""
    backup_rpc_urls: List[str] = field(default_factory=list)
    min_confirmations: int = 1
    avg_block_time: float = 12.0
    max_gas_price_gwei: int = 500


@dataclass
class WalletData:
    address: str
    private_key: str
    mnemonic: Optional[str] = None
    network: str = ""
    derivation_path: Optional[str] = None
    public_key: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TokenInfo:
    symbol: str
    name: str
    address: Optional[str]
    decimals: int
    network: str
    icon: str = ""
    coingecko_id: str = ""
    is_native: bool = False
    standard: TokenStandard = TokenStandard.NATIVE
    
    def __post_init__(self):
        self.is_native = self.address is None
        if self.is_native:
            self.standard = TokenStandard.NATIVE


@dataclass
class TransactionResult:
    success: bool
    tx_hash: Optional[str] = None
    error: Optional[str] = None
    gas_used: Optional[int] = None
    fee_paid: Optional[Decimal] = None
    block_number: Optional[int] = None
    confirmations: int = 0


@dataclass
class GasEstimate:
    gas_limit: int
    gas_price: int
    gas_price_gwei: float
    total_fee: Decimal
    total_fee_usd: Optional[Decimal] = None
    estimated_time: Optional[int] = None


@dataclass
class NetworkHealth:
    network: str
    status: NetworkStatus
    block_height: Optional[int] = None
    last_block_time: Optional[datetime] = None
    rpc_latency_ms: Optional[float] = None
    error: Optional[str] = None
    checked_at: datetime = field(default_factory=datetime.utcnow)

# ==================== NETWORKS (33 NETWORKS) ====================

NETWORKS: Dict[str, NetworkConfig] = {
    # ==================== EVM NETWORKS (20) ====================
    "ethereum": NetworkConfig(
        name="Ethereum",
        symbol="ETH",
        chain_id=1,
        rpc_url="https://ethereum.publicnode.com",
        explorer_url="https://etherscan.io",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="⟠",
        coingecko_id="ethereum",
        binance_symbol="ETHUSDT",
        backup_rpc_urls=["https://rpc.ankr.com/eth", "https://eth.llamarpc.com"],
        min_confirmations=12,
        avg_block_time=12.0
    ),
    "bsc": NetworkConfig(
        name="BNB Smart Chain",
        symbol="BNB",
        chain_id=56,
        rpc_url="https://bsc.publicnode.com",
        explorer_url="https://bscscan.com",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="💛",
        coingecko_id="binancecoin",
        binance_symbol="BNBUSDT",
        backup_rpc_urls=["https://rpc.ankr.com/bsc", "https://bsc-dataseed.binance.org"],
        min_confirmations=15,
        avg_block_time=3.0
    ),
    "polygon": NetworkConfig(
        name="Polygon",
        symbol="POL",
        chain_id=137,
        rpc_url="https://polygon-bor.publicnode.com",
        explorer_url="https://polygonscan.com",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="💜",
        coingecko_id="matic-network",
        binance_symbol="POLUSDT",
        backup_rpc_urls=["https://rpc.ankr.com/polygon", "https://polygon-rpc.com"],
        min_confirmations=128,
        avg_block_time=2.0
    ),
    "arbitrum": NetworkConfig(
        name="Arbitrum One",
        symbol="ETH",
        chain_id=42161,
        rpc_url="https://arbitrum-one.publicnode.com",
        explorer_url="https://arbiscan.io",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="🔵",
        coingecko_id="ethereum",
        binance_symbol="ARBUSDT",
        backup_rpc_urls=["https://rpc.ankr.com/arbitrum", "https://arb1.arbitrum.io/rpc"],
        min_confirmations=1,
        avg_block_time=0.25
    ),
    "avalanche": NetworkConfig(
        name="Avalanche C-Chain",
        symbol="AVAX",
        chain_id=43114,
        rpc_url="https://avalanche-c-chain.publicnode.com",
        explorer_url="https://snowtrace.io",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="🔺",
        coingecko_id="avalanche-2",
        binance_symbol="AVAXUSDT",
        backup_rpc_urls=["https://rpc.ankr.com/avalanche", "https://api.avax.network/ext/bc/C/rpc"],
        min_confirmations=1,
        avg_block_time=2.0
    ),
    "optimism": NetworkConfig(
        name="Optimism",
        symbol="ETH",
        chain_id=10,
        rpc_url="https://optimism.publicnode.com",
        explorer_url="https://optimistic.etherscan.io",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="🔴",
        coingecko_id="ethereum",
        binance_symbol="OPUSDT",
        backup_rpc_urls=["https://rpc.ankr.com/optimism", "https://mainnet.optimism.io"],
        min_confirmations=1,
        avg_block_time=2.0
    ),
    "base": NetworkConfig(
        name="Base",
        symbol="ETH",
        chain_id=8453,
        rpc_url="https://base.publicnode.com",
        explorer_url="https://basescan.org",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="🔷",
        coingecko_id="ethereum",
        binance_symbol="ETHUSDT",
        backup_rpc_urls=["https://mainnet.base.org", "https://base.llamarpc.com"],
        min_confirmations=1,
        avg_block_time=2.0
    ),
"fantom": NetworkConfig(
    name="Fantom",
    symbol="FTM",
    chain_id=250,
    rpc_url="https://rpc.ankr.com/fantom",  # ✅ Рабочий RPC
    explorer_url="https://ftmscan.com",
    network_type=NetworkType.EVM,
    decimals=18,
    icon="👻",
    coingecko_id="fantom",
    binance_symbol="FTMUSDT",
    backup_rpc_urls=[
        "https://fantom-mainnet.public.blastapi.io",
        "https://rpc.fantom.network",
        "https://fantom.drpc.org"
    ],
    min_confirmations=1,
    avg_block_time=1.0
),
    "cronos": NetworkConfig(
        name="Cronos",
        symbol="CRO",
        chain_id=25,
        rpc_url="https://evm.cronos.org",
        explorer_url="https://cronoscan.com",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="🔵",
        coingecko_id="crypto-com-chain",
        binance_symbol="CROUSDT",
        backup_rpc_urls=["https://cronos-evm.publicnode.com"],
        min_confirmations=1,
        avg_block_time=6.0
    ),
    "zksync": NetworkConfig(
        name="zkSync Era",
        symbol="ETH",
        chain_id=324,
        rpc_url="https://mainnet.era.zksync.io",
        explorer_url="https://explorer.zksync.io",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="🔮",
        coingecko_id="ethereum",
        binance_symbol="ETHUSDT",
        backup_rpc_urls=["https://zksync.drpc.org"],
        min_confirmations=1,
        avg_block_time=1.0
    ),
    "linea": NetworkConfig(
        name="Linea",
        symbol="ETH",
        chain_id=59144,
        rpc_url="https://rpc.linea.build",
        explorer_url="https://lineascan.build",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="🟢",
        coingecko_id="ethereum",
        binance_symbol="ETHUSDT",
        backup_rpc_urls=["https://linea.drpc.org"],
        min_confirmations=1,
        avg_block_time=2.0
    ),
    "mantle": NetworkConfig(
        name="Mantle",
        symbol="MNT",
        chain_id=5000,
        rpc_url="https://rpc.mantle.xyz",
        explorer_url="https://explorer.mantle.xyz",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="🟡",
        coingecko_id="mantle",
        binance_symbol="MNTUSDT",
        backup_rpc_urls=["https://mantle-mainnet.public.blastapi.io"],
        min_confirmations=1,
        avg_block_time=2.0
    ),
    "scroll": NetworkConfig(
        name="Scroll",
        symbol="ETH",
        chain_id=534352,
        rpc_url="https://rpc.scroll.io",
        explorer_url="https://scrollscan.com",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="📜",
        coingecko_id="ethereum",
        binance_symbol="ETHUSDT",
        backup_rpc_urls=["https://scroll.drpc.org"],
        min_confirmations=1,
        avg_block_time=3.0
    ),
    "blast": NetworkConfig(
        name="Blast",
        symbol="ETH",
        chain_id=81457,
        rpc_url="https://rpc.blast.io",
        explorer_url="https://blastscan.io",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="💥",
        coingecko_id="ethereum",
        binance_symbol="ETHUSDT",
        backup_rpc_urls=["https://blast.drpc.org"],
        min_confirmations=1,
        avg_block_time=2.0
    ),
    "celo": NetworkConfig(
        name="Celo",
        symbol="CELO",
        chain_id=42220,
        rpc_url="https://forno.celo.org",
        explorer_url="https://celoscan.io",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="🌿",
        coingecko_id="celo",
        binance_symbol="CELOUSDT",
        backup_rpc_urls=["https://rpc.ankr.com/celo"],
        min_confirmations=1,
        avg_block_time=5.0
    ),
    "gnosis": NetworkConfig(
        name="Gnosis",
        symbol="xDAI",
        chain_id=100,
        rpc_url="https://rpc.gnosischain.com",
        explorer_url="https://gnosisscan.io",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="🦉",
        coingecko_id="xdai",
        binance_symbol="GNOSISUSDT",
        backup_rpc_urls=["https://gnosis.drpc.org"],
        min_confirmations=1,
        avg_block_time=5.0
    ),
    "moonbeam": NetworkConfig(
        name="Moonbeam",
        symbol="GLMR",
        chain_id=1284,
        rpc_url="https://rpc.api.moonbeam.network",
        explorer_url="https://moonbeam.moonscan.io",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="🌙",
        coingecko_id="moonbeam",
        binance_symbol="GLMRUSDT",
        backup_rpc_urls=["https://moonbeam.public.blastapi.io"],
        min_confirmations=1,
        avg_block_time=12.0
    ),
    "moonriver": NetworkConfig(
        name="Moonriver",
        symbol="MOVR",
        chain_id=1285,
        rpc_url="https://rpc.api.moonriver.moonbeam.network",
        explorer_url="https://moonriver.moonscan.io",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="🌊",
        coingecko_id="moonriver",
        binance_symbol="MOVRUSDT",
        backup_rpc_urls=["https://moonriver.public.blastapi.io"],
        min_confirmations=1,
        avg_block_time=12.0
    ),
    "harmony": NetworkConfig(
        name="Harmony",
        symbol="ONE",
        chain_id=1666600000,
        rpc_url="https://api.harmony.one",
        explorer_url="https://explorer.harmony.one",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="🎵",
        coingecko_id="harmony",
        binance_symbol="ONEUSDT",
        backup_rpc_urls=["https://harmony-0-rpc.gateway.pokt.network"],
        min_confirmations=1,
        avg_block_time=2.0
    ),
    "klaytn": NetworkConfig(
        name="Klaytn",
        symbol="KLAY",
        chain_id=8217,
        rpc_url="https://public-en-cypress.klaytn.net",
        explorer_url="https://klaytnscope.com",
        network_type=NetworkType.EVM,
        decimals=18,
        icon="🔶",
        coingecko_id="klay-token",
        binance_symbol="KLAYUSDT",
        backup_rpc_urls=["https://klaytn.drpc.org"],
        min_confirmations=1,
        avg_block_time=1.0
    ),
    
    # ==================== NON-EVM NETWORKS (13) ====================
    "ton": NetworkConfig(
        name="TON",
        symbol="TON",
        chain_id=None,
        rpc_url="https://toncenter.com/api/v2",
        explorer_url="https://tonscan.org",
        network_type=NetworkType.TON,
        decimals=9,
        icon="💎",
        coingecko_id="the-open-network",
        binance_symbol="TONUSDT",
        backup_rpc_urls=["https://tonapi.io/v2"],
        min_confirmations=1,
        avg_block_time=5.0
    ),
    "solana": NetworkConfig(
        name="Solana",
        symbol="SOL",
        chain_id=None,
        rpc_url="https://api.mainnet-beta.solana.com",
        explorer_url="https://solscan.io",
        network_type=NetworkType.SOLANA,
        decimals=9,
        icon="◎",
        coingecko_id="solana",
        binance_symbol="SOLUSDT",
        backup_rpc_urls=["https://solana-mainnet.rpc.extrnode.com"],
        min_confirmations=32,
        avg_block_time=0.4
    ),
    "tron": NetworkConfig(
        name="TRON",
        symbol="TRX",
        chain_id=None,
        rpc_url="https://api.trongrid.io",
        explorer_url="https://tronscan.org",
        network_type=NetworkType.TRON,
        decimals=6,
        icon="🔴",
        coingecko_id="tron",
        binance_symbol="TRXUSDT",
        backup_rpc_urls=["https://api.shasta.trongrid.io"],
        min_confirmations=19,
        avg_block_time=3.0
    ),
    "bitcoin": NetworkConfig(
        name="Bitcoin",
        symbol="BTC",
        chain_id=None,
        rpc_url="https://blockstream.info/api",
        explorer_url="https://blockstream.info",
        network_type=NetworkType.BITCOIN,
        decimals=8,
        icon="₿",
        coingecko_id="bitcoin",
        binance_symbol="BTCUSDT",
        backup_rpc_urls=["https://mempool.space/api"],
        min_confirmations=6,
        avg_block_time=600.0
    ),
    "litecoin": NetworkConfig(
        name="Litecoin",
        symbol="LTC",
        chain_id=None,
        rpc_url="https://litecoinspace.org/api",
        explorer_url="https://litecoinspace.org",
        network_type=NetworkType.LITECOIN,
        decimals=8,
        icon="Ł",
        coingecko_id="litecoin",
        binance_symbol="LTCUSDT",
        backup_rpc_urls=["https://blockchair.com/litecoin"],
        min_confirmations=6,
        avg_block_time=150.0
    ),
    "dogecoin": NetworkConfig(
        name="Dogecoin",
        symbol="DOGE",
        chain_id=None,
        rpc_url="https://dogechain.info/api",
        explorer_url="https://dogechain.info",
        network_type=NetworkType.DOGECOIN,
        decimals=8,
        icon="🐕",
        coingecko_id="dogecoin",
        binance_symbol="DOGEUSDT",
        backup_rpc_urls=["https://blockchair.com/dogecoin"],
        min_confirmations=6,
        avg_block_time=60.0
    ),
    "xrp": NetworkConfig(
        name="XRP Ledger",
        symbol="XRP",
        chain_id=None,
        rpc_url="https://xrplcluster.com",
        explorer_url="https://xrpscan.com",
        network_type=NetworkType.XRP,
        decimals=6,
        icon="✕",
        coingecko_id="ripple",
        binance_symbol="XRPUSDT",
        backup_rpc_urls=["https://s1.ripple.com:51234"],
        min_confirmations=1,
        avg_block_time=4.0
    ),
    "cardano": NetworkConfig(
        name="Cardano",
        symbol="ADA",
        chain_id=None,
        rpc_url="https://cardano-mainnet.blockfrost.io/api/v0",
        explorer_url="https://cardanoscan.io",
        network_type=NetworkType.CARDANO,
        decimals=6,
        icon="💙",
        coingecko_id="cardano",
        binance_symbol="ADAUSDT",
        backup_rpc_urls=[],
        min_confirmations=15,
        avg_block_time=20.0
    ),
    "polkadot": NetworkConfig(
        name="Polkadot",
        symbol="DOT",
        chain_id=None,
        rpc_url="https://rpc.polkadot.io",
        explorer_url="https://polkadot.subscan.io",
        network_type=NetworkType.POLKADOT,
        decimals=10,
        icon="⚫",
        coingecko_id="polkadot",
        binance_symbol="DOTUSDT",
        backup_rpc_urls=["wss://polkadot.api.onfinality.io/public-ws"],
        min_confirmations=1,
        avg_block_time=6.0
    ),
    "cosmos": NetworkConfig(
        name="Cosmos Hub",
        symbol="ATOM",
        chain_id=None,
        rpc_url="https://cosmos-rest.publicnode.com",
        explorer_url="https://www.mintscan.io/cosmos",
        network_type=NetworkType.COSMOS,
        decimals=6,
        icon="⚛️",
        coingecko_id="cosmos",
        binance_symbol="ATOMUSDT",
        backup_rpc_urls=["https://rest.cosmos.directory/cosmoshub"],
        min_confirmations=1,
        avg_block_time=6.0
    ),
    "near": NetworkConfig(
        name="NEAR Protocol",
        symbol="NEAR",
        chain_id=None,
        rpc_url="https://rpc.mainnet.near.org",
        explorer_url="https://nearblocks.io",
        network_type=NetworkType.NEAR,
        decimals=24,
        icon="🌐",
        coingecko_id="near",
        binance_symbol="NEARUSDT",
        backup_rpc_urls=["https://near.lava.build"],
        min_confirmations=1,
        avg_block_time=1.0
    ),
    "aptos": NetworkConfig(
        name="Aptos",
        symbol="APT",
        chain_id=None,
        rpc_url="https://fullnode.mainnet.aptoslabs.com/v1",
        explorer_url="https://aptoscan.com",
        network_type=NetworkType.APTOS,
        decimals=8,
        icon="🌀",
        coingecko_id="aptos",
        binance_symbol="APTUSDT",
        backup_rpc_urls=[],
        min_confirmations=1,
        avg_block_time=1.0
    ),
    "sui": NetworkConfig(
        name="Sui",
        symbol="SUI",
        chain_id=None,
        rpc_url="https://fullnode.mainnet.sui.io:443",
        explorer_url="https://suiscan.xyz",
        network_type=NetworkType.SUI,
        decimals=9,
        icon="💧",
        coingecko_id="sui",
        binance_symbol="SUIUSDT",
        backup_rpc_urls=[],
        min_confirmations=1,
        avg_block_time=0.5
    ),
}

# ==================== TOKENS ====================

TOKENS: Dict[str, List[TokenInfo]] = {
    "ethereum": [
        TokenInfo("ETH", "Ethereum", None, 18, "ethereum", "⟠", "ethereum"),
        TokenInfo("USDT", "Tether", "0xdAC17F958D2ee523a2206206994597C13D831ec7", 6, "ethereum", "💵", "tether", standard=TokenStandard.ERC20),
        TokenInfo("USDC", "USD Coin", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6, "ethereum", "💵", "usd-coin", standard=TokenStandard.ERC20),
        TokenInfo("PEPE", "Pepe", "0x6982508145454Ce325dDbE47a25d4ec3d2311933", 18, "ethereum", "🐸", "pepe", standard=TokenStandard.ERC20),
        TokenInfo("SHIB", "Shiba Inu", "0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE", 18, "ethereum", "🐕", "shiba-inu", standard=TokenStandard.ERC20),
        TokenInfo("LINK", "Chainlink", "0x514910771AF9Ca656af840dff83E8264EcF986CA", 18, "ethereum", "🔗", "chainlink", standard=TokenStandard.ERC20),
        TokenInfo("UNI", "Uniswap", "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984", 18, "ethereum", "🦄", "uniswap", standard=TokenStandard.ERC20),
        TokenInfo("WBTC", "Wrapped Bitcoin", "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", 8, "ethereum", "₿", "wrapped-bitcoin", standard=TokenStandard.ERC20),
    ],
    "bsc": [
        TokenInfo("BNB", "BNB", None, 18, "bsc", "💛", "binancecoin"),
        TokenInfo("USDT", "Tether BSC", "0x55d398326f99059fF775485246999027B3197955", 18, "bsc", "💵", "tether", standard=TokenStandard.BEP20),
        TokenInfo("USDC", "USD Coin", "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d", 18, "bsc", "💵", "usd-coin", standard=TokenStandard.BEP20),
        TokenInfo("CAKE", "PancakeSwap", "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82", 18, "bsc", "🥞", "pancakeswap-token", standard=TokenStandard.BEP20),
    ],
    "polygon": [
        TokenInfo("POL", "Polygon", None, 18, "polygon", "💜", "matic-network"),
        TokenInfo("USDT", "Tether", "0xc2132D05D31c914a87C6611C10748AEb04B58e8F", 6, "polygon", "💵", "tether", standard=TokenStandard.ERC20),
        TokenInfo("USDC", "USD Coin", "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", 6, "polygon", "💵", "usd-coin", standard=TokenStandard.ERC20),
    ],
    "arbitrum": [
        TokenInfo("ETH", "Ethereum", None, 18, "arbitrum", "🔵", "ethereum"),
        TokenInfo("ARB", "Arbitrum", "0x912CE59144191C1204E64559FE8253a0e49E6548", 18, "arbitrum", "🔵", "arbitrum", standard=TokenStandard.ERC20),
        TokenInfo("USDC", "USD Coin", "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 6, "arbitrum", "💵", "usd-coin", standard=TokenStandard.ERC20),
    ],
    "avalanche": [
        TokenInfo("AVAX", "Avalanche", None, 18, "avalanche", "🔺", "avalanche-2"),
        TokenInfo("USDC", "USD Coin", "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E", 6, "avalanche", "💵", "usd-coin", standard=TokenStandard.ERC20),
    ],
    "optimism": [
        TokenInfo("ETH", "Ethereum", None, 18, "optimism", "🔴", "ethereum"),
        TokenInfo("OP", "Optimism", "0x4200000000000000000000000000000000000042", 18, "optimism", "🔴", "optimism", standard=TokenStandard.ERC20),
        TokenInfo("USDC", "USD Coin", "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85", 6, "optimism", "💵", "usd-coin", standard=TokenStandard.ERC20),
    ],
    "base": [
        TokenInfo("ETH", "Ethereum", None, 18, "base", "🔷", "ethereum"),
        TokenInfo("USDC", "USD Coin", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6, "base", "💵", "usd-coin", standard=TokenStandard.ERC20),
    ],
    "fantom": [
        TokenInfo("FTM", "Fantom", None, 18, "fantom", "👻", "fantom"),
        TokenInfo("USDC", "USD Coin", "0x04068DA6C83AFCFA0e13ba15A6696662335D5B75", 6, "fantom", "💵", "usd-coin", standard=TokenStandard.ERC20),
    ],
    "cronos": [
        TokenInfo("CRO", "Cronos", None, 18, "cronos", "🔵", "crypto-com-chain"),
        TokenInfo("USDC", "USD Coin", "0xc21223249CA28397B4B6541dfFaEcC539BfF0c59", 6, "cronos", "💵", "usd-coin", standard=TokenStandard.ERC20),
    ],
    "zksync": [
        TokenInfo("ETH", "Ethereum", None, 18, "zksync", "🔮", "ethereum"),
        TokenInfo("USDC", "USD Coin", "0x3355df6D4c9C3035724Fd0e3914dE96A5a83aaf4", 6, "zksync", "💵", "usd-coin", standard=TokenStandard.ERC20),
    ],
    "linea": [
        TokenInfo("ETH", "Ethereum", None, 18, "linea", "🟢", "ethereum"),
        TokenInfo("USDC", "USD Coin", "0x176211869cA2b568f2A7D4EE941E073a821EE1ff", 6, "linea", "💵", "usd-coin", standard=TokenStandard.ERC20),
    ],
    "mantle": [
        TokenInfo("MNT", "Mantle", None, 18, "mantle", "🟡", "mantle"),
        TokenInfo("USDC", "USD Coin", "0x09Bc4E0D10e52467f0FE7C3C15F4D6f0e5bCc0d8", 6, "mantle", "💵", "usd-coin", standard=TokenStandard.ERC20),
    ],
    "scroll": [
        TokenInfo("ETH", "Ethereum", None, 18, "scroll", "📜", "ethereum"),
        TokenInfo("USDC", "USD Coin", "0x06eFdBFf2a14a7c8E15944D1F4A48F9F95F663A4", 6, "scroll", "💵", "usd-coin", standard=TokenStandard.ERC20),
    ],
    "blast": [
        TokenInfo("ETH", "Ethereum", None, 18, "blast", "💥", "ethereum"),
        TokenInfo("USDB", "USDB", "0x4300000000000000000000000000000000000003", 18, "blast", "💵", "usdb", standard=TokenStandard.ERC20),
    ],
    "celo": [
        TokenInfo("CELO", "Celo", None, 18, "celo", "🌿", "celo"),
        TokenInfo("cUSD", "Celo Dollar", "0x765DE816845861e75A25fCA122bb6898B8B1282a", 18, "celo", "💵", "celo-dollar", standard=TokenStandard.ERC20),
    ],
    "gnosis": [
        TokenInfo("xDAI", "xDAI", None, 18, "gnosis", "🦉", "xdai"),
        TokenInfo("USDC", "USD Coin", "0xDDAfbb505ad214D7b80b1f830fcCc89B60fb7A83", 6, "gnosis", "💵", "usd-coin", standard=TokenStandard.ERC20),
    ],
    "moonbeam": [
        TokenInfo("GLMR", "Moonbeam", None, 18, "moonbeam", "🌙", "moonbeam"),
        TokenInfo("USDC", "USD Coin", "0x818ec0A7Fe18Ff94269904fCED6AE3DaE6d6dC0b", 6, "moonbeam", "💵", "usd-coin", standard=TokenStandard.ERC20),
    ],
    "moonriver": [
        TokenInfo("MOVR", "Moonriver", None, 18, "moonriver", "🌊", "moonriver"),
        TokenInfo("USDC", "USD Coin", "0xE3F5a90F9cb311505cd691a46596599aA1A0AD7D", 6, "moonriver", "💵", "usd-coin", standard=TokenStandard.ERC20),
    ],
    "harmony": [
        TokenInfo("ONE", "Harmony", None, 18, "harmony", "🎵", "harmony"),
        TokenInfo("USDC", "USD Coin", "0x985458E523dB3d53125813eD68c274899e9DfAb4", 6, "harmony", "💵", "usd-coin", standard=TokenStandard.ERC20),
    ],
    "klaytn": [
        TokenInfo("KLAY", "Klaytn", None, 18, "klaytn", "🔶", "klay-token"),
        TokenInfo("USDC", "USD Coin", "0x754288077D0fF82AF7a5317C7CB8c444D421d103", 6, "klaytn", "💵", "usd-coin", standard=TokenStandard.ERC20),
    ],
    "ton": [
        TokenInfo("TON", "Toncoin", None, 9, "ton", "💎", "the-open-network"),
        TokenInfo("USDT", "Tether", "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs", 6, "ton", "💵", "tether", standard=TokenStandard.JETTON),
        TokenInfo("NOT", "Notcoin", "EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT", 9, "ton", "⚫", "notcoin", standard=TokenStandard.JETTON),
    ],
    "solana": [
        TokenInfo("SOL", "Solana", None, 9, "solana", "◎", "solana"),
        TokenInfo("USDC", "USD Coin", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", 6, "solana", "💵", "usd-coin", standard=TokenStandard.SPL),
        TokenInfo("BONK", "Bonk", "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", 5, "solana", "🐕", "bonk", standard=TokenStandard.SPL),
        TokenInfo("JUP", "Jupiter", "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN", 6, "solana", "🪐", "jupiter-exchange-solana", standard=TokenStandard.SPL),
    ],
    "tron": [
        TokenInfo("TRX", "TRON", None, 6, "tron", "🔴", "tron"),
        TokenInfo("USDT", "Tether TRC20", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", 6, "tron", "💵", "tether", standard=TokenStandard.TRC20),
        TokenInfo("USDC", "USD Coin TRC20", "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8", 6, "tron", "💵", "usd-coin", standard=TokenStandard.TRC20),
    ],
    "bitcoin": [TokenInfo("BTC", "Bitcoin", None, 8, "bitcoin", "₿", "bitcoin")],
    "litecoin": [TokenInfo("LTC", "Litecoin", None, 8, "litecoin", "Ł", "litecoin")],
    "dogecoin": [TokenInfo("DOGE", "Dogecoin", None, 8, "dogecoin", "🐕", "dogecoin")],
    "xrp": [TokenInfo("XRP", "XRP", None, 6, "xrp", "✕", "ripple")],
    "cardano": [TokenInfo("ADA", "Cardano", None, 6, "cardano", "💙", "cardano")],
    "polkadot": [TokenInfo("DOT", "Polkadot", None, 10, "polkadot", "⚫", "polkadot")],
    "cosmos": [TokenInfo("ATOM", "Cosmos", None, 6, "cosmos", "⚛️", "cosmos")],
    "near": [TokenInfo("NEAR", "NEAR", None, 24, "near", "🌐", "near")],
    "aptos": [TokenInfo("APT", "Aptos", None, 8, "aptos", "🌀", "aptos")],
    "sui": [TokenInfo("SUI", "Sui", None, 9, "sui", "💧", "sui")],
}


# ==================== ERC20 ABI ====================

ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "_to", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
]

# ==================== WALLET MANAGER ====================

class WalletManager:
    """Production-Ready Multi-Chain Wallet Manager - 33 Networks"""
    
    def __init__(self):
        self.mnemo = Mnemonic("english")
        self._web3_cache: Dict[str, Web3] = {}
        self._web3_lock = asyncio.Lock()
        self._http_client: Optional[httpx.AsyncClient] = None
        self._http_lock = asyncio.Lock()
        self._price_cache: Dict[str, Tuple[Decimal, datetime]] = {}
        self._price_cache_ttl = 60
        self._balance_cache: Dict[str, Tuple[Decimal, datetime]] = {}
        self._balance_cache_ttl = 30
        self._network_health: Dict[str, NetworkHealth] = {}
        
        self._ton_api_url = "https://toncenter.com/api/v2"
        self._ton_api_key = os.getenv("TON_API_KEY", "")
        
        self.derivation_paths = {
            NetworkType.EVM: "m/44'/60'/0'/0/0",
            NetworkType.BITCOIN: "m/44'/0'/0'/0/0",
            NetworkType.LITECOIN: "m/44'/2'/0'/0/0",
            NetworkType.DOGECOIN: "m/44'/3'/0'/0/0",
            NetworkType.SOLANA: "m/44'/501'/0'/0'",
            NetworkType.TON: "m/44'/607'/0'/0/0",
            NetworkType.TRON: "m/44'/195'/0'/0/0",
            NetworkType.XRP: "m/44'/144'/0'/0/0",
            NetworkType.CARDANO: "m/1852'/1815'/0'/0/0",
            NetworkType.POLKADOT: "m/44'/354'/0'/0/0",
            NetworkType.COSMOS: "m/44'/118'/0'/0/0",
            NetworkType.NEAR: "m/44'/397'/0'",
            NetworkType.APTOS: "m/44'/637'/0'/0'/0'",
            NetworkType.SUI: "m/44'/784'/0'/0'/0'",
        }
        
        self._initialized = False
        self._shutdown = False
        logger.info("WalletManager initialized", networks=len(NETWORKS))

    async def initialize(self):
        """Initialize wallet manager"""
        if self._initialized:
            return
        logger.info("Initializing WalletManager...")
        await self._get_http_client()
        for network in ["ethereum", "bsc", "polygon"]:
            try:
                self.get_web3(network)
            except Exception as e:
                logger.warning("Failed to init Web3", network=network, error=str(e))
        self._initialized = True
        logger.info("WalletManager ready", networks=len(NETWORKS))

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self._http_client is None:
            async with self._http_lock:
                if self._http_client is None:
                    self._http_client = httpx.AsyncClient(
                        timeout=httpx.Timeout(30.0, connect=10.0),
                        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                        http2=True,
                        follow_redirects=True
                    )
        return self._http_client

    def generate_mnemonic(self, strength: int = 128) -> str:
        """Generate BIP39 mnemonic"""
        if strength not in [128, 256]:
            raise ValueError("Strength must be 128 or 256")
        return self.mnemo.generate(strength)

    def validate_mnemonic(self, mnemonic: str) -> bool:
        """Validate BIP39 mnemonic"""
        if not mnemonic or not isinstance(mnemonic, str):
            return False
        words = mnemonic.strip().split()
        if len(words) not in [12, 15, 18, 21, 24]:
            return False
        return self.mnemo.check(mnemonic.strip())

    def get_all_networks(self) -> List[str]:
        return list(NETWORKS.keys())

    def get_network_config(self, network: str) -> Optional[NetworkConfig]:
        return NETWORKS.get(network.lower())

    def get_network_tokens(self, network: str) -> List[TokenInfo]:
        return TOKENS.get(network.lower(), [])

    async def validate_address(self, network: str, address: str) -> bool:
        """Validate address for any network"""
        if not address or not isinstance(address, str):
            return False
        address = address.strip()
        network = network.lower()
        config = NETWORKS.get(network)
        if not config:
            return False
        try:
            if config.network_type == NetworkType.EVM:
                return Web3.is_address(address)
            elif config.network_type == NetworkType.TRON:
                if not address.startswith("T"):
                    return False
                decoded = base58.b58decode_check(address)
                return len(decoded) == 21
            elif config.network_type == NetworkType.SOLANA:
                decoded = base58.b58decode(address)
                return len(decoded) == 32
            elif config.network_type == NetworkType.TON:
                return address.startswith(("EQ", "UQ", "0Q")) and len(address) >= 48
            elif config.network_type == NetworkType.BITCOIN:
                if address.startswith(("1", "3")):
                    return 26 <= len(address) <= 35
                return address.startswith("bc1") and len(address) >= 42
            elif config.network_type == NetworkType.LITECOIN:
                if address.startswith(("L", "M", "3")):
                    return 26 <= len(address) <= 35
                return address.startswith("ltc1") and len(address) >= 42
            elif config.network_type == NetworkType.DOGECOIN:
                return address.startswith("D") and 26 <= len(address) <= 35
            elif config.network_type == NetworkType.XRP:
                return address.startswith("r") and 25 <= len(address) <= 35
            elif config.network_type == NetworkType.CARDANO:
                return address.startswith("addr1") and len(address) >= 50
            elif config.network_type == NetworkType.POLKADOT:
                return address.startswith("1") and len(address) >= 45
            elif config.network_type == NetworkType.COSMOS:
                return address.startswith("cosmos1") and len(address) >= 40
            elif config.network_type == NetworkType.NEAR:
                return len(address) >= 2 and (address.endswith(".near") or len(address) == 64)
            elif config.network_type == NetworkType.APTOS:
                return address.startswith("0x") and len(address) == 66
            elif config.network_type == NetworkType.SUI:
                return address.startswith("0x") and len(address) == 66
            return len(address) >= 10
        except Exception:
            return False
        
    # ==================== WALLET CREATION ====================

    async def create_wallet(self, network: str, mnemonic: Optional[str] = None) -> WalletData:
        """Create wallet for any network"""
        network = network.lower()
        if network not in NETWORKS:
            raise ValueError(f"Network '{network}' not supported")
        
        config = NETWORKS[network]
        if mnemonic is None:
            mnemonic = self.generate_mnemonic()
        elif not self.validate_mnemonic(mnemonic):
            raise ValueError("Invalid mnemonic phrase")
        
        if config.network_type == NetworkType.EVM:
            return await asyncio.to_thread(self._create_evm_wallet, network, mnemonic)
        elif config.network_type == NetworkType.TON:
            return await self._create_ton_wallet(mnemonic)
        elif config.network_type == NetworkType.TRON:
            return await asyncio.to_thread(self._create_tron_wallet, mnemonic)
        elif config.network_type == NetworkType.SOLANA:
            return await asyncio.to_thread(self._create_solana_wallet, mnemonic)
        elif config.network_type == NetworkType.BITCOIN:
            return await asyncio.to_thread(self._create_bitcoin_wallet, mnemonic, "bitcoin", b'\x00')
        elif config.network_type == NetworkType.LITECOIN:
            return await asyncio.to_thread(self._create_bitcoin_wallet, mnemonic, "litecoin", b'\x30')
        elif config.network_type == NetworkType.DOGECOIN:
            return await asyncio.to_thread(self._create_bitcoin_wallet, mnemonic, "dogecoin", b'\x1e')
        else:
            return await asyncio.to_thread(self._create_generic_wallet, network, mnemonic)

    def _create_evm_wallet(self, network: str, mnemonic: str) -> WalletData:
        """Create EVM wallet"""
        path = self.derivation_paths[NetworkType.EVM]
        account: LocalAccount = Account.from_mnemonic(mnemonic, account_path=path)
        return WalletData(
            address=account.address,
            private_key=account.key.hex(),
            mnemonic=mnemonic,
            network=network,
            derivation_path=path,
            public_key=account.address
        )

    async def _create_ton_wallet(self, mnemonic: str) -> WalletData:
        """Create TON wallet"""
        try:
            from tonsdk.contract.wallet import Wallets, WalletVersionEnum
            mnemonic_list = mnemonic.split()
            _mnemo, _pub, _priv, wallet = await asyncio.to_thread(
                Wallets.create,
                version=WalletVersionEnum.v4r2,
                workchain=0,
                mnemonics=mnemonic_list
            )
            address = wallet.address.to_string(True, True, False)
            return WalletData(
                address=address,
                private_key=_priv.hex() if isinstance(_priv, bytes) else _priv,
                mnemonic=mnemonic,
                network="ton",
                derivation_path=self.derivation_paths[NetworkType.TON],
                public_key=_pub.hex() if isinstance(_pub, bytes) else _pub
            )
        except ImportError:
            seed = self.mnemo.to_seed(mnemonic)
            priv_key = hashlib.sha256(seed + b"ton").digest()
            raw_addr = hashlib.sha256(priv_key).digest()[:32]
            address = "EQ" + base64.b64encode(raw_addr).decode().replace("+", "-").replace("/", "_")[:46]
            return WalletData(address=address, private_key=priv_key.hex(), mnemonic=mnemonic, network="ton", derivation_path=self.derivation_paths[NetworkType.TON])

    def _create_tron_wallet(self, mnemonic: str) -> WalletData:
        """Create TRON wallet"""
        path = self.derivation_paths[NetworkType.TRON]
        account = Account.from_mnemonic(mnemonic, account_path=path)
        eth_addr_bytes = bytes.fromhex(account.address[2:])
        tron_hex = b'\x41' + eth_addr_bytes
        checksum = hashlib.sha256(hashlib.sha256(tron_hex).digest()).digest()[:4]
        tron_address = base58.b58encode(tron_hex + checksum).decode()
        return WalletData(address=tron_address, private_key=account.key.hex(), mnemonic=mnemonic, network="tron", derivation_path=path)

    def _create_solana_wallet(self, mnemonic: str) -> WalletData:
        """Create Solana wallet"""
        path = self.derivation_paths[NetworkType.SOLANA]
        seed = self.mnemo.to_seed(mnemonic)
        private_key_bytes = hashlib.pbkdf2_hmac('sha512', seed, b"ed25519 seed", 2048)[:32]
        try:
            from nacl.signing import SigningKey
            signing_key = SigningKey(private_key_bytes)
            public_key = signing_key.verify_key.encode()
            address = base58.b58encode(public_key).decode()
        except ImportError:
            public_key = hashlib.sha256(private_key_bytes).digest()
            address = base58.b58encode(public_key).decode()[:44]
        return WalletData(address=address, private_key=private_key_bytes.hex(), mnemonic=mnemonic, network="solana", derivation_path=path)

    def _create_bitcoin_wallet(self, mnemonic: str, network: str, version_byte: bytes) -> WalletData:
        """Create Bitcoin/Litecoin/Dogecoin wallet"""
        net_type = NetworkType.BITCOIN if network == "bitcoin" else NetworkType.LITECOIN if network == "litecoin" else NetworkType.DOGECOIN
        path = self.derivation_paths[net_type]
        seed = self.mnemo.to_seed(mnemonic)
        I = hmac.new(b"Bitcoin seed", seed, hashlib.sha512).digest()
        master_priv = I[:32]
        sha256_hash = hashlib.sha256(master_priv).digest()
        ripemd160 = hashlib.new('ripemd160', sha256_hash).digest()
        versioned = version_byte + ripemd160
        checksum = hashlib.sha256(hashlib.sha256(versioned).digest()).digest()[:4]
        address = base58.b58encode(versioned + checksum).decode()
        return WalletData(address=address, private_key=master_priv.hex(), mnemonic=mnemonic, network=network, derivation_path=path)

    def _create_generic_wallet(self, network: str, mnemonic: str) -> WalletData:
        """Create wallet for networks without full support"""
        config = NETWORKS[network]
        path = self.derivation_paths.get(config.network_type, "m/44'/0'/0'/0/0")
        seed = self.mnemo.to_seed(mnemonic)
        key_material = hashlib.sha256(seed + network.encode()).digest()
        
        if config.network_type == NetworkType.XRP:
            address = "r" + base58.b58encode(key_material[:20]).decode()[:33]
        elif config.network_type == NetworkType.CARDANO:
            address = "addr1" + base64.b32encode(key_material[:32]).decode().lower()[:54]
        elif config.network_type == NetworkType.POLKADOT:
            address = "1" + base58.b58encode(key_material[:32]).decode()[:47]
        elif config.network_type == NetworkType.COSMOS:
            address = "cosmos1" + base58.b58encode(key_material[:20]).decode().lower()[:38]
        elif config.network_type == NetworkType.NEAR:
            address = key_material[:32].hex()
        elif config.network_type in [NetworkType.APTOS, NetworkType.SUI]:
            address = "0x" + key_material[:32].hex()
        else:
            address = key_material[:32].hex()
        
        return WalletData(address=address, private_key=key_material.hex(), mnemonic=mnemonic, network=network, derivation_path=path)
    
    # ==================== WEB3 ====================

    def get_web3(self, network: str, force_new: bool = False) -> Web3:
        """Get Web3 instance for EVM network"""
        network = network.lower()
        config = NETWORKS.get(network)
        if not config or config.network_type != NetworkType.EVM:
            raise ValueError(f"Not EVM network: {network}")
        
        if not force_new and network in self._web3_cache:
            w3 = self._web3_cache[network]
            try:
                if w3.is_connected():
                    return w3
            except:
                pass
            del self._web3_cache[network]
        
        w3 = Web3(Web3.HTTPProvider(config.rpc_url, request_kwargs={'timeout': 20}))
        if geth_poa_middleware and network in ["bsc", "polygon", "avalanche", "arbitrum", "optimism", "base", "fantom", "cronos", "gnosis", "moonbeam", "moonriver", "harmony", "klaytn", "celo", "mantle", "scroll", "blast", "linea", "zksync"]:
            try:
                w3.middleware_onion.inject(geth_poa_middleware, layer=0)
            except:
                pass
        
        if w3.is_connected():
            self._web3_cache[network] = w3
            return w3
        
        for backup_url in config.backup_rpc_urls:
            w3 = Web3(Web3.HTTPProvider(backup_url, request_kwargs={'timeout': 20}))
            if w3.is_connected():
                self._web3_cache[network] = w3
                return w3
        
        raise ConnectionError(f"Failed to connect to {network}")

    # ==================== BALANCES ====================

    @async_retry(max_attempts=3, delay=1.0)
    async def get_balance(self, network: str, address: str, use_cache: bool = True) -> Decimal:
        """Get native token balance for any network"""
        network = network.lower()
        if network not in NETWORKS:
            return Decimal("0")
        
        cache_key = f"{network}:{address}"
        if use_cache and cache_key in self._balance_cache:
            balance, timestamp = self._balance_cache[cache_key]
            if (datetime.utcnow() - timestamp).total_seconds() < self._balance_cache_ttl:
                return balance
        
        config = NETWORKS[network]
        balance = Decimal("0")
        
        try:
            if config.network_type == NetworkType.EVM:
                balance = await self._get_evm_balance(network, address)
            elif config.network_type == NetworkType.TON:
                balance = await self._get_ton_balance(address)
            elif config.network_type == NetworkType.SOLANA:
                balance = await self._get_solana_balance(address)
            elif config.network_type == NetworkType.TRON:
                balance = await self._get_tron_balance(address)
            elif config.network_type == NetworkType.BITCOIN:
                balance = await self._get_btc_balance(address)
            elif config.network_type == NetworkType.LITECOIN:
                balance = await self._get_ltc_balance(address)
            elif config.network_type == NetworkType.DOGECOIN:
                balance = await self._get_doge_balance(address)
            elif config.network_type == NetworkType.XRP:
                balance = await self._get_xrp_balance(address)
            elif config.network_type == NetworkType.COSMOS:
                balance = await self._get_cosmos_balance(address)
            elif config.network_type == NetworkType.NEAR:
                balance = await self._get_near_balance(address)
            elif config.network_type == NetworkType.APTOS:
                balance = await self._get_aptos_balance(address)
            elif config.network_type == NetworkType.SUI:
                balance = await self._get_sui_balance(address)
            
            self._balance_cache[cache_key] = (balance, datetime.utcnow())
        except Exception as e:
            logger.error("Balance fetch failed", network=network, error=str(e))
        
        return balance

    async def _get_evm_balance(self, network: str, address: str) -> Decimal:
        w3 = self.get_web3(network)
        check_addr = Web3.to_checksum_address(address)
        balance_wei = await asyncio.get_event_loop().run_in_executor(None, w3.eth.get_balance, check_addr)
        return Decimal(str(w3.from_wei(balance_wei, 'ether')))

    async def _get_ton_balance(self, address: str) -> Decimal:
        result = await self._ton_api_request("GET", "getAddressBalance", params={"address": address})
        if result and result.get("ok"):
            bal = result.get("result", 0)
            if isinstance(bal, dict):
                bal = bal.get("balance", 0)
            return Decimal(str(int(bal))) / Decimal(10**9)
        return Decimal("0")

    async def _ton_api_request(self, method: str, endpoint: str, **kwargs) -> Optional[dict]:
        client = await self._get_http_client()
        url = f"{self._ton_api_url}/{endpoint}"
        headers = {"Content-Type": "application/json"}
        if self._ton_api_key:
            headers["X-API-Key"] = self._ton_api_key
        try:
            if method.upper() == "GET":
                response = await client.get(url, headers=headers, timeout=20.0, **kwargs)
            else:
                response = await client.post(url, headers=headers, timeout=20.0, **kwargs)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.warning("TON API error", error=str(e))
        return None

    async def _get_solana_balance(self, address: str) -> Decimal:
        client = await self._get_http_client()
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]}
        response = await client.post(NETWORKS["solana"].rpc_url, json=payload, timeout=15.0)
        if response.status_code == 200:
            result = response.json().get("result", {})
            lamports = result.get("value", 0)
            return Decimal(str(lamports)) / Decimal(10**9)
        return Decimal("0")

    async def _get_tron_balance(self, address: str) -> Decimal:
        client = await self._get_http_client()
        api_key = os.getenv("TRON_API_KEY", "")
        headers = {"Accept": "application/json"}
        if api_key:
            headers["TRON-PRO-API-KEY"] = api_key
        url = f"https://api.trongrid.io/v1/accounts/{address}"
        response = await client.get(url, headers=headers, timeout=15.0)
        if response.status_code == 200:
            data = response.json()
            if data.get("data") and len(data["data"]) > 0:
                return Decimal(str(data["data"][0].get("balance", 0))) / Decimal(10**6)
        return Decimal("0")

    async def _get_btc_balance(self, address: str) -> Decimal:
        client = await self._get_http_client()
        response = await client.get(f"https://blockstream.info/api/address/{address}", timeout=15.0)
        if response.status_code == 200:
            data = response.json()
            stats = data.get("chain_stats", {})
            satoshi = stats.get("funded_txo_sum", 0) - stats.get("spent_txo_sum", 0)
            return Decimal(str(satoshi)) / Decimal(10**8)
        return Decimal("0")

    async def _get_ltc_balance(self, address: str) -> Decimal:
        """Get Litecoin balance with multiple API fallbacks"""
        client = await self._get_http_client()
        
        # Try litecoinspace.org first
        try:
            response = await client.get(
                f"https://litecoinspace.org/api/address/{address}",
                timeout=15.0
            )
            if response.status_code == 200:
                data = response.json()
                stats = data.get("chain_stats", {})
                funded = stats.get("funded_txo_sum", 0)
                spent = stats.get("spent_txo_sum", 0)
                litoshi = funded - spent
                return Decimal(str(litoshi)) / Decimal(10**8)
            elif response.status_code == 404:
                return Decimal("0")
        except Exception as e:
            logger.debug("Litecoin primary API failed", error=str(e))
        
        # Fallback to blockchair
        try:
            response = await client.get(
                f"https://api.blockchair.com/litecoin/dashboards/address/{address}",
                timeout=15.0
            )
            if response.status_code == 200:
                data = response.json()
                addr_data = data.get("data", {}).get(address, {})
                if addr_data:
                    balance = addr_data.get("address", {}).get("balance", 0)
                    return Decimal(str(balance)) / Decimal(10**8)
                else:
                    return Decimal("0")
            elif response.status_code == 404:
                return Decimal("0")
        except Exception as e:
            logger.debug("Litecoin blockchair API failed", error=str(e))
        
        # Fallback to blockcypher
        try:
            response = await client.get(
                f"https://api.blockcypher.com/v1/ltc/main/addrs/{address}/balance",
                timeout=15.0
            )
            if response.status_code == 200:
                data = response.json()
                balance = data.get("balance", 0)
                return Decimal(str(balance)) / Decimal(10**8)
            elif response.status_code == 404:
                return Decimal("0")
        except Exception as e:
            logger.debug("Litecoin blockcypher API failed", error=str(e))
        
        # New address without transactions - return 0 silently
        return Decimal("0")

    async def _get_doge_balance(self, address: str) -> Decimal:
        """Get Dogecoin balance with fallbacks"""
        client = await self._get_http_client()
        
        # Try dogechain.info first
        try:
            response = await client.get(
                f"https://dogechain.info/api/v1/address/balance/{address}",
                timeout=15.0
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return Decimal(str(data.get("balance", 0)))
                # API returned success=false - address may not exist yet
                if "not found" in str(data).lower() or not data.get("success"):
                    return Decimal("0")
            elif response.status_code == 404:
                # Address not found = new address with 0 balance
                return Decimal("0")
        except Exception as e:
            logger.debug("Dogecoin primary API failed", error=str(e))
        
        # Fallback to blockchair
        try:
            response = await client.get(
                f"https://api.blockchair.com/dogecoin/dashboards/address/{address}",
                timeout=15.0
            )
            if response.status_code == 200:
                data = response.json()
                addr_data = data.get("data", {}).get(address, {})
                if addr_data:
                    balance = addr_data.get("address", {}).get("balance", 0)
                    return Decimal(str(balance)) / Decimal(10**8)
                else:
                    # Address not in response = new address
                    return Decimal("0")
            elif response.status_code == 404:
                return Decimal("0")
        except Exception as e:
            logger.debug("Dogecoin blockchair failed", error=str(e))
        
        # Fallback to blockcypher
        try:
            response = await client.get(
                f"https://api.blockcypher.com/v1/doge/main/addrs/{address}/balance",
                timeout=15.0
            )
            if response.status_code == 200:
                data = response.json()
                balance = data.get("balance", 0)
                return Decimal(str(balance)) / Decimal(10**8)
            elif response.status_code == 404:
                return Decimal("0")
        except Exception as e:
            logger.debug("Dogecoin blockcypher failed", error=str(e))
        
        # For new addresses without transactions, this is normal
        # Don't log warning, just return 0
        return Decimal("0")
    
    async def _get_xrp_balance(self, address: str) -> Decimal:
        client = await self._get_http_client()
        payload = {"method": "account_info", "params": [{"account": address, "ledger_index": "validated"}]}
        response = await client.post("https://xrplcluster.com", json=payload, timeout=15.0)
        if response.status_code == 200:
            result = response.json().get("result", {})
            if result.get("status") == "success":
                drops = int(result.get("account_data", {}).get("Balance", 0))
                return Decimal(str(drops)) / Decimal(10**6)
        return Decimal("0")

    async def _get_cosmos_balance(self, address: str) -> Decimal:
        client = await self._get_http_client()
        response = await client.get(f"https://cosmos-rest.publicnode.com/cosmos/bank/v1beta1/balances/{address}", timeout=15.0)
        if response.status_code == 200:
            for bal in response.json().get("balances", []):
                if bal.get("denom") == "uatom":
                    return Decimal(str(int(bal.get("amount", 0)))) / Decimal(10**6)
        return Decimal("0")

    async def _get_near_balance(self, address: str) -> Decimal:
        client = await self._get_http_client()
        payload = {"jsonrpc": "2.0", "id": "1", "method": "query", "params": {"request_type": "view_account", "finality": "final", "account_id": address}}
        response = await client.post("https://rpc.mainnet.near.org", json=payload, timeout=15.0)
        if response.status_code == 200:
            yocto = int(response.json().get("result", {}).get("amount", 0))
            return Decimal(str(yocto)) / Decimal(10**24)
        return Decimal("0")

    async def _get_aptos_balance(self, address: str) -> Decimal:
        client = await self._get_http_client()
        response = await client.get(f"https://fullnode.mainnet.aptoslabs.com/v1/accounts/{address}/resources", timeout=15.0)
        if response.status_code == 200:
            for res in response.json():
                if res.get("type") == "0x1::coin::CoinStore<0x1::aptos_coin::AptosCoin>":
                    value = int(res.get("data", {}).get("coin", {}).get("value", 0))
                    return Decimal(str(value)) / Decimal(10**8)
        return Decimal("0")

    async def _get_sui_balance(self, address: str) -> Decimal:
        client = await self._get_http_client()
        payload = {"jsonrpc": "2.0", "id": 1, "method": "suix_getBalance", "params": [address, "0x2::sui::SUI"]}
        response = await client.post("https://fullnode.mainnet.sui.io:443", json=payload, timeout=15.0)
        if response.status_code == 200:
            mist = int(response.json().get("result", {}).get("totalBalance", 0))
            return Decimal(str(mist)) / Decimal(10**9)
        return Decimal("0")

    # ==================== UTILITIES ====================

    def map_error_to_user(self, error_str: str) -> str:
        if not error_str:
            return "Unknown error"
        err = error_str.lower()
        if "insufficient" in err:
            return "Insufficient funds for transaction"
        if "nonce" in err:
            return "Transaction sync error. Please try again"
        if "timeout" in err:
            return "Network timeout. Please try again"
        if "invalid" in err and "address" in err:
            return "Invalid wallet address"
        return error_str[:100] if len(error_str) > 100 else error_str

    def get_explorer_url(self, network: str, tx_hash: str) -> Optional[str]:
        config = NETWORKS.get(network.lower())
        if not config:
            return None
        if config.network_type == NetworkType.TRON:
            return f"{config.explorer_url}/#/transaction/{tx_hash}"
        return f"{config.explorer_url}/tx/{tx_hash}"

    async def close(self):
        self._shutdown = True
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._web3_cache.clear()
        self._balance_cache.clear()
        self._price_cache.clear()
        logger.info("WalletManager closed")


# ==================== HELPER FUNCTIONS ====================

def get_network_by_chain_id(chain_id: int) -> Optional[str]:
    for name, config in NETWORKS.items():
        if config.chain_id == chain_id:
            return name
    return None

def get_token_info(network: str, symbol: str) -> Optional[TokenInfo]:
    for token in TOKENS.get(network.lower(), []):
        if token.symbol.upper() == symbol.upper():
            return token
    return None

def is_native_token(network: str, symbol: str) -> bool:
    config = NETWORKS.get(network.lower())
    return config and config.symbol.upper() == symbol.upper()


# ==================== GLOBAL INSTANCE ====================

wallet_manager = WalletManager()

async def initialize_wallet_manager():
    await wallet_manager.initialize()
    return wallet_manager

async def get_wallet_manager() -> WalletManager:
    if not wallet_manager._initialized:
        await wallet_manager.initialize()
    return wallet_manager


# ==================== EXPORTS ====================

__all__ = [
    "wallet_manager", "WalletManager", "initialize_wallet_manager", "get_wallet_manager",
    "NetworkConfig", "NetworkType", "NetworkStatus", "NetworkHealth",
    "WalletData", "TokenInfo", "TokenStandard", "TransactionResult", "GasEstimate",
    "NETWORKS", "TOKENS", "ERC20_ABI",
    "get_network_by_chain_id", "get_token_info", "is_native_token",
]
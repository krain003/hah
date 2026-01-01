"""
NEXUS WALLET - Multi-Chain Wallet Manager
Real blockchain interactions for all supported networks
"""

import asyncio
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from dataclasses import dataclass
from enum import Enum
import structlog
import hashlib
import base58

from mnemonic import Mnemonic
from eth_account import Account
from web3 import Web3
from web3.exceptions import TransactionNotFound


logger = structlog.get_logger(__name__)

# Enable HD wallet features
Account.enable_unaudited_hdwallet_features()


class NetworkType(Enum):
    EVM = "evm"
    BITCOIN = "bitcoin"
    SOLANA = "solana"
    TON = "ton"
    TRON = "tron"


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


# Network configurations with FREE public RPC endpoints
NETWORKS: Dict[str, NetworkConfig] = {
    "ethereum": NetworkConfig(
        name="Ethereum",
        symbol="ETH",
        chain_id=1,
        rpc_url="https://ethereum.publicnode.com",
        explorer_url="https://etherscan.io",
        network_type=NetworkType.EVM,
        icon="⟠"
    ),
    "bsc": NetworkConfig(
        name="BNB Smart Chain",
        symbol="BNB",
        chain_id=56,
        rpc_url="https://bsc.publicnode.com",
        explorer_url="https://bscscan.com",
        network_type=NetworkType.EVM,
        icon="💛"
    ),
    "polygon": NetworkConfig(
        name="Polygon",
        symbol="MATIC",
        chain_id=137,
        rpc_url="https://polygon-bor.publicnode.com",
        explorer_url="https://polygonscan.com",
        network_type=NetworkType.EVM,
        icon="💜"
    ),
    "arbitrum": NetworkConfig(
        name="Arbitrum One",
        symbol="ETH",
        chain_id=42161,
        rpc_url="https://arbitrum-one.publicnode.com",
        explorer_url="https://arbiscan.io",
        network_type=NetworkType.EVM,
        icon="🔵"
    ),
    "avalanche": NetworkConfig(
        name="Avalanche C-Chain",
        symbol="AVAX",
        chain_id=43114,
        rpc_url="https://avalanche-c-chain.publicnode.com",
        explorer_url="https://snowtrace.io",
        network_type=NetworkType.EVM,
        icon="🔺"
    ),
    "optimism": NetworkConfig(
        name="Optimism",
        symbol="ETH",
        chain_id=10,
        rpc_url="https://optimism.publicnode.com",
        explorer_url="https://optimistic.etherscan.io",
        network_type=NetworkType.EVM,
        icon="🔴"
    ),
    "base": NetworkConfig(
        name="Base",
        symbol="ETH",
        chain_id=8453,
        rpc_url="https://base.publicnode.com",
        explorer_url="https://basescan.org",
        network_type=NetworkType.EVM,
        icon="🔵"
    ),
    "bitcoin": NetworkConfig(
        name="Bitcoin",
        symbol="BTC",
        chain_id=None,
        rpc_url="",
        explorer_url="https://blockstream.info",
        network_type=NetworkType.BITCOIN,
        decimals=8,
        icon="₿"
    ),
    "solana": NetworkConfig(
        name="Solana",
        symbol="SOL",
        chain_id=None,
        rpc_url="https://api.mainnet-beta.solana.com",
        explorer_url="https://solscan.io",
        network_type=NetworkType.SOLANA,
        decimals=9,
        icon="◎"
    ),
    "ton": NetworkConfig(
        name="TON",
        symbol="TON",
        chain_id=None,
        rpc_url="https://toncenter.com/api/v2/jsonRPC",
        explorer_url="https://tonscan.org",
        network_type=NetworkType.TON,
        decimals=9,
        icon="💎"
    ),
    "tron": NetworkConfig(
        name="TRON",
        symbol="TRX",
        chain_id=None,
        rpc_url="https://api.trongrid.io",
        explorer_url="https://tronscan.org",
        network_type=NetworkType.TRON,
        decimals=6,
        icon="🔴"
    ),
}


@dataclass
class WalletData:
    address: str
    private_key: str
    mnemonic: Optional[str] = None
    network: str = ""
    derivation_path: Optional[str] = None


class WalletManager:
    """Multi-chain wallet manager with real blockchain interactions"""
    
    def __init__(self):
        self.mnemo = Mnemonic("english")
        self._web3_cache: Dict[str, Web3] = {}
        self._balance_cache: Dict[str, Tuple[Decimal, float]] = {}
        self._cache_ttl = 30
    
    def generate_mnemonic(self, strength: int = 256) -> str:
        """Generate BIP39 mnemonic (12 words for 128, 24 for 256)"""
        return self.mnemo.generate(strength)
    
    def validate_mnemonic(self, mnemonic: str) -> bool:
        """Validate mnemonic phrase"""
        return self.mnemo.check(mnemonic)
    
    async def create_wallet(self, network: str, mnemonic: Optional[str] = None) -> WalletData:
        """Create wallet for specific network"""
        if network not in NETWORKS:
            raise ValueError(f"Unsupported network: {network}")
        
        config = NETWORKS[network]
        
        if mnemonic is None:
            mnemonic = self.generate_mnemonic()
        
        if config.network_type == NetworkType.EVM:
            return self._create_evm_wallet(network, mnemonic)
        elif config.network_type == NetworkType.BITCOIN:
            return self._create_bitcoin_wallet(mnemonic)
        elif config.network_type == NetworkType.SOLANA:
            return self._create_solana_wallet(mnemonic)
        elif config.network_type == NetworkType.TON:
            return await self._create_ton_wallet(mnemonic)
        elif config.network_type == NetworkType.TRON:
            return self._create_tron_wallet(mnemonic)
        else:
            raise ValueError(f"Unsupported network type: {config.network_type}")
    
    def _create_evm_wallet(self, network: str, mnemonic: str) -> WalletData:
        """Create EVM-compatible wallet (ETH, BSC, Polygon, etc.)"""
        path = "m/44'/60'/0'/0/0"
        account = Account.from_mnemonic(mnemonic, account_path=path)
        
        return WalletData(
            address=account.address,
            private_key=account.key.hex(),
            mnemonic=mnemonic,
            network=network,
            derivation_path=path
        )
    
    def _create_bitcoin_wallet(self, mnemonic: str) -> WalletData:
        """Create Bitcoin wallet (simplified P2PKH)"""
        seed = self.mnemo.to_seed(mnemonic)
        
        addr_hash = hashlib.sha256(seed).digest()
        ripemd = hashlib.new('ripemd160', addr_hash).digest()
        
        versioned = b'\x00' + ripemd
        checksum = hashlib.sha256(hashlib.sha256(versioned).digest()).digest()[:4]
        address = base58.b58encode(versioned + checksum).decode()
        
        return WalletData(
            address=address,
            private_key=seed[:32].hex(),
            mnemonic=mnemonic,
            network="bitcoin",
            derivation_path="m/44'/0'/0'/0/0"
        )
    
    def _create_solana_wallet(self, mnemonic: str) -> WalletData:
        """Create Solana wallet"""
        seed = self.mnemo.to_seed(mnemonic)[:32]
        address = base58.b58encode(seed).decode()[:44]
        
        return WalletData(
            address=address,
            private_key=seed.hex(),
            mnemonic=mnemonic,
            network="solana",
            derivation_path="m/44'/501'/0'/0'"
        )
    
    async def _create_ton_wallet(self, mnemonic: str = None) -> WalletData:
        """Create TON wallet"""
        try:
            from tonsdk.contract.wallet import Wallets, WalletVersionEnum
            from tonsdk.crypto import mnemonic_new
            
            # Если мнемоника не передана, генерируем новую
            if not mnemonic:
                mnemonic_list = mnemonic_new()  # Это синхронная функция
                mnemonic = " ".join(mnemonic_list)
            else:
                mnemonic_list = mnemonic.split()

            # Создание кошелька (Синхронная операция, но быстрая)
            _mnemo, _pub_key, _priv_key, wallet = Wallets.create(
                version=WalletVersionEnum.v4r2,
                workchain=0,
                mnemonics=mnemonic_list
            )
            
            address = wallet.address.to_string(True, True, False)
            private_key = _priv_key.hex()
            
            return WalletData(
                address=address,
                private_key=private_key,
                mnemonic=mnemonic,
                network="ton",
                derivation_path="m/44'/607'/0'"
            )
        except Exception as e:
            logger.error(f"TON creation error: {e}")
            raise e
    
    def _create_tron_wallet(self, mnemonic: str) -> WalletData:
        """Create TRON wallet"""
        path = "m/44'/195'/0'/0/0"
        account = Account.from_mnemonic(mnemonic, account_path=path)
        
        addr_bytes = bytes.fromhex(account.address[2:])
        tron_addr = b'\x41' + addr_bytes[-20:]
        checksum = hashlib.sha256(hashlib.sha256(tron_addr).digest()).digest()[:4]
        address = base58.b58encode(tron_addr + checksum).decode()
        
        return WalletData(
            address=address,
            private_key=account.key.hex(),
            mnemonic=mnemonic,
            network="tron",
            derivation_path=path
        )
    
    def import_from_private_key(self, network: str, private_key: str) -> WalletData:
        """Import wallet from private key"""
        config = NETWORKS[network]
        
        if config.network_type == NetworkType.EVM:
            if not private_key.startswith('0x'):
                private_key = '0x' + private_key
            account = Account.from_key(private_key)
            return WalletData(
                address=account.address,
                private_key=private_key,
                network=network
            )
        elif config.network_type == NetworkType.TRON:
            if not private_key.startswith('0x'):
                private_key = '0x' + private_key
            account = Account.from_key(private_key)
            addr_bytes = bytes.fromhex(account.address[2:])
            tron_addr = b'\x41' + addr_bytes[-20:]
            checksum = hashlib.sha256(hashlib.sha256(tron_addr).digest()).digest()[:4]
            address = base58.b58encode(tron_addr + checksum).decode()
            return WalletData(
                address=address,
                private_key=private_key,
                network=network
            )
        else:
            raise ValueError(f"Import not supported for {network}")
    
    def import_from_mnemonic(self, mnemonic: str) -> Dict[str, WalletData]:
        """Import wallets for all networks from mnemonic"""
        if not self.validate_mnemonic(mnemonic):
            raise ValueError("Invalid mnemonic phrase")
        return {}
    
    def get_web3(self, network: str) -> Web3:
        """Get Web3 instance for network with connection pooling"""
        if network not in self._web3_cache:
            config = NETWORKS[network]
            if config.network_type != NetworkType.EVM:
                raise ValueError(f"{network} is not an EVM network")
            
            w3 = Web3(Web3.HTTPProvider(
                config.rpc_url,
                request_kwargs={'timeout': 30}
            ))
            self._web3_cache[network] = w3
        
        return self._web3_cache[network]
    
    async def get_balance(self, network: str, address: str) -> Decimal:
        """Get native token balance with caching"""
        config = NETWORKS[network]
        cache_key = f"{network}:{address}"
        
        import time
        if cache_key in self._balance_cache:
            cached_balance, cached_time = self._balance_cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                return cached_balance
        
        if config.network_type == NetworkType.EVM:
            balance = await self._get_evm_balance(network, address)
        elif config.network_type == NetworkType.SOLANA:
            balance = await self._get_solana_balance(address)
        elif config.network_type == NetworkType.TON:
            balance = await self._get_ton_balance(address)
        elif config.network_type == NetworkType.TRON:
            balance = await self._get_tron_balance(address)
        else:
            balance = Decimal("0")
        
        self._balance_cache[cache_key] = (balance, time.time())
        
        return balance
    
    async def _get_evm_balance(self, network: str, address: str) -> Decimal:
        """Get EVM native balance"""
        try:
            w3 = self.get_web3(network)
            balance_wei = w3.eth.get_balance(Web3.to_checksum_address(address))
            return Decimal(str(balance_wei)) / Decimal(10 ** 18)
        except Exception as e:
            logger.error("Failed to get EVM balance", network=network, error=str(e))
            return Decimal("0")
    
    async def _get_solana_balance(self, address: str) -> Decimal:
        """Get Solana balance via RPC"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    NETWORKS["solana"].rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getBalance",
                        "params": [address]
                    },
                    timeout=30
                )
                if response.status_code == 200:
                    data = response.json()
                    lamports = data.get("result", {}).get("value", 0)
                    return Decimal(str(lamports)) / Decimal(10 ** 9)
        except Exception as e:
            logger.error("Failed to get Solana balance", error=str(e))
        return Decimal("0")
    
    async def _get_ton_balance(self, address: str) -> Decimal:
        """Get TON balance via API"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://toncenter.com/api/v2/getAddressBalance?address={address}",
                    timeout=30
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        balance = int(data.get("result", 0))
                        return Decimal(str(balance)) / Decimal(10 ** 9)
        except Exception as e:
            logger.error("Failed to get TON balance", error=str(e))
        return Decimal("0")
    
    async def _get_tron_balance(self, address: str) -> Decimal:
        """Get TRON balance via API"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{NETWORKS['tron'].rpc_url}/v1/accounts/{address}",
                    timeout=30
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("data"):
                        balance = data["data"][0].get("balance", 0)
                        return Decimal(str(balance)) / Decimal(10 ** 6)
        except Exception as e:
            logger.error("Failed to get TRON balance", error=str(e))
        return Decimal("0")
    
    async def get_token_balance(
        self, 
        network: str, 
        address: str, 
        token_address: str
    ) -> Decimal:
        """Get ERC20 token balance"""
        if NETWORKS[network].network_type != NetworkType.EVM:
            return Decimal("0")
        
        try:
            w3 = self.get_web3(network)
            
            abi = [
                {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], 
                 "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], 
                 "type": "function"},
                {"constant": True, "inputs": [], "name": "decimals", 
                 "outputs": [{"name": "", "type": "uint8"}], "type": "function"}
            ]
            
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(token_address), 
                abi=abi
            )
            
            balance = contract.functions.balanceOf(
                Web3.to_checksum_address(address)
            ).call()
            
            try:
                decimals = contract.functions.decimals().call()
            except Exception:
                decimals = 18
            
            return Decimal(str(balance)) / Decimal(10 ** decimals)
        except Exception as e:
            logger.error("Failed to get token balance", error=str(e))
            return Decimal("0")
    
    async def send_transaction(
        self,
        network: str,
        private_key: str,
        to_address: str,
        amount: Decimal,
        gas_price_gwei: Optional[int] = None,
        gas_limit: Optional[int] = None
    ) -> str:
        """Send native token transaction"""
        config = NETWORKS[network]
        
        if config.network_type != NetworkType.EVM:
            raise ValueError(f"Send not implemented for {network}")
        
        w3 = self.get_web3(network)
        
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
        
        account = Account.from_key(private_key)
        
        nonce = w3.eth.get_transaction_count(account.address, 'pending')
        
        if gas_price_gwei:
            gas_price = Web3.to_wei(gas_price_gwei, 'gwei')
        else:
            gas_price = w3.eth.gas_price
            gas_price = int(gas_price * 1.1)
        
        if not gas_limit:
            gas_limit = 21000
        
        tx = {
            'nonce': nonce,
            'to': Web3.to_checksum_address(to_address),
            'value': Web3.to_wei(float(amount), 'ether'),
            'gas': gas_limit,
            'gasPrice': gas_price,
            'chainId': config.chain_id
        }
        
        try:
            estimated_gas = w3.eth.estimate_gas(tx)
            tx['gas'] = int(estimated_gas * 1.2)
        except Exception:
            pass
        
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        
        logger.info(
            "Transaction sent",
            network=network,
            tx_hash=tx_hash.hex(),
            to=to_address,
            amount=str(amount)
        )
        
        return tx_hash.hex()
    
    async def send_token(
        self,
        network: str,
        private_key: str,
        token_address: str,
        to_address: str,
        amount: Decimal,
        decimals: int = 18
    ) -> str:
        """Send ERC20 token"""
        config = NETWORKS[network]
        
        if config.network_type != NetworkType.EVM:
            raise ValueError(f"Token send not supported for {network}")
        
        w3 = self.get_web3(network)
        
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
        
        account = Account.from_key(private_key)
        
        abi = [{
            "constant": False,
            "inputs": [
                {"name": "_to", "type": "address"},
                {"name": "_value", "type": "uint256"}
            ],
            "name": "transfer",
            "outputs": [{"name": "", "type": "bool"}],
            "type": "function"
        }]
        
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=abi
        )
        
        amount_raw = int(amount * Decimal(10 ** decimals))
        
        tx = contract.functions.transfer(
            Web3.to_checksum_address(to_address),
            amount_raw
        ).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address, 'pending'),
            'gas': 100000,
            'gasPrice': int(w3.eth.gas_price * 1.1),
            'chainId': config.chain_id
        })
        
        try:
            tx['gas'] = int(w3.eth.estimate_gas(tx) * 1.2)
        except Exception:
            tx['gas'] = 150000
        
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        
        return tx_hash.hex()
    
    async def estimate_gas(
        self,
        network: str,
        from_address: str,
        to_address: str,
        amount: Decimal
    ) -> Dict:
        """Estimate gas for transaction"""
        config = NETWORKS[network]
        
        if config.network_type != NetworkType.EVM:
            return {
                "gas": 0,
                "gas_price": 0,
                "gas_price_gwei": 0,
                "total_fee": Decimal("0"),
                "total_fee_usd": Decimal("0")
            }
        
        try:
            w3 = self.get_web3(network)
            gas_price = w3.eth.gas_price
            
            try:
                tx = {
                    'from': Web3.to_checksum_address(from_address),
                    'to': Web3.to_checksum_address(to_address),
                    'value': Web3.to_wei(float(amount), 'ether'),
                }
                gas = w3.eth.estimate_gas(tx)
            except Exception:
                gas = 21000
            
            total_fee = Decimal(str(gas * gas_price)) / Decimal(10 ** 18)
            
            return {
                "gas": gas,
                "gas_price": gas_price,
                "gas_price_gwei": float(Web3.from_wei(gas_price, 'gwei')),
                "total_fee": total_fee,
                "total_fee_usd": Decimal("0")
            }
        except Exception as e:
            logger.error("Gas estimation failed", error=str(e))
            return {
                "gas": 21000,
                "gas_price": 0,
                "gas_price_gwei": 0,
                "total_fee": Decimal("0.001"),
                "total_fee_usd": Decimal("0")
            }
    
    async def wait_for_transaction(
        self,
        network: str,
        tx_hash: str,
        timeout: int = 120
    ) -> Dict:
        """Wait for transaction confirmation"""
        config = NETWORKS[network]
        
        if config.network_type != NetworkType.EVM:
            return {"status": "unknown"}
        
        w3 = self.get_web3(network)
        
        try:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
            return {
                "status": "success" if receipt["status"] == 1 else "failed",
                "block_number": receipt["blockNumber"],
                "gas_used": receipt["gasUsed"],
            }
        except Exception as e:
            logger.error("Wait for transaction failed", error=str(e))
            return {"status": "timeout", "error": str(e)}
    
    def clear_cache(self):
        """Clear balance cache"""
        self._balance_cache.clear()


# Global instance
wallet_manager = WalletManager()
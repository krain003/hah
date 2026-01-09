"""
NEXUS WALLET - Wallet Service (Production-Ready)
Enterprise-grade wallet management with multi-chain support
"""
import uuid
import asyncio
import structlog
from typing import List, Optional, Dict, Any, Tuple
from decimal import Decimal
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from blockchain.wallet_manager import wallet_manager, NETWORKS, WalletData
from database.repositories.wallet_repository import WalletRepository
from database.repositories.user_repository import UserRepository
from security.encryption_manager import encryption_manager
from database.models import Wallet, WalletBalance, User
from database.connection import db_manager

logger = structlog.get_logger(__name__)


class WalletServiceError(Exception):
    """Base exception for wallet operations"""
    pass


class InsufficientFundsError(WalletServiceError):
    """Raised when balance is not enough"""
    pass


class WalletNotFoundError(WalletServiceError):
    """Raised when wallet doesn't exist"""
    pass


class InvalidPinError(WalletServiceError):
    """Raised when PIN verification fails"""
    pass


class TransactionFailedError(WalletServiceError):
    """Raised when transaction execution fails"""
    pass


class WalletService:
    DEFAULT_NETWORKS = []
    
    AVAILABLE_NETWORKS = [
    # EVM (20)
    "ethereum", "bsc", "polygon", "arbitrum", "avalanche", 
    "optimism", "base", "fantom", "cronos", "zksync",
    "linea", "mantle", "scroll", "blast", "celo",
    "gnosis", "moonbeam", "moonriver", "harmony", "klaytn",
    # Non-EVM (13)
    "ton", "solana", "tron", "bitcoin", "litecoin",
    "dogecoin", "xrp", "cardano", "polkadot", "cosmos",
    "near", "aptos", "sui"
]

    def __init__(self):
        self.wallet_repo = WalletRepository()
        self.user_repo = UserRepository()
        self._balance_cache: Dict[str, Tuple[Decimal, datetime]] = {}
        self._cache_ttl = 30

    async def create_initial_wallets(self, session: AsyncSession, user_id: int, pin: str, networks: Optional[List[str]] = None) -> List[Wallet]:
        """Генерирует только мнемонику, возвращает ПУСТОЙ список кошельков"""
        mnemonic = wallet_manager.generate_mnemonic(strength=128)
        encrypted_mnemonic = encryption_manager.encrypt_mnemonic(mnemonic, pin)
        
        try:
            wallet_data = await wallet_manager.create_wallet("ton", mnemonic)
            await self.wallet_repo.create(
                session=session, user_id=user_id, network="ton", 
                address=wallet_data.address, 
                encrypted_private_key=encryption_manager.encrypt_private_key(wallet_data.private_key),
                encrypted_mnemonic=encrypted_mnemonic,
                derivation_path=wallet_data.derivation_path, 
                is_imported=False, label="System Wallet"
            )
        except: 
            pass
        
        return []

    async def create_wallet_for_network(
        self,
        session: AsyncSession,
        user_id: int,
        network: str,
        pin: str = None
    ) -> Wallet:
        """
        Create a new wallet for a specific network.
        Reuses existing mnemonic if available.
        """
        if network not in NETWORKS:
            raise WalletServiceError(f"Network '{network}' is not supported")
        
        existing = await self.wallet_repo.get_user_wallet_by_network(session, user_id, network)
        if existing:
            raise WalletServiceError(f"Wallet for {network} already exists")
        
        mnemonic = None
        if pin:
            mnemonic = await self._get_user_mnemonic(session, user_id, pin)
        
        if not mnemonic:
            mnemonic = wallet_manager.generate_mnemonic(strength=128)
        
        encrypted_mnemonic = encryption_manager.encrypt_mnemonic(mnemonic, pin) if pin else None
        
        return await self._create_single_wallet(
            session=session,
            user_id=user_id,
            network=network,
            mnemonic=mnemonic,
            encrypted_mnemonic=encrypted_mnemonic,
            is_primary=False
        )

    async def create_all_network_wallets(
        self,
        session: AsyncSession,
        user_id: int,
        pin: str
    ) -> List[Wallet]:
        """Create wallets for all available networks"""
        existing_wallets = await self.wallet_repo.get_user_wallets(session, user_id)
        existing_networks = {w.network for w in existing_wallets}
        
        networks_to_create = [n for n in self.AVAILABLE_NETWORKS if n not in existing_networks]
        
        if not networks_to_create:
            return []
        
        mnemonic = await self._get_user_mnemonic(session, user_id, pin)
        if not mnemonic:
            mnemonic = wallet_manager.generate_mnemonic(strength=128)
        
        encrypted_mnemonic = encryption_manager.encrypt_mnemonic(mnemonic, pin)
        created = []
        
        for network in networks_to_create:
            try:
                wallet = await self._create_single_wallet(
                    session, user_id, network, mnemonic, encrypted_mnemonic, False
                )
                created.append(wallet)
            except Exception as e:
                logger.error("Wallet creation failed", network=network, error=str(e))
                
        return created

    async def _create_single_wallet(
        self,
        session: AsyncSession,
        user_id: int,
        network: str,
        mnemonic: str,
        encrypted_mnemonic: str,
        is_primary: bool = False
    ) -> Wallet:
        """Internal method to create a single wallet"""
        wallet_data = await wallet_manager.create_wallet(network, mnemonic)
        
        encrypted_pk = encryption_manager.encrypt_private_key(wallet_data.private_key)
        
        wallet = await self.wallet_repo.create(
            session=session,
            user_id=user_id,
            network=network,
            address=wallet_data.address,
            encrypted_private_key=encrypted_pk,
            encrypted_mnemonic=encrypted_mnemonic,
            derivation_path=wallet_data.derivation_path,
            is_imported=False,
            label=f"{NETWORKS[network].name} Wallet"
        )
        
        if is_primary:
            wallet.is_primary = True
        
        native_symbol = NETWORKS[network].symbol
        existing = await session.execute(
            select(WalletBalance).where(
                and_(
                WalletBalance.wallet_id == wallet.id,
                WalletBalance.token_symbol == native_symbol
            )
        )
    )
        if not existing.scalar_one_or_none():
            balance = WalletBalance(
            id=str(uuid.uuid4()),
            wallet_id=wallet.id,
            token_symbol=native_symbol,
            token_name=NETWORKS[network].name,
            token_decimals=NETWORKS[network].decimals,
            balance=Decimal("0"),
            locked=Decimal("0")  # ← Исправлено: locked вместо locked_balance
        )
        session.add(balance)
    
        return wallet

    # ==================== WALLET IMPORT ====================

    async def import_from_mnemonic(
        self,
        session: AsyncSession,
        user_id: int,
        mnemonic: str,
        pin: str,
        networks: Optional[List[str]] = None
    ) -> List[Wallet]:
        """Import wallets from existing mnemonic phrase"""
        if not wallet_manager.validate_mnemonic(mnemonic):
            raise WalletServiceError("Invalid mnemonic phrase")
        
        networks = networks or self.AVAILABLE_NETWORKS
        encrypted_mnemonic = encryption_manager.encrypt_mnemonic(mnemonic, pin)
        
        imported = []
        for network in networks:
            try:
                wallet_data = await wallet_manager.create_wallet(network, mnemonic)
                existing = await self.wallet_repo.get_by_address(session, wallet_data.address)
                
                if existing:
                    logger.info("Wallet already exists, skipping", address=wallet_data.address[:10])
                    continue
                
                wallet = await self._create_single_wallet(
                    session, user_id, network, mnemonic, encrypted_mnemonic, len(imported) == 0
                )
                wallet.is_imported = True
                imported.append(wallet)
                
            except Exception as e:
                logger.error("Import failed for network", network=network, error=str(e))
                
        return imported

    async def import_from_private_key(
        self,
        session: AsyncSession,
        user_id: int,
        private_key: str,
        network: str
    ) -> Wallet:
        """Import wallet from private key (no mnemonic backup available)"""
        if network not in NETWORKS:
            raise WalletServiceError(f"Network '{network}' not supported")
        
        config = NETWORKS[network]
        
        try:
            if config.network_type.value == "evm":
                from eth_account import Account
                if not private_key.startswith("0x"):
                    private_key = "0x" + private_key
                account = Account.from_key(private_key)
                address = account.address
            else:
                raise WalletServiceError(f"Private key import not supported for {network}")
        except Exception as e:
            raise WalletServiceError(f"Invalid private key: {str(e)}")
        
        existing = await self.wallet_repo.get_by_address(session, address)
        if existing:
            raise WalletServiceError("This wallet is already imported")
        
        encrypted_pk = encryption_manager.encrypt_private_key(private_key)
        
        wallet = await self.wallet_repo.create(
            session=session,
            user_id=user_id,
            network=network,
            address=address,
            encrypted_private_key=encrypted_pk,
            encrypted_mnemonic=None,
            is_imported=True,
            label=f"Imported {network.upper()}"
        )
        
        balance = WalletBalance(
            id=str(uuid.uuid4()),
            wallet_id=wallet.id,
            token_symbol=NETWORKS[network].symbol,
            token_decimals=NETWORKS[network].decimals,
            balance=Decimal("0"),
           locked=Decimal("0")
        )
        session.add(balance)
        
        return wallet

    # ==================== BALANCE OPERATIONS ====================

    async def get_user_balances(
        self,
        session: AsyncSession,
        user_id: str,
        refresh_from_blockchain: bool = False,
        refresh: bool = None
    ) -> List[Dict[str, Any]]:
        """Get all user balances from INTERNAL DATABASE."""
        from database.models import WalletBalance
        
        if refresh is not None:
            refresh_from_blockchain = refresh
        
        wallets = await self.wallet_repo.get_user_wallets(session, user_id)
        
        if not wallets:
            return []
        
        if refresh_from_blockchain:
            await self._sync_blockchain_balances(session, wallets)
        
        balances = []
        
        for wallet in wallets:
            config = NETWORKS.get(wallet.network)
            if not config:
                continue
            
            result = await session.execute(
                select(WalletBalance).where(WalletBalance.wallet_id == wallet.id)
            )
            db_balances = result.scalars().all()
            
            if db_balances:
                for bal in db_balances:
                    try:
                        from services.price_service import price_service
                        price = await price_service.get_price(bal.token_symbol)
                    except:
                        price = 0
                    
                    balance_val = float(bal.balance) if bal.balance else 0.0
                    locked_val = float(bal.locked) if bal.locked else 0.0
                    price_float = float(price) if isinstance(price, Decimal) else (price or 0.0)
                    balance_usd = balance_val * price_float
                    
                    balances.append({
                        "wallet_id": wallet.id,
                        "network": wallet.network,
                        "network_name": config.name,
                        "address": wallet.address,
                        "symbol": bal.token_symbol,
                        "name": config.name,
                        "icon": config.icon,
                        "balance": balance_val,
                        "balance_formatted": f"{balance_val:.6f}",
                        "balance_usd": balance_usd,
                        "locked": locked_val,
                        "is_primary": getattr(wallet, 'is_primary', False),
                        "decimals": config.decimals,
                    })
            else:
                balances.append({
                    "wallet_id": wallet.id,
                    "network": wallet.network,
                    "network_name": config.name,
                    "address": wallet.address,
                    "symbol": config.symbol,
                    "name": config.name,
                    "icon": config.icon,
                    "balance": 0,
                    "balance_formatted": "0.000000",
                    "balance_usd": 0,
                    "locked": 0,
                    "is_primary": getattr(wallet, 'is_primary', False),
                    "decimals": config.decimals,
                })
        
        balances.sort(key=lambda x: (-x.get("balance", 0), -x.get("balance_usd", 0)))
        
        return balances

    # ==================== LOCK/UNLOCK BALANCE ====================

    async def lock_balance(
        self,
        session: AsyncSession,
        user_id: str,
        network: str,
        token_symbol: str,
        amount: Decimal,
        reason: str = ""
    ) -> bool:
        """Lock funds for giveaway/trade/escrow"""
        from database.models import WalletBalance
        
        wallet = await self.wallet_repo.get_user_wallet_by_network(session, user_id, network)
        if not wallet:
            logger.error("Wallet not found for lock", user_id=user_id, network=network)
            return False
        
        result = await session.execute(
            select(WalletBalance).where(
                and_(
                    WalletBalance.wallet_id == wallet.id,
                    WalletBalance.token_symbol == token_symbol
                )
            )
        )
        balance = result.scalar_one_or_none()
        
        if not balance:
            logger.error("Balance not found", wallet_id=wallet.id, token=token_symbol)
            return False
        
        current_balance = Decimal(str(balance.balance or 0))
        current_locked = Decimal(str(balance.locked or 0))
        available = current_balance - current_locked
        
        if available < amount:
            logger.warning(
                "Insufficient balance for lock",
                available=str(available),
                requested=str(amount)
            )
            return False
        
        balance.locked = current_locked + amount
        
        logger.info(
            "Balance locked",
            user_id=user_id,
            network=network,
            token=token_symbol,
            amount=str(amount),
            reason=reason
        )
        return True

    async def unlock_balance(
        self,
        session: AsyncSession,
        user_id: str,
        network: str,
        token_symbol: str,
        amount: Decimal,
        reason: str = ""
    ) -> bool:
        """Unlock previously locked balance"""
        from database.models import WalletBalance
        
        wallet = await self.wallet_repo.get_user_wallet_by_network(session, user_id, network)
        if not wallet:
            return False
        
        result = await session.execute(
            select(WalletBalance).where(
                and_(
                    WalletBalance.wallet_id == wallet.id,
                    WalletBalance.token_symbol == token_symbol
                )
            )
        )
        balance = result.scalar_one_or_none()
        
        if not balance:
            return False
        
        current_locked = Decimal(str(balance.locked or 0))
        balance.locked = max(Decimal(0), current_locked - amount)
        
        logger.info(
            "Balance unlocked",
            user_id=user_id,
            amount=str(amount),
            reason=reason
        )
        return True

    async def deduct_locked_balance(
        self,
        session: AsyncSession,
        user_id: str,
        network: str,
        token_symbol: str,
        amount: Decimal,
        reason: str = ""
    ) -> bool:
        """Deduct from locked balance (after successful trade/giveaway)"""
        from database.models import WalletBalance
        
        wallet = await self.wallet_repo.get_user_wallet_by_network(session, user_id, network)
        if not wallet:
            return False
        
        result = await session.execute(
            select(WalletBalance).where(
                and_(
                    WalletBalance.wallet_id == wallet.id,
                    WalletBalance.token_symbol == token_symbol
                )
            )
        )
        balance = result.scalar_one_or_none()
        
        if not balance:
            return False
        
        current_balance = Decimal(str(balance.balance or 0))
        current_locked = Decimal(str(balance.locked or 0))
        
        if current_locked < amount:
            logger.warning("Trying to deduct more than locked", locked=str(current_locked), amount=str(amount))
            return False
        
        balance.balance = current_balance - amount
        balance.locked = current_locked - amount
        
        logger.info(
            "Locked balance deducted",
            user_id=user_id,
            amount=str(amount),
            reason=reason
        )
        return True

    async def credit_balance(
        self,
        session: AsyncSession,
        user_id: str,
        network: str,
        token_symbol: str,
        amount: Decimal,
        reason: str = ""
    ) -> bool:
        """Add funds to user balance (for giveaway winners, refunds, etc)"""
        from database.models import WalletBalance
        
        wallet = await self.wallet_repo.get_user_wallet_by_network(session, user_id, network)
        if not wallet:
            # Try to create wallet if doesn't exist
            logger.warning("Wallet not found for credit, skipping", user_id=user_id, network=network)
            return False
        
        result = await session.execute(
            select(WalletBalance).where(
                and_(
                    WalletBalance.wallet_id == wallet.id,
                    WalletBalance.token_symbol == token_symbol
                )
            )
        )
        balance = result.scalar_one_or_none()
        
        if not balance:
            config = NETWORKS.get(network)
            balance = WalletBalance(
                id=str(uuid.uuid4()),
                wallet_id=wallet.id,
                token_symbol=token_symbol,
                token_name=config.name if config else token_symbol,
                token_decimals=config.decimals if config else 18,
                balance=amount,
               locked=Decimal("0")
            )
            session.add(balance)
        else:
            balance.balance = Decimal(str(balance.balance or 0)) + amount
        
        logger.info(
            "Balance credited",
            user_id=user_id,
            network=network,
            token=token_symbol,
            amount=str(amount),
            reason=reason
        )
        return True

    # ==================== REGENERATE WALLET ====================

    async def regenerate_wallet(
        self,
        session: AsyncSession,
        user_id: str,
        network: str
    ) -> Optional[Dict[str, Any]]:
        """Regenerate wallet for a specific network."""
        from database.models import Wallet, WalletBalance
        
        old_wallet = await self.wallet_repo.get_user_wallet_by_network(session, user_id, network)
        
        if old_wallet:
            result = await session.execute(
                select(WalletBalance).where(WalletBalance.wallet_id == old_wallet.id)
            )
            balances = result.scalars().all()
            
            total_balance = sum(float(b.balance or 0) for b in balances)
            
            if total_balance > 0:
                logger.warning(
                    "Regenerating wallet with balance!",
                    user_id=user_id,
                    network=network,
                    balance=total_balance
                )
            
            for bal in balances:
                await session.delete(bal)
            
            await session.delete(old_wallet)
            await session.flush()
        
        config = NETWORKS.get(network)
        if not config:
            return None
        
        wallet_data = await wallet_manager.create_wallet(network)
        
        new_wallet = Wallet(
            id=str(uuid.uuid4()),
            user_id=user_id,
            network=network,
            address=wallet_data.address,
            encrypted_private_key=encryption_manager.encrypt_private_key(wallet_data.private_key),
            is_primary=False
        )
        session.add(new_wallet)
        await session.flush()
        
        new_balance = WalletBalance(
            id=str(uuid.uuid4()),
            wallet_id=new_wallet.id,
            token_symbol=config.symbol,
            token_name=config.name,
            token_decimals=config.decimals,
            balance=Decimal("0"),
           locked=Decimal("0")
        )
        session.add(new_balance)
        
        logger.info(
            "Wallet regenerated",
            user_id=user_id,
            network=network,
            new_address=wallet_data.address[:10]
        )
        
        return {
            "network": network,
            "address": wallet_data.address,
            "symbol": config.symbol
        }

    # ==================== SYNC BLOCKCHAIN BALANCES ====================

    async def _sync_blockchain_balances(
        self, 
        session: AsyncSession, 
        wallets: list
    ) -> None:
        """Sync balances from blockchain to DB (for deposits)"""
        from database.models import WalletBalance
        
        for wallet in wallets:
            config = NETWORKS.get(wallet.network)
            if not config:
                continue
            
            try:
                blockchain_balance = await self._get_blockchain_balance(wallet, config)
                
                if blockchain_balance <= 0:
                    continue
                
                result = await session.execute(
                    select(WalletBalance).where(
                        and_(
                            WalletBalance.wallet_id == wallet.id,
                            WalletBalance.token_symbol == config.symbol
                        )
                    )
                )
                bal = result.scalar_one_or_none()
                
                if bal:
                    if blockchain_balance > Decimal(str(bal.balance or 0)):
                        bal.balance = blockchain_balance
                        logger.info(
                            "Deposit detected",
                            wallet=wallet.address[:10],
                            amount=str(blockchain_balance),
                            token=config.symbol
                        )
                else:
                    bal = WalletBalance(
                        id=str(uuid.uuid4()),
                        wallet_id=wallet.id,
                        token_symbol=config.symbol,
                        token_name=config.name,
                        token_decimals=config.decimals,
                        balance=blockchain_balance,
                       locked=Decimal("0")
                    )
                    session.add(bal)
                
            except Exception as e:
                logger.error(f"Blockchain sync failed for {wallet.network}: {e}")
                continue

    async def _get_blockchain_balance(self, wallet, config) -> Decimal:
        """Get balance from blockchain"""
        try:
            if wallet.network == "ton":
                try:
                    from services.ton_service import ton_service
                    balance = await ton_service.get_balance(wallet.address)
                    return Decimal(str(balance))
                except:
                    pass
            
            elif wallet.network in ["ethereum", "bsc", "polygon", "arbitrum", "optimism", "avalanche", "base"]:
                try:
                    from blockchain.evm_client import evm_client
                    balance = await evm_client.get_balance(wallet.address, wallet.network)
                    return Decimal(str(balance))
                except:
                    pass
            
            elif wallet.network == "solana":
                try:
                    from blockchain.solana_client import solana_client
                    balance = await solana_client.get_balance(wallet.address)
                    return Decimal(str(balance))
                except:
                    pass
            
            elif wallet.network == "tron":
                try:
                    from blockchain.tron_client import tron_client
                    balance = await tron_client.get_balance(wallet.address)
                    return Decimal(str(balance))
                except:
                    pass
            
            elif wallet.network == "bitcoin":
                try:
                    from blockchain.btc_client import btc_client
                    balance = await btc_client.get_balance(wallet.address)
                    return Decimal(str(balance))
                except:
                    pass
            
            return Decimal("0")
            
        except Exception as e:
            logger.error(f"Blockchain balance fetch failed: {e}")
            return Decimal("0")

    # ==================== TRANSACTION PREPARATION ====================

    async def prepare_send(
        self,
        session: AsyncSession,
        user_id: int,
        network: str,
        to_address: str,
        amount: Decimal
    ) -> Dict[str, Any]:
        """Prepare a send transaction (validate and estimate fees)."""
        wallet = await self.wallet_repo.get_user_wallet_by_network(session, user_id, network)
        if not wallet:
            raise WalletNotFoundError(f"No wallet found for {network}")
        
        is_valid = await wallet_manager.validate_address(network, to_address)
        if not is_valid:
            raise WalletServiceError(f"Invalid {network} address")
        
        balance = await wallet_manager.get_balance(network, wallet.address)
        
        gas_info = await wallet_manager.estimate_gas(network, wallet.address, to_address, amount)
        total_fee = gas_info.get("total_fee", Decimal("0"))
        
        total_needed = amount + total_fee
        if balance < total_needed:
            raise InsufficientFundsError(
                f"Insufficient balance. Need {total_needed} {NETWORKS[network].symbol}, "
                f"have {balance}"
            )
        
        config = NETWORKS[network]
        
        return {
            "wallet_id": wallet.id,
            "from_address": wallet.address,
            "to_address": to_address,
            "amount": str(amount),
            "amount_formatted": f"{amount:.8f}".rstrip('0').rstrip('.'),
            "network": network,
            "symbol": config.symbol,
            "icon": config.icon,
            "fee": str(total_fee),
            "fee_formatted": f"{total_fee:.8f}".rstrip('0').rstrip('.'),
            "gas_info": gas_info,
            "balance_after": str(balance - total_needed),
            "explorer_url": config.explorer_url
        }

    async def execute_send(
        self,
        session: AsyncSession,
        user_id: int,
        wallet_id: str,
        to_address: str,
        amount: Decimal,
        pin: str
    ) -> str:
        """Execute a send transaction. Returns transaction hash."""
        wallet = await self.wallet_repo.get_by_id(session, wallet_id)
        if not wallet or wallet.user_id != user_id:
            raise WalletNotFoundError("Wallet not found or access denied")
        
        user = await self.user_repo.get_by_id(session, user_id)
        if not encryption_manager.verify_pin(pin, user.pin_hash):
            raise InvalidPinError("Incorrect PIN")
        
        private_key = encryption_manager.decrypt_private_key(wallet.encrypted_private_key)
        
        try:
            logger.info(
                "Sending transaction",
                network=wallet.network,
                to=f"{to_address[:10]}...",
                amount=str(amount)
            )
            
            result = await wallet_manager.send_transaction(
                network=wallet.network,
                private_key=private_key,
                to_address=to_address,
                amount=amount
            )
            
            if hasattr(result, 'success'):
                if not result.success:
                    error_msg = result.error or "Transaction failed on blockchain"
                    logger.error("Transaction failed", network=wallet.network, error=error_msg)
                    raise TransactionFailedError(error_msg)
                
                tx_hash = result.tx_hash
                if not tx_hash:
                    raise TransactionFailedError("Transaction succeeded but no hash returned")
                
                logger.info("Transaction sent successfully", tx_hash=tx_hash, network=wallet.network)
                return tx_hash
            
            elif isinstance(result, str):
                logger.info("Transaction sent successfully", tx_hash=result, network=wallet.network)
                return result
            
            else:
                raise TransactionFailedError(f"Unexpected result type: {type(result)}")
            
        except (TransactionFailedError, InsufficientFundsError):
            raise
        except Exception as e:
            error_str = str(e)
            logger.error("Transaction execution error", network=wallet.network, error=error_str)
            error_msg = wallet_manager.map_error_to_user(error_str)
            raise WalletServiceError(error_msg)

    # ==================== BACKUP & RECOVERY ====================

    async def get_mnemonic_for_backup(
        self,
        session: AsyncSession,
        user_id: int,
        pin: str
    ) -> Optional[str]:
        """Retrieve decrypted mnemonic for backup display."""
        user = await self.user_repo.get_by_id(session, user_id)
        if not user:
            raise WalletServiceError("User not found")
        
        if not encryption_manager.verify_pin(pin, user.pin_hash):
            raise InvalidPinError("Incorrect PIN")
        
        return await self._get_user_mnemonic(session, user_id, pin)

    async def _get_user_mnemonic(
        self,
        session: AsyncSession,
        user_id: int,
        pin: str
    ) -> Optional[str]:
        """Get decrypted mnemonic from any user wallet"""
        wallets = await self.wallet_repo.get_user_wallets(session, user_id)
        
        for wallet in wallets:
            if wallet.encrypted_mnemonic:
                try:
                    return encryption_manager.decrypt_mnemonic(wallet.encrypted_mnemonic, pin)
                except Exception:
                    continue
        
        return None

    async def verify_backup_word(
        self,
        session: AsyncSession,
        user_id: int,
        pin: str,
        word_index: int,
        word: str
    ) -> bool:
        """Verify a specific word from the mnemonic"""
        mnemonic = await self._get_user_mnemonic(session, user_id, pin)
        if not mnemonic:
            return False
        
        words = mnemonic.split()
        if word_index < 0 or word_index >= len(words):
            return False
        
        return words[word_index].lower() == word.lower().strip()

    # ==================== UTILITIES ====================

    async def get_wallet_addresses(
        self,
        session: AsyncSession,
        user_id: int
    ) -> List[Dict[str, str]]:
        """Get all user wallet addresses for display"""
        wallets = await self.wallet_repo.get_user_wallets(session, user_id)
        
        return [
            {
                "network": w.network,
                "network_name": NETWORKS[w.network].name,
                "icon": NETWORKS[w.network].icon,
                "symbol": NETWORKS[w.network].symbol,
                "address": w.address,
                "address_short": f"{w.address[:8]}...{w.address[-6:]}",
                "is_primary": w.is_primary,
                "explorer_url": f"{NETWORKS[w.network].explorer_url}/address/{w.address}"
            }
            for w in wallets if w.network in NETWORKS
        ]

    async def set_primary_wallet(
        self,
        session: AsyncSession,
        user_id: int,
        wallet_id: str
    ) -> bool:
        """Set a wallet as the primary wallet"""
        wallets = await self.wallet_repo.get_user_wallets(session, user_id)
        
        for wallet in wallets:
            wallet.is_primary = (wallet.id == wallet_id)
        
        await session.flush()
        return True

    def get_supported_networks(self) -> List[Dict[str, Any]]:
        """Get list of all supported networks"""
        return [
            {
                "key": key,
                "name": config.name,
                "symbol": config.symbol,
                "icon": config.icon,
                "chain_id": config.chain_id,
                "is_testnet": config.is_testnet,
                "explorer": config.explorer_url
            }
            for key, config in NETWORKS.items()
        ]

    async def get_total_portfolio_usd(self, session: AsyncSession, user_id: int) -> Decimal:
        """Calculate total portfolio value in USD"""
        balances = await self.get_user_balances(session, user_id, refresh=False)
        return Decimal(str(sum(b.get("balance_usd", 0) for b in balances)))


# Global instance
wallet_service = WalletService()
"""
NEXUS WALLET - Deposit Watcher Service (Fixed for Internal Swaps)
Monitors blockchain and respects internal balance changes
"""

import asyncio
from decimal import Decimal
from datetime import datetime
import structlog
from sqlalchemy import select

from database.connection import db_manager
from database.models import Wallet, WalletBalance, Transaction, TransactionType, TransactionStatus, SystemConfig
from blockchain.wallet_manager import wallet_manager, NETWORKS

logger = structlog.get_logger(__name__)

class DepositWatcher:
    def __init__(self):
        self.is_running = False
        
    async def check_deposits(self):
        if self.is_running: return
        self.is_running = True
        
        try:
            async with db_manager.session() as session:
                result = await session.execute(select(Wallet).where(Wallet.is_active == True))
                wallets = result.scalars().all()
                for wallet in wallets:
                    await self._check_wallet_deposits(session, wallet)
        except Exception as e:
            logger.error("deposit_watcher.error", error=str(e))
        finally:
            self.is_running = False

    async def _check_wallet_deposits(self, session, wallet: Wallet):
        network_config = NETWORKS.get(wallet.network)
        if not network_config: return

        try:
            # 1. Get Real Chain Balance
            chain_balance = await wallet_manager.get_balance(wallet.network, wallet.address)
            
            # 2. Get Last Known Chain Balance from SystemConfig
            # We use SystemConfig table to store this state without modifying WalletBalance schema
            config_key = f"chain_bal:{wallet.id}:{network_config.symbol}"
            
            last_known_obj = await session.scalar(
                select(SystemConfig).where(SystemConfig.key == config_key)
            )
            
            last_known_balance = Decimal(last_known_obj.value) if last_known_obj else Decimal("-1")
            
            # 3. Get User Balance Record
            balance_obj = await session.scalar(
                select(WalletBalance).where(
                    WalletBalance.wallet_id == wallet.id,
                    WalletBalance.token_symbol == network_config.symbol
                )
            )

            # First time seeing this wallet?
            if last_known_balance == Decimal("-1"):
                # Initialize tracker
                if not last_known_obj:
                    session.add(SystemConfig(key=config_key, value=str(chain_balance)))
                
                # If user has no balance record but has money on chain -> Initial Deposit
                if not balance_obj and chain_balance > 0:
                    import uuid
                    balance_obj = WalletBalance(
                        id=str(uuid.uuid4()),
                        wallet_id=wallet.id,
                        token_symbol=network_config.symbol,
                        balance=chain_balance,
                        updated_at=datetime.utcnow()
                    )
                    session.add(balance_obj)
                    await self._record_deposit(session, wallet, network_config.symbol, chain_balance, "Initial Import")
                
                await session.commit()
                return

            # 4. Check for NEW Deposits
            # Logic: If real blockchain balance INCREASED since last check -> It's a deposit!
            if chain_balance > last_known_balance:
                diff = chain_balance - last_known_balance
                
                # Add difference to user's internal balance
                if balance_obj:
                    balance_obj.balance += diff
                    balance_obj.updated_at = datetime.utcnow()
                else:
                    # Create if missing
                    import uuid
                    balance_obj = WalletBalance(
                        id=str(uuid.uuid4()),
                        wallet_id=wallet.id,
                        token_symbol=network_config.symbol,
                        balance=diff,
                        updated_at=datetime.utcnow()
                    )
                    session.add(balance_obj)
                
                # Update tracker
                last_known_obj.value = str(chain_balance)
                
                await self._record_deposit(session, wallet, network_config.symbol, diff, "Deposit Detected")
                await session.commit()
                logger.info(f"Deposit detected: +{diff} {network_config.symbol} (Wallet: {wallet.address})")
            
            # 5. If chain balance DECREASED (e.g. we made a withdrawal or paid gas)
            elif chain_balance < last_known_balance:
                # Just sync the tracker down. User balance was already deducted by our system when withdrawal was requested.
                # If it was an external withdrawal (seed phrase used elsewhere), user balance won't reflect it, 
                # but we shouldn't punish them by double-deducting.
                last_known_obj.value = str(chain_balance)
                await session.commit()

        except Exception as e:
            # logger.warning(f"Check failed for {wallet.address}", error=str(e))
            pass

    async def _record_deposit(self, session, wallet, symbol, amount, note):
        import uuid
        tx = Transaction(
            id=str(uuid.uuid4()),
            user_id=wallet.user_id,
            wallet_id=wallet.id,
            tx_type=TransactionType.DEPOSIT,
            status=TransactionStatus.COMPLETED,
            network=wallet.network,
            token_symbol=symbol,
            amount=amount,
            to_address=wallet.address,
            memo=note,
            created_at=datetime.utcnow(),
            confirmed_at=datetime.utcnow()
        )
        session.add(tx)

deposit_watcher = DepositWatcher()
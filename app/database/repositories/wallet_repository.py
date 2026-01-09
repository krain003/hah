"""
NEXUS WALLET - Wallet Repository
"""

from typing import List, Optional
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from database.models import Wallet, WalletBalance

logger = structlog.get_logger()


class WalletRepository:
    
    async def create(
        self,
        session: AsyncSession,
        user_id: int,
        network: str,
        address: str,
        encrypted_private_key: str,
        encrypted_mnemonic: Optional[str] = None,
        derivation_path: Optional[str] = None,
        is_imported: bool = False,
        label: Optional[str] = None
    ) -> Wallet:
        wallet = Wallet(
            user_id=user_id,
            network=network,
            address=address,
            encrypted_private_key=encrypted_private_key,
            encrypted_mnemonic=encrypted_mnemonic,
            derivation_path=derivation_path,
            is_imported=is_imported,
            label=label
        )
        session.add(wallet)
        await session.flush()
        logger.info("Wallet created", wallet_id=wallet.id, network=network)
        return wallet
    
    async def get_by_id(self, session: AsyncSession, wallet_id: str) -> Optional[Wallet]:
        result = await session.execute(
            select(Wallet).where(Wallet.id == wallet_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_address(self, session: AsyncSession, address: str) -> Optional[Wallet]:
        result = await session.execute(
            select(Wallet).where(Wallet.address == address)
        )
        return result.scalar_one_or_none()
    
    async def get_user_wallets(
        self, 
        session: AsyncSession, 
        user_id: int,
        network: Optional[str] = None,
        active_only: bool = True
    ) -> List[Wallet]:
        query = select(Wallet).where(Wallet.user_id == user_id)
        if network:
            query = query.where(Wallet.network == network)
        if active_only:
            query = query.where(Wallet.is_active == True)
        query = query.order_by(Wallet.created_at.desc())
        result = await session.execute(query)
        return list(result.scalars().all())
    
    async def get_user_wallet_by_network(
        self,
        session: AsyncSession,
        user_id: int,
        network: str
    ) -> Optional[Wallet]:
        result = await session.execute(
            select(Wallet).where(
                and_(
                    Wallet.user_id == user_id,
                    Wallet.network == network,
                    Wallet.is_active == True
                )
            )
        )
        return result.scalar_one_or_none()
    
    async def update(self, session: AsyncSession, wallet_id: str, **kwargs) -> Optional[Wallet]:
        wallet = await self.get_by_id(session, wallet_id)
        if not wallet:
            return None
        for key, value in kwargs.items():
            if hasattr(wallet, key):
                setattr(wallet, key, value)
        await session.flush()
        return wallet
    
    async def deactivate(self, session: AsyncSession, wallet_id: str) -> bool:
        wallet = await self.get_by_id(session, wallet_id)
        if not wallet:
            return False
        wallet.is_active = False
        await session.flush()
        return True
    
    async def get_balances(self, session: AsyncSession, wallet_id: str) -> List[WalletBalance]:
        result = await session.execute(
            select(WalletBalance).where(WalletBalance.wallet_id == wallet_id)
        )
        return list(result.scalars().all())
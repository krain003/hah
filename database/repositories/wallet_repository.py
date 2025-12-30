from typing import List, Optional
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Wallet

class WalletRepository:
    async def create(self, session: AsyncSession, **kwargs) -> Wallet:
        wallet = Wallet(**kwargs)
        session.add(wallet)
        await session.flush()
        return wallet
        
    async def get_user_wallets(self, session: AsyncSession, user_id: int) -> List[Wallet]:
        result = await session.execute(select(Wallet).where(Wallet.user_id == user_id))
        return list(result.scalars().all())

    async def get_user_wallet_by_network(self, session: AsyncSession, user_id: int, network: str) -> Optional[Wallet]:
        result = await session.execute(select(Wallet).where(and_(Wallet.user_id == user_id, Wallet.network == network)))
        return result.scalar_one_or_none()
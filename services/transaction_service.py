from decimal import Decimal
from typing import Optional, List
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from database.models import Transaction
from services.price_service import price_service

logger = structlog.get_logger(__name__)

class TransactionService:
    async def create_transaction(self, session: AsyncSession, user_id: int, tx_type: str, network: str, token_symbol: str, amount: Decimal, **kwargs) -> Transaction:
        price = await price_service.get_price(token_symbol)
        amount_usd = Decimal(str(float(amount) * float(price))) if price else None
        
        tx = Transaction(user_id=user_id, tx_type=tx_type, network=network, token_symbol=token_symbol, amount=amount, amount_usd=amount_usd, **kwargs)
        session.add(tx)
        await session.flush()
        logger.info("Transaction created", tx_id=tx.id, tx_type=tx_type)
        return tx

    async def get_user_transactions(self, session: AsyncSession, user_id: int, limit: int = 50) -> List[Transaction]:
        result = await session.execute(
            select(Transaction).where(Transaction.user_id == user_id).order_by(desc(Transaction.created_at)).limit(limit)
        )
        return list(result.scalars().all())

transaction_service = TransactionService()
"""
NEXUS WALLET - Transaction Service
Handles real transaction recording and retrieval
"""

from decimal import Decimal
from typing import Optional, List, Dict
from datetime import datetime
from sqlalchemy import select, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from database.models import Transaction, TransactionType, TransactionStatus
from services.price_service import price_service

logger = structlog.get_logger()


class TransactionService:
    """Service for managing transactions"""
    
    async def create_transaction(
        self,
        session: AsyncSession,
        user_id: int,
        tx_type: str,
        network: str,
        token_symbol: str,
        amount: Decimal,
        wallet_id: Optional[str] = None,
        tx_hash: Optional[str] = None,
        from_address: Optional[str] = None,
        to_address: Optional[str] = None,
        fee_amount: Optional[Decimal] = None,
        fee_token: Optional[str] = None,
        status: str = "pending",
        memo: Optional[str] = None,
        p2p_trade_id: Optional[str] = None,
        swap_to_token: Optional[str] = None,
        swap_to_amount: Optional[Decimal] = None,
    ) -> Transaction:
        """Create new transaction record"""
        
        # Get USD value
        price = await price_service.get_price(token_symbol)
        amount_usd = Decimal(str(float(amount) * float(price))) if price else None
        
        fee_usd = None
        if fee_amount and fee_token:
            fee_price = await price_service.get_price(fee_token)
            if fee_price:
                fee_usd = Decimal(str(float(fee_amount) * float(fee_price)))
        
        tx = Transaction(
            user_id=user_id,
            wallet_id=wallet_id,
            tx_type=tx_type,
            status=status,
            network=network,
            tx_hash=tx_hash,
            token_symbol=token_symbol,
            amount=amount,
            amount_usd=amount_usd,
            from_address=from_address,
            to_address=to_address,
            fee_amount=fee_amount,
            fee_token=fee_token,
            fee_usd=fee_usd,
            memo=memo,
            p2p_trade_id=p2p_trade_id,
            swap_to_token=swap_to_token,
            swap_to_amount=swap_to_amount,
        )
        
        session.add(tx)
        await session.flush()
        
        logger.info(
            "Transaction created",
            tx_id=tx.id,
            tx_type=tx_type,
            amount=str(amount),
            token=token_symbol
        )
        
        return tx
    
    async def update_transaction(
        self,
        session: AsyncSession,
        tx_id: str,
        **kwargs
    ) -> Optional[Transaction]:
        """Update transaction"""
        result = await session.execute(
            select(Transaction).where(Transaction.id == tx_id)
        )
        tx = result.scalar_one_or_none()
        
        if not tx:
            return None
        
        for key, value in kwargs.items():
            if hasattr(tx, key):
                setattr(tx, key, value)
        
        # Set confirmed_at if completed
        if kwargs.get("status") == "completed" and not tx.confirmed_at:
            tx.confirmed_at = datetime.utcnow()
        
        await session.flush()
        return tx
    
    async def confirm_transaction(
        self,
        session: AsyncSession,
        tx_id: str,
        tx_hash: str,
        block_number: Optional[int] = None,
        confirmations: int = 1
    ) -> Optional[Transaction]:
        """Mark transaction as confirmed"""
        return await self.update_transaction(
            session,
            tx_id,
            status="completed",
            tx_hash=tx_hash,
            block_number=block_number,
            confirmations=confirmations,
            confirmed_at=datetime.utcnow()
        )
    
    async def fail_transaction(
        self,
        session: AsyncSession,
        tx_id: str,
        error_message: str
    ) -> Optional[Transaction]:
        """Mark transaction as failed"""
        return await self.update_transaction(
            session,
            tx_id,
            status="failed",
            error_message=error_message
        )
    
    async def get_transaction(
        self,
        session: AsyncSession,
        tx_id: str
    ) -> Optional[Transaction]:
        """Get transaction by ID"""
        result = await session.execute(
            select(Transaction).where(Transaction.id == tx_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_hash(
        self,
        session: AsyncSession,
        tx_hash: str
    ) -> Optional[Transaction]:
        """Get transaction by blockchain hash"""
        result = await session.execute(
            select(Transaction).where(Transaction.tx_hash == tx_hash)
        )
        return result.scalar_one_or_none()
    
    async def get_user_transactions(
        self,
        session: AsyncSession,
        user_id: int,
        tx_type: Optional[str] = None,
        status: Optional[str] = None,
        network: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Transaction]:
        """Get user's transactions with filters"""
        query = select(Transaction).where(Transaction.user_id == user_id)
        
        if tx_type:
            if tx_type == "p2p":
                query = query.where(
                    or_(
                        Transaction.tx_type == "p2p_buy",
                        Transaction.tx_type == "p2p_sell"
                    )
                )
            else:
                query = query.where(Transaction.tx_type == tx_type)
        
        if status:
            query = query.where(Transaction.status == status)
        
        if network:
            query = query.where(Transaction.network == network)
        
        query = query.order_by(desc(Transaction.created_at))
        query = query.limit(limit).offset(offset)
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    async def get_pending_transactions(
        self,
        session: AsyncSession,
        user_id: Optional[int] = None
    ) -> List[Transaction]:
        """Get pending transactions"""
        query = select(Transaction).where(
            Transaction.status.in_(["pending", "confirming"])
        )
        
        if user_id:
            query = query.where(Transaction.user_id == user_id)
        
        query = query.order_by(Transaction.created_at)
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    async def get_user_stats(
        self,
        session: AsyncSession,
        user_id: int
    ) -> Dict:
        """Get user transaction statistics"""
        txs = await self.get_user_transactions(session, user_id, limit=1000)
        
        total_sent = Decimal("0")
        total_received = Decimal("0")
        total_swaps = 0
        total_p2p = 0
        
        for tx in txs:
            if tx.status != "completed":
                continue
            
            usd = tx.amount_usd or Decimal("0")
            
            if tx.tx_type == "send":
                total_sent += usd
            elif tx.tx_type == "receive":
                total_received += usd
            elif tx.tx_type == "swap":
                total_swaps += 1
            elif tx.tx_type in ["p2p_buy", "p2p_sell"]:
                total_p2p += 1
        
        return {
            "total_transactions": len(txs),
            "total_sent_usd": total_sent,
            "total_received_usd": total_received,
            "total_swaps": total_swaps,
            "total_p2p_trades": total_p2p,
        }


# Global instance
transaction_service = TransactionService()
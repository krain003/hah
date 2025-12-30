"""
NEXUS WALLET - P2P Service
Real P2P trading with escrow protection
"""

import json
from decimal import Decimal
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from sqlalchemy import select, and_, or_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from database.models import (
    P2POrder, P2PTrade, P2PMessage, Escrow, User, Wallet,
    OrderStatus, TradeStatus, EscrowStatus
)
from services.price_service import price_service
from services.transaction_service import transaction_service

logger = structlog.get_logger()


# Payment methods
PAYMENT_METHODS = {
    "bank_transfer": {"name": "Bank Transfer", "icon": "🏦"},
    "card": {"name": "Card Payment", "icon": "💳"},
    "cash": {"name": "Cash", "icon": "💵"},
    "paypal": {"name": "PayPal", "icon": "🅿️"},
    "wise": {"name": "Wise", "icon": "💸"},
    "revolut": {"name": "Revolut", "icon": "📱"},
    "skrill": {"name": "Skrill", "icon": "💰"},
    "webmoney": {"name": "WebMoney", "icon": "🌐"},
    "qiwi": {"name": "QIWI", "icon": "🥝"},
    "sberbank": {"name": "Сбербанк", "icon": "💚"},
    "tinkoff": {"name": "Тинькофф", "icon": "💛"},
    "monobank": {"name": "Monobank", "icon": "🖤"},
}


class P2PService:
    """Service for P2P trading operations"""
    
    # ==================== ORDERS ====================
    
    async def create_order(
        self,
        session: AsyncSession,
        user_id: int,
        order_type: str,  # "buy" or "sell"
        network: str,
        token_symbol: str,
        total_amount: Decimal,
        price_per_unit: Decimal,
        fiat_currency: str,
        payment_methods: List[str],
        min_trade_amount: Optional[Decimal] = None,
        max_trade_amount: Optional[Decimal] = None,
        terms: Optional[str] = None,
        time_limit_minutes: int = 30,
        expires_hours: int = 24,
    ) -> P2POrder:
        """Create new P2P order"""
        
        # Validate payment methods
        valid_methods = [m for m in payment_methods if m in PAYMENT_METHODS]
        if not valid_methods:
            raise ValueError("At least one valid payment method required")
        
        # Set defaults
        if min_trade_amount is None:
            min_trade_amount = total_amount * Decimal("0.1")
        if max_trade_amount is None:
            max_trade_amount = total_amount
        
        order = P2POrder(
            user_id=user_id,
            order_type=order_type,
            status="active",
            network=network,
            token_symbol=token_symbol,
            total_amount=total_amount,
            available_amount=total_amount,
            filled_amount=Decimal("0"),
            min_trade_amount=min_trade_amount,
            max_trade_amount=max_trade_amount,
            fiat_currency=fiat_currency,
            price_per_unit=price_per_unit,
            payment_methods=json.dumps(valid_methods),
            terms=terms,
            time_limit_minutes=time_limit_minutes,
            expires_at=datetime.utcnow() + timedelta(hours=expires_hours),
        )
        
        session.add(order)
        await session.flush()
        
        logger.info(
            "P2P order created",
            order_id=order.id,
            order_type=order_type,
            amount=str(total_amount),
            token=token_symbol
        )
        
        return order
    
    async def get_order(
        self, 
        session: AsyncSession, 
        order_id: str
    ) -> Optional[P2POrder]:
        """Get order by ID"""
        result = await session.execute(
            select(P2POrder).where(P2POrder.id == order_id)
        )
        return result.scalar_one_or_none()
    
    async def get_active_orders(
        self,
        session: AsyncSession,
        order_type: Optional[str] = None,
        token_symbol: Optional[str] = None,
        fiat_currency: Optional[str] = None,
        payment_method: Optional[str] = None,
        exclude_user_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[P2POrder]:
        """Get active orders with filters"""
        query = select(P2POrder).where(
            and_(
                P2POrder.status == "active",
                P2POrder.available_amount > 0,
                or_(
                    P2POrder.expires_at.is_(None),
                    P2POrder.expires_at > datetime.utcnow()
                )
            )
        )
        
        if order_type:
            query = query.where(P2POrder.order_type == order_type)
        
        if token_symbol:
            query = query.where(P2POrder.token_symbol == token_symbol)
        
        if fiat_currency:
            query = query.where(P2POrder.fiat_currency == fiat_currency)
        
        if exclude_user_id:
            query = query.where(P2POrder.user_id != exclude_user_id)
        
        # Order by best price
        if order_type == "sell":
            query = query.order_by(P2POrder.price_per_unit.asc())
        else:
            query = query.order_by(P2POrder.price_per_unit.desc())
        
        query = query.limit(limit).offset(offset)
        
        result = await session.execute(query)
        orders = list(result.scalars().all())
        
        # Filter by payment method if specified
        if payment_method:
            filtered = []
            for order in orders:
                methods = json.loads(order.payment_methods)
                if payment_method in methods:
                    filtered.append(order)
            orders = filtered
        
        return orders
    
    async def get_user_orders(
        self,
        session: AsyncSession,
        user_id: int,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[P2POrder]:
        """Get user's orders"""
        query = select(P2POrder).where(P2POrder.user_id == user_id)
        
        if status:
            query = query.where(P2POrder.status == status)
        
        query = query.order_by(desc(P2POrder.created_at)).limit(limit)
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    async def cancel_order(
        self,
        session: AsyncSession,
        order_id: str,
        user_id: int
    ) -> bool:
        """Cancel order (only by owner)"""
        order = await self.get_order(session, order_id)
        
        if not order or order.user_id != user_id:
            return False
        
        if order.status != "active":
            return False
        
        # Check if there are active trades
        active_trades = await self.get_order_trades(
            session, order_id, status="pending"
        )
        if active_trades:
            return False
        
        order.status = "cancelled"
        await session.flush()
        
        logger.info("P2P order cancelled", order_id=order_id)
        return True
    
    # ==================== TRADES ====================
    
    async def create_trade(
        self,
        session: AsyncSession,
        order_id: str,
        initiator_id: int,
        crypto_amount: Decimal,
        payment_method: str,
    ) -> P2PTrade:
        """Create trade from order"""
        order = await self.get_order(session, order_id)
        if not order:
            raise ValueError("Order not found")
        
        if order.status != "active":
            raise ValueError("Order is not active")
        
        if crypto_amount > order.available_amount:
            raise ValueError("Amount exceeds available")
        
        if order.min_trade_amount and crypto_amount < order.min_trade_amount:
            raise ValueError(f"Minimum amount is {order.min_trade_amount}")
        
        if order.max_trade_amount and crypto_amount > order.max_trade_amount:
            raise ValueError(f"Maximum amount is {order.max_trade_amount}")
        
        # Validate payment method
        allowed_methods = json.loads(order.payment_methods)
        if payment_method not in allowed_methods:
            raise ValueError("Payment method not allowed")
        
        # Calculate fiat amount
        fiat_amount = crypto_amount * order.price_per_unit
        
        # Determine buyer and seller
        if order.order_type == "sell":
            seller_id = order.user_id
            buyer_id = initiator_id
        else:
            seller_id = initiator_id
            buyer_id = order.user_id
        
        # Create trade
        trade = P2PTrade(
            order_id=order_id,
            buyer_id=buyer_id,
            seller_id=seller_id,
            crypto_amount=crypto_amount,
            fiat_amount=fiat_amount,
            price_per_unit=order.price_per_unit,
            fiat_currency=order.fiat_currency,
            token_symbol=order.token_symbol,
            network=order.network,
            payment_method=payment_method,
            status="pending",
            expires_at=datetime.utcnow() + timedelta(minutes=order.time_limit_minutes),
        )
        
        session.add(trade)
        await session.flush()
        
        # Update order available amount
        order.available_amount -= crypto_amount
        order.trades_count += 1
        
        if order.available_amount <= 0:
            order.status = "completed"
        
        logger.info(
            "P2P trade created",
            trade_id=trade.id,
            order_id=order_id,
            amount=str(crypto_amount)
        )
        
        return trade
    
    async def get_trade(
        self, 
        session: AsyncSession, 
        trade_id: str
    ) -> Optional[P2PTrade]:
        """Get trade by ID"""
        result = await session.execute(
            select(P2PTrade).where(P2PTrade.id == trade_id)
        )
        return result.scalar_one_or_none()
    
    async def get_user_trades(
        self,
        session: AsyncSession,
        user_id: int,
        status: Optional[str] = None,
        role: Optional[str] = None,  # "buyer", "seller", or None for both
        limit: int = 50
    ) -> List[P2PTrade]:
        """Get user's trades"""
        if role == "buyer":
            query = select(P2PTrade).where(P2PTrade.buyer_id == user_id)
        elif role == "seller":
            query = select(P2PTrade).where(P2PTrade.seller_id == user_id)
        else:
            query = select(P2PTrade).where(
                or_(
                    P2PTrade.buyer_id == user_id,
                    P2PTrade.seller_id == user_id
                )
            )
        
        if status:
            query = query.where(P2PTrade.status == status)
        
        query = query.order_by(desc(P2PTrade.created_at)).limit(limit)
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    async def get_order_trades(
        self,
        session: AsyncSession,
        order_id: str,
        status: Optional[str] = None
    ) -> List[P2PTrade]:
        """Get trades for an order"""
        query = select(P2PTrade).where(P2PTrade.order_id == order_id)
        
        if status:
            query = query.where(P2PTrade.status == status)
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    async def mark_as_paid(
        self,
        session: AsyncSession,
        trade_id: str,
        user_id: int
    ) -> bool:
        """Buyer marks trade as paid"""
        trade = await self.get_trade(session, trade_id)
        
        if not trade or trade.buyer_id != user_id:
            return False
        
        if trade.status != "pending":
            return False
        
        trade.status = "paid"
        trade.paid_at = datetime.utcnow()
        
        # Add system message
        await self.add_message(
            session, trade_id, user_id,
            "💵 Buyer marked payment as sent",
            is_system=True
        )
        
        await session.flush()
        logger.info("Trade marked as paid", trade_id=trade_id)
        return True
    
    async def release_crypto(
        self,
        session: AsyncSession,
        trade_id: str,
        user_id: int
    ) -> bool:
        """Seller releases crypto to buyer"""
        trade = await self.get_trade(session, trade_id)
        
        if not trade or trade.seller_id != user_id:
            return False
        
        if trade.status not in ["pending", "paid"]:
            return False
        
        # Release escrow if exists
        if trade.escrow_id:
            escrow = await self.get_escrow(session, trade.escrow_id)
            if escrow:
                escrow.status = "released"
                escrow.released_at = datetime.utcnow()
        
        trade.status = "completed"
        trade.released_at = datetime.utcnow()
        
        # Update user stats
        await self._update_user_stats(session, trade.buyer_id, success=True)
        await self._update_user_stats(session, trade.seller_id, success=True)
        
        # Record transaction for both parties
        await transaction_service.create_transaction(
            session,
            user_id=trade.seller_id,
            tx_type="p2p_sell",
            network=trade.network,
            token_symbol=trade.token_symbol,
            amount=trade.crypto_amount,
            status="completed",
            p2p_trade_id=trade_id
        )
        
        await transaction_service.create_transaction(
            session,
            user_id=trade.buyer_id,
            tx_type="p2p_buy",
            network=trade.network,
            token_symbol=trade.token_symbol,
            amount=trade.crypto_amount,
            status="completed",
            p2p_trade_id=trade_id
        )
        
        # Add system message
        await self.add_message(
            session, trade_id, user_id,
            "✅ Crypto released! Trade completed successfully.",
            is_system=True
        )
        
        await session.flush()
        logger.info("Trade completed", trade_id=trade_id)
        return True
    
    async def cancel_trade(
        self,
        session: AsyncSession,
        trade_id: str,
        user_id: int,
        reason: Optional[str] = None
    ) -> bool:
        """Cancel trade"""
        trade = await self.get_trade(session, trade_id)
        
        if not trade:
            return False
        
        # Only buyer or seller can cancel
        if user_id not in [trade.buyer_id, trade.seller_id]:
            return False
        
        # Can only cancel pending trades
        if trade.status != "pending":
            return False
        
        # Refund escrow if exists
        if trade.escrow_id:
            escrow = await self.get_escrow(session, trade.escrow_id)
            if escrow:
                escrow.status = "refunded"
                escrow.refunded_at = datetime.utcnow()
        
        # Return amount to order
        order = await self.get_order(session, trade.order_id)
        if order:
            order.available_amount += trade.crypto_amount
            if order.status == "completed":
                order.status = "active"
        
        trade.status = "cancelled"
        trade.cancelled_at = datetime.utcnow()
        
        await self.add_message(
            session, trade_id, user_id,
            f"❌ Trade cancelled. Reason: {reason or 'Not specified'}",
            is_system=True
        )
        
        await session.flush()
        logger.info("Trade cancelled", trade_id=trade_id, reason=reason)
        return True
    
    async def open_dispute(
        self,
        session: AsyncSession,
        trade_id: str,
        user_id: int,
        reason: str
    ) -> bool:
        """Open dispute for trade"""
        trade = await self.get_trade(session, trade_id)
        
        if not trade:
            return False
        
        if user_id not in [trade.buyer_id, trade.seller_id]:
            return False
        
        if trade.status not in ["pending", "paid"]:
            return False
        
        trade.status = "disputed"
        trade.disputed_at = datetime.utcnow()
        trade.dispute_reason = reason
        
        await self.add_message(
            session, trade_id, user_id,
            f"⚠️ Dispute opened: {reason}",
            is_system=True
        )
        
        await session.flush()
        logger.warning("Dispute opened", trade_id=trade_id, reason=reason)
        return True
    
    # ==================== ESCROW ====================
    
    async def create_escrow(
        self,
        session: AsyncSession,
        trade: P2PTrade,
        from_wallet_id: str,
    ) -> Escrow:
        """Create escrow for trade"""
        escrow = Escrow(
            network=trade.network,
            token_symbol=trade.token_symbol,
            amount=trade.crypto_amount,
            from_wallet_id=from_wallet_id,
            from_user_id=trade.seller_id,
            to_user_id=trade.buyer_id,
            status="funded",
            funded_at=datetime.utcnow(),
            expires_at=trade.expires_at + timedelta(hours=24),
        )
        
        session.add(escrow)
        await session.flush()
        
        # Link to trade
        trade.escrow_id = escrow.id
        
        logger.info("Escrow created", escrow_id=escrow.id, trade_id=trade.id)
        return escrow
    
    async def get_escrow(
        self, 
        session: AsyncSession, 
        escrow_id: str
    ) -> Optional[Escrow]:
        """Get escrow by ID"""
        result = await session.execute(
            select(Escrow).where(Escrow.id == escrow_id)
        )
        return result.scalar_one_or_none()
    
    # ==================== MESSAGES ====================
    
    async def add_message(
        self,
        session: AsyncSession,
        trade_id: str,
        sender_id: int,
        message: str,
        is_system: bool = False
    ) -> P2PMessage:
        """Add message to trade chat"""
        msg = P2PMessage(
            trade_id=trade_id,
            sender_id=sender_id,
            message=message,
            is_system=is_system,
        )
        
        session.add(msg)
        await session.flush()
        return msg
    
    async def get_trade_messages(
        self,
        session: AsyncSession,
        trade_id: str,
        limit: int = 100
    ) -> List[P2PMessage]:
        """Get messages for trade"""
        result = await session.execute(
            select(P2PMessage)
            .where(P2PMessage.trade_id == trade_id)
            .order_by(P2PMessage.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())
    
    # ==================== RATINGS ====================
    
    async def rate_trade(
        self,
        session: AsyncSession,
        trade_id: str,
        user_id: int,
        rating: int,
        comment: Optional[str] = None
    ) -> bool:
        """Rate completed trade (1-5)"""
        if rating < 1 or rating > 5:
            return False
        
        trade = await self.get_trade(session, trade_id)
        if not trade or trade.status != "completed":
            return False
        
        if user_id == trade.buyer_id:
            trade.buyer_rating = rating
            trade.buyer_comment = comment
            other_user_id = trade.seller_id
        elif user_id == trade.seller_id:
            trade.seller_rating = rating
            trade.seller_comment = comment
            other_user_id = trade.buyer_id
        else:
            return False
        
        # Update other user's rating
        await self._update_user_rating(session, other_user_id, rating)
        
        await session.flush()
        return True
    
    async def _update_user_stats(
        self,
        session: AsyncSession,
        user_id: int,
        success: bool
    ):
        """Update user trading stats"""
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            user.total_trades = (user.total_trades or 0) + 1
            if success:
                user.successful_trades = (user.successful_trades or 0) + 1
    
    async def _update_user_rating(
        self,
        session: AsyncSession,
        user_id: int,
        new_rating: int
    ):
        """Update user's average rating"""
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            # Simple moving average
            total_trades = user.total_trades or 1
            current_rating = user.rating or 100.0
            
            # Convert 1-5 to percentage (1=20%, 5=100%)
            new_pct = new_rating * 20.0
            
            # Weighted average
            user.rating = (current_rating * (total_trades - 1) + new_pct) / total_trades
    
    # ==================== HELPERS ====================
    
    async def get_user_with_stats(
        self,
        session: AsyncSession,
        user_id: int
    ) -> Optional[Dict]:
        """Get user with trading stats"""
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            return None
        
        return {
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "total_trades": user.total_trades or 0,
            "successful_trades": user.successful_trades or 0,
            "rating": user.rating or 100.0,
            "created_at": user.created_at,
        }
    
    def format_payment_methods(self, methods_json: str) -> str:
        """Format payment methods for display"""
        methods = json.loads(methods_json)
        formatted = []
        for m in methods:
            info = PAYMENT_METHODS.get(m, {"name": m, "icon": "💳"})
            formatted.append(f"{info['icon']} {info['name']}")
        return ", ".join(formatted)


# Global instance
p2p_service = P2PService()
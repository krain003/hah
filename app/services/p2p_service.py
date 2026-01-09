"""
NEXUS WALLET - P2P Service Engine (Complete Edition)
Full P2P trading: orders, trades, escrow, disputes, payment methods
"""

import asyncio
import re
from decimal import Decimal
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy import select, update, delete, func, or_, and_, desc
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from database.models import (
    User, Wallet, WalletBalance, Transaction, PaymentMethod,
    P2POrder, P2PTrade, P2PMessage, Escrow, Review, Dispute,
    OrderStatus, TradeStatus, TransactionType, TransactionStatus,
    EscrowStatus, DisputeStatus, PaymentMethodType
)

logger = structlog.get_logger(__name__)


# ==================== CONSTANTS ====================

SUPPORTED_CRYPTOS = {
    "ethereum": {"symbol": "ETH", "icon": "⟠", "name": "Ethereum"},
    "bsc": {"symbol": "BNB", "icon": "💛", "name": "BNB"},
    "polygon": {"symbol": "MATIC", "icon": "💜", "name": "Polygon"},
    "arbitrum": {"symbol": "ETH", "icon": "🔵", "name": "Arbitrum"},
    "avalanche": {"symbol": "AVAX", "icon": "🔺", "name": "Avalanche"},
    "optimism": {"symbol": "ETH", "icon": "🔴", "name": "Optimism"},
    "base": {"symbol": "ETH", "icon": "🔷", "name": "Base"},
    "ton": {"symbol": "TON", "icon": "💎", "name": "TON"},
    "solana": {"symbol": "SOL", "icon": "◎", "name": "Solana"},
    "tron": {"symbol": "TRX", "icon": "🔴", "name": "TRON"},
    "bitcoin": {"symbol": "BTC", "icon": "₿", "name": "Bitcoin"},
}

SUPPORTED_FIATS = {
    "USD": {"symbol": "$", "name": "US Dollar"},
    "EUR": {"symbol": "€", "name": "Euro"},
    "RUB": {"symbol": "₽", "name": "Russian Ruble"},
    "UAH": {"symbol": "₴", "name": "Ukrainian Hryvnia"},
    "KZT": {"symbol": "₸", "name": "Kazakh Tenge"},
    "GBP": {"symbol": "£", "name": "British Pound"},
    "TRY": {"symbol": "₺", "name": "Turkish Lira"},
    "CNY": {"symbol": "¥", "name": "Chinese Yuan"},
    "INR": {"symbol": "₹", "name": "Indian Rupee"},
    "AED": {"symbol": "د.إ", "name": "UAE Dirham"},
}

PAYMENT_METHOD_TYPES = {
    "bank_transfer": {
        "name": "Bank Transfer",
        "icon": "🏦",
        "fields": ["bank_name", "account_number", "account_name"],
        "validators": {
            "account_number": r"^\d{10,20}$"
        }
    },
    "card": {
        "name": "Bank Card",
        "icon": "💳",
        "fields": ["card_number", "card_holder", "bank_name"],
        "validators": {
            "card_number": "luhn"
        }
    },
    "sbp": {
        "name": "SBP (СБП)",
        "icon": "📱",
        "fields": ["phone_number", "bank_name", "recipient_name"],
        "validators": {
            "phone_number": r"^\+?[0-9]{10,15}$"
        }
    },
    "crypto_wallet": {
        "name": "Crypto Wallet",
        "icon": "🔐",
        "fields": ["wallet_address", "network"],
        "validators": {}
    },
    "paypal": {
        "name": "PayPal",
        "icon": "🅿️",
        "fields": ["email"],
        "validators": {
            "email": r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        }
    },
    "wise": {
        "name": "Wise",
        "icon": "💚",
        "fields": ["email", "account_name"],
        "validators": {}
    },
    "revolut": {
        "name": "Revolut",
        "icon": "💜",
        "fields": ["phone_number", "username"],
        "validators": {}
    },
    "cash": {
        "name": "Cash",
        "icon": "💵",
        "fields": ["location", "notes"],
        "validators": {}
    }
}


# ==================== VALIDATORS ====================

class PaymentValidator:
    """Validate payment method details"""
    
    @staticmethod
    def validate_luhn(card_number: str) -> bool:
        """Luhn algorithm for card validation"""
        card_number = re.sub(r'\D', '', card_number)
        if not card_number or len(card_number) < 13 or len(card_number) > 19:
            return False
        
        total = 0
        reverse_digits = card_number[::-1]
        for i, digit in enumerate(reverse_digits):
            n = int(digit)
            if i % 2 == 1:
                n *= 2
                if n > 9:
                    n -= 9
            total += n
        return total % 10 == 0
    
    @staticmethod
    def validate_field(field_name: str, value: str, validator: str) -> Tuple[bool, str]:
        """Validate a single field"""
        if not value or not value.strip():
            return False, f"{field_name} is required"
        
        value = value.strip()
        
        if validator == "luhn":
            if not PaymentValidator.validate_luhn(value):
                return False, "Invalid card number"
            return True, ""
        
        if validator.startswith("^"):  # Regex pattern
            if not re.match(validator, value):
                return False, f"Invalid {field_name} format"
            return True, ""
        
        return True, ""
    
    @classmethod
    def validate_payment_method(
        cls, 
        method_type: str, 
        data: Dict[str, str]
    ) -> Tuple[bool, List[str]]:
        """Validate all fields of a payment method"""
        errors = []
        
        method_config = PAYMENT_METHOD_TYPES.get(method_type)
        if not method_config:
            return False, ["Unknown payment method type"]
        
        # Check required fields
        for field in method_config["fields"]:
            if field not in data or not data[field]:
                errors.append(f"Missing required field: {field}")
                continue
            
            # Validate field if validator exists
            validators = method_config.get("validators", {})
            if field in validators:
                is_valid, error = cls.validate_field(
                    field, data[field], validators[field]
                )
                if not is_valid:
                    errors.append(error)
        
        return len(errors) == 0, errors


# ==================== P2P SERVICE ====================

class P2PService:
    """Complete P2P Trading Service"""
    
    def __init__(self):
        self.platform_fee_percent = Decimal("0.5")  # 0.5% fee
        self.escrow_timeout_minutes = 30
        self.trade_timeout_minutes = 60
        self.min_order_usd = Decimal("10")
        self.max_order_usd = Decimal("50000")
    
    # ==================== PAYMENT METHODS ====================
    
    async def add_payment_method(
        self,
        session: AsyncSession,
        user_id: int,
        method_type: str,
        name: str,
        details: Dict[str, str]
    ) -> Tuple[Optional[PaymentMethod], List[str]]:
        """Add a new payment method with validation"""
        
        # Validate payment details
        is_valid, errors = PaymentValidator.validate_payment_method(method_type, details)
        if not is_valid:
            return None, errors
        
        # Check for duplicates
        existing = await session.execute(
            select(PaymentMethod).where(
                PaymentMethod.user_id == user_id,
                PaymentMethod.type == PaymentMethodType(method_type),
                PaymentMethod.is_active == True
            )
        )
        existing_methods = existing.scalars().all()
        
        # Check if same account already exists
        for method in existing_methods:
            if method.account_number == details.get("card_number") or \
               method.account_number == details.get("account_number") or \
               method.account_number == details.get("phone_number"):
                return None, ["This payment method already exists"]
        
        # Mask sensitive data for display
        display_number = None
        raw_number = details.get("card_number") or details.get("account_number") or details.get("phone_number")
        if raw_number:
            clean = re.sub(r'\D', '', raw_number)
            if len(clean) >= 4:
                display_number = f"****{clean[-4:]}"
        
        method_config = PAYMENT_METHOD_TYPES.get(method_type, {})
        
        payment_method = PaymentMethod(
            user_id=user_id,
            type=PaymentMethodType(method_type),
            name=name or method_config.get("name", method_type),
            account_name=details.get("account_name") or details.get("card_holder") or details.get("recipient_name"),
            account_number=display_number,
            bank_name=details.get("bank_name"),
            additional_info=str(details),  # Store full details encrypted in production
            icon=method_config.get("icon", "💳"),
            is_active=True,
            is_verified=False
        )
        
        session.add(payment_method)
        await session.flush()
        
        logger.info("Payment method added", user_id=user_id, type=method_type)
        return payment_method, []
    
    async def get_user_payment_methods(
        self,
        session: AsyncSession,
        user_id: int,
        active_only: bool = True
    ) -> List[PaymentMethod]:
        """Get all payment methods for a user"""
        query = select(PaymentMethod).where(PaymentMethod.user_id == user_id)
        if active_only:
            query = query.where(PaymentMethod.is_active == True)
        query = query.order_by(PaymentMethod.created_at.desc())
        
        result = await session.execute(query)
        return result.scalars().all()
    
    async def delete_payment_method(
        self,
        session: AsyncSession,
        user_id: int,
        method_id: str
    ) -> bool:
        """Delete (deactivate) a payment method"""
        result = await session.execute(
            update(PaymentMethod)
            .where(
                PaymentMethod.id == method_id,
                PaymentMethod.user_id == user_id
            )
            .values(is_active=False)
        )
        return result.rowcount > 0
    
    # ==================== ORDERS (ADS) ====================
    
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
        min_limit: Decimal,
        max_limit: Decimal,
        payment_method_ids: List[str],
        terms: Optional[str] = None
    ) -> Tuple[Optional[P2POrder], List[str]]:
        """Create a new P2P order (advertisement)"""
        errors = []
        
        # Validations
        if network not in SUPPORTED_CRYPTOS:
            errors.append(f"Unsupported network: {network}")
        
        if fiat_currency not in SUPPORTED_FIATS:
            errors.append(f"Unsupported currency: {fiat_currency}")
        
        if order_type not in ["buy", "sell"]:
            errors.append("Order type must be 'buy' or 'sell'")
        
        if total_amount <= 0:
            errors.append("Amount must be positive")
        
        if price_per_unit <= 0:
            errors.append("Price must be positive")
        
        if min_limit <= 0 or max_limit <= 0:
            errors.append("Limits must be positive")
        
        if min_limit > max_limit:
            errors.append("Min limit cannot be greater than max limit")
        
        if not payment_method_ids:
            errors.append("At least one payment method is required")
        
        if errors:
            return None, errors
        
        # For sell orders, check if user has enough balance
        if order_type == "sell":
            wallet = await session.execute(
                select(Wallet).where(
                    Wallet.user_id == user_id,
                    Wallet.network == network,
                    Wallet.is_active == True
                )
            )
            wallet = wallet.scalar_one_or_none()
            
            if not wallet:
                return None, [f"No wallet found for {network}"]
            
            # Get balance
            balance = await session.execute(
                select(WalletBalance).where(
                    WalletBalance.wallet_id == wallet.id,
                    WalletBalance.token_symbol == token_symbol
                )
            )
            balance = balance.scalar_one_or_none()
            
            available = Decimal(str(balance.balance)) - Decimal(str(balance.locked_balance)) if balance else Decimal("0")
            
            if available < total_amount:
                return None, [f"Insufficient balance. Available: {available} {token_symbol}"]
        
        # Verify payment methods belong to user
        methods_result = await session.execute(
            select(PaymentMethod).where(
                PaymentMethod.id.in_(payment_method_ids),
                PaymentMethod.user_id == user_id,
                PaymentMethod.is_active == True
            )
        )
        valid_methods = methods_result.scalars().all()
        
        if len(valid_methods) != len(payment_method_ids):
            return None, ["Some payment methods are invalid"]
        
        # Create order
        order = P2POrder(
            user_id=user_id,
            order_type=order_type,
            network=network,
            token_symbol=token_symbol,
            total_amount=total_amount,
            available_amount=total_amount,
            min_limit=min_limit,
            max_limit=max_limit,
            fiat_currency=fiat_currency,
            price_per_unit=price_per_unit,
            payment_methods=[m.id for m in valid_methods],
            terms_of_trade=terms,
            status=OrderStatus.ACTIVE,
            payment_time_limit=self.escrow_timeout_minutes
        )
        
        session.add(order)
        await session.flush()
        
        # Lock funds for sell orders
        if order_type == "sell" and balance:
            balance.locked_balance = Decimal(str(balance.locked_balance)) + total_amount
        
        logger.info(
            "P2P order created",
            order_id=order.id,
            user_id=user_id,
            type=order_type,
            amount=str(total_amount)
        )
        
        return order, []
    
    async def get_market_orders(
        self,
        session: AsyncSession,
        order_type: str,  # "buy" or "sell"
        network: Optional[str] = None,
        fiat_currency: Optional[str] = None,
        token_symbol: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[P2POrder]:
        """Get active orders from the market"""
        query = (
            select(P2POrder)
            .where(
                P2POrder.status == OrderStatus.ACTIVE,
                P2POrder.available_amount > 0,
                P2POrder.order_type == order_type
            )
            .options(selectinload(P2POrder.user))
        )
        
        if network:
            query = query.where(P2POrder.network == network)
        if fiat_currency:
            query = query.where(P2POrder.fiat_currency == fiat_currency)
        if token_symbol:
            query = query.where(P2POrder.token_symbol == token_symbol)
        
        # Sort: sell orders by price ASC (cheapest first), buy orders by price DESC (best offer first)
        if order_type == "sell":
            query = query.order_by(P2POrder.price_per_unit.asc())
        else:
            query = query.order_by(P2POrder.price_per_unit.desc())
        
        query = query.limit(limit).offset(offset)
        
        result = await session.execute(query)
        return result.scalars().all()
    
    async def get_user_orders(
        self,
        session: AsyncSession,
        user_id: int,
        status: Optional[OrderStatus] = None
    ) -> List[P2POrder]:
        """Get orders created by a user"""
        query = select(P2POrder).where(P2POrder.user_id == user_id)
        
        if status:
            query = query.where(P2POrder.status == status)
        
        query = query.order_by(P2POrder.created_at.desc())
        
        result = await session.execute(query)
        return result.scalars().all()
    
    async def get_order_by_id(
        self,
        session: AsyncSession,
        order_id: str
    ) -> Optional[P2POrder]:
        """Get order by ID"""
        result = await session.execute(
            select(P2POrder)
            .where(P2POrder.id == order_id)
            .options(selectinload(P2POrder.user))
        )
        return result.scalar_one_or_none()
    
    async def cancel_order(
        self,
        session: AsyncSession,
        user_id: int,
        order_id: str
    ) -> Tuple[bool, str]:
        """Cancel an order"""
        order = await self.get_order_by_id(session, order_id)
        
        if not order:
            return False, "Order not found"
        
        if order.user_id != user_id:
            return False, "Access denied"
        
        if order.status != OrderStatus.ACTIVE:
            return False, "Order cannot be cancelled"
        
        # Check for active trades
        active_trades = await session.execute(
            select(func.count(P2PTrade.id)).where(
                P2PTrade.order_id == order_id,
                P2PTrade.status.in_([
                    TradeStatus.PENDING,
                    TradeStatus.AWAITING_PAYMENT,
                    TradeStatus.PAYMENT_SENT
                ])
            )
        )
        if active_trades.scalar() > 0:
            return False, "Cannot cancel order with active trades"
        
        # Unlock funds if sell order
        if order.order_type == "sell":
            wallet = await session.execute(
                select(Wallet).where(
                    Wallet.user_id == user_id,
                    Wallet.network == order.network
                )
            )
            wallet = wallet.scalar_one_or_none()
            
            if wallet:
                balance = await session.execute(
                    select(WalletBalance).where(
                        WalletBalance.wallet_id == wallet.id,
                        WalletBalance.token_symbol == order.token_symbol
                    )
                )
                balance = balance.scalar_one_or_none()
                if balance:
                    balance.locked_balance = max(
                        Decimal("0"),
                        Decimal(str(balance.locked_balance)) - order.available_amount
                    )
        
        order.status = OrderStatus.CANCELLED
        
        logger.info("Order cancelled", order_id=order_id, user_id=user_id)
        return True, "Order cancelled"
    
    # ==================== TRADES ====================
    
    async def initiate_trade(
        self,
        session: AsyncSession,
        taker_id: int,
        order_id: str,
        crypto_amount: Decimal,
        payment_method_id: Optional[str] = None
    ) -> Tuple[Optional[P2PTrade], str]:
        """Initiate a trade from an order"""
        
        # Get order with lock
        order = await session.execute(
            select(P2POrder)
            .where(P2POrder.id == order_id)
            .with_for_update()
        )
        order = order.scalar_one_or_none()
        
        if not order:
            return None, "Order not found"
        
        if order.status != OrderStatus.ACTIVE:
            return None, "Order is not active"
        
        if order.user_id == taker_id:
            return None, "Cannot trade with yourself"
        
        if crypto_amount <= 0:
            return None, "Invalid amount"
        
        if crypto_amount > order.available_amount:
            return None, f"Maximum available: {order.available_amount}"
        
        # Check limits
        fiat_amount = crypto_amount * order.price_per_unit
        
        if fiat_amount < order.min_limit:
            return None, f"Minimum trade: {order.min_limit} {order.fiat_currency}"
        
        if fiat_amount > order.max_limit:
            return None, f"Maximum trade: {order.max_limit} {order.fiat_currency}"
        
        # Determine buyer and seller
        if order.order_type == "sell":
            buyer_id = taker_id
            seller_id = order.user_id
        else:
            buyer_id = order.user_id
            seller_id = taker_id
        
        # Get payment details
        payment_method_name = None
        payment_details = None
        
        if payment_method_id and order.payment_methods:
            pm_result = await session.execute(
                select(PaymentMethod).where(PaymentMethod.id == payment_method_id)
            )
            pm = pm_result.scalar_one_or_none()
            if pm:
                payment_method_name = pm.name
                payment_details = pm.additional_info
        
        # Create trade
        trade = P2PTrade(
            order_id=order.id,
            buyer_id=buyer_id,
            seller_id=seller_id,
            network=order.network,
            token_symbol=order.token_symbol,
            crypto_amount=crypto_amount,
            fiat_amount=fiat_amount,
            fiat_currency=order.fiat_currency,
            price_at_trade=order.price_per_unit,
            status=TradeStatus.PENDING,
            payment_method_id=payment_method_id,
            payment_method_name=payment_method_name,
            payment_details=payment_details,
            expires_at=datetime.utcnow() + timedelta(minutes=self.trade_timeout_minutes)
        )
        
        session.add(trade)
        
        # Update order available amount
        order.available_amount -= crypto_amount
        order.total_trades += 1
        
        if order.available_amount <= 0:
            order.status = OrderStatus.FILLED
        
        # Create escrow for seller's crypto
        escrow = Escrow(
            trade_id=trade.id,
            network=order.network,
            token_symbol=order.token_symbol,
            amount=crypto_amount,
            seller_id=seller_id,
            status=EscrowStatus.LOCKED
        )
        session.add(escrow)
        
        await session.flush()
        
        logger.info(
            "Trade initiated",
            trade_id=trade.id,
            buyer_id=buyer_id,
            seller_id=seller_id,
            amount=str(crypto_amount)
        )
        
        return trade, "Trade created successfully"
    
    async def get_trade_by_id(
        self,
        session: AsyncSession,
        trade_id: str
    ) -> Optional[P2PTrade]:
        """Get trade with related data"""
        result = await session.execute(
            select(P2PTrade)
            .where(P2PTrade.id == trade_id)
            .options(
                selectinload(P2PTrade.buyer),
                selectinload(P2PTrade.seller),
                selectinload(P2PTrade.order),
                selectinload(P2PTrade.escrow)
            )
        )
        return result.scalar_one_or_none()
    
    async def get_user_trades(
        self,
        session: AsyncSession,
        user_id: int,
        status: Optional[TradeStatus] = None,
        limit: int = 20
    ) -> List[P2PTrade]:
        """Get user's trades"""
        query = (
            select(P2PTrade)
            .where(
                or_(
                    P2PTrade.buyer_id == user_id,
                    P2PTrade.seller_id == user_id
                )
            )
            .options(
                selectinload(P2PTrade.buyer),
                selectinload(P2PTrade.seller)
            )
            .order_by(P2PTrade.created_at.desc())
            .limit(limit)
        )
        
        if status:
            query = query.where(P2PTrade.status == status)
        
        result = await session.execute(query)
        return result.scalars().all()
    
    async def mark_payment_sent(
        self,
        session: AsyncSession,
        trade_id: str,
        user_id: int,
        proof_file_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Buyer marks payment as sent"""
        trade = await self.get_trade_by_id(session, trade_id)
        
        if not trade:
            return False, "Trade not found"
        
        if trade.buyer_id != user_id:
            return False, "Only buyer can mark payment"
        
        if trade.status != TradeStatus.PENDING and trade.status != TradeStatus.AWAITING_PAYMENT:
            return False, f"Invalid trade status: {trade.status}"
        
        trade.status = TradeStatus.PAYMENT_SENT
        trade.payment_sent_at = datetime.utcnow()
        trade.payment_proof = proof_file_id
        
        # Add system message
        msg = P2PMessage(
            trade_id=trade_id,
            sender_id=user_id,
            content="💸 Buyer marked payment as sent",
            is_system=True,
            is_payment_proof=bool(proof_file_id),
            attachment_file_id=proof_file_id
        )
        session.add(msg)
        
        logger.info("Payment marked as sent", trade_id=trade_id, buyer_id=user_id)
        return True, "Payment marked as sent"
    
    async def confirm_payment_received(
        self,
        session: AsyncSession,
        trade_id: str,
        user_id: int
    ) -> Tuple[bool, str]:
        """Seller confirms payment received and releases crypto"""
        trade = await self.get_trade_by_id(session, trade_id)
        
        if not trade:
            return False, "Trade not found"
        
        if trade.seller_id != user_id:
            return False, "Only seller can confirm payment"
        
        if trade.status != TradeStatus.PAYMENT_SENT:
            return False, f"Invalid trade status: {trade.status}"
        
        # Release escrow
        if trade.escrow:
            trade.escrow.status = EscrowStatus.RELEASED
            trade.escrow.released_at = datetime.utcnow()
        
        # Complete trade
        trade.status = TradeStatus.COMPLETED
        trade.payment_confirmed_at = datetime.utcnow()
        trade.completed_at = datetime.utcnow()
        
        # Update order stats
        if trade.order:
            trade.order.completed_trades += 1
        
        # Update user stats
        buyer = await session.get(User, trade.buyer_id)
        seller = await session.get(User, trade.seller_id)
        
        if buyer:
            buyer.total_trades_count += 1
            buyer.successful_trades_count += 1
            buyer.total_volume_usd += trade.fiat_amount
        
        if seller:
            seller.total_trades_count += 1
            seller.successful_trades_count += 1
            seller.total_volume_usd += trade.fiat_amount
        
        # Add system message
        msg = P2PMessage(
            trade_id=trade_id,
            sender_id=user_id,
            content="✅ Trade completed! Crypto released to buyer.",
            is_system=True
        )
        session.add(msg)
        
        logger.info("Trade completed", trade_id=trade_id)
        return True, "Trade completed successfully"
    
    async def cancel_trade(
        self,
        session: AsyncSession,
        trade_id: str,
        user_id: int,
        reason: str = ""
    ) -> Tuple[bool, str]:
        """Cancel a trade"""
        trade = await self.get_trade_by_id(session, trade_id)
        
        if not trade:
            return False, "Trade not found"
        
        if trade.buyer_id != user_id and trade.seller_id != user_id:
            return False, "Access denied"
        
        # Only pending trades can be cancelled freely
        if trade.status not in [TradeStatus.PENDING, TradeStatus.AWAITING_PAYMENT]:
            if trade.status == TradeStatus.PAYMENT_SENT:
                return False, "Cannot cancel after payment sent. Open a dispute instead."
            return False, f"Trade cannot be cancelled in status: {trade.status}"
        
        # Refund escrow
        if trade.escrow:
            trade.escrow.status = EscrowStatus.REFUNDED
            trade.escrow.refunded_at = datetime.utcnow()
        
        # Return amount to order
        if trade.order and trade.order.status != OrderStatus.CANCELLED:
            trade.order.available_amount += trade.crypto_amount
            if trade.order.status == OrderStatus.FILLED:
                trade.order.status = OrderStatus.ACTIVE
        
        trade.status = TradeStatus.CANCELLED
        trade.cancelled_at = datetime.utcnow()
        trade.cancelled_by = user_id
        trade.cancel_reason = reason
        
        # Update user stats
        canceller = await session.get(User, user_id)
        if canceller:
            canceller.cancelled_trades_count += 1
        
        logger.info("Trade cancelled", trade_id=trade_id, by=user_id, reason=reason)
        return True, "Trade cancelled"
    
    # ==================== DISPUTES ====================
    
    async def open_dispute(
        self,
        session: AsyncSession,
        trade_id: str,
        user_id: int,
        reason: str
    ) -> Tuple[Optional[Dispute], str]:
        """Open a dispute for a trade"""
        trade = await self.get_trade_by_id(session, trade_id)
        
        if not trade:
            return None, "Trade not found"
        
        if trade.buyer_id != user_id and trade.seller_id != user_id:
            return None, "Access denied"
        
        if trade.status == TradeStatus.COMPLETED:
            return None, "Cannot dispute completed trade"
        
        if trade.status == TradeStatus.CANCELLED:
            return None, "Cannot dispute cancelled trade"
        
        # Check if dispute already exists
        existing = await session.execute(
            select(Dispute).where(Dispute.trade_id == trade_id)
        )
        if existing.scalar_one_or_none():
            return None, "Dispute already exists for this trade"
        
        trade.status = TradeStatus.DISPUTED
        
        if trade.escrow:
            trade.escrow.status = EscrowStatus.DISPUTED
        
        dispute = Dispute(
            trade_id=trade_id,
            opened_by=user_id,
            reason=reason,
            status=DisputeStatus.OPEN
        )
        session.add(dispute)
        
        # Update user stats
        user = await session.get(User, user_id)
        if user:
            user.disputed_trades_count += 1
        
        await session.flush()
        
        logger.warning("Dispute opened", trade_id=trade_id, by=user_id)
        return dispute, "Dispute opened. Admin will review."
    
    # ==================== CHAT ====================
    
    async def send_message(
        self,
        session: AsyncSession,
        trade_id: str,
        user_id: int,
        content: str,
        attachment_file_id: Optional[str] = None,
        attachment_type: Optional[str] = None
    ) -> Optional[P2PMessage]:
        """Send a chat message in a trade"""
        trade = await self.get_trade_by_id(session, trade_id)
        
        if not trade:
            return None
        
        if trade.buyer_id != user_id and trade.seller_id != user_id:
            return None
        
        msg = P2PMessage(
            trade_id=trade_id,
            sender_id=user_id,
            content=content,
            attachment_type=attachment_type,
            attachment_file_id=attachment_file_id,
            is_system=False
        )
        session.add(msg)
        await session.flush()
        
        return msg
    
    async def get_trade_messages(
        self,
        session: AsyncSession,
        trade_id: str,
        limit: int = 50
    ) -> List[P2PMessage]:
        """Get messages for a trade"""
        result = await session.execute(
            select(P2PMessage)
            .where(P2PMessage.trade_id == trade_id)
            .order_by(P2PMessage.created_at.asc())
            .limit(limit)
        )
        return result.scalars().all()
    
    # ==================== STATS ====================
    
    async def get_user_p2p_stats(
        self,
        session: AsyncSession,
        user_id: int
    ) -> Dict[str, Any]:
        """Get comprehensive P2P stats for a user"""
        user = await session.get(User, user_id)
        
        if not user:
            return {}
        
        # Count active orders
        active_orders = await session.scalar(
            select(func.count(P2POrder.id)).where(
                P2POrder.user_id == user_id,
                P2POrder.status == OrderStatus.ACTIVE
            )
        )
        
        # Count trades by status
        completed_trades = await session.scalar(
            select(func.count(P2PTrade.id)).where(
                or_(P2PTrade.buyer_id == user_id, P2PTrade.seller_id == user_id),
                P2PTrade.status == TradeStatus.COMPLETED
            )
        )
        
        active_trades = await session.scalar(
            select(func.count(P2PTrade.id)).where(
                or_(P2PTrade.buyer_id == user_id, P2PTrade.seller_id == user_id),
                P2PTrade.status.in_([
                    TradeStatus.PENDING,
                    TradeStatus.AWAITING_PAYMENT,
                    TradeStatus.PAYMENT_SENT
                ])
            )
        )
        
        # Get reviews
        positive = user.positive_reviews
        negative = user.negative_reviews
        total_reviews = positive + negative
        
        success_rate = 0
        if user.total_trades_count > 0:
            success_rate = (user.successful_trades_count / user.total_trades_count) * 100
        
        return {
            "user_id": user_id,
            "username": user.username,
            "rating": user.rating,
            "trust_score": user.trust_score,
            "total_trades": user.total_trades_count,
            "successful_trades": user.successful_trades_count,
            "cancelled_trades": user.cancelled_trades_count,
            "disputed_trades": user.disputed_trades_count,
            "success_rate": round(success_rate, 1),
            "total_volume_usd": float(user.total_volume_usd),
            "active_orders": active_orders,
            "active_trades": active_trades,
            "completed_trades": completed_trades,
            "positive_reviews": positive,
            "negative_reviews": negative,
            "total_reviews": total_reviews,
            "is_verified": user.merchant_verified,
            "vip_tier": user.vip_tier,
            "member_since": user.created_at.strftime("%Y-%m-%d")
        }
    
    async def get_market_stats(
        self,
        session: AsyncSession
    ) -> Dict[str, Any]:
        """Get overall P2P market statistics"""
        # Active orders count
        active_orders = await session.scalar(
            select(func.count(P2POrder.id)).where(P2POrder.status == OrderStatus.ACTIVE)
        )
        
        # 24h volume
        yesterday = datetime.utcnow() - timedelta(days=1)
        volume_24h = await session.scalar(
            select(func.sum(P2PTrade.fiat_amount)).where(
                P2PTrade.status == TradeStatus.COMPLETED,
                P2PTrade.completed_at >= yesterday
            )
        )
        
        # 24h trades count
        trades_24h = await session.scalar(
            select(func.count(P2PTrade.id)).where(
                P2PTrade.status == TradeStatus.COMPLETED,
                P2PTrade.completed_at >= yesterday
            )
        )
        
        # Active traders
        active_traders = await session.scalar(
            select(func.count(func.distinct(P2POrder.user_id))).where(
                P2POrder.status == OrderStatus.ACTIVE
            )
        )
        
        return {
            "active_orders": active_orders or 0,
            "volume_24h_usd": float(volume_24h or 0),
            "trades_24h": trades_24h or 0,
            "active_traders": active_traders or 0
        }


# ==================== GLOBAL INSTANCE ====================

p2p_service = P2PService()
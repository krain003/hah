"""
NEXUS WALLET - Database Models
Real production models for all features
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
import uuid

from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Boolean,
    DateTime, Numeric, ForeignKey, Index, Float
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


# ==================== ENUMS ====================

class UserStatus(PyEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BANNED = "banned"


class TransactionStatus(PyEnum):
    PENDING = "pending"
    CONFIRMING = "confirming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TransactionType(PyEnum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    SEND = "send"
    RECEIVE = "receive"
    SWAP = "swap"
    P2P_BUY = "p2p_buy"
    P2P_SELL = "p2p_sell"
    ESCROW_LOCK = "escrow_lock"
    ESCROW_RELEASE = "escrow_release"


class OrderStatus(PyEnum):
    ACTIVE = "active"
    PARTIALLY_FILLED = "partially_filled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class OrderType(PyEnum):
    BUY = "buy"
    SELL = "sell"


class TradeStatus(PyEnum):
    PENDING = "pending"
    PAID = "paid"
    CONFIRMING = "confirming"
    COMPLETED = "completed"
    DISPUTED = "disputed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class EscrowStatus(PyEnum):
    CREATED = "created"
    FUNDED = "funded"
    RELEASED = "released"
    DISPUTED = "disputed"
    REFUNDED = "refunded"
    EXPIRED = "expired"


# ==================== USER ====================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    language_code = Column(String(10), default="en")

    status = Column(String(20), default="active")
    default_currency = Column(String(10), default="USD")
    notifications_enabled = Column(Boolean, default=True)

    pin_hash = Column(String(255), nullable=True)
    two_factor_enabled = Column(Boolean, default=False)
    two_factor_secret = Column(String(255), nullable=True)

    referral_code = Column(String(20), unique=True, nullable=True)
    referred_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Trading stats
    vip_tier = Column(Integer, default=0)
    total_volume_usd = Column(Numeric(28, 2), default=0)
    total_trades = Column(Integer, default=0)
    successful_trades = Column(Integer, default=0)
    rating = Column(Float, default=100.0)  # percentage

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_active_at = Column(DateTime, nullable=True)

    # Relationships
    wallets = relationship("Wallet", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")
    p2p_orders = relationship("P2POrder", back_populates="user")
    
    __table_args__ = (
        Index('idx_user_telegram', 'telegram_id'),
        Index('idx_user_referral', 'referral_code'),
    )


# ==================== WALLET ====================

class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    network = Column(String(50), nullable=False, index=True)
    address = Column(String(255), nullable=False)

    encrypted_private_key = Column(Text, nullable=False)
    encrypted_mnemonic = Column(Text, nullable=True)
    derivation_path = Column(String(100), nullable=True)

    is_active = Column(Boolean, default=True)
    is_imported = Column(Boolean, default=False)
    label = Column(String(100), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="wallets")
    balances = relationship("WalletBalance", back_populates="wallet", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_wallet_user', 'user_id'),
        Index('idx_wallet_address', 'address'),
        Index('idx_wallet_network', 'network'),
    )


class WalletBalance(Base):
    __tablename__ = "wallet_balances"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    wallet_id = Column(String(36), ForeignKey("wallets.id"), nullable=False)

    token_symbol = Column(String(20), nullable=False)
    token_address = Column(String(255), nullable=True)  # None for native tokens
    token_decimals = Column(Integer, default=18)

    balance = Column(Numeric(38, 18), default=0)
    locked_balance = Column(Numeric(38, 18), default=0)  # Locked in escrow
    balance_usd = Column(Numeric(28, 2), default=0)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    wallet = relationship("Wallet", back_populates="balances")

    __table_args__ = (
        Index('idx_balance_wallet', 'wallet_id'),
        Index('idx_balance_token', 'token_symbol'),
    )


# ==================== TRANSACTION ====================

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    wallet_id = Column(String(36), ForeignKey("wallets.id"), nullable=True)

    tx_type = Column(String(20), nullable=False)  # send, receive, swap, etc.
    status = Column(String(20), default="pending")

    network = Column(String(50), nullable=False)
    tx_hash = Column(String(255), nullable=True, index=True)
    block_number = Column(BigInteger, nullable=True)
    confirmations = Column(Integer, default=0)

    token_symbol = Column(String(20), nullable=False)
    token_address = Column(String(255), nullable=True)

    amount = Column(Numeric(38, 18), nullable=False)
    amount_usd = Column(Numeric(28, 2), nullable=True)

    from_address = Column(String(255), nullable=True)
    to_address = Column(String(255), nullable=True)

    fee_amount = Column(Numeric(38, 18), nullable=True)
    fee_token = Column(String(20), nullable=True)
    fee_usd = Column(Numeric(28, 2), nullable=True)

    # For swaps
    swap_to_token = Column(String(20), nullable=True)
    swap_to_amount = Column(Numeric(38, 18), nullable=True)

    # For P2P
    p2p_trade_id = Column(String(36), nullable=True)

    memo = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    confirmed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="transactions")

    __table_args__ = (
        Index('idx_tx_user', 'user_id'),
        Index('idx_tx_hash', 'tx_hash'),
        Index('idx_tx_status', 'status'),
        Index('idx_tx_created', 'created_at'),
    )


# ==================== P2P ORDER ====================

class P2POrder(Base):
    __tablename__ = "p2p_orders"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    order_type = Column(String(10), nullable=False)  # buy, sell
    status = Column(String(20), default="active")

    # What crypto
    network = Column(String(50), nullable=False)
    token_symbol = Column(String(20), nullable=False)

    # Amount
    total_amount = Column(Numeric(38, 18), nullable=False)
    available_amount = Column(Numeric(38, 18), nullable=False)  # Remaining
    filled_amount = Column(Numeric(38, 18), default=0)
    min_trade_amount = Column(Numeric(38, 18), nullable=True)
    max_trade_amount = Column(Numeric(38, 18), nullable=True)

    # Price
    fiat_currency = Column(String(10), nullable=False)
    price_per_unit = Column(Numeric(28, 8), nullable=False)
    is_fixed_price = Column(Boolean, default=True)
    margin_percent = Column(Float, nullable=True)  # For floating price

    # Payment methods (JSON string)
    payment_methods = Column(Text, nullable=False)  # JSON: ["bank", "card"]
    payment_details = Column(Text, nullable=True)  # JSON with payment info

    # Terms
    terms = Column(Text, nullable=True)
    auto_reply = Column(Text, nullable=True)
    time_limit_minutes = Column(Integer, default=30)

    # Stats
    trades_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="p2p_orders")
    trades = relationship("P2PTrade", back_populates="order")

    __table_args__ = (
        Index('idx_order_user', 'user_id'),
        Index('idx_order_status', 'status'),
        Index('idx_order_type', 'order_type'),
        Index('idx_order_token', 'token_symbol'),
        Index('idx_order_fiat', 'fiat_currency'),
    )


# ==================== P2P TRADE ====================

class P2PTrade(Base):
    __tablename__ = "p2p_trades"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String(36), ForeignKey("p2p_orders.id"), nullable=False)
    escrow_id = Column(String(36), ForeignKey("escrow.id"), nullable=True)

    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Trade details
    crypto_amount = Column(Numeric(38, 18), nullable=False)
    fiat_amount = Column(Numeric(28, 2), nullable=False)
    price_per_unit = Column(Numeric(28, 8), nullable=False)
    fiat_currency = Column(String(10), nullable=False)
    
    token_symbol = Column(String(20), nullable=False)
    network = Column(String(50), nullable=False)

    payment_method = Column(String(50), nullable=False)
    payment_details = Column(Text, nullable=True)

    status = Column(String(20), default="pending")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)
    released_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)

    # Dispute
    disputed_at = Column(DateTime, nullable=True)
    dispute_reason = Column(Text, nullable=True)
    dispute_resolved_at = Column(DateTime, nullable=True)
    dispute_winner_id = Column(Integer, nullable=True)

    # Ratings
    buyer_rating = Column(Integer, nullable=True)  # 1-5
    seller_rating = Column(Integer, nullable=True)
    buyer_comment = Column(Text, nullable=True)
    seller_comment = Column(Text, nullable=True)

    order = relationship("P2POrder", back_populates="trades")
    escrow = relationship("Escrow", back_populates="trade")
    messages = relationship("P2PMessage", back_populates="trade", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_trade_order', 'order_id'),
        Index('idx_trade_buyer', 'buyer_id'),
        Index('idx_trade_seller', 'seller_id'),
        Index('idx_trade_status', 'status'),
    )


# ==================== P2P MESSAGES ====================

class P2PMessage(Base):
    __tablename__ = "p2p_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    trade_id = Column(String(36), ForeignKey("p2p_trades.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    message = Column(Text, nullable=False)
    is_system = Column(Boolean, default=False)  # System messages

    created_at = Column(DateTime, default=datetime.utcnow)
    read_at = Column(DateTime, nullable=True)

    trade = relationship("P2PTrade", back_populates="messages")

    __table_args__ = (
        Index('idx_message_trade', 'trade_id'),
    )


# ==================== ESCROW ====================

class Escrow(Base):
    __tablename__ = "escrow"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # What's locked
    network = Column(String(50), nullable=False)
    token_symbol = Column(String(20), nullable=False)
    token_address = Column(String(255), nullable=True)
    amount = Column(Numeric(38, 18), nullable=False)

    # From internal wallet
    from_wallet_id = Column(String(36), ForeignKey("wallets.id"), nullable=False)
    from_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    to_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    status = Column(String(20), default="created")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    funded_at = Column(DateTime, nullable=True)
    released_at = Column(DateTime, nullable=True)
    refunded_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)

    # Release transaction
    release_tx_hash = Column(String(255), nullable=True)
    release_to_address = Column(String(255), nullable=True)

    trade = relationship("P2PTrade", back_populates="escrow", uselist=False)

    __table_args__ = (
        Index('idx_escrow_status', 'status'),
        Index('idx_escrow_from', 'from_user_id'),
        Index('idx_escrow_to', 'to_user_id'),
    )


# ==================== PRICE CACHE ====================

class PriceCache(Base):
    """Cache for crypto prices"""
    __tablename__ = "price_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_symbol = Column(String(20), nullable=False, index=True)
    fiat_currency = Column(String(10), default="USD")
    
    price = Column(Numeric(28, 8), nullable=False)
    price_change_24h = Column(Float, nullable=True)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_price_token_fiat', 'token_symbol', 'fiat_currency'),
    )


# ==================== SWAP ====================

class Swap(Base):
    """Track swap transactions"""
    __tablename__ = "swaps"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    wallet_id = Column(String(36), ForeignKey("wallets.id"), nullable=False)
    transaction_id = Column(String(36), ForeignKey("transactions.id"), nullable=True)

    network = Column(String(50), nullable=False)
    
    # From
    from_token = Column(String(20), nullable=False)
    from_token_address = Column(String(255), nullable=True)
    from_amount = Column(Numeric(38, 18), nullable=False)
    
    # To
    to_token = Column(String(20), nullable=False)
    to_token_address = Column(String(255), nullable=True)
    to_amount = Column(Numeric(38, 18), nullable=True)  # Actual received
    to_amount_expected = Column(Numeric(38, 18), nullable=False)

    # DEX info
    dex_name = Column(String(50), nullable=True)  # 1inch, Jupiter, etc.
    slippage = Column(Float, default=0.5)
    
    # Execution
    status = Column(String(20), default="pending")
    tx_hash = Column(String(255), nullable=True)
    
    fee_amount = Column(Numeric(38, 18), nullable=True)
    fee_usd = Column(Numeric(28, 2), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        Index('idx_swap_user', 'user_id'),
        Index('idx_swap_status', 'status'),
    )
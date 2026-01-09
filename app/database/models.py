"""
NEXUS WALLET - Database Models (Complete Edition)
Full schema with P2P, Shops, Direct Purchase, Reviews, and more
"""

import uuid
import enum
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, ForeignKey, Boolean,
    DateTime, Numeric, ForeignKey, Index, Float,
    Enum as SAEnum,
    UniqueConstraint, CheckConstraint, JSON
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


# ==================== ENUMERATIONS ====================

class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BANNED = "banned"
    PENDING_VERIFICATION = "pending_verification"


class TransactionStatus(str, enum.Enum):
    PENDING = "pending"
    BROADCASTED = "broadcasted"
    CONFIRMING = "confirming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REVERTED = "reverted"


class TransactionType(str, enum.Enum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    SEND = "send"
    RECEIVE = "receive"
    SWAP = "swap"
    P2P_BUY = "p2p_buy"
    P2P_SELL = "p2p_sell"
    ESCROW_LOCK = "escrow_lock"
    ESCROW_RELEASE = "escrow_release"
    DIRECT_PURCHASE = "direct_purchase"
    SHOP_PURCHASE = "shop_purchase"
    COMMISSION = "commission"


class OrderStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class TradeStatus(str, enum.Enum):
    PENDING = "pending"
    AWAITING_PAYMENT = "awaiting_payment"
    PAYMENT_SENT = "payment_sent"
    PAYMENT_CONFIRMED = "payment_confirmed"
    COMPLETED = "completed"
    DISPUTED = "disputed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REFUNDED = "refunded"


class DisputeStatus(str, enum.Enum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    RESOLVED_BUYER = "resolved_buyer"
    RESOLVED_SELLER = "resolved_seller"
    CLOSED = "closed"


class EscrowStatus(str, enum.Enum):
    LOCKED = "locked"
    RELEASED = "released"
    REFUNDED = "refunded"
    DISPUTED = "disputed"


class ShopStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class ShopApplicationStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PaymentMethodType(str, enum.Enum):
    """Payment method types for P2P"""
    BANK_TRANSFER = "bank_transfer"
    CARD = "card"
    CASH = "cash"
    SBP = "sbp"
    QIWI = "qiwi"
    YOOMONEY = "yoomoney"
    PAYPAL = "paypal"
    WISE = "wise"
    REVOLUT = "revolut"
    CRYPTO = "crypto"
    OTHER = "other"


class OrderType(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


# ==================== USER SYSTEM ====================

class User(Base):
    """Main User Model with full profile and trading stats"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True, index=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)

    # Regional Settings
    language_code = Column(String(10), default="en", index=True)
    default_currency = Column(String(10), default="USD")
    timezone = Column(String(50), default="UTC")

    # Security & Auth
    status = Column(SAEnum(UserStatus), default=UserStatus.ACTIVE, index=True)
    password_hash = Column(String(255), nullable=True)
    pin_hash = Column(String(255), nullable=True)
    two_factor_enabled = Column(Boolean, default=False)
    two_factor_secret = Column(String(255), nullable=True)

    # Referral System
    referral_code = Column(String(20), unique=True, nullable=True, index=True)
    referred_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    referral_bonus_earned = Column(Numeric(28, 8), default=0)
    referral_count = Column(Integer, default=0)

    # Trading & Reputation
    vip_tier = Column(Integer, default=0)
    rating = Column(Float, default=100.0)
    total_reviews = Column(Integer, default=0)
    positive_reviews = Column(Integer, default=0)
    negative_reviews = Column(Integer, default=0)
    total_volume_usd = Column(Numeric(28, 2), default=0)
    total_trades_count = Column(Integer, default=0)
    successful_trades_count = Column(Integer, default=0)
    cancelled_trades_count = Column(Integer, default=0)
    disputed_trades_count = Column(Integer, default=0)
    merchant_verified = Column(Boolean, default=False)
    verified_at = Column(DateTime, nullable=True)

    # Notifications
    notifications_enabled = Column(Boolean, default=True)
    email_notifications = Column(Boolean, default=False)
    email = Column(String(255), nullable=True)

    # Shop
    has_shop = Column(Boolean, default=False)
    shop_id = Column(String(36), nullable=True)

    # Meta
    is_admin = Column(Boolean, default=False)
    is_support = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_active_at = Column(DateTime, nullable=True)
    banned_at = Column(DateTime, nullable=True)
    ban_reason = Column(Text, nullable=True)

    # Relationships
    wallets = relationship("Wallet", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user", foreign_keys="Transaction.user_id")
    p2p_orders = relationship("P2POrder", back_populates="user")
    trades_as_buyer = relationship("P2PTrade", foreign_keys="P2PTrade.buyer_id", back_populates="buyer")
    trades_as_seller = relationship("P2PTrade", foreign_keys="P2PTrade.seller_id", back_populates="seller")
    trade_positions = relationship("TradePosition", back_populates="user")
    reviews_given = relationship("Review", foreign_keys="Review.reviewer_id", back_populates="reviewer")
    reviews_received = relationship("Review", foreign_keys="Review.reviewed_id", back_populates="reviewed")
    payment_methods = relationship("PaymentMethod", back_populates="user", cascade="all, delete-orphan")
    shop = relationship("Shop", back_populates="owner", uselist=False, foreign_keys="Shop.owner_id")
    shop_applications = relationship(
        "ShopApplication",
        foreign_keys="ShopApplication.user_id",
        back_populates="user"
    )
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    direct_purchases = relationship("DirectPurchase", back_populates="user")
    swaps = relationship("Swap", back_populates="user")
    exchange_orders = relationship("ExchangeOrder", back_populates="user")
    checks_created = relationship("NexusCheck", back_populates="creator")
    check_activations = relationship("CheckActivation", back_populates="user")
    giveaways_created = relationship("Giveaway", back_populates="creator")
    giveaway_participations = relationship("GiveawayParticipant", back_populates="user")
    giveaway_wins = relationship("GiveawayWinner", back_populates="user")

    __table_args__ = (
        CheckConstraint('rating >= 0 AND rating <= 100', name='check_rating_range'),
        Index('idx_user_status_active', 'status', postgresql_where=(status == UserStatus.ACTIVE)),
    )

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        return self.first_name or f"User#{self.id}"

    @property
    def trust_score(self) -> float:
        """Calculate trust score based on trading history"""
        if self.total_trades_count == 0:
            return 50.0

        success_rate = (self.successful_trades_count / self.total_trades_count) * 100
        dispute_penalty = self.disputed_trades_count * 5

        score = min(100, max(0, success_rate - dispute_penalty))

        if self.merchant_verified:
            score = min(100, score + 10)

        return round(score, 1)


# ==================== WALLET & BALANCES ====================

class Wallet(Base):
    """Multi-chain cryptocurrency wallet"""
    __tablename__ = "wallets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    network = Column(String(50), nullable=False, index=True)
    address = Column(String(255), nullable=False, index=True)
    public_key = Column(Text, nullable=True)

    # Security
    encrypted_private_key = Column(Text, nullable=False)
    encrypted_mnemonic = Column(Text, nullable=True)
    derivation_path = Column(String(100), nullable=True)

    # State
    label = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    is_primary = Column(Boolean, default=False)
    is_imported = Column(Boolean, default=False)

    # Nonce management for EVM
    last_nonce = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="wallets")
    balances = relationship("WalletBalance", back_populates="wallet", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_wallet_user_network', 'user_id', 'network'),
        UniqueConstraint('address', 'network', name='uq_wallet_address_network'),
    )


class WalletBalance(Base):
    """Token balances for each wallet"""
    __tablename__ = "wallet_balances"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    wallet_id = Column(String(36), ForeignKey("wallets.id"), nullable=False, index=True)

    token_symbol = Column(String(20), nullable=False, index=True)
    token_address = Column(String(255), nullable=True)
    token_name = Column(String(100), nullable=True)
    token_decimals = Column(Integer, default=18)

    balance = Column(Numeric(38, 18), default=0)
    locked = Column(Numeric(36, 18), default=0)
    
    balance_usd = Column(Numeric(28, 2), default=0)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    wallet = relationship("Wallet", back_populates="balances")

    __table_args__ = (
        Index('idx_balance_wallet_token', 'wallet_id', 'token_symbol'),
    )


# ==================== TRANSACTIONS ====================

class Transaction(Base):
    """Universal transaction ledger"""
    __tablename__ = "transactions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    wallet_id = Column(String(36), ForeignKey("wallets.id"), nullable=True)

    status = Column(SAEnum(TransactionStatus), default=TransactionStatus.PENDING)
    tx_type = Column(SAEnum(TransactionType), nullable=False)

    network = Column(String(50), nullable=False)
    tx_hash = Column(String(255), nullable=True, index=True)
    block_number = Column(BigInteger, nullable=True)
    confirmations = Column(Integer, default=0)

    # Asset Info
    token_symbol = Column(String(20), nullable=False)
    token_address = Column(String(255), nullable=True)
    amount = Column(Numeric(38, 18), nullable=False)
    amount_usd = Column(Numeric(28, 2), nullable=True)

    # Routing
    from_address = Column(String(255), nullable=True)
    to_address = Column(String(255), nullable=True)

    # Fees
    fee_amount = Column(Numeric(38, 18), nullable=True)
    fee_token = Column(String(20), nullable=True)
    fee_usd = Column(Numeric(28, 2), nullable=True)

    # References
    p2p_trade_id = Column(String(36), nullable=True)
    shop_order_id = Column(String(36), nullable=True)
    direct_purchase_id = Column(String(36), nullable=True)

    # Swap specific
    swap_to_token = Column(String(20), nullable=True)
    swap_to_amount = Column(Numeric(38, 18), nullable=True)

    # Metadata
    memo = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    internal_ref = Column(String(100), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    confirmed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="transactions", foreign_keys=[user_id])

    __table_args__ = (
        Index('idx_tx_user_created', 'user_id', 'created_at'),
        Index('idx_tx_status_type', 'status', 'tx_type'),
    )


# ==================== PAYMENT METHODS ====================

class PaymentMethod(Base):
    """User payment methods for P2P trading"""
    __tablename__ = "payment_methods"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    type = Column(SAEnum(PaymentMethodType), nullable=False)
    name = Column(String(100), nullable=False)

    # Details
    account_name = Column(String(255), nullable=True)
    account_number = Column(String(255), nullable=True)
    bank_name = Column(String(100), nullable=True)
    additional_info = Column(Text, nullable=True)

    # For display
    icon = Column(String(50), nullable=True)
    color = Column(String(20), nullable=True)

    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="payment_methods")

    __table_args__ = (
        Index('idx_payment_user_active', 'user_id', 'is_active'),
    )


# ==================== P2P TRADING SYSTEM ====================

class P2POrder(Base):
    """P2P market advertisements"""
    __tablename__ = "p2p_orders"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    order_type = Column(SAEnum(OrderType), nullable=False, index=True)
    status = Column(SAEnum(OrderStatus), default=OrderStatus.ACTIVE, index=True)

    # Crypto Info
    network = Column(String(50), nullable=False, index=True)
    token_symbol = Column(String(20), nullable=False, index=True)
    token_address = Column(String(255), nullable=True)

    # Volume
    total_amount = Column(Numeric(38, 18), nullable=False)
    available_amount = Column(Numeric(38, 18), nullable=False)
    completed_amount = Column(Numeric(38, 18), default=0)
    min_limit = Column(Numeric(28, 2), nullable=False)
    max_limit = Column(Numeric(28, 2), nullable=False)

    # Pricing
    fiat_currency = Column(String(10), nullable=False, index=True)
    price_per_unit = Column(Numeric(28, 8), nullable=False)
    is_fixed_price = Column(Boolean, default=True)
    margin_percentage = Column(Float, nullable=True)

    # Payment
    payment_methods = Column(JSON, nullable=False)
    payment_time_limit = Column(Integer, default=30)

    # Terms
    terms_of_trade = Column(Text, nullable=True)
    auto_reply_msg = Column(Text, nullable=True)

    # Stats
    total_trades = Column(Integer, default=0)
    completed_trades = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="p2p_orders")
    trades = relationship("P2PTrade", back_populates="order")

    __table_args__ = (
        Index('idx_p2p_order_search', 'token_symbol', 'fiat_currency', 'status', 'order_type'),
        Index('idx_p2p_order_user', 'user_id', 'status'),
    )


class P2PTrade(Base):
    """Individual P2P trade instances"""
    __tablename__ = "p2p_trades"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String(36), ForeignKey("p2p_orders.id"), nullable=False, index=True)

    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Trade details
    network = Column(String(50), nullable=False)
    token_symbol = Column(String(20), nullable=False)
    crypto_amount = Column(Numeric(38, 18), nullable=False)
    fiat_amount = Column(Numeric(28, 2), nullable=False)
    fiat_currency = Column(String(10), nullable=False)
    price_at_trade = Column(Numeric(28, 8), nullable=False)

    status = Column(SAEnum(TradeStatus), default=TradeStatus.PENDING, index=True)

    # Payment
    payment_method_id = Column(String(36), nullable=True)
    payment_method_name = Column(String(100), nullable=True)
    payment_details = Column(Text, nullable=True)
    payment_proof = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    payment_sent_at = Column(DateTime, nullable=True)
    payment_confirmed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)

    # Cancellation
    cancelled_by = Column(Integer, nullable=True)
    cancel_reason = Column(Text, nullable=True)

    order = relationship("P2POrder", back_populates="trades")
    buyer = relationship("User", foreign_keys=[buyer_id], back_populates="trades_as_buyer")
    seller = relationship("User", foreign_keys=[seller_id], back_populates="trades_as_seller")
    messages = relationship("P2PMessage", back_populates="trade", cascade="all, delete-orphan")
    escrow = relationship("Escrow", back_populates="trade", uselist=False)
    dispute = relationship("Dispute", back_populates="trade", uselist=False)
    reviews = relationship("Review", back_populates="trade")

    __table_args__ = (
        Index('idx_trade_buyer', 'buyer_id', 'status'),
        Index('idx_trade_seller', 'seller_id', 'status'),
        Index('idx_trade_status', 'status', 'created_at'),
    )


class P2PMessage(Base):
    """Chat messages for P2P trades"""
    __tablename__ = "p2p_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    trade_id = Column(String(36), ForeignKey("p2p_trades.id"), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    content = Column(Text, nullable=True)

    # Attachments
    attachment_type = Column(String(20), nullable=True)
    attachment_file_id = Column(String(255), nullable=True)
    attachment_url = Column(Text, nullable=True)

    is_system = Column(Boolean, default=False)
    is_payment_proof = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    read_at = Column(DateTime, nullable=True)

    trade = relationship("P2PTrade", back_populates="messages")

    __table_args__ = (
        Index('idx_message_trade', 'trade_id', 'created_at'),
    )


class Escrow(Base):
    """Escrow for P2P trades"""
    __tablename__ = "escrows"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    trade_id = Column(String(36), ForeignKey("p2p_trades.id"), nullable=False, unique=True)

    network = Column(String(50), nullable=False)
    token_symbol = Column(String(20), nullable=False)
    amount = Column(Numeric(38, 18), nullable=False)

    seller_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    status = Column(SAEnum(EscrowStatus), default=EscrowStatus.LOCKED)

    # Transaction references
    lock_tx_id = Column(String(36), nullable=True)
    release_tx_id = Column(String(36), nullable=True)
    refund_tx_id = Column(String(36), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    released_at = Column(DateTime, nullable=True)
    refunded_at = Column(DateTime, nullable=True)

    trade = relationship("P2PTrade", back_populates="escrow")


class Dispute(Base):
    """Disputes for P2P trades"""
    __tablename__ = "disputes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    trade_id = Column(String(36), ForeignKey("p2p_trades.id"), nullable=False, unique=True)

    opened_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    reason = Column(Text, nullable=False)

    status = Column(SAEnum(DisputeStatus), default=DisputeStatus.OPEN)

    # Resolution
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    winner_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Evidence
    evidence = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    trade = relationship("P2PTrade", back_populates="dispute")


# ==================== REVIEWS ====================

class Review(Base):
    """Reviews for P2P trades"""
    __tablename__ = "reviews"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    trade_id = Column(String(36), ForeignKey("p2p_trades.id"), nullable=False)

    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    reviewed_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    rating = Column(Integer, nullable=False)
    is_positive = Column(Boolean, nullable=False)
    comment = Column(Text, nullable=True)

    # Trade context
    trade_type = Column(String(10), nullable=False)
    trade_amount_usd = Column(Numeric(28, 2), nullable=True)

    is_visible = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    trade = relationship("P2PTrade", back_populates="reviews")
    reviewer = relationship("User", foreign_keys=[reviewer_id], back_populates="reviews_given")
    reviewed = relationship("User", foreign_keys=[reviewed_id], back_populates="reviews_received")

    __table_args__ = (
        UniqueConstraint('trade_id', 'reviewer_id', name='uq_review_trade_reviewer'),
        CheckConstraint('rating >= 1 AND rating <= 5', name='check_review_rating'),
        Index('idx_review_reviewed', 'reviewed_id', 'created_at'),
    )


# ==================== SHOPS ====================

class Shop(Base):
    """Mini-shops for verified merchants"""
    __tablename__ = "shops"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)

    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    logo_file_id = Column(String(255), nullable=True)
    banner_file_id = Column(String(255), nullable=True)

    status = Column(SAEnum(ShopStatus), default=ShopStatus.PENDING)

    # Supported tokens
    supported_tokens = Column(JSON, nullable=False)

    # Pricing settings
    default_margin = Column(Float, default=2.0)
    min_order_usd = Column(Numeric(28, 2), default=10)
    max_order_usd = Column(Numeric(28, 2), default=10000)

    # Stats
    total_orders = Column(Integer, default=0)
    completed_orders = Column(Integer, default=0)
    total_volume_usd = Column(Numeric(28, 2), default=0)
    rating = Column(Float, default=5.0)

    # Commission
    commission_rate = Column(Float, default=20.0)
    total_commission_paid = Column(Numeric(28, 2), default=0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    suspended_at = Column(DateTime, nullable=True)

    owner = relationship("User", back_populates="shop", foreign_keys=[owner_id])
    products = relationship("ShopProduct", back_populates="shop", cascade="all, delete-orphan")
    orders = relationship("ShopOrder", back_populates="shop")


class ShopProduct(Base):
    """Products in a shop"""
    __tablename__ = "shop_products"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    shop_id = Column(String(36), ForeignKey("shops.id"), nullable=False, index=True)

    network = Column(String(50), nullable=False)
    token_symbol = Column(String(20), nullable=False)
    token_address = Column(String(255), nullable=True)

    # Pricing
    price_type = Column(String(20), default="market")
    fixed_price_usd = Column(Numeric(28, 8), nullable=True)
    margin_percentage = Column(Float, default=2.0)

    # Stock
    available_amount = Column(Numeric(38, 18), default=0)
    min_purchase = Column(Numeric(38, 18), nullable=True)
    max_purchase = Column(Numeric(38, 18), nullable=True)

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    shop = relationship("Shop", back_populates="products")


class ShopOrder(Base):
    """Orders from shops"""
    __tablename__ = "shop_orders"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    shop_id = Column(String(36), ForeignKey("shops.id"), nullable=False, index=True)
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey("shop_products.id"), nullable=False)

    # Order details
    network = Column(String(50), nullable=False)
    token_symbol = Column(String(20), nullable=False)
    amount = Column(Numeric(38, 18), nullable=False)
    price_usd = Column(Numeric(28, 2), nullable=False)

    # Commission
    commission_amount = Column(Numeric(28, 2), nullable=False)
    seller_receives = Column(Numeric(28, 2), nullable=False)

    status = Column(String(20), default="pending")

    # Buyer's receiving address
    buyer_address = Column(String(255), nullable=False)

    # Transaction
    tx_hash = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    shop = relationship("Shop", back_populates="orders")


class ShopApplication(Base):
    """Applications to open a shop"""
    __tablename__ = "shop_applications"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    shop_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # Why they want to open a shop
    motivation = Column(Text, nullable=False)

    # Proposed tokens to sell
    proposed_tokens = Column(JSON, nullable=False)

    # ВОТ ИСПРАВЛЕННАЯ СТРОКА:
    status = Column(SAEnum(ShopApplicationStatus), default=ShopApplicationStatus.PENDING, nullable=False)

    # Review
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    review_notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)

    user = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="shop_applications"
    )
    reviewer = relationship(
        "User",
        foreign_keys=[reviewed_by]
    )


# ==================== DIRECT PURCHASE ====================

class DirectPurchase(Base):
    """Direct crypto purchases through official channels"""
    __tablename__ = "direct_purchases"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # What user is buying
    network = Column(String(50), nullable=False)
    token_symbol = Column(String(20), nullable=False)
    amount = Column(Numeric(38, 18), nullable=False)

    # Price and fees
    price_usd = Column(Numeric(28, 2), nullable=False)
    platform_fee_usd = Column(Numeric(28, 2), nullable=False)
    network_fee_usd = Column(Numeric(28, 2), nullable=True)
    total_usd = Column(Numeric(28, 2), nullable=False)

    # Payment method
    payment_provider = Column(String(50), nullable=False)
    payment_method = Column(String(50), nullable=True)
    provider_order_id = Column(String(255), nullable=True)

    # Receiving address
    receiving_address = Column(String(255), nullable=False)

    status = Column(String(20), default="pending")

    # Transaction
    tx_hash = Column(String(255), nullable=True)

    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="direct_purchases")


class Swap(Base):
    """DEX/Aggregation swap history"""
    __tablename__ = "swap_executions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    network = Column(String(50), nullable=False)
    from_token = Column(String(20), nullable=False)
    from_amount = Column(Numeric(38, 18), nullable=False)

    to_token = Column(String(20), nullable=False)
    to_amount_expected = Column(Numeric(38, 18), nullable=False)
    to_amount_received = Column(Numeric(38, 18), nullable=True)

    slippage = Column(Float, default=0.5)
    tx_hash = Column(String(255), nullable=True)
    status = Column(SAEnum(TransactionStatus), default=TransactionStatus.PENDING)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="swaps")


# ==================== SYSTEM ====================

class SystemConfig(Base):
    """System configuration storage"""
    __tablename__ = "system_configs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<SystemConfig {self.key}>"


class FeeConfig(Base):
    """Fee configuration for different operations"""
    __tablename__ = "fee_config"

    id = Column(Integer, primary_key=True, autoincrement=True)

    operation_type = Column(String(50), unique=True, nullable=False)

    fee_type = Column(String(20), default="percentage")
    fee_value = Column(Numeric(10, 4), nullable=False)
    min_fee = Column(Numeric(28, 8), nullable=True)
    max_fee = Column(Numeric(28, 8), nullable=True)

    # Network-specific overrides
    network_overrides = Column(JSON, nullable=True)

    is_active = Column(Boolean, default=True)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PriceCache(Base):
    """Cached price data"""
    __tablename__ = "price_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_symbol = Column(String(20), nullable=False, unique=True, index=True)
    price_usd = Column(Numeric(28, 10), nullable=False)
    change_24h = Column(Float, nullable=True)
    volume_24h = Column(Numeric(28, 2), nullable=True)
    market_cap = Column(Numeric(38, 2), nullable=True)

    source = Column(String(50), default="binance")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Notification(Base):
    """User notifications"""
    __tablename__ = "notifications"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    title = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)
    type = Column(String(50), default="info")

    # Action
    action_type = Column(String(50), nullable=True)
    action_data = Column(JSON, nullable=True)

    is_read = Column(Boolean, default=False)
    is_sent = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    read_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="notifications")

    __table_args__ = (
        Index('idx_notification_user_unread', 'user_id', 'is_read'),
    )


class AuditLog(Base):
    """Audit log for admin actions"""
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String(100), nullable=False)
    target_type = Column(String(50), nullable=True)
    target_id = Column(String(100), nullable=True)

    details = Column(JSON, nullable=True)
    ip_address = Column(String(50), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_audit_admin', 'admin_id', 'created_at'),
        Index('idx_audit_action', 'action', 'created_at'),
    )


class TradePosition(Base):
    """Futures/Margin positions"""
    __tablename__ = "trade_positions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    symbol = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)
    leverage = Column(Integer, default=1)

    # Financials
    margin_amount = Column(Float, nullable=False)
    position_size = Column(Float, nullable=False)

    # Entry/Exit
    entry_price = Column(Float, nullable=False)
    liquidation_price = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)

    # Current State
    is_open = Column(Boolean, default=True)
    realized_pnl = Column(Float, default=0.0)
    close_reason = Column(String(50), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="trade_positions")

# ==================== EXCHANGE MODELS ====================

class ExchangeOrder(Base):
    """Exchange order model"""
    __tablename__ = "exchange_orders"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    
    pair = Column(String(20), nullable=False, index=True)  # e.g., "TON/USDT"
    side = Column(String(10), nullable=False)  # "buy" or "sell"
    order_type = Column(String(10), nullable=False, default="limit")  # "limit" or "market"
    
    price = Column(Numeric(36, 18), nullable=False)
    amount = Column(Numeric(36, 18), nullable=False)
    remaining = Column(Numeric(36, 18), nullable=False)
    filled = Column(Numeric(36, 18), nullable=False, default=0)
    
    status = Column(String(20), nullable=False, default="open", index=True)  # open, filled, cancelled, partial
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="exchange_orders")
    trades_as_buyer = relationship("Trade", foreign_keys="Trade.buyer_order_id", back_populates="buyer_order")
    trades_as_seller = relationship("Trade", foreign_keys="Trade.seller_order_id", back_populates="seller_order")


class Trade(Base):
    """Executed trade model"""
    __tablename__ = "trades"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    pair = Column(String(20), nullable=False, index=True)
    buyer_order_id = Column(String(36), ForeignKey("exchange_orders.id"), nullable=False)
    seller_order_id = Column(String(36), ForeignKey("exchange_orders.id"), nullable=False)
    buyer_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    seller_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    
    price = Column(Numeric(36, 18), nullable=False)
    amount = Column(Numeric(36, 18), nullable=False)
    total = Column(Numeric(36, 18), nullable=False)
    fee = Column(Numeric(36, 18), default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    buyer_order = relationship("ExchangeOrder", foreign_keys=[buyer_order_id], back_populates="trades_as_buyer")
    seller_order = relationship("ExchangeOrder", foreign_keys=[seller_order_id], back_populates="trades_as_seller")


# ==================== CHECK MODELS ====================

class NexusCheck(Base):
    """Crypto check model"""
    __tablename__ = "nexus_checks"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    
    network = Column(String(20), nullable=False)
    token_symbol = Column(String(20), nullable=False)
    
    amount = Column(Numeric(36, 18), nullable=False)
    amount_per_activation = Column(Numeric(36, 18), nullable=False)
    max_activations = Column(Integer, nullable=False, default=1)
    activated_count = Column(Integer, nullable=False, default=0)
    
    code = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)
    
    status = Column(String(20), nullable=False, default="active", index=True)  # active, depleted, cancelled
    
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    
    # Relationships
    creator = relationship("User", back_populates="checks_created")
    activations = relationship("CheckActivation", back_populates="check")


class CheckActivation(Base):
    """Check activation record"""
    __tablename__ = "check_activations"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    check_id = Column(String(36), ForeignKey("nexus_checks.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    
    amount = Column(Numeric(36, 18), nullable=False)
    activated_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    check = relationship("NexusCheck", back_populates="activations")
    user = relationship("User", back_populates="check_activations")


# ==================== GIVEAWAY MODELS ====================

class Giveaway(Base):
    """Giveaway model"""
    __tablename__ = "giveaways"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    
    network = Column(String(20), nullable=False)
    token_symbol = Column(String(20), nullable=False)
    
    total_amount = Column(Numeric(36, 18), nullable=False)
    amount_per_winner = Column(Numeric(36, 18), nullable=False)
    winners_count = Column(Integer, nullable=False, default=1)
    
    code = Column(String(50), unique=True, nullable=False, index=True)
    caption = Column(Text, nullable=True)
    
    chat_id = Column(BigInteger, nullable=True)  # Chat where giveaway was posted
    message_id = Column(BigInteger, nullable=True)  # Message with giveaway
    
    status = Column(String(20), nullable=False, default="active", index=True)  # active, completed, cancelled
    
    created_at = Column(DateTime, default=datetime.utcnow)
    ends_at = Column(DateTime, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    creator = relationship("User", back_populates="giveaways_created")
    participants = relationship("GiveawayParticipant", back_populates="giveaway")
    winners = relationship("GiveawayWinner", back_populates="giveaway")


class GiveawayParticipant(Base):
    """Giveaway participant"""
    __tablename__ = "giveaway_participants"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    giveaway_id = Column(String(36), ForeignKey("giveaways.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    
    joined_at = Column(DateTime, default=datetime.utcnow)
    
    # Unique constraint - user can join giveaway only once
    __table_args__ = (
        UniqueConstraint('giveaway_id', 'user_id', name='unique_giveaway_participant'),
    )
    
    # Relationships
    giveaway = relationship("Giveaway", back_populates="participants")
    user = relationship("User", back_populates="giveaway_participations")


class GiveawayWinner(Base):
    """Giveaway winner"""
    __tablename__ = "giveaway_winners"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    giveaway_id = Column(String(36), ForeignKey("giveaways.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    
    amount = Column(Numeric(36, 18), nullable=False)
    claimed = Column(Boolean, default=True)
    
    won_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    giveaway = relationship("Giveaway", back_populates="winners")
    user = relationship("User", back_populates="giveaway_wins")

# ==================== INDEXES ====================

Index('idx_p2p_market', P2POrder.token_symbol, P2POrder.fiat_currency, P2POrder.status, P2POrder.order_type)
Index('idx_trades_active', P2PTrade.status, P2PTrade.expires_at)
Index('idx_wallet_lookup', Wallet.address, Wallet.network)
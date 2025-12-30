"""
NEXUS WALLET - Database Models
"""
from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
import uuid
from sqlalchemy import (Column, Integer, BigInteger, String, Text, Boolean, DateTime, Numeric, ForeignKey, Index, Float)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    language_code = Column(String(10), default="en")
    status = Column(String(20), default="active")
    default_currency = Column(String(10), default="USD")
    pin_hash = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    wallets = relationship("Wallet", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")

class Wallet(Base):
    __tablename__ = "wallets"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    network = Column(String(50), nullable=False, index=True)
    address = Column(String(255), nullable=False)
    encrypted_private_key = Column(Text, nullable=False)
    encrypted_mnemonic = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", back_populates="wallets")
    balances = relationship("WalletBalance", back_populates="wallet")

class WalletBalance(Base):
    __tablename__ = "wallet_balances"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    wallet_id = Column(String(36), ForeignKey("wallets.id"), nullable=False)
    token_symbol = Column(String(20), nullable=False)
    balance = Column(Numeric(38, 18), default=0)
    wallet = relationship("Wallet", back_populates="balances")

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tx_type = Column(String(20), nullable=False)
    status = Column(String(20), default="pending")
    network = Column(String(50), nullable=False)
    token_symbol = Column(String(20), nullable=False)
    amount = Column(Numeric(38, 18), nullable=False)
    tx_hash = Column(String(255), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", back_populates="transactions")
# ==================== admin_test.py ====================
"""
NEXUS WALLET - Admin Test Mode Commands
Complete testing, development and shop management panel
"""

from __future__ import annotations

import asyncio
import random
import string
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple, TYPE_CHECKING

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
import structlog

from sqlalchemy import select, update, delete, func, and_, or_
from sqlalchemy.orm import selectinload

from database.connection import db_manager
from database.models import (
    User, Wallet, WalletBalance, Transaction, TransactionType,
    TransactionStatus, UserStatus,
    Shop, ShopStatus, ShopProduct, ShopOrder,
    ShopApplication, ShopApplicationStatus
)
from config.settings import settings
from blockchain.wallet_manager import wallet_manager, NETWORKS

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)
router = Router(name="admin_test")


# ==================== CONSTANTS ====================

class AdminConfig:
    """Admin panel configuration"""
    MAX_TEST_USERS = 50
    MAX_SIMULATED_TXS = 100
    MAX_AIRDROP_AMOUNT = Decimal("10000")
    TEST_USER_ID_PREFIX = -1  # Negative IDs for test users


class BypassConfig:
    """Bypass requirements configuration"""
    DAYS_OLD = 60
    TOTAL_TRADES = 200
    SUCCESSFUL_TRADES = 200
    VOLUME_USD = Decimal("75000.00")
    RATING = Decimal("100.0")
    DISPUTES = 0


SHOP_REQUIREMENTS = {
    "min_trades": 50,
    "min_volume": Decimal("10000"),
    "min_success_rate": Decimal("95.0"),
    "min_rating": Decimal("90.0"),
    "min_account_age_days": 30,
    "max_disputes": 0
}


# ==================== MODEL FIELD DETECTION ====================

def get_model_fields(model) -> set:
    """Get all available fields for a SQLAlchemy model"""
    try:
        from sqlalchemy import inspect
        mapper = inspect(model)
        return {c.key for c in mapper.columns}
    except Exception as e:
        logger.warning(f"Failed to get fields for {model}: {e}")
        return set()


# Cache model fields at module load
USER_FIELDS = get_model_fields(User)
TX_FIELDS = get_model_fields(Transaction)
WALLET_BALANCE_FIELDS = get_model_fields(WalletBalance)
WALLET_FIELDS = get_model_fields(Wallet)


# ==================== HELPER FUNCTIONS ====================

def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id in settings.ADMIN_IDS


def create_wallet_balance_kwargs(
    wallet_id: str,
    token_symbol: str,
    balance: Decimal,
    decimals: int = 18,
    token_address: Optional[str] = None
) -> dict:
    """Create WalletBalance kwargs with only available fields"""
    kwargs = {
        "wallet_id": wallet_id,
        "token_symbol": token_symbol,
        "balance": balance,
    }
    
    if 'decimals' in WALLET_BALANCE_FIELDS:
        kwargs["decimals"] = decimals
    
    if 'token_address' in WALLET_BALANCE_FIELDS and token_address:
        kwargs["token_address"] = token_address
    
    if 'updated_at' in WALLET_BALANCE_FIELDS:
        kwargs["updated_at"] = datetime.utcnow()
    
    return kwargs


def create_transaction_kwargs(
    user_id: str,
    wallet_id: str,
    tx_type: TransactionType,
    network: str,
    token_symbol: str,
    amount: Decimal,
    status: TransactionStatus,
    from_address: str,
    to_address: str,
    note_text: Optional[str] = None,
    tx_hash: Optional[str] = None
) -> dict:
    """Create transaction kwargs with only available fields"""
    kwargs = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "wallet_id": wallet_id,
        "tx_type": tx_type,
        "network": network,
        "token_symbol": token_symbol,
        "amount": amount,
        "status": status,
        "from_address": from_address,
        "to_address": to_address,
    }
    
    if 'created_at' in TX_FIELDS:
        kwargs["created_at"] = datetime.utcnow()
    
    if 'completed_at' in TX_FIELDS and status == TransactionStatus.COMPLETED:
        kwargs["completed_at"] = datetime.utcnow()
    
    if 'tx_hash' in TX_FIELDS and tx_hash:
        kwargs["tx_hash"] = tx_hash
    
    if note_text:
        for field in ['note', 'description', 'memo']:
            if field in TX_FIELDS:
                kwargs[field] = note_text
                break
    
    return kwargs


# ==================== FSM STATES ====================

class AdminTestStates(StatesGroup):
    """Admin test panel states"""
    # Balance operations
    add_balance_user = State()
    add_balance_network = State()
    add_balance_amount = State()
    
    set_balance_user = State()
    set_balance_network = State()
    set_balance_amount = State()
    
    # User operations
    create_test_user_count = State()
    reset_user_input = State()
    reset_user_confirm = State()
    
    # Transaction simulation
    simulate_tx_user = State()
    simulate_tx_type = State()
    simulate_tx_network = State()
    simulate_tx_amount = State()
    simulate_tx_count = State()
    
    # Token airdrop
    airdrop_network = State()
    airdrop_amount = State()
    airdrop_confirm = State()
    
    # Bypass requirements
    bypass_requirements_user = State()
    bypass_requirements_confirm = State()
    
    # Remove requirements
    remove_requirements_user = State()
    remove_requirements_confirm = State()
    
    # Shop management
    shop_search = State()
    shop_suspend_reason = State()
    shop_edit_field = State()
    shop_edit_value = State()
    shop_fee_value = State()
    
    # Finance panel
    finance_user_search = State()
    finance_amount = State()
    finance_reason = State()
    
    # Mass credit
    mass_credit_network = State()
    mass_credit_amount = State()
    mass_credit_confirm = State()
    
    # Cleanup
    cleanup_confirm = State()


# ==================== UTILITY FUNCTIONS ====================

async def safe_edit(
    message: Message,
    text: str,
    keyboard: Optional[InlineKeyboardMarkup] = None
) -> bool:
    """Safely edit message"""
    try:
        if message.photo or message.document:
            await message.delete()
            await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            return True
        
        await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        return True
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.warning("Edit failed", error=str(e))
        return False
    except Exception as e:
        logger.error("Edit error", error=str(e))
        return False


async def safe_answer(
    callback: CallbackQuery,
    text: Optional[str] = None,
    show_alert: bool = False
) -> None:
    """Safe callback answer"""
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except Exception:
        pass


async def get_user_by_query(
    session: "AsyncSession",
    query: str
) -> Optional[User]:
    """Find user by telegram_id or username"""
    query = query.strip()
    
    if query.isdigit():
        return await session.scalar(
            select(User).where(User.telegram_id == int(query))
        )
    elif query.startswith("@"):
        return await session.scalar(
            select(User).where(User.username == query[1:])
        )
    else:
        return await session.scalar(
            select(User).where(User.username == query)
        )


def parse_decimal(value: str) -> Optional[Decimal]:
    """Parse string to Decimal"""
    try:
        cleaned = value.strip().replace(",", ".")
        result = Decimal(cleaned)
        return result if result > 0 else None
    except (InvalidOperation, ValueError):
        return None


# ==================== KEYBOARDS ====================

class AdminKeyboards:
    """Admin panel keyboards"""
    
    @staticmethod
    def main_menu() -> InlineKeyboardMarkup:
        """Test mode main menu"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Finance Panel", callback_data="admin_test:finance_menu")],
            [
                InlineKeyboardButton(text="💳 Add Balance", callback_data="admin_test:add_balance"),
                InlineKeyboardButton(text="📊 Set Balance", callback_data="admin_test:set_balance")
            ],
            [
                InlineKeyboardButton(text="🔄 Simulate TX", callback_data="admin_test:simulate_tx"),
                InlineKeyboardButton(text="🎁 Airdrop All", callback_data="admin_test:airdrop")
            ],
            [InlineKeyboardButton(text="🏪 Shop Management", callback_data="admin_test:shop_menu")],
            [
                InlineKeyboardButton(text="✅ Bypass Requirements", callback_data="admin_test:bypass_req"),
                InlineKeyboardButton(text="❌ Remove Requirements", callback_data="admin_test:remove_req")
            ],
            [
                InlineKeyboardButton(text="👤 Create Test Users", callback_data="admin_test:create_user"),
                InlineKeyboardButton(text="🗑 Reset User", callback_data="admin_test:reset_user")
            ],
            [
                InlineKeyboardButton(text="🔧 Test Networks", callback_data="admin_test:test_networks"),
                InlineKeyboardButton(text="💎 TON Faucet", callback_data="admin_test:ton_faucet")
            ],
            [
                InlineKeyboardButton(text="📋 View Test Data", callback_data="admin_test:view_data"),
                InlineKeyboardButton(text="🧹 Cleanup", callback_data="admin_test:cleanup")
            ],
            [InlineKeyboardButton(text="🔙 Admin Menu", callback_data="admin:main")]
        ])
    
    @staticmethod
    def back(callback_data: str = "admin_test:menu") -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back", callback_data=callback_data)]
        ])
    
    @staticmethod
    def cancel(callback_data: str = "admin_test:menu") -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data=callback_data)]
        ])
    
    @staticmethod
    def confirm(confirm_data: str, cancel_data: str = "admin_test:menu") -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Confirm", callback_data=confirm_data),
                InlineKeyboardButton(text="❌ Cancel", callback_data=cancel_data)
            ]
        ])
    
    @staticmethod
    def network_select(
        callback_prefix: str,
        include_all: bool = False
    ) -> InlineKeyboardMarkup:
        """Network selection keyboard"""
        buttons = []
        row = []
        
        if include_all:
            buttons.append([InlineKeyboardButton(
                text="🌐 All Networks",
                callback_data=f"{callback_prefix}:all"
            )])
        
        for network, config in NETWORKS.items():
            testnet_mark = "🧪" if getattr(config, 'is_testnet', False) else ""
            row.append(InlineKeyboardButton(
                text=f"{config.icon} {config.symbol} {testnet_mark}",
                callback_data=f"{callback_prefix}:{network}"
            ))
            if len(row) == 3:
                buttons.append(row)
                row = []
        
        if row:
            buttons.append(row)
        
        buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="admin_test:menu")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def tx_type_select() -> InlineKeyboardMarkup:
        """Transaction type selection"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📥 Deposit", callback_data="admin_test:sim_type:deposit"),
                InlineKeyboardButton(text="📤 Withdraw", callback_data="admin_test:sim_type:withdraw")
            ],
            [
                InlineKeyboardButton(text="🔄 Transfer", callback_data="admin_test:sim_type:transfer"),
                InlineKeyboardButton(text="💱 Swap", callback_data="admin_test:sim_type:swap")
            ],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_test:menu")]
        ])
    
    @staticmethod
    def finance_menu() -> InlineKeyboardMarkup:
        """Finance panel menu"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Overview", callback_data="admin_test:finance_overview")],
            [
                InlineKeyboardButton(text="💰 Credit User", callback_data="admin_test:finance_credit"),
                InlineKeyboardButton(text="💸 Debit User", callback_data="admin_test:finance_debit")
            ],
            [
                InlineKeyboardButton(text="🔄 Mass Credit", callback_data="admin_test:finance_mass_credit"),
                InlineKeyboardButton(text="📋 TX History", callback_data="admin_test:finance_history")
            ],
            [
                InlineKeyboardButton(text="🏦 Reserves", callback_data="admin_test:finance_reserves"),
                InlineKeyboardButton(text="📈 Daily Report", callback_data="admin_test:finance_daily")
            ],
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin_test:menu")]
        ])
    
    @staticmethod
    def shop_menu() -> InlineKeyboardMarkup:
        """Shop management menu"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 All Shops", callback_data="admin_test:shop_list"),
                InlineKeyboardButton(text="🔍 Search Shop", callback_data="admin_test:shop_search")
            ],
            [
                InlineKeyboardButton(text="⏳ Pending Apps", callback_data="admin_test:shop_pending"),
                InlineKeyboardButton(text="🚫 Suspended", callback_data="admin_test:shop_suspended")
            ],
            [
                InlineKeyboardButton(text="📊 Stats", callback_data="admin_test:shop_stats"),
                InlineKeyboardButton(text="💰 Fees", callback_data="admin_test:shop_fees")
            ],
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin_test:menu")]
        ])


# ==================== MAIN MENU ====================

@router.callback_query(F.data.in_({"admin_test:menu", "admin:test"}))
async def admin_test_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Test mode main menu"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    # Get stats
    stats = await _get_system_stats()
    
    # Get testnet networks
    testnet_networks = [
        n for n, c in NETWORKS.items()
        if getattr(c, 'is_testnet', False)
    ]
    
    text = f"""
🧪 <b>Test Mode Panel</b>

⚠️ <b>WARNING:</b> These commands modify database directly!
Use only for testing purposes.

<b>📊 Current Stats:</b>
├ 👥 Users: {stats['users']}
├ 💳 Wallets: {stats['wallets']}
├ 🔄 Transactions: {stats['transactions']}
├ 🏪 Active Shops: {stats['shops']}
└ ⏳ Pending Applications: {stats['pending_apps']}

<b>🧪 Testnet Networks:</b>
{', '.join([f"{NETWORKS[n].icon} {n.upper()}" for n in testnet_networks]) or 'None configured'}

Select an action:
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.main_menu())
    await safe_answer(callback)


async def _get_system_stats() -> Dict[str, int]:
    """Get system statistics"""
    try:
        async with db_manager.session() as session:
            users = await session.scalar(select(func.count(User.id))) or 0
            wallets = await session.scalar(select(func.count(Wallet.id))) or 0
            txs = await session.scalar(select(func.count(Transaction.id))) or 0
            
            shops = 0
            pending_apps = 0
            
            if Shop is not None:
                shops = await session.scalar(
                    select(func.count(Shop.id)).where(
                        Shop.status == ShopStatus.APPROVED
                    )
                ) or 0
            
            if ShopApplication is not None:
                pending_apps = await session.scalar(
                    select(func.count(ShopApplication.id)).where(
                        ShopApplication.status == ShopApplicationStatus.PENDING
                    )
                ) or 0
            
            return {
                "users": users,
                "wallets": wallets,
                "transactions": txs,
                "shops": shops,
                "pending_apps": pending_apps
            }
    except Exception as e:
        logger.warning("Failed to get stats", error=str(e))
        return {
            "users": 0, "wallets": 0, "transactions": 0,
            "shops": 0, "pending_apps": 0
        }


# ==================== FINANCE PANEL ====================

@router.callback_query(F.data == "admin_test:finance_menu")
async def finance_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Finance panel menu"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    text = """
💰 <b>Finance Panel</b>

Complete financial control and management.

<b>Actions:</b>
├ 📊 Overview - System financial stats
├ 💰 Credit User - Add funds to user
├ 💸 Debit User - Remove funds from user
├ 🔄 Mass Credit - Credit multiple users
├ 📋 TX History - Admin transaction log
├ 🏦 Reserves - View/manage reserves
└ 📈 Daily Report - Financial summary

Select an action:
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.finance_menu())
    await safe_answer(callback)


@router.callback_query(F.data == "admin_test:finance_overview")
async def finance_overview(callback: CallbackQuery) -> None:
    """Financial overview"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await safe_edit(callback.message, "⏳ Loading...")
    
    try:
        async with db_manager.session() as session:
            # Total balances by token
            result = await session.execute(
                select(
                    WalletBalance.token_symbol,
                    func.sum(WalletBalance.balance)
                ).group_by(WalletBalance.token_symbol)
            )
            balances = {row[0]: row[1] for row in result}
            
            # Transaction stats (7 days)
            week_ago = datetime.utcnow() - timedelta(days=7)
            tx_result = await session.execute(
                select(
                    Transaction.tx_type,
                    func.count(Transaction.id),
                    func.sum(Transaction.amount)
                )
                .where(Transaction.created_at >= week_ago)
                .group_by(Transaction.tx_type)
            )
            
            tx_summary = {}
            for row in tx_result:
                tx_type_str = row[0].value if hasattr(row[0], 'value') else str(row[0])
                tx_summary[tx_type_str] = {
                    "count": row[1],
                    "volume": row[2] or Decimal("0")
                }
            
            # User counts
            total_users = await session.scalar(select(func.count(User.id))) or 0
            
            # Active users in last 7 days
            active_users = 0
            for field in ['last_active', 'updated_at', 'created_at']:
                if field in USER_FIELDS:
                    active_users = await session.scalar(
                        select(func.count(User.id)).where(
                            getattr(User, field) >= week_ago
                        )
                    ) or 0
                    break
        
        text = "📊 <b>Financial Overview</b>\n\n<b>💰 Balances:</b>\n"
        
        for token, bal in sorted(balances.items()):
            text += f"├ {token}: {bal:,.4f}\n"
        
        if not balances:
            text += "├ <i>None</i>\n"
        
        text += "\n<b>📈 7-Day Stats:</b>\n"
        
        for tx_type, data in tx_summary.items():
            text += f"├ {tx_type}: {data['count']} txs\n"
        
        if not tx_summary:
            text += "├ <i>None</i>\n"
        
        text += f"\n<b>👥 Users:</b> {total_users} (active 7d: {active_users})"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_test:finance_overview")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin_test:finance_menu")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        
    except Exception as e:
        logger.error("Finance overview failed", error=str(e), exc_info=True)
        await callback.message.edit_text(
            f"❌ Error: {str(e)[:200]}",
            reply_markup=AdminKeyboards.back("admin_test:finance_menu")
        )
    
    await safe_answer(callback)


@router.callback_query(F.data == "admin_test:finance_credit")
async def finance_credit_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start credit user flow"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.update_data(finance_action="credit")
    
    text = """
💰 <b>Credit User</b>

Enter Telegram ID or @username:
<i>(or "me" for yourself)</i>
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.cancel("admin_test:finance_menu"))
    await state.set_state(AdminTestStates.finance_user_search)
    await safe_answer(callback)


@router.callback_query(F.data == "admin_test:finance_debit")
async def finance_debit_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start debit user flow"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.update_data(finance_action="debit")
    
    text = """
💸 <b>Debit User</b>

Enter Telegram ID or @username:
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.cancel("admin_test:finance_menu"))
    await state.set_state(AdminTestStates.finance_user_search)
    await safe_answer(callback)


@router.message(AdminTestStates.finance_user_search)
async def finance_user_search(message: Message, state: FSMContext) -> None:
    """Process user search for finance action"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    query = message.text.strip()
    
    async with db_manager.session() as session:
        if query.lower() == "me":
            user = await session.scalar(
                select(User).where(User.telegram_id == message.from_user.id)
            )
        else:
            user = await get_user_by_query(session, query)
        
        if not user:
            await message.answer(
                "❌ User not found. Try again:",
                reply_markup=AdminKeyboards.cancel("admin_test:finance_menu")
            )
            return
        
        await state.update_data(
            target_user_id=str(user.id),
            target_tg_id=user.telegram_id,
            target_username=user.username
        )
    
    data = await state.get_data()
    action = data.get("finance_action", "credit")
    action_text = "Credit" if action == "credit" else "Debit"
    
    text = f"""
💰 <b>{action_text} User</b>

User: <code>{user.telegram_id}</code> (@{user.username or 'N/A'})

Select network:
"""
    
    await message.answer(
        text,
        reply_markup=AdminKeyboards.network_select("admin_test:finance_net"),
        parse_mode="HTML"
    )
    await state.set_state(AdminTestStates.add_balance_network)


@router.callback_query(F.data.startswith("admin_test:finance_net:"))
async def finance_network_select(callback: CallbackQuery, state: FSMContext) -> None:
    """Select network for finance action"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    network = callback.data.split(":")[-1]
    
    if network not in NETWORKS:
        await safe_answer(callback, "❌ Invalid network", show_alert=True)
        return
    
    await state.update_data(network=network)
    
    config = NETWORKS[network]
    data = await state.get_data()
    action = data.get("finance_action", "credit")
    
    text = f"""
💰 <b>{'Credit' if action == 'credit' else 'Debit'} {config.icon} {config.symbol}</b>

Enter amount:
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.cancel("admin_test:finance_menu"))
    await state.set_state(AdminTestStates.finance_amount)
    await safe_answer(callback)


@router.message(AdminTestStates.finance_amount)
async def finance_amount_input(message: Message, state: FSMContext) -> None:
    """Process amount for finance action"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    amount = parse_decimal(message.text)
    
    if not amount:
        await message.answer(
            "❌ Invalid amount. Enter a positive number:",
            reply_markup=AdminKeyboards.cancel("admin_test:finance_menu")
        )
        return
    
    await state.update_data(amount=str(amount))
    
    text = """
📝 <b>Enter Reason</b>

Provide a reason for this transaction:
<i>(This will be logged)</i>
"""
    
    await message.answer(
        text,
        reply_markup=AdminKeyboards.cancel("admin_test:finance_menu"),
        parse_mode="HTML"
    )
    await state.set_state(AdminTestStates.finance_reason)


@router.message(AdminTestStates.finance_reason)
async def finance_execute(message: Message, state: FSMContext) -> None:
    """Execute finance action"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    reason = message.text.strip()
    data = await state.get_data()
    
    user_id = data['target_user_id']
    network = data['network']
    amount = Decimal(data['amount'])
    action = data.get('finance_action', 'credit')
    config = NETWORKS[network]
    
    try:
        async with db_manager.session() as session:
            # Get or create wallet
            wallet = await session.scalar(
                select(Wallet).where(
                    Wallet.user_id == user_id,
                    Wallet.network == network
                )
            )
            
            if not wallet:
                wallet_data = await wallet_manager.create_wallet(network)
                wallet = Wallet(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    network=network,
                    address=wallet_data.address,
                    encrypted_private_key=wallet_data.private_key,
                    is_active=True
                )
                session.add(wallet)
                await session.flush()
            
            # Get or create balance
            balance = await session.scalar(
                select(WalletBalance).where(
                    WalletBalance.wallet_id == wallet.id,
                    WalletBalance.token_symbol == config.symbol
                )
            )
            
            old_balance = Decimal("0")
            
            if balance:
                old_balance = balance.balance
                if action == "credit":
                    balance.balance += amount
                else:
                    if balance.balance < amount:
                        await message.answer(
                            f"❌ Insufficient balance. Current: {balance.balance} {config.symbol}",
                            reply_markup=AdminKeyboards.back("admin_test:finance_menu")
                        )
                        await state.clear()
                        return
                    balance.balance -= amount
                
                if 'updated_at' in WALLET_BALANCE_FIELDS:
                    balance.updated_at = datetime.utcnow()
            else:
                if action == "debit":
                    await message.answer(
                        "❌ No balance to debit.",
                        reply_markup=AdminKeyboards.back("admin_test:finance_menu")
                    )
                    await state.clear()
                    return
                
                balance_kwargs = create_wallet_balance_kwargs(
                    wallet_id=wallet.id,
                    token_symbol=config.symbol,
                    balance=amount,
                    decimals=config.decimals
                )
                balance = WalletBalance(**balance_kwargs)
                session.add(balance)
            
            new_balance = balance.balance
            
            # Create transaction record
            tx_kwargs = create_transaction_kwargs(
                user_id=user_id,
                wallet_id=wallet.id,
                tx_type=TransactionType.DEPOSIT if action == "credit" else TransactionType.WITHDRAW,
                network=network,
                token_symbol=config.symbol,
                amount=amount,
                status=TransactionStatus.COMPLETED,
                from_address=f"ADMIN_{action.upper()}",
                to_address=wallet.address,
                note_text=f"Admin {action}: {reason} (by {message.from_user.id})"
            )
            tx = Transaction(**tx_kwargs)
            session.add(tx)
            
            await session.commit()
            
            logger.info(
                f"Admin finance {action}",
                admin_id=message.from_user.id,
                user_id=user_id,
                network=network,
                amount=str(amount),
                reason=reason
            )
        
        action_symbol = "+" if action == "credit" else "-"
        
        await message.answer(
            f"✅ <b>{'Credit' if action == 'credit' else 'Debit'} Successful!</b>\n\n"
            f"User: <code>{data['target_tg_id']}</code>\n"
            f"Network: {config.icon} {network.upper()}\n"
            f"Amount: <b>{action_symbol}{amount} {config.symbol}</b>\n"
            f"Old balance: {old_balance}\n"
            f"New balance: <b>{new_balance}</b>\n\n"
            f"Reason: {reason}",
            reply_markup=AdminKeyboards.back("admin_test:finance_menu"),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error("Finance action failed", error=str(e), exc_info=True)
        await message.answer(
            f"❌ Error: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back("admin_test:finance_menu")
        )
    
    await state.clear()


@router.callback_query(F.data == "admin_test:finance_mass_credit")
async def finance_mass_credit_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start mass credit flow"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    text = """
🔄 <b>Mass Credit</b>

This will credit ALL users who have wallets on the selected network.

⚠️ Use with caution!

Select network:
"""
    
    await safe_edit(
        callback.message, text,
        AdminKeyboards.network_select("admin_test:mass_credit_net")
    )
    await state.set_state(AdminTestStates.mass_credit_network)
    await safe_answer(callback)


@router.callback_query(
    AdminTestStates.mass_credit_network,
    F.data.startswith("admin_test:mass_credit_net:")
)
async def mass_credit_network(callback: CallbackQuery, state: FSMContext) -> None:
    """Select network for mass credit"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    network = callback.data.split(":")[-1]
    
    if network not in NETWORKS:
        await safe_answer(callback, "❌ Invalid network", show_alert=True)
        return
    
    await state.update_data(network=network)
    config = NETWORKS[network]
    
    # Count eligible wallets
    async with db_manager.session() as session:
        wallet_count = await session.scalar(
            select(func.count(Wallet.id)).where(Wallet.network == network)
        ) or 0
    
    if wallet_count == 0:
        await callback.message.edit_text(
            f"❌ No wallets found for {config.icon} {network.upper()}",
            reply_markup=AdminKeyboards.back("admin_test:finance_menu"),
            parse_mode="HTML"
        )
        await state.clear()
        await safe_answer(callback)
        return
    
    text = f"""
🔄 <b>Mass Credit {config.icon} {config.symbol}</b>

Found <b>{wallet_count}</b> wallets on this network.

Enter amount to credit per wallet:
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.cancel("admin_test:finance_menu"))
    await state.set_state(AdminTestStates.mass_credit_amount)
    await safe_answer(callback)


@router.message(AdminTestStates.mass_credit_amount)
async def mass_credit_amount(message: Message, state: FSMContext) -> None:
    """Process mass credit amount"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    amount = parse_decimal(message.text)
    
    if not amount:
        await message.answer(
            "❌ Invalid amount. Enter a positive number:",
            reply_markup=AdminKeyboards.cancel("admin_test:finance_menu")
        )
        return
    
    if amount > AdminConfig.MAX_AIRDROP_AMOUNT:
        await message.answer(
            f"❌ Amount too large. Maximum: {AdminConfig.MAX_AIRDROP_AMOUNT}",
            reply_markup=AdminKeyboards.cancel("admin_test:finance_menu")
        )
        return
    
    await state.update_data(amount=str(amount))
    
    data = await state.get_data()
    network = data['network']
    config = NETWORKS[network]
    
    # Count eligible wallets again
    async with db_manager.session() as session:
        wallet_count = await session.scalar(
            select(func.count(Wallet.id)).where(Wallet.network == network)
        ) or 0
    
    total_amount = amount * wallet_count
    
    text = f"""
🔄 <b>Confirm Mass Credit</b>

<b>Network:</b> {config.icon} {network.upper()}
<b>Amount per wallet:</b> {amount} {config.symbol}
<b>Total wallets:</b> {wallet_count}
<b>Total to distribute:</b> {total_amount} {config.symbol}

⚠️ This will add balance to ALL wallets on this network!

Proceed?
"""
    
    keyboard = AdminKeyboards.confirm(
        "admin_test:mass_credit_confirm",
        "admin_test:finance_menu"
    )
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(AdminTestStates.mass_credit_confirm)


@router.callback_query(
    AdminTestStates.mass_credit_confirm,
    F.data == "admin_test:mass_credit_confirm"
)
async def mass_credit_execute(callback: CallbackQuery, state: FSMContext) -> None:
    """Execute mass credit"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    data = await state.get_data()
    network = data['network']
    amount = Decimal(data['amount'])
    config = NETWORKS[network]
    
    await safe_edit(callback.message, "⏳ <b>Processing mass credit...</b>")
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(Wallet).where(Wallet.network == network)
            )
            wallets = result.scalars().all()
            
            credited = 0
            errors = 0
            
            for wallet in wallets:
                try:
                    balance = await session.scalar(
                        select(WalletBalance).where(
                            WalletBalance.wallet_id == wallet.id,
                            WalletBalance.token_symbol == config.symbol
                        )
                    )
                    
                    if balance:
                        balance.balance += amount
                        if 'updated_at' in WALLET_BALANCE_FIELDS:
                            balance.updated_at = datetime.utcnow()
                    else:
                        balance_kwargs = create_wallet_balance_kwargs(
                            wallet_id=wallet.id,
                            token_symbol=config.symbol,
                            balance=amount,
                            decimals=config.decimals
                        )
                        balance = WalletBalance(**balance_kwargs)
                        session.add(balance)
                    
                    # Create transaction record
                    tx_kwargs = create_transaction_kwargs(
                        user_id=wallet.user_id,
                        wallet_id=wallet.id,
                        tx_type=TransactionType.DEPOSIT,
                        network=network,
                        token_symbol=config.symbol,
                        amount=amount,
                        status=TransactionStatus.COMPLETED,
                        from_address="ADMIN_MASS_CREDIT",
                        to_address=wallet.address,
                        note_text=f"Mass credit by admin {callback.from_user.id}"
                    )
                    tx = Transaction(**tx_kwargs)
                    session.add(tx)
                    
                    credited += 1
                    
                except Exception as e:
                    logger.warning(f"Failed to credit wallet {wallet.id}", error=str(e))
                    errors += 1
            
            await session.commit()
            
            logger.info(
                "Mass credit completed",
                admin_id=callback.from_user.id,
                network=network,
                amount=str(amount),
                credited=credited,
                errors=errors
            )
        
        total_distributed = amount * credited
        
        text = f"""
✅ <b>Mass Credit Complete!</b>

<b>Network:</b> {config.icon} {network.upper()}
<b>Amount per wallet:</b> {amount} {config.symbol}
<b>Wallets credited:</b> {credited}
<b>Total distributed:</b> {total_distributed} {config.symbol}
"""
        
        if errors > 0:
            text += f"\n⚠️ Errors: {errors}"
        
        await callback.message.edit_text(
            text,
            reply_markup=AdminKeyboards.back("admin_test:finance_menu"),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error("Mass credit failed", error=str(e), exc_info=True)
        await callback.message.edit_text(
            f"❌ Mass credit failed: {str(e)[:200]}",
            reply_markup=AdminKeyboards.back("admin_test:finance_menu")
        )
    
    await state.clear()
    await safe_answer(callback)


@router.callback_query(F.data == "admin_test:finance_history")
async def finance_history(callback: CallbackQuery) -> None:
    """Show admin transaction history"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(Transaction)
                .where(Transaction.from_address.like("ADMIN%"))
                .order_by(Transaction.created_at.desc())
                .limit(20)
            )
            txs = result.scalars().all()
            
            if not txs:
                text = "📋 <b>Admin Transaction History</b>\n\n<i>No admin transactions yet.</i>"
            else:
                text = "📋 <b>Admin Transaction History</b>\n\n"
                
                for tx in txs:
                    time_str = tx.created_at.strftime("%m/%d %H:%M") if tx.created_at else "?"
                    tx_type_str = tx.tx_type.value if hasattr(tx.tx_type, 'value') else str(tx.tx_type)
                    text += f"• {time_str} | {tx_type_str} | {tx.amount} {tx.token_symbol}\n"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_test:finance_history")],
                [InlineKeyboardButton(text="🔙 Back", callback_data="admin_test:finance_menu")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error("Finance history failed", error=str(e), exc_info=True)
        await callback.message.edit_text(
            f"❌ Error: {str(e)[:200]}",
            reply_markup=AdminKeyboards.back("admin_test:finance_menu")
        )
    
    await safe_answer(callback)


@router.callback_query(F.data == "admin_test:finance_reserves")
async def finance_reserves(callback: CallbackQuery) -> None:
    """View system reserves"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(
                    WalletBalance.token_symbol,
                    func.sum(WalletBalance.balance),
                    func.count(WalletBalance.id)
                ).group_by(WalletBalance.token_symbol)
            )
            
            text = "🏦 <b>System Reserves</b>\n\n"
            total_usd = Decimal("0")
            
            for row in result:
                token, total, count = row
                text += f"<b>{token}:</b>\n"
                text += f"├ Total: {total:,.4f}\n"
                text += f"└ Wallets: {count}\n\n"
                
                if token in ["USDT", "USDC", "DAI", "BUSD"]:
                    total_usd += total or Decimal("0")
            
            text += f"<b>Estimated Total (Stables):</b> ${total_usd:,.2f}"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_test:finance_reserves")],
                [InlineKeyboardButton(text="🔙 Back", callback_data="admin_test:finance_menu")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error("Finance reserves failed", error=str(e))
        await callback.message.edit_text(
            f"❌ Error: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back("admin_test:finance_menu")
        )
    
    await safe_answer(callback)


@router.callback_query(F.data == "admin_test:finance_daily")
async def finance_daily_report(callback: CallbackQuery) -> None:
    """Daily financial report"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    try:
        async with db_manager.session() as session:
            today = datetime.utcnow().date()
            yesterday = today - timedelta(days=1)
            
            # Today's stats
            today_txs = await session.scalar(
                select(func.count(Transaction.id)).where(
                    func.date(Transaction.created_at) == today
                )
            ) or 0
            
            today_volume = await session.scalar(
                select(func.sum(Transaction.amount)).where(
                    func.date(Transaction.created_at) == today
                )
            ) or Decimal("0")
            
            # Yesterday's stats
            yesterday_txs = await session.scalar(
                select(func.count(Transaction.id)).where(
                    func.date(Transaction.created_at) == yesterday
                )
            ) or 0
            
            yesterday_volume = await session.scalar(
                select(func.sum(Transaction.amount)).where(
                    func.date(Transaction.created_at) == yesterday
                )
            ) or Decimal("0")
            
            # New users today
            new_users = await session.scalar(
                select(func.count(User.id)).where(
                    func.date(User.created_at) == today
                )
            ) or 0
            
            # Calculate changes
            tx_change = ((today_txs - yesterday_txs) / yesterday_txs * 100) if yesterday_txs else 0
            vol_change = ((today_volume - yesterday_volume) / yesterday_volume * 100) if yesterday_volume else 0
            
            tx_arrow = "📈" if tx_change >= 0 else "📉"
            vol_arrow = "📈" if vol_change >= 0 else "📉"
            
            text = f"""
📈 <b>Daily Financial Report</b>
<i>{today.strftime('%Y-%m-%d')}</i>

<b>Today's Activity:</b>
├ Transactions: {today_txs} {tx_arrow} {tx_change:+.1f}%
├ Volume: {today_volume:,.2f} {vol_arrow} {vol_change:+.1f}%
└ New Users: {new_users}

<b>Yesterday:</b>
├ Transactions: {yesterday_txs}
└ Volume: {yesterday_volume:,.2f}
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_test:finance_daily")],
                [InlineKeyboardButton(text="🔙 Back", callback_data="admin_test:finance_menu")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error("Daily report failed", error=str(e))
        await callback.message.edit_text(
            f"❌ Error: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back("admin_test:finance_menu")
        )
    
    await safe_answer(callback)


# ==================== ADD/SET BALANCE ====================

@router.callback_query(F.data == "admin_test:add_balance")
async def add_balance_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start add balance flow"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    text = """
💰 <b>Add Balance to User</b>

Enter the Telegram ID or @username:
<i>(or "me" for yourself)</i>
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.cancel())
    await state.set_state(AdminTestStates.add_balance_user)
    await safe_answer(callback)


@router.message(AdminTestStates.add_balance_user)
async def add_balance_user(message: Message, state: FSMContext) -> None:
    """Process user input for add balance"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    query = message.text.strip()
    
    async with db_manager.session() as session:
        if query.lower() == "me":
            user = await session.scalar(
                select(User).where(User.telegram_id == message.from_user.id)
            )
        else:
            user = await get_user_by_query(session, query)
        
        if not user:
            await message.answer(
                "❌ User not found. Try again or cancel.",
                reply_markup=AdminKeyboards.cancel()
            )
            return
        
        await state.update_data(
            target_user_id=str(user.id),
            target_tg_id=user.telegram_id
        )
    
    text = f"""
💰 <b>Add Balance</b>

User: <code>{user.telegram_id}</code> (@{user.username or 'N/A'})

Select network:
"""
    
    await message.answer(
        text,
        reply_markup=AdminKeyboards.network_select("admin_test:add_bal_net"),
        parse_mode="HTML"
    )
    await state.set_state(AdminTestStates.add_balance_network)


@router.callback_query(
    AdminTestStates.add_balance_network,
    F.data.startswith("admin_test:add_bal_net:")
)
async def add_balance_network(callback: CallbackQuery, state: FSMContext) -> None:
    """Select network for balance"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    network = callback.data.split(":")[-1]
    
    if network not in NETWORKS:
        await safe_answer(callback, "❌ Invalid network", show_alert=True)
        return
    
    await state.update_data(network=network)
    config = NETWORKS[network]
    
    text = f"""
💰 <b>Add {config.icon} {config.symbol} Balance</b>

Enter amount to add:
<i>Example: 100 or 0.5</i>
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.cancel())
    await state.set_state(AdminTestStates.add_balance_amount)
    await safe_answer(callback)


@router.message(AdminTestStates.add_balance_amount)
async def add_balance_amount(message: Message, state: FSMContext) -> None:
    """Process amount and add balance"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    amount = parse_decimal(message.text)
    
    if not amount:
        await message.answer(
            "❌ Invalid amount. Enter a positive number.",
            reply_markup=AdminKeyboards.cancel()
        )
        return
    
    data = await state.get_data()
    user_id = data['target_user_id']
    network = data['network']
    config = NETWORKS[network]
    
    try:
        async with db_manager.session() as session:
            wallet = await session.scalar(
                select(Wallet).where(
                    Wallet.user_id == user_id,
                    Wallet.network == network
                )
            )
            
            if not wallet:
                wallet_data = await wallet_manager.create_wallet(network)
                wallet = Wallet(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    network=network,
                    address=wallet_data.address,
                    encrypted_private_key=wallet_data.private_key,
                    is_active=True
                )
                session.add(wallet)
                await session.flush()
            
            balance = await session.scalar(
                select(WalletBalance).where(
                    WalletBalance.wallet_id == wallet.id,
                    WalletBalance.token_symbol == config.symbol
                )
            )
            
            old_balance = Decimal("0")
            
            if balance:
                old_balance = balance.balance
                balance.balance += amount
                if 'updated_at' in WALLET_BALANCE_FIELDS:
                    balance.updated_at = datetime.utcnow()
            else:
                balance_kwargs = create_wallet_balance_kwargs(
                    wallet_id=wallet.id,
                    token_symbol=config.symbol,
                    balance=amount,
                    decimals=config.decimals
                )
                balance = WalletBalance(**balance_kwargs)
                session.add(balance)
            
            # Create transaction record
            tx_kwargs = create_transaction_kwargs(
                user_id=user_id,
                wallet_id=wallet.id,
                tx_type=TransactionType.DEPOSIT,
                network=network,
                token_symbol=config.symbol,
                amount=amount,
                status=TransactionStatus.COMPLETED,
                from_address="ADMIN_TEST_CREDIT",
                to_address=wallet.address,
                note_text=f"Test credit by admin {message.from_user.id}"
            )
            tx = Transaction(**tx_kwargs)
            session.add(tx)
            
            await session.commit()
            
            new_balance = old_balance + amount
            
            logger.info(
                "Test balance added",
                admin_id=message.from_user.id,
                user_id=user_id,
                network=network,
                amount=str(amount)
            )
        
        await message.answer(
            f"✅ <b>Balance Added!</b>\n\n"
            f"User: <code>{data['target_tg_id']}</code>\n"
            f"Network: {config.icon} {network.upper()}\n"
            f"Added: <b>+{amount} {config.symbol}</b>\n"
            f"Old balance: {old_balance} {config.symbol}\n"
            f"New balance: <b>{new_balance} {config.symbol}</b>",
            reply_markup=AdminKeyboards.back(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error("Add balance failed", error=str(e), exc_info=True)
        await message.answer(
            f"❌ Failed to add balance: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back()
        )
    
    await state.clear()


# ==================== BYPASS REQUIREMENTS ====================

@router.callback_query(F.data == "admin_test:bypass_req")
async def bypass_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start bypass requirements flow"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    text = """
🔓 <b>Bypass Shop Requirements</b>

This will set all shop requirements to passing values for a user.

Enter Telegram ID or @username:
<i>(or "me" for yourself)</i>
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.cancel())
    await state.set_state(AdminTestStates.bypass_requirements_user)
    await safe_answer(callback)

@router.message(AdminTestStates.bypass_requirements_user)
async def bypass_user_input(message: Message, state: FSMContext) -> None:
    """Process user input for bypass"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    query = message.text.strip()
    
    if not query:
        await message.answer(
            "❌ Empty input. Enter ID or @username:",
            reply_markup=AdminKeyboards.cancel()
        )
        return
    
    try:
        async with db_manager.session() as session:
            if query.lower() == "me":
                user = await session.scalar(
                    select(User).where(User.telegram_id == message.from_user.id)
                )
            else:
                user = await get_user_by_query(session, query)
            
            if not user:
                await message.answer(
                    "❌ User not found. Try again:",
                    reply_markup=AdminKeyboards.cancel()
                )
                return
            
            await state.update_data(
                target_user_id=user.id,
                target_tg_id=user.telegram_id,
                target_username=user.username
            )
            
            # Show confirmation
            config = BypassConfig
            username_display = f"@{user.username}" if user.username else "—"
            
            text = f"""
🔓 <b>Confirm Bypass</b>

👤 User: <code>{user.telegram_id}</code>
📛 Username: {username_display}

<b>Will be set:</b>
├ 📊 Trades: {config.TOTAL_TRADES}
├ 💰 Volume: ${config.VOLUME_USD:,.2f}
├ ✅ Success rate: 100%
├ ⭐ Rating: {config.RATING}
├ 📅 Account age: {config.DAYS_OLD} days
├ ⚠️ Disputes: {config.DISPUTES}
└ 🏪 Merchant verified: ✓

Confirm?
"""
            
            await message.answer(
                text,
                reply_markup=AdminKeyboards.confirm("admin_test:bypass_execute"),
                parse_mode="HTML"
            )
            await state.set_state(AdminTestStates.bypass_requirements_confirm)
            
    except Exception as e:
        logger.error("Bypass user search failed", error=str(e), exc_info=True)
        await message.answer(
            f"❌ Error: {str(e)[:100]}",
            reply_markup=AdminKeyboards.cancel()
        )


@router.callback_query(
    AdminTestStates.bypass_requirements_confirm,
    F.data == "admin_test:bypass_execute"
)
async def bypass_execute(callback: CallbackQuery, state: FSMContext) -> None:
    """Execute bypass requirements"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    data = await state.get_data()
    user_id = data.get("target_user_id")
    target_tg_id = data.get("target_tg_id")
    
    if not user_id:
        await safe_edit(callback.message, "❌ Session expired. Start again.")
        await state.clear()
        await safe_answer(callback)
        return
    
    await safe_edit(callback.message, "⏳ Applying bypass...")
    
    try:
        async with db_manager.session() as session:
            user = await session.get(User, user_id)
            
            if not user:
                await callback.message.edit_text(
                    "❌ User not found",
                    reply_markup=AdminKeyboards.back()
                )
                await state.clear()
                await safe_answer(callback)
                return
            
            config = BypassConfig
            
            # ===== DELETE PENDING APPLICATIONS =====
            from database.models import ShopApplication, ShopApplicationStatus
            
            deleted_apps = await session.execute(
                delete(ShopApplication).where(
                    ShopApplication.user_id == user_id,
                    ShopApplication.status == ShopApplicationStatus.PENDING
                )
            )
            deleted_count = deleted_apps.rowcount
            if deleted_count > 0:
                logger.info(f"Deleted {deleted_count} pending applications for user {user_id}")
            # ===== END DELETE =====
            
            # Set account age
            user.created_at = datetime.utcnow() - timedelta(days=config.DAYS_OLD)
            
            # Set trades
            if hasattr(user, 'total_trades_count'):
                user.total_trades_count = config.TOTAL_TRADES
            
            # Set successful trades
            if hasattr(user, 'successful_trades_count'):
                user.successful_trades_count = config.SUCCESSFUL_TRADES
            
            # Set volume
            if hasattr(user, 'total_volume_usd'):
                user.total_volume_usd = config.VOLUME_USD
            
            # Set rating
            if hasattr(user, 'rating'):
                user.rating = config.RATING
            
            # Set disputes
            if hasattr(user, 'disputed_trades_count'):
                user.disputed_trades_count = config.DISPUTES
            
            # Set merchant verified
            if hasattr(user, 'merchant_verified'):
                user.merchant_verified = True
            
            # Reset has_shop
            if hasattr(user, 'has_shop'):
                user.has_shop = False
            
            await session.commit()
            await session.refresh(user)
            
            logger.info(
                "Bypass requirements applied",
                admin_id=callback.from_user.id,
                target_user_id=user_id,
                deleted_pending_apps=deleted_count
            )
        
        text = f"""
✅ <b>Bypass Applied!</b>

👤 User: <code>{target_tg_id}</code>

<b>Set values:</b>
├ 📊 Trades: {config.TOTAL_TRADES}
├ 💰 Volume: ${float(config.VOLUME_USD):,.2f}
├ ✅ Success rate: 100%
├ ⭐ Rating: {config.RATING}
├ 📅 Account age: {config.DAYS_OLD} days
├ ⚠️ Disputes: {config.DISPUTES}
└ 🗑 Deleted pending apps: {deleted_count}

🏪 User can now apply for a shop!
"""
        
        await callback.message.edit_text(
            text,
            reply_markup=AdminKeyboards.back(),
            parse_mode="HTML"
        )
        await safe_answer(callback, "✅ Bypass applied!")
        
    except Exception as e:
        logger.error("Bypass execution failed", error=str(e), exc_info=True)
        await callback.message.edit_text(
            f"❌ Error: {str(e)[:200]}",
            reply_markup=AdminKeyboards.back()
        )
    
    await state.clear()


# ==================== REMOVE REQUIREMENTS ====================

@router.callback_query(F.data == "admin_test:remove_req")
async def remove_requirements_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start remove requirements flow"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    text = """
❌ <b>Remove Shop Requirements</b>

This will RESET all shop requirements for a user to zero.

⚠️ User will NOT be able to create shop after this!

Enter Telegram ID or @username:
<i>(or "me" for yourself)</i>
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.cancel())
    await state.set_state(AdminTestStates.remove_requirements_user)
    await safe_answer(callback)


@router.message(AdminTestStates.remove_requirements_user)
async def remove_requirements_user(message: Message, state: FSMContext) -> None:
    """Process user for remove requirements"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    query = message.text.strip()
    
    async with db_manager.session() as session:
        if query.lower() == "me":
            user = await session.scalar(
                select(User).where(User.telegram_id == message.from_user.id)
            )
        else:
            user = await get_user_by_query(session, query)
        
        if not user:
            await message.answer(
                "❌ User not found.",
                reply_markup=AdminKeyboards.cancel()
            )
            return
        
        # Get current stats
        tx_count = await session.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.user_id == user.id,
                Transaction.status == TransactionStatus.COMPLETED
            )
        ) or 0
        
        bypass_tx_count = await session.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.user_id == user.id,
                Transaction.from_address.like("BYPASS%")
            )
        ) or 0
        
        await state.update_data(
            target_user_id=str(user.id),
            target_tg_id=user.telegram_id,
            target_username=user.username,
            tx_count=tx_count,
            bypass_tx_count=bypass_tx_count
        )
    
    account_age = (datetime.utcnow() - user.created_at).days if user.created_at else 0
    
    text = f"""
❌ <b>Confirm Remove Requirements</b>

<b>User:</b> <code>{user.telegram_id}</code> (@{user.username or 'N/A'})

<b>Current Data:</b>
├ Account age: {account_age} days
├ Total transactions: {tx_count}
└ Bypass transactions: {bypass_tx_count}

<b>This will:</b>
├ Reset all trade stats to zero
├ Set account created_at to NOW
└ Remove merchant verification

⚠️ <b>This cannot be undone!</b>

Proceed?
"""
    
    await message.answer(
        text,
        reply_markup=AdminKeyboards.confirm("admin_test:remove_req_confirm"),
        parse_mode="HTML"
    )
    await state.set_state(AdminTestStates.remove_requirements_confirm)


@router.callback_query(
    AdminTestStates.remove_requirements_confirm,
    F.data == "admin_test:remove_req_confirm"
)
async def remove_requirements_execute(callback: CallbackQuery, state: FSMContext) -> None:
    """Execute remove requirements"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    data = await state.get_data()
    user_id = data['target_user_id']
    target_tg_id = data['target_tg_id']
    
    await safe_edit(callback.message, "⏳ <b>Removing requirements...</b>")
    
    changes_made = []
    
    try:
        async with db_manager.session() as session:
            user = await session.scalar(
                select(User).where(User.id == user_id)
            )
            
            if not user:
                await callback.message.edit_text(
                    "❌ User not found.",
                    reply_markup=AdminKeyboards.back()
                )
                await state.clear()
                return
            
            # Reset user stats
            reset_fields = [
                ('total_trades_count', 0),
                ('successful_trades_count', 0),
                ('total_volume_usd', Decimal("0")),
                ('rating', Decimal("0")),
                ('disputed_trades_count', 0),
                ('merchant_verified', False),
            ]
            
            for field, value in reset_fields:
                if hasattr(user, field):
                    setattr(user, field, value)
                    changes_made.append(f"✓ {field} = {value}")
            
            # Reset account age
            old_date = user.created_at
            user.created_at = datetime.utcnow()
            if old_date:
                old_age = (datetime.utcnow() - old_date).days
                changes_made.append(f"✓ Account age reset (was {old_age} days)")
            
            # Delete bypass transactions
            result = await session.execute(
                delete(Transaction).where(
                    Transaction.user_id == user_id,
                    or_(
                        Transaction.from_address.like("BYPASS%"),
                        Transaction.from_address.like("ADMIN_BYPASS%")
                    )
                )
            )
            if result.rowcount > 0:
                changes_made.append(f"✓ Deleted {result.rowcount} bypass transactions")
            
            await session.commit()
            
            logger.info(
                "Remove requirements executed",
                admin_id=callback.from_user.id,
                target_user_id=user_id,
                changes=len(changes_made)
            )
        
        text = f"""
✅ <b>Requirements Removed!</b>

<b>User:</b> <code>{target_tg_id}</code> (@{data.get('target_username') or 'N/A'})

<b>Changes made:</b>
"""
        
        for change in changes_made:
            text += f"{change}\n"
        
        if not changes_made:
            text += "<i>No changes made</i>\n"
        
        text += "\n❌ User now does NOT meet shop requirements."
        
        await callback.message.edit_text(
            text,
            reply_markup=AdminKeyboards.back(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error("Remove requirements failed", error=str(e), exc_info=True)
        await callback.message.edit_text(
            f"❌ Failed: {str(e)[:300]}",
            reply_markup=AdminKeyboards.back()
        )
    
    await state.clear()
    await safe_answer(callback)


# ==================== SIMULATE TRANSACTION ====================

@router.callback_query(F.data == "admin_test:simulate_tx")
async def simulate_tx_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start transaction simulation"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    text = """
🔄 <b>Simulate Transaction</b>

This creates fake transaction records for testing.

Enter Telegram ID or @username:
<i>(or "me" for yourself)</i>
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.cancel())
    await state.set_state(AdminTestStates.simulate_tx_user)
    await safe_answer(callback)


@router.message(AdminTestStates.simulate_tx_user)
async def simulate_tx_user(message: Message, state: FSMContext) -> None:
    """Process user for simulation"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    query = message.text.strip()
    
    async with db_manager.session() as session:
        if query.lower() == "me":
            user = await session.scalar(
                select(User).where(User.telegram_id == message.from_user.id)
            )
        else:
            user = await get_user_by_query(session, query)
        
        if not user:
            await message.answer(
                "❌ User not found.",
                reply_markup=AdminKeyboards.cancel()
            )
            return
        
        await state.update_data(
            target_user_id=str(user.id),
            target_tg_id=user.telegram_id
        )
    
    text = f"""
🔄 <b>Simulate Transaction</b>

User: <code>{user.telegram_id}</code>

Select transaction type:
"""
    
    await message.answer(
        text,
        reply_markup=AdminKeyboards.tx_type_select(),
        parse_mode="HTML"
    )
    await state.set_state(AdminTestStates.simulate_tx_type)


@router.callback_query(
    AdminTestStates.simulate_tx_type,
    F.data.startswith("admin_test:sim_type:")
)
async def simulate_tx_type(callback: CallbackQuery, state: FSMContext) -> None:
    """Select transaction type"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    tx_type = callback.data.split(":")[-1]
    await state.update_data(tx_type=tx_type)
    
    text = "🔄 <b>Select Network</b>"
    
    await safe_edit(
        callback.message, text,
        AdminKeyboards.network_select("admin_test:sim_net")
    )
    await state.set_state(AdminTestStates.simulate_tx_network)
    await safe_answer(callback)


@router.callback_query(
    AdminTestStates.simulate_tx_network,
    F.data.startswith("admin_test:sim_net:")
)
async def simulate_tx_network(callback: CallbackQuery, state: FSMContext) -> None:
    """Select network for simulation"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    network = callback.data.split(":")[-1]
    await state.update_data(network=network)
    
    config = NETWORKS[network]
    
    text = f"""
🔄 <b>Simulate {config.icon} Transaction</b>

Enter amount (or "random" for random amount):
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.cancel())
    await state.set_state(AdminTestStates.simulate_tx_amount)
    await safe_answer(callback)


@router.message(AdminTestStates.simulate_tx_amount)
async def simulate_tx_amount(message: Message, state: FSMContext) -> None:
    """Process amount for simulation"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    text = message.text.strip().lower()
    
    if text == "random":
        amount = Decimal(str(random.uniform(10, 1000))).quantize(Decimal("0.01"))
    else:
        amount = parse_decimal(text)
        if not amount:
            await message.answer(
                "❌ Invalid amount.",
                reply_markup=AdminKeyboards.cancel()
            )
            return
    
    await state.update_data(amount=str(amount))
    
    text = f"""
🔄 <b>How many transactions to create?</b>

Enter count (1-{AdminConfig.MAX_SIMULATED_TXS}):
"""
    
    await message.answer(text, reply_markup=AdminKeyboards.cancel(), parse_mode="HTML")
    await state.set_state(AdminTestStates.simulate_tx_count)


@router.message(AdminTestStates.simulate_tx_count)
async def simulate_tx_execute(message: Message, state: FSMContext) -> None:
    """Execute transaction simulation"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        count = int(message.text.strip())
        if count < 1 or count > AdminConfig.MAX_SIMULATED_TXS:
            raise ValueError()
    except (ValueError, TypeError):
        await message.answer(
            f"❌ Enter a number between 1 and {AdminConfig.MAX_SIMULATED_TXS}.",
            reply_markup=AdminKeyboards.cancel()
        )
        return
    
    data = await state.get_data()
    user_id = data['target_user_id']
    network = data['network']
    tx_type_str = data['tx_type']
    base_amount = Decimal(data['amount'])
    config = NETWORKS[network]
    
    # Map tx type string to enum
    tx_type_map = {
        "deposit": TransactionType.DEPOSIT,
        "withdraw": TransactionType.WITHDRAW,
        "transfer": TransactionType.TRANSFER,
        "swap": TransactionType.SWAP,
    }
    
    tx_type = tx_type_map.get(tx_type_str, TransactionType.DEPOSIT)
    
    progress_msg = await message.answer(f"⏳ Creating {count} transactions...")
    
    try:
        async with db_manager.session() as session:
            # Get or create wallet
            wallet = await session.scalar(
                select(Wallet).where(
                    Wallet.user_id == user_id,
                    Wallet.network == network
                )
            )
            
            if not wallet:
                wallet_data = await wallet_manager.create_wallet(network)
                wallet = Wallet(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    network=network,
                    address=wallet_data.address,
                    encrypted_private_key=wallet_data.private_key,
                    is_active=True
                )
                session.add(wallet)
                await session.flush()
            
            created = 0
            for i in range(count):
                # Vary the amount slightly
                amount = base_amount * Decimal(str(random.uniform(0.8, 1.2)))
                amount = amount.quantize(Decimal("0.0001"))
                
                # Random time in past 30 days
                random_days = random.randint(0, 30)
                random_hours = random.randint(0, 23)
                tx_time = datetime.utcnow() - timedelta(days=random_days, hours=random_hours)
                
                tx_kwargs = create_transaction_kwargs(
                    user_id=user_id,
                    wallet_id=wallet.id,
                    tx_type=tx_type,
                    network=network,
                    token_symbol=config.symbol,
                    amount=amount,
                    status=TransactionStatus.COMPLETED,
                    from_address="0x" + ''.join(random.choices('0123456789abcdef', k=40)),
                    to_address=wallet.address,
                    note_text=f"Simulated {tx_type_str} #{i+1}",
                    tx_hash="0x" + ''.join(random.choices('0123456789abcdef', k=64))
                )
                
                # Override timestamp
                if 'created_at' in TX_FIELDS:
                    tx_kwargs["created_at"] = tx_time
                if 'completed_at' in TX_FIELDS:
                    tx_kwargs["completed_at"] = tx_time
                
                tx = Transaction(**tx_kwargs)
                session.add(tx)
                created += 1
            
            await session.commit()
            
            logger.info(
                "Transactions simulated",
                admin_id=message.from_user.id,
                user_id=user_id,
                count=created,
                network=network
            )
        
        await progress_msg.edit_text(
            f"✅ <b>Simulation Complete!</b>\n\n"
            f"Created: <b>{created}</b> transactions\n"
            f"Type: {tx_type_str}\n"
            f"Network: {config.icon} {network.upper()}\n"
            f"Base Amount: {base_amount} {config.symbol}",
            reply_markup=AdminKeyboards.back(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error("Simulation failed", error=str(e), exc_info=True)
        await progress_msg.edit_text(
            f"❌ Simulation failed: {str(e)[:200]}",
            reply_markup=AdminKeyboards.back()
        )
    
    await state.clear()


# ==================== AIRDROP ====================

@router.callback_query(F.data == "admin_test:airdrop")
async def airdrop_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start airdrop flow"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    text = """
🎁 <b>Token Airdrop</b>

This will give tokens to ALL users with wallets on the selected network.

⚠️ Use carefully!

Select network:
"""
    
    await safe_edit(
        callback.message, text,
        AdminKeyboards.network_select("admin_test:airdrop_net")
    )
    await state.set_state(AdminTestStates.airdrop_network)
    await safe_answer(callback)


@router.callback_query(
    AdminTestStates.airdrop_network,
    F.data.startswith("admin_test:airdrop_net:")
)
async def airdrop_network(callback: CallbackQuery, state: FSMContext) -> None:
    """Select network for airdrop"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    network = callback.data.split(":")[-1]
    await state.update_data(network=network)
    
    config = NETWORKS[network]
    
    text = f"""
🎁 <b>Airdrop {config.icon} {config.symbol}</b>

Enter amount per user:
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.cancel())
    await state.set_state(AdminTestStates.airdrop_amount)
    await safe_answer(callback)


@router.message(AdminTestStates.airdrop_amount)
async def airdrop_amount(message: Message, state: FSMContext) -> None:
    """Process airdrop amount"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    amount = parse_decimal(message.text)
    
    if not amount:
        await message.answer(
            "❌ Invalid amount.",
            reply_markup=AdminKeyboards.cancel()
        )
        return
    
    if amount > AdminConfig.MAX_AIRDROP_AMOUNT:
        await message.answer(
            f"❌ Amount too large. Maximum: {AdminConfig.MAX_AIRDROP_AMOUNT}",
            reply_markup=AdminKeyboards.cancel()
        )
        return
    
    await state.update_data(amount=str(amount))
    
    data = await state.get_data()
    network = data['network']
    config = NETWORKS[network]
    
    # Count eligible users
    async with db_manager.session() as session:
        wallet_count = await session.scalar(
            select(func.count(Wallet.id)).where(Wallet.network == network)
        ) or 0
    
    if wallet_count == 0:
        await message.answer(
            f"❌ No wallets found for {network}.",
            reply_markup=AdminKeyboards.back()
        )
        await state.clear()
        return
    
    total_amount = amount * wallet_count
    
    text = f"""
🎁 <b>Confirm Airdrop</b>

Network: {config.icon} {network.upper()}
Amount per user: <b>{amount} {config.symbol}</b>
Eligible wallets: <b>{wallet_count}</b>
Total distribution: <b>{total_amount} {config.symbol}</b>

Proceed with airdrop?
"""
    
    await message.answer(
        text,
        reply_markup=AdminKeyboards.confirm("admin_test:airdrop_confirm"),
        parse_mode="HTML"
    )
    await state.set_state(AdminTestStates.airdrop_confirm)


@router.callback_query(
    AdminTestStates.airdrop_confirm,
    F.data == "admin_test:airdrop_confirm"
)
async def airdrop_execute(callback: CallbackQuery, state: FSMContext) -> None:
    """Execute airdrop"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    data = await state.get_data()
    network = data['network']
    amount = Decimal(data['amount'])
    config = NETWORKS[network]
    
    await safe_edit(callback.message, "⏳ <b>Processing airdrop...</b>")
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(Wallet).where(Wallet.network == network)
            )
            wallets = result.scalars().all()
            
            credited = 0
            for wallet in wallets:
                balance = await session.scalar(
                    select(WalletBalance).where(
                        WalletBalance.wallet_id == wallet.id,
                        WalletBalance.token_symbol == config.symbol
                    )
                )
                
                if balance:
                    balance.balance += amount
                    if 'updated_at' in WALLET_BALANCE_FIELDS:
                        balance.updated_at = datetime.utcnow()
                else:
                    balance_kwargs = create_wallet_balance_kwargs(
                        wallet_id=wallet.id,
                        token_symbol=config.symbol,
                        balance=amount,
                        decimals=config.decimals
                    )
                    balance = WalletBalance(**balance_kwargs)
                    session.add(balance)
                
                # Create transaction record
                tx_kwargs = create_transaction_kwargs(
                    user_id=wallet.user_id,
                    wallet_id=wallet.id,
                    tx_type=TransactionType.DEPOSIT,
                    network=network,
                    token_symbol=config.symbol,
                    amount=amount,
                    status=TransactionStatus.COMPLETED,
                    from_address="ADMIN_AIRDROP",
                    to_address=wallet.address,
                    note_text=f"Airdrop by admin {callback.from_user.id}"
                )
                tx = Transaction(**tx_kwargs)
                session.add(tx)
                credited += 1
            
            await session.commit()
            
            logger.info(
                "Airdrop completed",
                admin_id=callback.from_user.id,
                network=network,
                amount=str(amount),
                users=credited
            )
        
        await callback.message.edit_text(
            f"✅ <b>Airdrop Complete!</b>\n\n"
            f"Network: {config.icon} {network.upper()}\n"
            f"Amount per user: {amount} {config.symbol}\n"
            f"Users credited: <b>{credited}</b>\n"
            f"Total distributed: <b>{amount * credited} {config.symbol}</b>",
            reply_markup=AdminKeyboards.back(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error("Airdrop failed", error=str(e), exc_info=True)
        await callback.message.edit_text(
            f"❌ Airdrop failed: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back()
        )
    
    await state.clear()
    await safe_answer(callback)


# ==================== CREATE TEST USERS ====================

@router.callback_query(F.data == "admin_test:create_user")
async def create_user_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start create test users flow"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    text = f"""
👤 <b>Create Test Users</b>

This will create fake user accounts for testing.

How many users to create? (1-{AdminConfig.MAX_TEST_USERS}):
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.cancel())
    await state.set_state(AdminTestStates.create_test_user_count)
    await safe_answer(callback)


@router.message(AdminTestStates.create_test_user_count)
async def create_users_execute(message: Message, state: FSMContext) -> None:
    """Execute user creation"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        count = int(message.text.strip())
        if count < 1 or count > AdminConfig.MAX_TEST_USERS:
            raise ValueError()
    except (ValueError, TypeError):
        await message.answer(
            f"❌ Enter a number between 1 and {AdminConfig.MAX_TEST_USERS}.",
            reply_markup=AdminKeyboards.cancel()
        )
        return
    
    progress_msg = await message.answer(f"⏳ Creating {count} test users...")
    
    try:
        async with db_manager.session() as session:
            created = 0
            created_users = []
            
            for i in range(count):
                # Generate fake telegram ID (negative to distinguish from real)
                fake_tg_id = AdminConfig.TEST_USER_ID_PREFIX * random.randint(100000000, 999999999)
                
                # Check if exists
                existing = await session.scalar(
                    select(User).where(User.telegram_id == fake_tg_id)
                )
                if existing:
                    continue
                
                # Generate random username
                username = f"test_user_{''.join(random.choices(string.ascii_lowercase + string.digits, k=8))}"
                
                # Create user
                user = User(
                    id=str(uuid.uuid4()),
                    telegram_id=fake_tg_id,
                    username=username,
                    first_name=f"Test{i+1}",
                    last_name="User",
                    status=UserStatus.ACTIVE,
                    created_at=datetime.utcnow() - timedelta(days=random.randint(1, 365))
                )
                
                if hasattr(user, 'last_active'):
                    user.last_active = datetime.utcnow()
                
                session.add(user)
                await session.flush()
                
                # Create wallets for each network
                for network, config in NETWORKS.items():
                    try:
                        wallet_data = await wallet_manager.create_wallet(network)
                        wallet = Wallet(
                            id=str(uuid.uuid4()),
                            user_id=user.id,
                            network=network,
                            address=wallet_data.address,
                            encrypted_private_key=wallet_data.private_key,
                            is_active=True
                        )
                        session.add(wallet)
                        await session.flush()
                        
                        # Add some random balance (70% chance)
                        if random.random() > 0.3:
                            balance_kwargs = create_wallet_balance_kwargs(
                                wallet_id=wallet.id,
                                token_symbol=config.symbol,
                                balance=Decimal(str(random.uniform(0, 1000))).quantize(Decimal("0.0001")),
                                decimals=config.decimals
                            )
                            balance = WalletBalance(**balance_kwargs)
                            session.add(balance)
                    except Exception as e:
                        logger.warning(f"Failed to create wallet for {network}", error=str(e))
                
                created += 1
                created_users.append(f"@{username} (ID: {fake_tg_id})")
            
            await session.commit()
            
            logger.info(
                "Test users created",
                admin_id=message.from_user.id,
                count=created
            )
        
        # Format created users list
        users_list = "\n".join(created_users[:10])
        if len(created_users) > 10:
            users_list += f"\n... and {len(created_users) - 10} more"
        
        await progress_msg.edit_text(
            f"✅ <b>Test Users Created!</b>\n\n"
            f"Created: <b>{created}</b> users\n\n"
            f"<b>Users:</b>\n{users_list}",
            reply_markup=AdminKeyboards.back(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error("Create users failed", error=str(e), exc_info=True)
        await progress_msg.edit_text(
            f"❌ Failed: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back()
        )
    
    await state.clear()


# ==================== RESET USER ====================

@router.callback_query(F.data == "admin_test:reset_user")
async def reset_user_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start reset user flow"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    text = """
🗑 <b>Reset User Data</b>

This will reset all user data including:
• All balances (set to 0)
• Transaction history
• Trading stats

Enter Telegram ID or @username:
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.cancel())
    await state.set_state(AdminTestStates.reset_user_input)
    await safe_answer(callback)


@router.message(AdminTestStates.reset_user_input)
async def reset_user_input(message: Message, state: FSMContext) -> None:
    """Process user for reset"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    query = message.text.strip()
    
    async with db_manager.session() as session:
        if query.lower() == "me":
            user = await session.scalar(
                select(User).where(User.telegram_id == message.from_user.id)
            )
        else:
            user = await get_user_by_query(session, query)
        
        if not user:
            await message.answer(
                "❌ User not found.",
                reply_markup=AdminKeyboards.cancel()
            )
            return
        
        # Get current stats
        wallet_count = await session.scalar(
            select(func.count(Wallet.id)).where(Wallet.user_id == user.id)
        ) or 0
        
        tx_count = await session.scalar(
            select(func.count(Transaction.id)).where(Transaction.user_id == user.id)
        ) or 0
        
        await state.update_data(
            target_user_id=str(user.id),
            target_tg_id=user.telegram_id,
            target_username=user.username,
            wallet_count=wallet_count,
            tx_count=tx_count
        )
    
    text = f"""
🗑 <b>Confirm Reset</b>

User: <code>{user.telegram_id}</code> (@{user.username or 'N/A'})

<b>Data to be reset:</b>
├ Wallets: {wallet_count}
├ Transactions: {tx_count}
└ All balances → 0

⚠️ This action cannot be undone!
"""
    
    await message.answer(
        text,
        reply_markup=AdminKeyboards.confirm("admin_test:reset_user_confirm"),
        parse_mode="HTML"
    )
    await state.set_state(AdminTestStates.reset_user_confirm)


@router.callback_query(
    AdminTestStates.reset_user_confirm,
    F.data == "admin_test:reset_user_confirm"
)
async def reset_user_execute(callback: CallbackQuery, state: FSMContext) -> None:
    """Execute user reset"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    data = await state.get_data()
    user_id = data['target_user_id']
    
    await safe_edit(callback.message, "⏳ <b>Resetting user data...</b>")
    
    try:
        async with db_manager.session() as session:
            # Get all wallet IDs
            result = await session.execute(
                select(Wallet.id).where(Wallet.user_id == user_id)
            )
            wallet_ids = [r[0] for r in result]
            
            balances_reset = 0
            txs_deleted = 0
            
            if wallet_ids:
                # Reset all balances to 0
                result = await session.execute(
                    update(WalletBalance)
                    .where(WalletBalance.wallet_id.in_(wallet_ids))
                    .values(balance=Decimal("0"))
                )
                balances_reset = result.rowcount
            
            # Delete all transactions
            result = await session.execute(
                delete(Transaction).where(Transaction.user_id == user_id)
            )
            txs_deleted = result.rowcount
            
            await session.commit()
            
            logger.info(
                "User reset completed",
                admin_id=callback.from_user.id,
                user_id=user_id,
                balances_reset=balances_reset,
                txs_deleted=txs_deleted
            )
        
        await callback.message.edit_text(
            f"✅ <b>User Reset Complete!</b>\n\n"
            f"User: <code>{data['target_tg_id']}</code>\n\n"
            f"<b>Reset stats:</b>\n"
            f"├ Balances reset: {balances_reset}\n"
            f"├ Transactions deleted: {txs_deleted}\n"
            f"└ Stats reset: ✓",
            reply_markup=AdminKeyboards.back(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error("User reset failed", error=str(e), exc_info=True)
        await callback.message.edit_text(
            f"❌ Reset failed: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back()
        )
    
    await state.clear()
    await safe_answer(callback)


# ==================== TEST NETWORKS ====================

@router.callback_query(F.data == "admin_test:test_networks")
async def test_networks(callback: CallbackQuery) -> None:
    """Test all network RPC connections"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await safe_edit(callback.message, "⏳ <b>Testing network connections...</b>")
    
    results = {}
    
    for network, config in NETWORKS.items():
        try:
            start_time = datetime.utcnow()
            
            if hasattr(wallet_manager, 'test_connection'):
                is_connected = await wallet_manager.test_connection(network)
            else:
                is_connected = True
            
            latency = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            results[network] = {
                "status": "✅" if is_connected else "❌",
                "latency": f"{latency:.0f}ms",
                "icon": config.icon,
                "testnet": getattr(config, 'is_testnet', False)
            }
            
        except Exception as e:
            results[network] = {
                "status": "❌",
                "latency": "N/A",
                "icon": config.icon,
                "error": str(e)[:30],
                "testnet": getattr(config, 'is_testnet', False)
            }
    
    text = "🔧 <b>Network Status</b>\n\n"
    
    for network, data in results.items():
        testnet_mark = " 🧪" if data.get('testnet') else ""
        text += f"{data['icon']} <b>{network.upper()}</b>{testnet_mark}\n"
        text += f"├ Status: {data['status']}\n"
        text += f"├ Latency: {data['latency']}\n"
        if 'error' in data:
            text += f"└ Error: <code>{data['error']}</code>\n"
        else:
            text += f"└ RPC: OK\n"
        text += "\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_test:test_networks")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin_test:menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await safe_answer(callback)


# ==================== TON FAUCET ====================

@router.callback_query(F.data == "admin_test:ton_faucet")
async def ton_faucet(callback: CallbackQuery) -> None:
    """TON testnet faucet info"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    text = """
💎 <b>TON Testnet Faucet</b>

To get testnet TON:

<b>1. Official Testnet Faucet:</b>
🔗 https://t.me/testgiver_ton_bot

<b>2. Alternative Faucets:</b>
🔗 https://faucet.toncenter.com/
🔗 https://t.me/ton_testnet_faucet_bot

<b>Instructions:</b>
1. Get your testnet wallet address
2. Visit one of the faucets
3. Enter your address
4. Receive testnet TON

⚠️ Testnet TON has no real value!
"""
    
    # Get admin's TON wallet
    try:
        async with db_manager.session() as session:
            admin_user = await session.scalar(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            
            if admin_user:
                ton_wallet = await session.scalar(
                    select(Wallet).where(
                        Wallet.user_id == admin_user.id,
                        Wallet.network == "ton"
                    )
                )
                
                if ton_wallet:
                    text += f"\n<b>Your TON wallet:</b>\n<code>{ton_wallet.address}</code>"
                else:
                    text += "\n<i>No TON wallet found</i>"
    except Exception as e:
        text += f"\n<i>Error: {str(e)[:50]}</i>"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Open Faucet Bot", url="https://t.me/testgiver_ton_bot")],
        [InlineKeyboardButton(text="🌐 Web Faucet", url="https://faucet.toncenter.com/")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin_test:menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await safe_answer(callback)


# ==================== VIEW TEST DATA ====================

@router.callback_query(F.data == "admin_test:view_data")
async def view_test_data(callback: CallbackQuery) -> None:
    """View test data statistics"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    try:
        async with db_manager.session() as session:
            # Count test users (negative telegram_id)
            test_users = await session.scalar(
                select(func.count(User.id)).where(User.telegram_id < 0)
            ) or 0
            
            # Count admin transactions
            admin_txs = await session.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.from_address.like("ADMIN%")
                )
            ) or 0
            
            # Count total data
            total_users = await session.scalar(select(func.count(User.id))) or 0
            total_wallets = await session.scalar(select(func.count(Wallet.id))) or 0
            total_txs = await session.scalar(select(func.count(Transaction.id))) or 0
            total_balances = await session.scalar(select(func.count(WalletBalance.id))) or 0
            
            # Recent admin activity
            recent_admin_txs = await session.execute(
                select(Transaction)
                .where(Transaction.from_address.like("ADMIN%"))
                .order_by(Transaction.created_at.desc())
                .limit(5)
            )
            recent = recent_admin_txs.scalars().all()
        
        text = f"""
📋 <b>Test Data Overview</b>

<b>Test Data:</b>
├ Test Users: {test_users}
└ Admin Transactions: {admin_txs}

<b>Total Data:</b>
├ Users: {total_users}
├ Wallets: {total_wallets}
├ Transactions: {total_txs}
└ Balance Records: {total_balances}

<b>Recent Admin Activity:</b>
"""
        
        if recent:
            for tx in recent:
                time_str = tx.created_at.strftime("%m/%d %H:%M") if tx.created_at else "?"
                text += f"• {time_str} | {tx.amount} {tx.token_symbol}\n"
        else:
            text += "<i>No recent activity</i>\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_test:view_data")],
            [InlineKeyboardButton(text="🧹 Cleanup Test Data", callback_data="admin_test:cleanup")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin_test:menu")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        
    except Exception as e:
        logger.error("View data failed", error=str(e))
        await callback.message.edit_text(
            f"❌ Error: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back()
        )
    
    await safe_answer(callback)


# ==================== CLEANUP ====================

@router.callback_query(F.data == "admin_test:cleanup")
async def cleanup_start(callback: CallbackQuery) -> None:
    """Start cleanup flow"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    try:
        async with db_manager.session() as session:
            test_users = await session.scalar(
                select(func.count(User.id)).where(User.telegram_id < 0)
            ) or 0
            
            admin_txs = await session.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.from_address.like("ADMIN%")
                )
            ) or 0
    except Exception:
        test_users = admin_txs = 0
    
    text = f"""
🧹 <b>Cleanup Test Data</b>

This will permanently delete:
├ Test users (fake accounts): <b>{test_users}</b>
├ Admin/simulated transactions: <b>{admin_txs}</b>
└ Associated wallets and balances

⚠️ <b>This action cannot be undone!</b>

Proceed with cleanup?
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑 Delete All", callback_data="admin_test:cleanup_all"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="admin_test:menu")
        ],
        [
            InlineKeyboardButton(text="👤 Only Test Users", callback_data="admin_test:cleanup_users"),
            InlineKeyboardButton(text="📝 Only Fake TXs", callback_data="admin_test:cleanup_txs")
        ]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await safe_answer(callback)


@router.callback_query(F.data == "admin_test:cleanup_all")
async def cleanup_all(callback: CallbackQuery) -> None:
    """Delete all test data"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await safe_edit(callback.message, "⏳ <b>Cleaning up...</b>")
    
    try:
        async with db_manager.session() as session:
            deleted_users = 0
            deleted_txs = 0
            deleted_wallets = 0
            
            # Get test user IDs
            result = await session.execute(
                select(User.id).where(User.telegram_id < 0)
            )
            test_user_ids = [r[0] for r in result]
            
            if test_user_ids:
                # Get their wallet IDs
                result = await session.execute(
                    select(Wallet.id).where(Wallet.user_id.in_(test_user_ids))
                )
                wallet_ids = [r[0] for r in result]
                
                # Delete balances
                if wallet_ids:
                    await session.execute(
                        delete(WalletBalance).where(WalletBalance.wallet_id.in_(wallet_ids))
                    )
                
                # Delete transactions
                result = await session.execute(
                    delete(Transaction).where(Transaction.user_id.in_(test_user_ids))
                )
                deleted_txs += result.rowcount
                
                # Delete wallets
                result = await session.execute(
                    delete(Wallet).where(Wallet.user_id.in_(test_user_ids))
                )
                deleted_wallets = result.rowcount
                
                # Delete users
                result = await session.execute(
                    delete(User).where(User.id.in_(test_user_ids))
                )
                deleted_users = result.rowcount
            
            # Delete admin/simulated transactions for real users
            result = await session.execute(
                delete(Transaction).where(
                    Transaction.from_address.like("ADMIN%")
                )
            )
            deleted_txs += result.rowcount
            
            await session.commit()
            
            logger.info(
                "Cleanup completed",
                admin_id=callback.from_user.id,
                deleted_users=deleted_users,
                deleted_wallets=deleted_wallets,
                deleted_txs=deleted_txs
            )
        
        await callback.message.edit_text(
            f"✅ <b>Cleanup Complete!</b>\n\n"
            f"Deleted:\n"
            f"├ Users: {deleted_users}\n"
            f"├ Wallets: {deleted_wallets}\n"
            f"└ Transactions: {deleted_txs}",
            reply_markup=AdminKeyboards.back(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error("Cleanup failed", error=str(e), exc_info=True)
        await callback.message.edit_text(
            f"❌ Cleanup failed: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back()
        )
    
    await safe_answer(callback)


@router.callback_query(F.data == "admin_test:cleanup_users")
async def cleanup_users_only(callback: CallbackQuery) -> None:
    """Delete only test users"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await safe_edit(callback.message, "⏳ <b>Deleting test users...</b>")
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(User.id).where(User.telegram_id < 0)
            )
            test_user_ids = [r[0] for r in result]
            
            deleted = 0
            
            if test_user_ids:
                result = await session.execute(
                    select(Wallet.id).where(Wallet.user_id.in_(test_user_ids))
                )
                wallet_ids = [r[0] for r in result]
                
                if wallet_ids:
                    await session.execute(
                        delete(WalletBalance).where(WalletBalance.wallet_id.in_(wallet_ids))
                    )
                
                await session.execute(
                    delete(Transaction).where(Transaction.user_id.in_(test_user_ids))
                )
                
                await session.execute(
                    delete(Wallet).where(Wallet.user_id.in_(test_user_ids))
                )
                
                result = await session.execute(
                    delete(User).where(User.id.in_(test_user_ids))
                )
                deleted = result.rowcount
            
            await session.commit()
        
        await callback.message.edit_text(
            f"✅ Deleted {deleted} test users and their data.",
            reply_markup=AdminKeyboards.back(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error("Cleanup users failed", error=str(e))
        await callback.message.edit_text(
            f"❌ Failed: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back()
        )
    
    await safe_answer(callback)


@router.callback_query(F.data == "admin_test:cleanup_txs")
async def cleanup_txs_only(callback: CallbackQuery) -> None:
    """Delete only fake transactions"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await safe_edit(callback.message, "⏳ <b>Deleting fake transactions...</b>")
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                delete(Transaction).where(
                    Transaction.from_address.like("ADMIN%")
                )
            )
            deleted = result.rowcount
            
            await session.commit()
        
        await callback.message.edit_text(
            f"✅ Deleted {deleted} fake transactions.",
            reply_markup=AdminKeyboards.back(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error("Cleanup txs failed", error=str(e))
        await callback.message.edit_text(
            f"❌ Failed: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back()
        )
    
    await safe_answer(callback)

# ==================== admin_test.py (НЕДОСТАЮЩИЕ ЧАСТИ) ====================
# Добавить после cleanup_txs_only

# ==================== SET BALANCE (полный flow) ====================

@router.callback_query(F.data == "admin_test:set_balance")
async def set_balance_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start set balance flow"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    text = """
📊 <b>Set Exact Balance</b>

Enter the Telegram ID or @username:
<i>(or "me" for yourself)</i>
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.cancel())
    await state.set_state(AdminTestStates.set_balance_user)
    await safe_answer(callback)


@router.message(AdminTestStates.set_balance_user)
async def set_balance_user(message: Message, state: FSMContext) -> None:
    """Process user for set balance"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    query = message.text.strip()
    
    async with db_manager.session() as session:
        if query.lower() == "me":
            user = await session.scalar(
                select(User).where(User.telegram_id == message.from_user.id)
            )
        else:
            user = await get_user_by_query(session, query)
        
        if not user:
            await message.answer(
                "❌ User not found.",
                reply_markup=AdminKeyboards.cancel()
            )
            return
        
        await state.update_data(
            target_user_id=str(user.id),
            target_tg_id=user.telegram_id
        )
    
    text = f"📊 User: <code>{user.telegram_id}</code> (@{user.username or 'N/A'})\n\nSelect network:"
    await message.answer(
        text,
        reply_markup=AdminKeyboards.network_select("admin_test:set_bal_net"),
        parse_mode="HTML"
    )
    await state.set_state(AdminTestStates.set_balance_network)


@router.callback_query(
    AdminTestStates.set_balance_network,
    F.data.startswith("admin_test:set_bal_net:")
)
async def set_balance_network(callback: CallbackQuery, state: FSMContext) -> None:
    """Select network for set balance"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    network = callback.data.split(":")[-1]
    await state.update_data(network=network)
    
    config = NETWORKS[network]
    
    text = f"""
📊 <b>Set {config.icon} {config.symbol} Balance</b>

Enter the exact balance to set:
<i>This will REPLACE the current balance!</i>
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.cancel())
    await state.set_state(AdminTestStates.set_balance_amount)
    await safe_answer(callback)


@router.message(AdminTestStates.set_balance_amount)
async def set_balance_amount(message: Message, state: FSMContext) -> None:
    """Set exact balance"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        amount = Decimal(message.text.strip().replace(",", "."))
        if amount < 0:
            raise ValueError("Amount cannot be negative")
    except (InvalidOperation, ValueError):
        await message.answer(
            "❌ Invalid amount.",
            reply_markup=AdminKeyboards.cancel()
        )
        return
    
    data = await state.get_data()
    user_id = data['target_user_id']
    network = data['network']
    config = NETWORKS[network]
    
    try:
        async with db_manager.session() as session:
            wallet = await session.scalar(
                select(Wallet).where(
                    Wallet.user_id == user_id,
                    Wallet.network == network
                )
            )
            
            if not wallet:
                wallet_data = await wallet_manager.create_wallet(network)
                wallet = Wallet(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    network=network,
                    address=wallet_data.address,
                    encrypted_private_key=wallet_data.private_key,
                    is_active=True
                )
                session.add(wallet)
                await session.flush()
            
            balance = await session.scalar(
                select(WalletBalance).where(
                    WalletBalance.wallet_id == wallet.id,
                    WalletBalance.token_symbol == config.symbol
                )
            )
            
            old_balance = Decimal("0")
            
            if balance:
                old_balance = balance.balance
                balance.balance = amount
                if 'updated_at' in WALLET_BALANCE_FIELDS:
                    balance.updated_at = datetime.utcnow()
            else:
                balance_kwargs = create_wallet_balance_kwargs(
                    wallet_id=wallet.id,
                    token_symbol=config.symbol,
                    balance=amount,
                    decimals=config.decimals
                )
                balance = WalletBalance(**balance_kwargs)
                session.add(balance)
            
            await session.commit()
            
            logger.info(
                "Test balance set",
                admin_id=message.from_user.id,
                user_id=user_id,
                network=network,
                old_balance=str(old_balance),
                new_balance=str(amount)
            )
        
        await message.answer(
            f"✅ <b>Balance Set!</b>\n\n"
            f"User: <code>{data['target_tg_id']}</code>\n"
            f"Network: {config.icon} {network.upper()}\n"
            f"Old: {old_balance} {config.symbol}\n"
            f"New: <b>{amount} {config.symbol}</b>",
            reply_markup=AdminKeyboards.back(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error("Set balance failed", error=str(e), exc_info=True)
        await message.answer(
            f"❌ Failed: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back()
        )
    
    await state.clear()


# ==================== SHOP VIEW ====================

@router.callback_query(F.data.startswith("admin_test:shop_view:"))
async def shop_view(callback: CallbackQuery, state: FSMContext) -> None:
    """View single shop details"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    shop_id = callback.data.split(":")[-1]
    
    try:
        async with db_manager.session() as session:
            if not Shop:
                await safe_answer(callback, "❌ Shop model not available", show_alert=True)
                return
            
            shop = await session.scalar(
                select(Shop)
                .options(selectinload(Shop.owner))
                .where(Shop.id == shop_id)
            )
            
            if not shop:
                await safe_answer(callback, "❌ Shop not found", show_alert=True)
                return
            
            # Get additional stats
            product_count = 0
            order_count = 0
            total_revenue = Decimal("0")
            
            if ShopProduct:
                product_count = await session.scalar(
                    select(func.count(ShopProduct.id)).where(ShopProduct.shop_id == shop_id)
                ) or 0
            
            if ShopOrder:
                order_count = await session.scalar(
                    select(func.count(ShopOrder.id)).where(ShopOrder.shop_id == shop_id)
                ) or 0
                
                total_revenue = await session.scalar(
                    select(func.sum(ShopOrder.price_usd)).where(
                        ShopOrder.shop_id == shop_id,
                        ShopOrder.status == "completed"
                    )
                ) or Decimal("0")
            
            status_emoji = {
                ShopStatus.APPROVED: "🟢 Active",
                ShopStatus.PENDING: "⏳ Pending",
                ShopStatus.SUSPENDED: "🚫 Suspended",
            }
            
            owner_info = f"@{shop.owner.username}" if shop.owner and shop.owner.username else "N/A"
            owner_tg = shop.owner.telegram_id if shop.owner else "N/A"
            description = getattr(shop, 'description', None) or "No description"
            
            text = f"""
🏪 <b>Shop Details</b>

<b>Name:</b> {shop.name}
<b>ID:</b> <code>{shop.id}</code>
<b>Status:</b> {status_emoji.get(shop.status, str(shop.status))}

<b>Owner:</b>
├ Username: {owner_info}
└ Telegram ID: <code>{owner_tg}</code>

<b>Statistics:</b>
├ Products: {product_count}
├ Orders: {order_count}
└ Revenue: ${float(total_revenue):,.2f}

<b>Description:</b>
{description[:200]}

<b>Created:</b> {shop.created_at.strftime('%Y-%m-%d %H:%M') if shop.created_at else 'N/A'}
"""
            
            # Build action keyboard based on status
            buttons = []
            
            if shop.status == ShopStatus.PENDING:
                buttons.append([
                    InlineKeyboardButton(text="✅ Approve", callback_data=f"admin_test:shop_approve:{shop_id}"),
                    InlineKeyboardButton(text="❌ Reject", callback_data=f"admin_test:shop_reject:{shop_id}")
                ])
            elif shop.status == ShopStatus.APPROVED:
                buttons.append([
                    InlineKeyboardButton(text="🚫 Suspend", callback_data=f"admin_test:shop_suspend:{shop_id}")
                ])
            elif shop.status == ShopStatus.SUSPENDED:
                buttons.append([
                    InlineKeyboardButton(text="✅ Unsuspend", callback_data=f"admin_test:shop_unsuspend:{shop_id}"),
                    InlineKeyboardButton(text="❌ Close", callback_data=f"admin_test:shop_close:{shop_id}")
                ])
            
            buttons.append([
                InlineKeyboardButton(text="📝 Edit", callback_data=f"admin_test:shop_edit:{shop_id}"),
                InlineKeyboardButton(text="🗑 Delete", callback_data=f"admin_test:shop_delete:{shop_id}")
            ])
            
            buttons.append([
                InlineKeyboardButton(text="📦 Products", callback_data=f"admin_test:shop_products:{shop_id}")
            ])
            
            buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin_test:shop_list")])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error("Shop view failed", error=str(e), exc_info=True)
        await safe_answer(callback, f"❌ Error: {str(e)[:50]}", show_alert=True)
    
    await safe_answer(callback)


# ==================== APPLICATION VIEW ====================

@router.callback_query(F.data.startswith("admin_test:app_view:"))
async def app_view(callback: CallbackQuery, state: FSMContext) -> None:
    """View shop application details"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    app_id_short = callback.data.split(":")[-1]
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(ShopApplication)
                .options(selectinload(ShopApplication.user))
                .where(ShopApplication.id.like(f"{app_id_short}%"))
            )
            app = result.scalar_one_or_none()
            
            if not app:
                await safe_answer(callback, "❌ Application not found", show_alert=True)
                return
            
            user = app.user
            username = f"@{user.username}" if user and user.username else "N/A"
            tg_id = user.telegram_id if user else "N/A"
            
            # Get user stats
            trades = getattr(user, 'total_trades_count', 0) or 0
            volume = float(getattr(user, 'total_volume_usd', 0) or 0)
            rating = float(getattr(user, 'rating', 0) or 0)
            
            tokens = app.proposed_tokens or []
            token_list = ", ".join([t.get('symbol', t.get('network', '?')) for t in tokens])
            
            text = f"""
📝 <b>Shop Application</b>

<b>Shop Name:</b> {app.shop_name}
<b>ID:</b> <code>{app.id}</code>
<b>Status:</b> {app.status.value if hasattr(app.status, 'value') else app.status}

<b>Applicant:</b>
├ Username: {username}
├ Telegram ID: <code>{tg_id}</code>
├ Trades: {trades}
├ Volume: ${volume:,.0f}
└ Rating: {rating:.1f}

<b>Tokens:</b> {token_list or 'None'}

<b>Description:</b>
{(app.description or 'None')[:200]}

<b>Motivation:</b>
{(app.motivation or 'None')[:300]}

<b>Submitted:</b> {app.created_at.strftime('%Y-%m-%d %H:%M') if app.created_at else 'N/A'}
"""
            
            if app.status == ShopApplicationStatus.PENDING:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Approve", callback_data=f"admin_test:app_approve:{app.id}"),
                        InlineKeyboardButton(text="❌ Reject", callback_data=f"admin_test:app_reject:{app.id}")
                    ],
                    [InlineKeyboardButton(text="🔙 Back", callback_data="admin_test:shop_pending")]
                ])
            else:
                keyboard = AdminKeyboards.back("admin_test:shop_pending")
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error("App view failed", error=str(e))
        await safe_answer(callback, f"❌ Error: {str(e)[:50]}", show_alert=True)
    
    await safe_answer(callback)


# ==================== APPLICATION APPROVE/REJECT ====================

@router.callback_query(F.data.startswith("admin_test:app_approve:"))
async def app_approve(callback: CallbackQuery, state: FSMContext) -> None:
    """Approve shop application"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    app_id = callback.data.split(":")[-1]
    
    try:
        from services.shop_service import shop_service
        
        async with db_manager.session() as session:
            shop, message = await shop_service.approve_application(
                session=session,
                app_id=app_id,
                admin_id=callback.from_user.id,
                notes="Approved via admin panel"
            )
            
            if shop:
                await session.commit()
                
                # Notify owner
                try:
                    app = await shop_service.get_application_by_id(session, app_id)
                    if app and app.user:
                        await callback.bot.send_message(
                            app.user.telegram_id,
                            f"🎉 <b>Congratulations!</b>\n\n"
                            f"Your shop <b>{shop.name}</b> has been approved!\n"
                            f"You can now start adding products.",
                            parse_mode="HTML"
                        )
                except Exception as e:
                    logger.warning("Failed to notify shop owner", error=str(e))
                
                await safe_answer(callback, f"✅ Shop '{shop.name}' approved!", show_alert=True)
            else:
                await safe_answer(callback, f"❌ {message}", show_alert=True)
        
        # Refresh pending list
        await shop_pending_list(callback)
        
    except Exception as e:
        logger.error("App approve failed", error=str(e))
        await safe_answer(callback, f"❌ Error: {str(e)[:50]}", show_alert=True)


@router.callback_query(F.data.startswith("admin_test:app_reject:"))
async def app_reject(callback: CallbackQuery, state: FSMContext) -> None:
    """Reject shop application"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    app_id = callback.data.split(":")[-1]
    
    try:
        from services.shop_service import shop_service
        
        async with db_manager.session() as session:
            success, message = await shop_service.reject_application(
                session=session,
                app_id=app_id,
                admin_id=callback.from_user.id,
                reason="Rejected via admin panel"
            )
            
            if success:
                await session.commit()
                
                # Notify owner
                try:
                    app = await shop_service.get_application_by_id(session, app_id)
                    if app and app.user:
                        await callback.bot.send_message(
                            app.user.telegram_id,
                            f"❌ <b>Shop Application Rejected</b>\n\n"
                            f"Your shop application <b>{app.shop_name}</b> was not approved.\n"
                            f"Please contact support for more information.",
                            parse_mode="HTML"
                        )
                except Exception as e:
                    logger.warning("Failed to notify applicant", error=str(e))
                
                await safe_answer(callback, "❌ Application rejected", show_alert=True)
            else:
                await safe_answer(callback, f"❌ {message}", show_alert=True)
        
        await shop_pending_list(callback)
        
    except Exception as e:
        logger.error("App reject failed", error=str(e))
        await safe_answer(callback, f"❌ Error: {str(e)[:50]}", show_alert=True)


# ==================== SHOP APPROVE/SUSPEND/UNSUSPEND ====================

@router.callback_query(F.data.startswith("admin_test:shop_approve:"))
async def shop_approve(callback: CallbackQuery, state: FSMContext) -> None:
    """Approve a shop"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    shop_id = callback.data.split(":")[-1]
    
    try:
        async with db_manager.session() as session:
            shop = await session.scalar(
                select(Shop).options(selectinload(Shop.owner)).where(Shop.id == shop_id)
            )
            
            if not shop:
                await safe_answer(callback, "❌ Shop not found", show_alert=True)
                return
            
            shop.status = ShopStatus.APPROVED
            if hasattr(shop, 'approved_at'):
                shop.approved_at = datetime.utcnow()
            
            shop_name = shop.name
            owner = shop.owner
            
            await session.commit()
            
            logger.info("Shop approved", shop_id=shop_id, admin_id=callback.from_user.id)
            
            # Notify owner
            try:
                if owner:
                    await callback.bot.send_message(
                        owner.telegram_id,
                        f"🎉 <b>Congratulations!</b>\n\n"
                        f"Your shop <b>{shop_name}</b> has been approved!\n"
                        f"You can now start adding products.",
                        parse_mode="HTML"
                    )
            except Exception as e:
                logger.warning("Failed to notify shop owner", error=str(e))
            
            await safe_answer(callback, f"✅ Shop '{shop_name}' approved!", show_alert=True)
            
            # Refresh shop view
            callback.data = f"admin_test:shop_view:{shop_id}"
            await shop_view(callback, state)
            
    except Exception as e:
        logger.error("Shop approve failed", error=str(e))
        await safe_answer(callback, f"❌ Error: {str(e)[:50]}", show_alert=True)


@router.callback_query(F.data.startswith("admin_test:shop_suspend:"))
async def shop_suspend_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start shop suspension"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    shop_id = callback.data.split(":")[-1]
    await state.update_data(action_shop_id=shop_id)
    
    text = """
🚫 <b>Suspend Shop</b>

Enter the reason for suspension:
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=AdminKeyboards.cancel("admin_test:shop_menu"),
        parse_mode="HTML"
    )
    await state.set_state(AdminTestStates.shop_suspend_reason)
    await safe_answer(callback)


@router.message(AdminTestStates.shop_suspend_reason)
async def shop_suspend_execute(message: Message, state: FSMContext) -> None:
    """Execute shop suspension"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    reason = message.text.strip()
    data = await state.get_data()
    shop_id = data.get("action_shop_id")
    
    if not shop_id:
        await message.answer(
            "❌ Session expired.",
            reply_markup=AdminKeyboards.back("admin_test:shop_menu")
        )
        await state.clear()
        return
    
    try:
        async with db_manager.session() as session:
            shop = await session.scalar(
                select(Shop).options(selectinload(Shop.owner)).where(Shop.id == shop_id)
            )
            
            if not shop:
                await message.answer(
                    "❌ Shop not found.",
                    reply_markup=AdminKeyboards.back("admin_test:shop_menu")
                )
                await state.clear()
                return
            
            shop.status = ShopStatus.SUSPENDED
            if hasattr(shop, 'suspended_at'):
                shop.suspended_at = datetime.utcnow()
            
            # Update owner
            if shop.owner and hasattr(shop.owner, 'has_shop'):
                shop.owner.has_shop = False
            
            shop_name = shop.name
            owner = shop.owner
            
            await session.commit()
            
            logger.info(
                "Shop suspended",
                shop_id=shop_id,
                admin_id=message.from_user.id,
                reason=reason
            )
            
            # Notify owner
            try:
                if owner:
                    await message.bot.send_message(
                        owner.telegram_id,
                        f"🚫 <b>Shop Suspended</b>\n\n"
                        f"Your shop <b>{shop_name}</b> has been suspended.\n\n"
                        f"<b>Reason:</b> {reason}\n\n"
                        f"Please contact support to resolve this issue.",
                        parse_mode="HTML"
                    )
            except Exception as e:
                logger.warning("Failed to notify shop owner", error=str(e))
        
        await message.answer(
            f"✅ <b>Shop Suspended</b>\n\n"
            f"Shop: {shop_name}\n"
            f"Reason: {reason}",
            reply_markup=AdminKeyboards.back("admin_test:shop_menu"),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error("Shop suspend failed", error=str(e))
        await message.answer(
            f"❌ Error: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back("admin_test:shop_menu")
        )
    
    await state.clear()


@router.callback_query(F.data.startswith("admin_test:shop_unsuspend:"))
async def shop_unsuspend(callback: CallbackQuery, state: FSMContext) -> None:
    """Unsuspend a shop"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    shop_id = callback.data.split(":")[-1]
    
    try:
        async with db_manager.session() as session:
            shop = await session.scalar(
                select(Shop).options(selectinload(Shop.owner)).where(Shop.id == shop_id)
            )
            
            if not shop:
                await safe_answer(callback, "❌ Shop not found", show_alert=True)
                return
            
            shop.status = ShopStatus.APPROVED
            if hasattr(shop, 'suspended_at'):
                shop.suspended_at = None
            
            # Update owner
            if shop.owner and hasattr(shop.owner, 'has_shop'):
                shop.owner.has_shop = True
            
            shop_name = shop.name
            owner = shop.owner
            
            await session.commit()
            
            logger.info("Shop unsuspended", shop_id=shop_id, admin_id=callback.from_user.id)
            
            # Notify owner
            try:
                if owner:
                    await callback.bot.send_message(
                        owner.telegram_id,
                        f"✅ <b>Shop Reactivated</b>\n\n"
                        f"Your shop <b>{shop_name}</b> has been reactivated.\n"
                        f"You can continue normal operations.",
                        parse_mode="HTML"
                    )
            except Exception as e:
                logger.warning("Failed to notify shop owner", error=str(e))
            
            await safe_answer(callback, f"✅ Shop '{shop_name}' reactivated!", show_alert=True)
            
            # Refresh shop view
            callback.data = f"admin_test:shop_view:{shop_id}"
            await shop_view(callback, state)
            
    except Exception as e:
        logger.error("Shop unsuspend failed", error=str(e))
        await safe_answer(callback, f"❌ Error: {str(e)[:50]}", show_alert=True)


# ==================== SHOP CLOSE/DELETE ====================

@router.callback_query(F.data.startswith("admin_test:shop_close:"))
async def shop_close(callback: CallbackQuery, state: FSMContext) -> None:
    """Permanently close a shop"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    shop_id = callback.data.split(":")[-1]
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yes, Close", callback_data=f"admin_test:shop_close_confirm:{shop_id}"),
            InlineKeyboardButton(text="❌ Cancel", callback_data=f"admin_test:shop_view:{shop_id}")
        ]
    ])
    
    await callback.message.edit_text(
        "⚠️ <b>Confirm Shop Closure</b>\n\n"
        "Are you sure you want to permanently close this shop?\n"
        "This action cannot be easily undone.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await safe_answer(callback)


@router.callback_query(F.data.startswith("admin_test:shop_close_confirm:"))
async def shop_close_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """Execute shop closure"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    shop_id = callback.data.split(":")[-1]
    
    try:
        async with db_manager.session() as session:
            shop = await session.scalar(
                select(Shop).options(selectinload(Shop.owner)).where(Shop.id == shop_id)
            )
            
            if not shop:
                await safe_answer(callback, "❌ Shop not found", show_alert=True)
                return
            
            # Use SUSPENDED as "closed" if no CLOSED status
            if hasattr(ShopStatus, 'CLOSED'):
                shop.status = ShopStatus.CLOSED
            else:
                shop.status = ShopStatus.SUSPENDED
            
            shop_name = shop.name
            owner = shop.owner
            
            # Update owner
            if owner and hasattr(owner, 'has_shop'):
                owner.has_shop = False
            
            await session.commit()
            
            logger.info("Shop closed", shop_id=shop_id, admin_id=callback.from_user.id)
            
            # Notify owner
            try:
                if owner:
                    await callback.bot.send_message(
                        owner.telegram_id,
                        f"❌ <b>Shop Closed</b>\n\n"
                        f"Your shop <b>{shop_name}</b> has been permanently closed.\n"
                        f"Contact support if you believe this is an error.",
                        parse_mode="HTML"
                    )
            except Exception:
                pass
            
            await safe_answer(callback, f"❌ Shop '{shop_name}' closed", show_alert=True)
            await shop_management_menu(callback, state)
            
    except Exception as e:
        logger.error("Shop close failed", error=str(e))
        await safe_answer(callback, f"❌ Error: {str(e)[:50]}", show_alert=True)


@router.callback_query(F.data.startswith("admin_test:shop_delete:"))
async def shop_delete(callback: CallbackQuery, state: FSMContext) -> None:
    """Delete a shop completely"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    shop_id = callback.data.split(":")[-1]
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑 Yes, Delete", callback_data=f"admin_test:shop_delete_confirm:{shop_id}"),
            InlineKeyboardButton(text="❌ Cancel", callback_data=f"admin_test:shop_view:{shop_id}")
        ]
    ])
    
    await callback.message.edit_text(
        "⚠️ <b>Confirm Shop Deletion</b>\n\n"
        "Are you sure you want to PERMANENTLY DELETE this shop?\n\n"
        "<b>This will delete:</b>\n"
        "• All products\n"
        "• All order history\n"
        "• All shop data\n\n"
        "⛔ <b>This action CANNOT be undone!</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await safe_answer(callback)


@router.callback_query(F.data.startswith("admin_test:shop_delete_confirm:"))
async def shop_delete_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """Execute shop deletion"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    shop_id = callback.data.split(":")[-1]
    
    try:
        async with db_manager.session() as session:
            shop = await session.scalar(select(Shop).where(Shop.id == shop_id))
            
            if not shop:
                await safe_answer(callback, "❌ Shop not found", show_alert=True)
                return
            
            shop_name = shop.name
            
            # Delete related data first
            if ShopProduct:
                await session.execute(
                    delete(ShopProduct).where(ShopProduct.shop_id == shop_id)
                )
            if ShopOrder:
                await session.execute(
                    delete(ShopOrder).where(ShopOrder.shop_id == shop_id)
                )
            
            # Delete shop
            await session.delete(shop)
            await session.commit()
            
            logger.info(
                "Shop deleted",
                shop_id=shop_id,
                shop_name=shop_name,
                admin_id=callback.from_user.id
            )
            
            await safe_answer(callback, f"🗑 Shop '{shop_name}' deleted", show_alert=True)
            await shop_management_menu(callback, state)
            
    except Exception as e:
        logger.error("Shop delete failed", error=str(e), exc_info=True)
        await safe_answer(callback, f"❌ Error: {str(e)[:50]}", show_alert=True)


# ==================== SHOP EDIT ====================

@router.callback_query(F.data.startswith("admin_test:shop_edit:"))
async def shop_edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start shop edit"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    shop_id = callback.data.split(":")[-1]
    await state.update_data(edit_shop_id=shop_id)
    
    text = """
📝 <b>Edit Shop</b>

Select field to edit:
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📛 Name", callback_data="admin_test:shop_edit_field:name")],
        [InlineKeyboardButton(text="📝 Description", callback_data="admin_test:shop_edit_field:description")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"admin_test:shop_view:{shop_id}")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await safe_answer(callback)


@router.callback_query(F.data.startswith("admin_test:shop_edit_field:"))
async def shop_edit_field(callback: CallbackQuery, state: FSMContext) -> None:
    """Edit shop field"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    field = callback.data.split(":")[-1]
    await state.update_data(edit_field=field)
    
    field_names = {
        "name": "Shop Name",
        "description": "Description"
    }
    
    data = await state.get_data()
    shop_id = data.get("edit_shop_id")
    
    text = f"""
📝 <b>Edit {field_names.get(field, field)}</b>

Enter new value:
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=AdminKeyboards.cancel(f"admin_test:shop_view:{shop_id}"),
        parse_mode="HTML"
    )
    await state.set_state(AdminTestStates.shop_edit_value)
    await safe_answer(callback)


@router.message(AdminTestStates.shop_edit_value)
async def shop_edit_save(message: Message, state: FSMContext) -> None:
    """Save shop edit"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    value = message.text.strip()
    data = await state.get_data()
    shop_id = data.get("edit_shop_id")
    field = data.get("edit_field")
    
    if not shop_id or not field:
        await message.answer(
            "❌ Session expired.",
            reply_markup=AdminKeyboards.back("admin_test:shop_menu")
        )
        await state.clear()
        return
    
    try:
        async with db_manager.session() as session:
            shop = await session.scalar(select(Shop).where(Shop.id == shop_id))
            
            if not shop:
                await message.answer(
                    "❌ Shop not found.",
                    reply_markup=AdminKeyboards.back("admin_test:shop_menu")
                )
                await state.clear()
                return
            
            if field == "name":
                shop.name = value
            elif field == "description":
                if hasattr(shop, 'description'):
                    shop.description = value
            
            await session.commit()
            
            logger.info(
                "Shop edited",
                admin_id=message.from_user.id,
                shop_id=shop_id,
                field=field
            )
        
        await message.answer(
            f"✅ <b>Shop Updated!</b>\n\n"
            f"Field: {field}\n"
            f"New value: {value[:100]}{'...' if len(value) > 100 else ''}",
            reply_markup=AdminKeyboards.back(f"admin_test:shop_view:{shop_id}"),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error("Shop edit failed", error=str(e))
        await message.answer(
            f"❌ Error: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back("admin_test:shop_menu")
        )
    
    await state.clear()


# ==================== SHOP PRODUCTS VIEW ====================

@router.callback_query(F.data.startswith("admin_test:shop_products:"))
async def shop_products_view(callback: CallbackQuery, state: FSMContext) -> None:
    """View shop products"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    shop_id = callback.data.split(":")[-1]
    
    try:
        async with db_manager.session() as session:
            if not ShopProduct:
                await callback.message.edit_text(
                    "❌ ShopProduct model not available.",
                    reply_markup=AdminKeyboards.back(f"admin_test:shop_view:{shop_id}")
                )
                await safe_answer(callback)
                return
            
            result = await session.execute(
                select(ShopProduct)
                .where(ShopProduct.shop_id == shop_id)
                .order_by(ShopProduct.created_at.desc())
                .limit(20)
            )
            products = result.scalars().all()
            
            shop = await session.scalar(select(Shop).where(Shop.id == shop_id))
            shop_name = shop.name if shop else "Unknown"
            
            if not products:
                text = f"📦 <b>Products: {shop_name}</b>\n\n<i>No products yet.</i>"
            else:
                text = f"📦 <b>Products: {shop_name} ({len(products)})</b>\n\n"
                
                for p in products[:15]:
                    is_active = getattr(p, 'is_active', True)
                    status = "✅" if is_active else "❌"
                    symbol = getattr(p, 'token_symbol', 'N/A')
                    available = getattr(p, 'available_amount', 0)
                    margin = getattr(p, 'margin_percentage', 0)
                    
                    text += f"{status} <b>{symbol}</b>\n"
                    text += f"   Available: {available:.4f}\n"
                    text += f"   Margin: +{margin}%\n\n"
                
                if len(products) > 15:
                    text += f"<i>+{len(products) - 15} more...</i>"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back", callback_data=f"admin_test:shop_view:{shop_id}")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error("Shop products failed", error=str(e))
        await callback.message.edit_text(
            f"❌ Error: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back(f"admin_test:shop_view:{shop_id}")
        )
    
    await safe_answer(callback)

# ==================== SHOP MANAGEMENT ====================

@router.callback_query(F.data == "admin_test:shop_menu")
async def shop_management_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Shop management menu"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    # Get shop stats
    stats = {"total": 0, "active": 0, "pending": 0, "suspended": 0}
    
    try:
        async with db_manager.session() as session:
            if Shop:
                stats["total"] = await session.scalar(select(func.count(Shop.id))) or 0
                stats["active"] = await session.scalar(
                    select(func.count(Shop.id)).where(Shop.status == ShopStatus.APPROVED)
                ) or 0
                stats["suspended"] = await session.scalar(
                    select(func.count(Shop.id)).where(Shop.status == ShopStatus.SUSPENDED)
                ) or 0
            
            if ShopApplication:
                stats["pending"] = await session.scalar(
                    select(func.count(ShopApplication.id)).where(
                        ShopApplication.status == ShopApplicationStatus.PENDING
                    )
                ) or 0
    except Exception as e:
        logger.warning("Failed to get shop stats", error=str(e))
    
    text = f"""
🏪 <b>Shop Management</b>

<b>Statistics:</b>
├ Total Shops: {stats['total']}
├ 🟢 Active: {stats['active']}
├ ⏳ Pending Apps: {stats['pending']}
└ 🚫 Suspended: {stats['suspended']}

Select an action:
"""
    
    await safe_edit(callback.message, text, AdminKeyboards.shop_menu())
    await safe_answer(callback)


@router.callback_query(F.data == "admin_test:shop_list")
async def shop_list(callback: CallbackQuery) -> None:
    """List all shops"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    try:
        async with db_manager.session() as session:
            if not Shop:
                await callback.message.edit_text(
                    "❌ Shop model not available.",
                    reply_markup=AdminKeyboards.back("admin_test:shop_menu")
                )
                await safe_answer(callback)
                return
            
            result = await session.execute(
                select(Shop)
                .options(selectinload(Shop.owner))
                .order_by(Shop.created_at.desc())
                .limit(20)
            )
            shops = result.scalars().all()
            
            if not shops:
                text = "📋 <b>All Shops</b>\n\n<i>No shops found.</i>"
            else:
                text = f"📋 <b>All Shops ({len(shops)})</b>\n\n"
                
                status_emoji = {
                    ShopStatus.APPROVED: "🟢",
                    ShopStatus.PENDING: "⏳",
                    ShopStatus.SUSPENDED: "🚫",
                }
                
                for i, shop in enumerate(shops, 1):
                    emoji = status_emoji.get(shop.status, "❓")
                    owner_name = f"@{shop.owner.username}" if shop.owner and shop.owner.username else "N/A"
                    text += f"{i}. {emoji} <b>{shop.name}</b>\n"
                    text += f"   Owner: {owner_name}\n\n"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_test:shop_list")],
                [InlineKeyboardButton(text="🔙 Back", callback_data="admin_test:shop_menu")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error("Shop list failed", error=str(e))
        await callback.message.edit_text(
            f"❌ Error: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back("admin_test:shop_menu")
        )
    
    await safe_answer(callback)


@router.callback_query(F.data == "admin_test:shop_pending")
async def shop_pending_list(callback: CallbackQuery) -> None:
    """Show pending shop applications"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    try:
        async with db_manager.session() as session:
            if not ShopApplication:
                await callback.message.edit_text(
                    "❌ ShopApplication model not available.",
                    reply_markup=AdminKeyboards.back("admin_test:shop_menu")
                )
                await safe_answer(callback)
                return
            
            result = await session.execute(
                select(ShopApplication)
                .options(selectinload(ShopApplication.user))
                .where(ShopApplication.status == ShopApplicationStatus.PENDING)
                .order_by(ShopApplication.created_at.asc())
            )
            apps = result.scalars().all()
            
            if not apps:
                text = "⏳ <b>Pending Applications</b>\n\n<i>No pending applications!</i> 🎉"
                keyboard = AdminKeyboards.back("admin_test:shop_menu")
            else:
                text = f"⏳ <b>Pending Applications ({len(apps)})</b>\n\n"
                buttons = []
                
                for app in apps[:10]:
                    username = f"@{app.user.username}" if app.user and app.user.username else f"ID:{app.user.telegram_id if app.user else 'N/A'}"
                    text += f"• <b>{app.shop_name}</b>\n  {username}\n\n"
                    buttons.append([InlineKeyboardButton(
                        text=f"📝 {app.shop_name[:20]}",
                        callback_data=f"admin_test:app_view:{app.id[:8]}"
                    )])
                
                buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin_test:shop_menu")])
                keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error("Pending apps error", error=str(e))
        await callback.message.edit_text(
            f"❌ Error: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back("admin_test:shop_menu")
        )
    
    await safe_answer(callback)


@router.callback_query(F.data == "admin_test:shop_stats")
async def shop_stats(callback: CallbackQuery) -> None:
    """Show shop statistics"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    try:
        async with db_manager.session() as session:
            total_shops = await session.scalar(select(func.count(Shop.id))) or 0
            active_shops = await session.scalar(
                select(func.count(Shop.id)).where(Shop.status == ShopStatus.APPROVED)
            ) or 0
            
            pending_apps = 0
            if ShopApplication:
                pending_apps = await session.scalar(
                    select(func.count(ShopApplication.id)).where(
                        ShopApplication.status == ShopApplicationStatus.PENDING
                    )
                ) or 0
            
            total_volume = await session.scalar(
                select(func.sum(Shop.total_volume_usd))
            ) or Decimal("0")
            
            total_commission = await session.scalar(
                select(func.sum(Shop.total_commission_paid))
            ) or Decimal("0")
            
            # Today's orders
            today = datetime.utcnow().date()
            today_orders = 0
            if ShopOrder:
                today_orders = await session.scalar(
                    select(func.count(ShopOrder.id)).where(
                        func.date(ShopOrder.created_at) == today
                    )
                ) or 0
            
            text = f"""
📊 <b>Shop System Statistics</b>

<b>Shops:</b>
├ Total: {total_shops}
├ Active: {active_shops}
└ Pending Applications: {pending_apps}

<b>Orders Today:</b> {today_orders}

<b>Revenue:</b>
├ Total Volume: ${float(total_volume):,.2f}
└ Platform Commission: ${float(total_commission):,.2f}
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_test:shop_stats")],
                [InlineKeyboardButton(text="🔙 Back", callback_data="admin_test:shop_menu")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error("Shop stats failed", error=str(e), exc_info=True)
        await callback.message.edit_text(
            f"❌ Failed: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back("admin_test:shop_menu")
        )
    
    await safe_answer(callback)


@router.callback_query(F.data == "admin_test:shop_suspended")
async def shop_suspended_list(callback: CallbackQuery) -> None:
    """List suspended shops"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    try:
        async with db_manager.session() as session:
            if not Shop:
                await callback.message.edit_text(
                    "❌ Shop model not available.",
                    reply_markup=AdminKeyboards.back("admin_test:shop_menu")
                )
                await safe_answer(callback)
                return
            
            result = await session.execute(
                select(Shop)
                .options(selectinload(Shop.owner))
                .where(Shop.status == ShopStatus.SUSPENDED)
                .order_by(Shop.created_at.desc())
            )
            shops = result.scalars().all()
            
            if not shops:
                text = "🚫 <b>Suspended Shops</b>\n\n<i>No suspended shops!</i> 🎉"
            else:
                text = f"🚫 <b>Suspended Shops ({len(shops)})</b>\n\n"
                
                for shop in shops[:10]:
                    owner_name = f"@{shop.owner.username}" if shop.owner and shop.owner.username else "N/A"
                    text += f"• <b>{shop.name}</b> ({owner_name})\n"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_test:shop_suspended")],
                [InlineKeyboardButton(text="🔙 Back", callback_data="admin_test:shop_menu")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error("Suspended shops list failed", error=str(e))
        await callback.message.edit_text(
            f"❌ Error: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back("admin_test:shop_menu")
        )
    
    await safe_answer(callback)


@router.callback_query(F.data == "admin_test:shop_search")
async def shop_search_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start shop search"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    text = """
🔍 <b>Search Shop</b>

Enter shop name or owner @username:
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=AdminKeyboards.cancel("admin_test:shop_menu"),
        parse_mode="HTML"
    )
    await state.set_state(AdminTestStates.shop_search)
    await safe_answer(callback)


@router.message(AdminTestStates.shop_search)
async def shop_search_execute(message: Message, state: FSMContext) -> None:
    """Execute shop search"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    query = message.text.strip()
    
    try:
        async with db_manager.session() as session:
            if not Shop:
                await message.answer(
                    "❌ Shop model not available.",
                    reply_markup=AdminKeyboards.back("admin_test:shop_menu")
                )
                await state.clear()
                return
            
            # Search by shop name
            results = await session.execute(
                select(Shop)
                .options(selectinload(Shop.owner))
                .where(
                    or_(
                        Shop.name.ilike(f"%{query}%"),
                        Shop.id.ilike(f"%{query}%")
                    )
                )
                .limit(10)
            )
            shops = list(results.scalars().all())
            
            # Also search by owner username
            search_username = query[1:] if query.startswith("@") else query
            
            owner_results = await session.execute(
                select(Shop)
                .options(selectinload(Shop.owner))
                .join(User, Shop.owner_id == User.id)
                .where(User.username.ilike(f"%{search_username}%"))
                .limit(10)
            )
            
            for shop in owner_results.scalars().all():
                if shop not in shops:
                    shops.append(shop)
            
            if not shops:
                await message.answer(
                    f"❌ No shops found for: <code>{query}</code>",
                    reply_markup=AdminKeyboards.back("admin_test:shop_menu"),
                    parse_mode="HTML"
                )
                await state.clear()
                return
            
            text = f"🔍 <b>Search Results ({len(shops)})</b>\n\n"
            
            status_emoji = {
                ShopStatus.APPROVED: "🟢",
                ShopStatus.PENDING: "⏳",
                ShopStatus.SUSPENDED: "🚫",
            }
            
            for shop in shops[:10]:
                emoji = status_emoji.get(shop.status, "❓")
                owner_name = f"@{shop.owner.username}" if shop.owner and shop.owner.username else "N/A"
                text += f"{emoji} <b>{shop.name}</b> ({owner_name})\n"
            
            await message.answer(
                text,
                reply_markup=AdminKeyboards.back("admin_test:shop_menu"),
                parse_mode="HTML"
            )
            
    except Exception as e:
        logger.error("Shop search failed", error=str(e))
        await message.answer(
            f"❌ Error: {str(e)[:100]}",
            reply_markup=AdminKeyboards.back("admin_test:shop_menu")
        )
    
    await state.clear()


@router.callback_query(F.data == "admin_test:shop_fees")
async def shop_fees_menu(callback: CallbackQuery) -> None:
    """Shop fee settings"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    # Default fee values
    shop_fee = Decimal("5.0")
    withdrawal_fee = Decimal("1.0")
    min_withdrawal = Decimal("10.0")
    
    text = f"""
💰 <b>Shop Fee Settings</b>

<b>Current Settings:</b>
├ Shop Commission: <b>{shop_fee}%</b>
├ Withdrawal Fee: <b>{withdrawal_fee}%</b>
└ Min Withdrawal: <b>${min_withdrawal}</b>

<i>Fee configuration is managed in settings.</i>
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin_test:shop_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await safe_answer(callback)


# ==================== FALLBACK HANDLER ====================

@router.callback_query(F.data.startswith("admin_test:"))
async def admin_test_fallback(callback: CallbackQuery) -> None:
    """Fallback for unhandled admin_test callbacks"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    logger.warning("Unhandled admin_test callback", data=callback.data)
    await safe_answer(callback, "🚧 This feature is coming soon!", show_alert=True)


# ==================== REGISTER HANDLERS ====================

def register_admin_test_handlers(dp) -> None:
    """Register all admin test handlers"""
    dp.include_router(router)

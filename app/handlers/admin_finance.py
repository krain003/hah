"""
NEXUS WALLET - Admin Finance Panel (FIXED)
Complete financial management functionality
"""

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import structlog

from sqlalchemy import select, func, and_, update
from database.connection import db_manager
from database.models import (
    Transaction, User, Wallet, WalletBalance,
    TransactionStatus, TransactionType, P2PTrade
)
from config.settings import settings
from blockchain.wallet_manager import wallet_manager, NETWORKS

logger = structlog.get_logger(__name__)
router = Router(name="admin_finance")


# ==================== ADMIN CHECK ====================

def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id in settings.ADMIN_IDS


# ==================== FSM STATES ====================

class AdminFinanceStates(StatesGroup):
    # Purchase settings
    set_buy_fee = State()
    set_sell_fee = State()
    set_min_buy = State()
    set_max_buy = State()
    set_min_sell = State()
    set_max_sell = State()
    
    # P2P settings
    set_p2p_fee = State()
    set_p2p_min = State()
    set_p2p_max = State()
    set_escrow_timeout = State()
    set_trade_timeout = State()
    
    # Manual operations
    manual_credit_user = State()
    manual_credit_network = State()
    manual_credit_amount = State()
    manual_debit_user = State()
    manual_debit_network = State()
    manual_debit_amount = State()


# ==================== FINANCE SETTINGS STORAGE ====================

class FinanceSettings:
    """In-memory finance settings (use config_manager for persistence)"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_defaults()
        return cls._instance
    
    def _init_defaults(self):
        self.platform_fee_buy_percent = Decimal("1.5")
        self.platform_fee_sell_percent = Decimal("1.5")
        self.min_buy_usd = Decimal("10")
        self.max_buy_usd = Decimal("10000")
        self.min_sell_usd = Decimal("10")
        self.max_sell_usd = Decimal("10000")
        self.p2p_fee_percent = Decimal("0.5")
        self.p2p_min_usd = 10
        self.p2p_max_usd = 50000
        self.escrow_timeout_minutes = 30
        self.trade_timeout_minutes = 60
    
    def get_limits(self) -> Dict[str, Any]:
        return {
            'platform_fee_buy_percent': float(self.platform_fee_buy_percent),
            'platform_fee_sell_percent': float(self.platform_fee_sell_percent),
            'buy': {'min_usd': float(self.min_buy_usd), 'max_usd': float(self.max_buy_usd)},
            'sell': {'min_usd': float(self.min_sell_usd), 'max_usd': float(self.max_sell_usd)}
        }
    
    def update_limits(self, **kwargs):
        if 'fee_buy' in kwargs:
            self.platform_fee_buy_percent = Decimal(str(kwargs['fee_buy']))
        if 'fee_sell' in kwargs:
            self.platform_fee_sell_percent = Decimal(str(kwargs['fee_sell']))
        if 'min_buy' in kwargs:
            self.min_buy_usd = Decimal(str(kwargs['min_buy']))
        if 'max_buy' in kwargs:
            self.max_buy_usd = Decimal(str(kwargs['max_buy']))
        if 'min_sell' in kwargs:
            self.min_sell_usd = Decimal(str(kwargs['min_sell']))
        if 'max_sell' in kwargs:
            self.max_sell_usd = Decimal(str(kwargs['max_sell']))


# Global instance
finance_settings = FinanceSettings()


# ==================== UTILITY FUNCTIONS ====================

async def safe_edit(message: Message, text: str, keyboard: InlineKeyboardMarkup = None) -> bool:
    """Safely edit message"""
    try:
        if message.photo or message.document or message.video or message.audio:
            chat_id = message.chat.id
            try:
                await message.delete()
            except:
                pass
            await message.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return True
        
        await message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return True
        
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return True
        if "message to edit not found" in str(e).lower():
            try:
                await message.bot.send_message(
                    chat_id=message.chat.id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return True
            except:
                pass
        return False
    except Exception as e:
        logger.error("Edit error", error=str(e))
        return False


async def safe_answer(callback: CallbackQuery, text: str = None, show_alert: bool = False):
    """Safe callback answer"""
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except:
        pass


def format_currency(amount, symbol: str = "$") -> str:
    """Format currency"""
    if amount is None:
        return f"{symbol}0.00"
    return f"{symbol}{float(amount):,.2f}"


def get_back_keyboard(callback_data: str = "adm_fin:menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data=callback_data)]
    ])


def get_cancel_keyboard(callback_data: str = "adm_fin:menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data=callback_data)]
    ])


# ==================== KEYBOARDS ====================

def get_admin_finance_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Revenue", callback_data="adm_fin:revenue"),
            InlineKeyboardButton(text="📊 TX Stats", callback_data="adm_fin:tx_stats")
        ],
        [
            InlineKeyboardButton(text="💳 Purchase Settings", callback_data="adm_fin:purchase_settings"),
            InlineKeyboardButton(text="🤝 P2P Settings", callback_data="adm_fin:p2p_settings")
        ],
        [
            InlineKeyboardButton(text="🏦 Hot Wallets", callback_data="adm_fin:hot_wallets"),
            InlineKeyboardButton(text="📤 Pending WD", callback_data="adm_fin:pending_wd")
        ],
        [
            InlineKeyboardButton(text="➕ Manual Credit", callback_data="adm_fin:manual_credit"),
            InlineKeyboardButton(text="➖ Manual Debit", callback_data="adm_fin:manual_debit")
        ],
        [
            InlineKeyboardButton(text="📈 Daily Report", callback_data="adm_fin:daily")
        ],
        [InlineKeyboardButton(text="🔙 Admin Menu", callback_data="admin:main")]
    ])


# ==================== MAIN MENU ====================

@router.callback_query(F.data == "adm_fin:menu")
async def admin_finance_menu(callback: CallbackQuery, state: FSMContext):
    """Admin finance main menu"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Today's fees
            today_fees = await session.scalar(
                select(func.sum(Transaction.fee_usd)).where(
                    and_(
                        Transaction.created_at >= today,
                        Transaction.status == TransactionStatus.COMPLETED
                    )
                )
            ) or Decimal("0")
            
            # Pending withdrawals
            pending_wd = await session.scalar(
                select(func.count(Transaction.id)).where(
                    and_(
                        Transaction.status == TransactionStatus.PENDING,
                        Transaction.tx_type == TransactionType.WITHDRAWAL
                    )
                )
            ) or 0
            
            # Today's transactions count
            today_tx_count = await session.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.created_at >= today
                )
            ) or 0
        
        limits = finance_settings.get_limits()
        
        text = f"""
💰 <b>Financial Management</b>

<b>Today's Overview:</b>
├ Fee Revenue: <b>{format_currency(today_fees)}</b>
├ Transactions: <b>{today_tx_count}</b>
└ Pending Withdrawals: <b>{pending_wd}</b>

<b>Current Settings:</b>
├ Buy Fee: <b>{limits['platform_fee_buy_percent']}%</b>
├ Sell Fee: <b>{limits['platform_fee_sell_percent']}%</b>
├ P2P Fee: <b>{float(finance_settings.p2p_fee_percent)}%</b>
└ Buy Limits: <b>${limits['buy']['min_usd']:.0f} - ${limits['buy']['max_usd']:,.0f}</b>

Select an option:
"""
        
        await safe_edit(callback.message, text, get_admin_finance_keyboard())
        
    except Exception as e:
        logger.error("Finance menu error", error=str(e))
        await safe_edit(
            callback.message,
            "❌ Failed to load finance data.",
            get_back_keyboard("admin:main")
        )
    
    await safe_answer(callback)


# ==================== REVENUE ====================

@router.callback_query(F.data == "adm_fin:revenue")
async def admin_revenue(callback: CallbackQuery, state: FSMContext):
    """Revenue overview"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    await safe_answer(callback, "📊 Loading...")
    
    try:
        async with db_manager.session() as session:
            # All time fees
            total_fees = await session.scalar(
                select(func.sum(Transaction.fee_usd)).where(
                    Transaction.status == TransactionStatus.COMPLETED
                )
            ) or Decimal("0")
            
            # Last 24h
            yesterday = datetime.utcnow() - timedelta(days=1)
            fees_24h = await session.scalar(
                select(func.sum(Transaction.fee_usd)).where(
                    and_(
                        Transaction.created_at >= yesterday,
                        Transaction.status == TransactionStatus.COMPLETED
                    )
                )
            ) or Decimal("0")
            
            # Last 7 days
            week_ago = datetime.utcnow() - timedelta(days=7)
            fees_7d = await session.scalar(
                select(func.sum(Transaction.fee_usd)).where(
                    and_(
                        Transaction.created_at >= week_ago,
                        Transaction.status == TransactionStatus.COMPLETED
                    )
                )
            ) or Decimal("0")
            
            # Last 30 days
            month_ago = datetime.utcnow() - timedelta(days=30)
            fees_30d = await session.scalar(
                select(func.sum(Transaction.fee_usd)).where(
                    and_(
                        Transaction.created_at >= month_ago,
                        Transaction.status == TransactionStatus.COMPLETED
                    )
                )
            ) or Decimal("0")
            
            # Volume stats
            total_volume = await session.scalar(
                select(func.sum(Transaction.amount_usd)).where(
                    Transaction.status == TransactionStatus.COMPLETED
                )
            ) or Decimal("0")
            
            volume_7d = await session.scalar(
                select(func.sum(Transaction.amount_usd)).where(
                    and_(
                        Transaction.created_at >= week_ago,
                        Transaction.status == TransactionStatus.COMPLETED
                    )
                )
            ) or Decimal("0")
        
        text = f"""
💰 <b>Revenue Overview</b>

<b>Fee Revenue:</b>
├ All Time: <b>{format_currency(total_fees)}</b>
├ Last 30 Days: <b>{format_currency(fees_30d)}</b>
├ Last 7 Days: <b>{format_currency(fees_7d)}</b>
└ Last 24 Hours: <b>{format_currency(fees_24h)}</b>

<b>Transaction Volume:</b>
├ All Time: <b>{format_currency(total_volume)}</b>
└ Last 7 Days: <b>{format_currency(volume_7d)}</b>

<b>Average Fee Rate:</b>
└ {(float(total_fees) / float(total_volume) * 100) if total_volume > 0 else 0:.2f}%
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh", callback_data="adm_fin:revenue")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="adm_fin:menu")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("Revenue error", error=str(e))
        await safe_edit(callback.message, "❌ Failed to load revenue.", get_back_keyboard())


# ==================== TRANSACTION STATS ====================

@router.callback_query(F.data == "adm_fin:tx_stats")
async def admin_tx_stats(callback: CallbackQuery, state: FSMContext):
    """Transaction statistics"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            # By status
            completed = await session.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.status == TransactionStatus.COMPLETED
                )
            ) or 0
            
            pending = await session.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.status == TransactionStatus.PENDING
                )
            ) or 0
            
            failed = await session.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.status == TransactionStatus.FAILED
                )
            ) or 0
            
            # By type
            result = await session.execute(
                select(
                    Transaction.tx_type,
                    func.count(Transaction.id).label('count'),
                    func.sum(Transaction.amount_usd).label('volume')
                )
                .where(Transaction.status == TransactionStatus.COMPLETED)
                .group_by(Transaction.tx_type)
            )
            type_stats = result.fetchall()
            
            # By network
            network_result = await session.execute(
                select(
                    Transaction.network,
                    func.count(Transaction.id).label('count'),
                    func.sum(Transaction.amount_usd).label('volume')
                )
                .where(Transaction.status == TransactionStatus.COMPLETED)
                .group_by(Transaction.network)
            )
            network_stats = network_result.fetchall()
        
        text = f"""
📊 <b>Transaction Statistics</b>

<b>By Status:</b>
├ ✅ Completed: {completed:,}
├ ⏳ Pending: {pending:,}
└ ❌ Failed: {failed:,}

<b>By Type:</b>
"""
        
        for row in type_stats:
            tx_type = row.tx_type.value if hasattr(row.tx_type, 'value') else str(row.tx_type)
            text += f"├ {tx_type}: {row.count:,} | {format_currency(row.volume)}\n"
        
        text += "\n<b>By Network:</b>\n"
        
        for row in network_stats:
            network = row.network or "Unknown"
            config = NETWORKS.get(network)
            icon = config.icon if config else "🔗"
            text += f"{icon} {network}: {row.count:,} | {format_currency(row.volume)}\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh", callback_data="adm_fin:tx_stats")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="adm_fin:menu")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("TX stats error", error=str(e))
        await safe_edit(callback.message, "❌ Failed to load stats.", get_back_keyboard())
    
    await safe_answer(callback)


# ==================== HOT WALLETS ====================

@router.callback_query(F.data == "adm_fin:hot_wallets")
async def admin_hot_wallets(callback: CallbackQuery, state: FSMContext):
    """Hot wallet status"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    await safe_answer(callback, "🏦 Checking wallets...")
    
    try:
        # Get network status
        status = await wallet_manager.get_system_status()
        
        text = "🏦 <b>Network & Hot Wallet Status</b>\n\n"
        
        online_count = 0
        offline_count = 0
        
        for network, info in status.items():
            config = NETWORKS.get(network)
            if not config:
                continue
            
            testnet = "🧪" if getattr(config, 'is_testnet', False) else ""
            
            if info.get("online"):
                online_count += 1
                emoji = "🟢"
                height = info.get("height", "N/A")
                latency = info.get("latency_ms")
                latency_str = f" ({latency:.0f}ms)" if latency else ""
                text += f"{emoji} {config.icon} <b>{network.upper()}</b> {testnet}\n"
                text += f"   Block: #{height}{latency_str}\n"
            else:
                offline_count += 1
                error = info.get("error", "Unknown")[:40]
                text += f"🔴 {config.icon} <b>{network.upper()}</b> {testnet}\n"
                text += f"   Error: {error}\n"
        
        text += f"\n<b>Summary:</b> {online_count} online, {offline_count} offline"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh", callback_data="adm_fin:hot_wallets")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="adm_fin:menu")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("Hot wallets error", error=str(e))
        await safe_edit(callback.message, "❌ Failed to check wallets.", get_back_keyboard())


# ==================== PENDING WITHDRAWALS ====================

@router.callback_query(F.data == "adm_fin:pending_wd")
async def admin_pending_withdrawals(callback: CallbackQuery, state: FSMContext):
    """Pending withdrawals"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(Transaction)
                .where(
                    and_(
                        Transaction.status == TransactionStatus.PENDING,
                        Transaction.tx_type == TransactionType.WITHDRAWAL
                    )
                )
                .order_by(Transaction.created_at.asc())
                .limit(20)
            )
            withdrawals = result.scalars().all()
        
        if not withdrawals:
            text = "📤 <b>Pending Withdrawals</b>\n\n✅ No pending withdrawals!"
        else:
            text = f"📤 <b>Pending Withdrawals ({len(withdrawals)})</b>\n\n"
            
            for wd in withdrawals:
                age = (datetime.utcnow() - wd.created_at).total_seconds() / 60 if wd.created_at else 0
                
                to_addr = wd.to_address or "Unknown"
                if len(to_addr) > 16:
                    to_addr = f"{to_addr[:8]}...{to_addr[-6:]}"
                
                config = NETWORKS.get(wd.network)
                icon = config.icon if config else "🔗"
                
                text += f"⏳ {icon} <code>{wd.id[:8]}</code>\n"
                text += f"   {float(wd.amount):.6f} {wd.token_symbol}\n"
                text += f"   To: <code>{to_addr}</code>\n"
                text += f"   Age: {age:.0f} min\n\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh", callback_data="adm_fin:pending_wd")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="adm_fin:menu")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("Pending WD error", error=str(e))
        await safe_edit(callback.message, "❌ Failed to load.", get_back_keyboard())
    
    await safe_answer(callback)


# ==================== PURCHASE SETTINGS ====================

@router.callback_query(F.data == "adm_fin:purchase_settings")
async def admin_purchase_settings(callback: CallbackQuery, state: FSMContext):
    """Purchase settings"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    limits = finance_settings.get_limits()
    
    text = f"""
💳 <b>Purchase Settings</b>

<b>Fees:</b>
├ Buy Fee: <b>{limits['platform_fee_buy_percent']}%</b>
└ Sell Fee: <b>{limits['platform_fee_sell_percent']}%</b>

<b>Limits:</b>
├ Min Buy: <b>${limits['buy']['min_usd']:.0f}</b>
├ Max Buy: <b>${limits['buy']['max_usd']:,.0f}</b>
├ Min Sell: <b>${limits['sell']['min_usd']:.0f}</b>
└ Max Sell: <b>${limits['sell']['max_usd']:,.0f}</b>

Select setting to modify:
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Buy Fee", callback_data="adm_fin:set:buy_fee"),
            InlineKeyboardButton(text="💸 Sell Fee", callback_data="adm_fin:set:sell_fee")
        ],
        [
            InlineKeyboardButton(text="📉 Min Buy", callback_data="adm_fin:set:min_buy"),
            InlineKeyboardButton(text="📈 Max Buy", callback_data="adm_fin:set:max_buy")
        ],
        [
            InlineKeyboardButton(text="📉 Min Sell", callback_data="adm_fin:set:min_sell"),
            InlineKeyboardButton(text="📈 Max Sell", callback_data="adm_fin:set:max_sell")
        ],
        [InlineKeyboardButton(text="🔙 Back", callback_data="adm_fin:menu")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer(callback)


@router.callback_query(F.data == "adm_fin:set:buy_fee")
async def set_buy_fee_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    text = f"""
💰 <b>Set Buy Fee</b>

Current: <b>{finance_settings.platform_fee_buy_percent}%</b>

Enter new fee (0-10):
"""
    await safe_edit(callback.message, text, get_cancel_keyboard("adm_fin:purchase_settings"))
    await state.set_state(AdminFinanceStates.set_buy_fee)
    await safe_answer(callback)


@router.message(AdminFinanceStates.set_buy_fee)
async def set_buy_fee_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        fee = Decimal(message.text.strip())
        if fee < 0 or fee > 10:
            raise ValueError()
        
        finance_settings.platform_fee_buy_percent = fee
        logger.info("Buy fee updated", fee=str(fee), admin=message.from_user.id)
        
        await message.answer(
            f"✅ Buy fee set to <b>{fee}%</b>",
            reply_markup=get_back_keyboard("adm_fin:purchase_settings"),
            parse_mode="HTML"
        )
    except:
        await message.answer("❌ Invalid. Enter 0-10.", reply_markup=get_cancel_keyboard("adm_fin:purchase_settings"))
        return
    
    await state.clear()


@router.callback_query(F.data == "adm_fin:set:sell_fee")
async def set_sell_fee_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    text = f"💸 <b>Set Sell Fee</b>\n\nCurrent: <b>{finance_settings.platform_fee_sell_percent}%</b>\n\nEnter new fee (0-10):"
    await safe_edit(callback.message, text, get_cancel_keyboard("adm_fin:purchase_settings"))
    await state.set_state(AdminFinanceStates.set_sell_fee)
    await safe_answer(callback)


@router.message(AdminFinanceStates.set_sell_fee)
async def set_sell_fee_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        fee = Decimal(message.text.strip())
        if fee < 0 or fee > 10:
            raise ValueError()
        
        finance_settings.platform_fee_sell_percent = fee
        await message.answer(f"✅ Sell fee set to <b>{fee}%</b>", reply_markup=get_back_keyboard("adm_fin:purchase_settings"), parse_mode="HTML")
    except:
        await message.answer("❌ Invalid.", reply_markup=get_cancel_keyboard("adm_fin:purchase_settings"))
        return
    
    await state.clear()


@router.callback_query(F.data == "adm_fin:set:min_buy")
async def set_min_buy_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    text = f"📉 <b>Set Min Buy</b>\n\nCurrent: <b>${finance_settings.min_buy_usd}</b>\n\nEnter amount (1-1000):"
    await safe_edit(callback.message, text, get_cancel_keyboard("adm_fin:purchase_settings"))
    await state.set_state(AdminFinanceStates.set_min_buy)
    await safe_answer(callback)


@router.message(AdminFinanceStates.set_min_buy)
async def set_min_buy_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        amount = Decimal(message.text.strip().replace("$", "").replace(",", ""))
        if amount < 1 or amount > 1000:
            raise ValueError()
        
        finance_settings.min_buy_usd = amount
        await message.answer(f"✅ Min buy set to <b>${amount}</b>", reply_markup=get_back_keyboard("adm_fin:purchase_settings"), parse_mode="HTML")
    except:
        await message.answer("❌ Invalid.", reply_markup=get_cancel_keyboard("adm_fin:purchase_settings"))
        return
    
    await state.clear()


@router.callback_query(F.data == "adm_fin:set:max_buy")
async def set_max_buy_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    text = f"📈 <b>Set Max Buy</b>\n\nCurrent: <b>${finance_settings.max_buy_usd:,}</b>\n\nEnter amount (100-1000000):"
    await safe_edit(callback.message, text, get_cancel_keyboard("adm_fin:purchase_settings"))
    await state.set_state(AdminFinanceStates.set_max_buy)
    await safe_answer(callback)


@router.message(AdminFinanceStates.set_max_buy)
async def set_max_buy_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        amount = Decimal(message.text.strip().replace("$", "").replace(",", ""))
        if amount < 100 or amount > 1000000:
            raise ValueError()
        
        finance_settings.max_buy_usd = amount
        await message.answer(f"✅ Max buy set to <b>${amount:,}</b>", reply_markup=get_back_keyboard("adm_fin:purchase_settings"), parse_mode="HTML")
    except:
        await message.answer("❌ Invalid.", reply_markup=get_cancel_keyboard("adm_fin:purchase_settings"))
        return
    
    await state.clear()


@router.callback_query(F.data == "adm_fin:set:min_sell")
async def set_min_sell_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    text = f"📉 <b>Set Min Sell</b>\n\nCurrent: <b>${finance_settings.min_sell_usd}</b>\n\nEnter amount (1-1000):"
    await safe_edit(callback.message, text, get_cancel_keyboard("adm_fin:purchase_settings"))
    await state.set_state(AdminFinanceStates.set_min_sell)
    await safe_answer(callback)


@router.message(AdminFinanceStates.set_min_sell)
async def set_min_sell_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        amount = Decimal(message.text.strip().replace("$", "").replace(",", ""))
        if amount < 1 or amount > 1000:
            raise ValueError()
        
        finance_settings.min_sell_usd = amount
        await message.answer(f"✅ Min sell set to <b>${amount}</b>", reply_markup=get_back_keyboard("adm_fin:purchase_settings"), parse_mode="HTML")
    except:
        await message.answer("❌ Invalid.", reply_markup=get_cancel_keyboard("adm_fin:purchase_settings"))
        return
    
    await state.clear()


@router.callback_query(F.data == "adm_fin:set:max_sell")
async def set_max_sell_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    text = f"📈 <b>Set Max Sell</b>\n\nCurrent: <b>${finance_settings.max_sell_usd:,}</b>\n\nEnter amount (100-1000000):"
    await safe_edit(callback.message, text, get_cancel_keyboard("adm_fin:purchase_settings"))
    await state.set_state(AdminFinanceStates.set_max_sell)
    await safe_answer(callback)


@router.message(AdminFinanceStates.set_max_sell)
async def set_max_sell_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        amount = Decimal(message.text.strip().replace("$", "").replace(",", ""))
        if amount < 100 or amount > 1000000:
            raise ValueError()
        
        finance_settings.max_sell_usd = amount
        await message.answer(f"✅ Max sell set to <b>${amount:,}</b>", reply_markup=get_back_keyboard("adm_fin:purchase_settings"), parse_mode="HTML")
    except:
        await message.answer("❌ Invalid.", reply_markup=get_cancel_keyboard("adm_fin:purchase_settings"))
        return
    
    await state.clear()


# ==================== P2P SETTINGS ====================

@router.callback_query(F.data == "adm_fin:p2p_settings")
async def admin_p2p_settings(callback: CallbackQuery, state: FSMContext):
    """P2P settings"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    text = f"""
🤝 <b>P2P Settings</b>

<b>Current:</b>
├ Platform Fee: <b>{finance_settings.p2p_fee_percent}%</b>
├ Min Order: <b>${finance_settings.p2p_min_usd}</b>
├ Max Order: <b>${finance_settings.p2p_max_usd:,}</b>
├ Escrow Timeout: <b>{finance_settings.escrow_timeout_minutes} min</b>
└ Trade Timeout: <b>{finance_settings.trade_timeout_minutes} min</b>

Select to modify:
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 P2P Fee", callback_data="adm_fin:set:p2p_fee")],
        [
            InlineKeyboardButton(text="📉 Min Order", callback_data="adm_fin:set:p2p_min"),
            InlineKeyboardButton(text="📈 Max Order", callback_data="adm_fin:set:p2p_max")
        ],
        [
            InlineKeyboardButton(text="🔒 Escrow Time", callback_data="adm_fin:set:escrow"),
            InlineKeyboardButton(text="⏱ Trade Time", callback_data="adm_fin:set:trade_time")
        ],
        [InlineKeyboardButton(text="🔙 Back", callback_data="adm_fin:menu")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer(callback)


@router.callback_query(F.data == "adm_fin:set:p2p_fee")
async def set_p2p_fee_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    text = f"💰 <b>Set P2P Fee</b>\n\nCurrent: <b>{finance_settings.p2p_fee_percent}%</b>\n\nEnter new fee (0-5):"
    await safe_edit(callback.message, text, get_cancel_keyboard("adm_fin:p2p_settings"))
    await state.set_state(AdminFinanceStates.set_p2p_fee)
    await safe_answer(callback)


@router.message(AdminFinanceStates.set_p2p_fee)
async def set_p2p_fee_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        fee = Decimal(message.text.strip())
        if fee < 0 or fee > 5:
            raise ValueError()
        
        finance_settings.p2p_fee_percent = fee
        await message.answer(f"✅ P2P fee set to <b>{fee}%</b>", reply_markup=get_back_keyboard("adm_fin:p2p_settings"), parse_mode="HTML")
    except:
        await message.answer("❌ Invalid.", reply_markup=get_cancel_keyboard("adm_fin:p2p_settings"))
        return
    
    await state.clear()


@router.callback_query(F.data == "adm_fin:set:p2p_min")
async def set_p2p_min_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    text = f"📉 <b>Set P2P Min</b>\n\nCurrent: <b>${finance_settings.p2p_min_usd}</b>\n\nEnter amount (1-1000):"
    await safe_edit(callback.message, text, get_cancel_keyboard("adm_fin:p2p_settings"))
    await state.set_state(AdminFinanceStates.set_p2p_min)
    await safe_answer(callback)


@router.message(AdminFinanceStates.set_p2p_min)
async def set_p2p_min_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        amount = int(message.text.strip().replace("$", "").replace(",", ""))
        if amount < 1 or amount > 1000:
            raise ValueError()
        
        finance_settings.p2p_min_usd = amount
        await message.answer(f"✅ P2P min set to <b>${amount}</b>", reply_markup=get_back_keyboard("adm_fin:p2p_settings"), parse_mode="HTML")
    except:
        await message.answer("❌ Invalid.", reply_markup=get_cancel_keyboard("adm_fin:p2p_settings"))
        return
    
    await state.clear()


@router.callback_query(F.data == "adm_fin:set:p2p_max")
async def set_p2p_max_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    text = f"📈 <b>Set P2P Max</b>\n\nCurrent: <b>${finance_settings.p2p_max_usd:,}</b>\n\nEnter amount (100-1000000):"
    await safe_edit(callback.message, text, get_cancel_keyboard("adm_fin:p2p_settings"))
    await state.set_state(AdminFinanceStates.set_p2p_max)
    await safe_answer(callback)


@router.message(AdminFinanceStates.set_p2p_max)
async def set_p2p_max_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        amount = int(message.text.strip().replace("$", "").replace(",", ""))
        if amount < 100 or amount > 1000000:
            raise ValueError()
        
        finance_settings.p2p_max_usd = amount
        await message.answer(f"✅ P2P max set to <b>${amount:,}</b>", reply_markup=get_back_keyboard("adm_fin:p2p_settings"), parse_mode="HTML")
    except:
        await message.answer("❌ Invalid.", reply_markup=get_cancel_keyboard("adm_fin:p2p_settings"))
        return
    
    await state.clear()


@router.callback_query(F.data == "adm_fin:set:escrow")
async def set_escrow_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    text = f"🔒 <b>Set Escrow Timeout</b>\n\nCurrent: <b>{finance_settings.escrow_timeout_minutes} min</b>\n\nEnter minutes (5-120):"
    await safe_edit(callback.message, text, get_cancel_keyboard("adm_fin:p2p_settings"))
    await state.set_state(AdminFinanceStates.set_escrow_timeout)
    await safe_answer(callback)


@router.message(AdminFinanceStates.set_escrow_timeout)
async def set_escrow_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        minutes = int(message.text.strip())
        if minutes < 5 or minutes > 120:
            raise ValueError()
        
        finance_settings.escrow_timeout_minutes = minutes
        await message.answer(f"✅ Escrow timeout set to <b>{minutes} min</b>", reply_markup=get_back_keyboard("adm_fin:p2p_settings"), parse_mode="HTML")
    except:
        await message.answer("❌ Invalid.", reply_markup=get_cancel_keyboard("adm_fin:p2p_settings"))
        return
    
    await state.clear()


@router.callback_query(F.data == "adm_fin:set:trade_time")
async def set_trade_time_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    text = f"⏱ <b>Set Trade Timeout</b>\n\nCurrent: <b>{finance_settings.trade_timeout_minutes} min</b>\n\nEnter minutes (15-480):"
    await safe_edit(callback.message, text, get_cancel_keyboard("adm_fin:p2p_settings"))
    await state.set_state(AdminFinanceStates.set_trade_timeout)
    await safe_answer(callback)


@router.message(AdminFinanceStates.set_trade_timeout)
async def set_trade_time_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        minutes = int(message.text.strip())
        if minutes < 15 or minutes > 480:
            raise ValueError()
        
        finance_settings.trade_timeout_minutes = minutes
        await message.answer(f"✅ Trade timeout set to <b>{minutes} min</b>", reply_markup=get_back_keyboard("adm_fin:p2p_settings"), parse_mode="HTML")
    except:
        await message.answer("❌ Invalid.", reply_markup=get_cancel_keyboard("adm_fin:p2p_settings"))
        return
    
    await state.clear()


# ==================== MANUAL CREDIT ====================

@router.callback_query(F.data == "adm_fin:manual_credit")
async def manual_credit_start(callback: CallbackQuery, state: FSMContext):
    """Start manual credit"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    text = """
➕ <b>Manual Credit</b>

⚠️ This will add balance to a user's wallet.
All actions are logged.

Enter Telegram ID or @username:
"""
    await safe_edit(callback.message, text, get_cancel_keyboard())
    await state.set_state(AdminFinanceStates.manual_credit_user)
    await safe_answer(callback)


@router.message(AdminFinanceStates.manual_credit_user)
async def manual_credit_user(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    query = message.text.strip()
    
    async with db_manager.session() as session:
        user = None
        if query.isdigit():
            user = await session.scalar(select(User).where(User.telegram_id == int(query)))
        else:
            username = query[1:] if query.startswith("@") else query
            user = await session.scalar(select(User).where(User.username == username))
        
        if not user:
            await message.answer("❌ User not found.", reply_markup=get_cancel_keyboard())
            return
        
        await state.update_data(credit_user_id=str(user.id), credit_tg_id=user.telegram_id)
    
    # Show network selection
    buttons = []
    row = []
    for network, config in NETWORKS.items():
        row.append(InlineKeyboardButton(
            text=f"{config.icon} {config.symbol}",
            callback_data=f"adm_fin:credit_net:{network}"
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="adm_fin:menu")])
    
    await message.answer(
        f"User: <code>{user.telegram_id}</code>\n\nSelect network:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await state.set_state(AdminFinanceStates.manual_credit_network)


@router.callback_query(AdminFinanceStates.manual_credit_network, F.data.startswith("adm_fin:credit_net:"))
async def manual_credit_network(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    network = callback.data.split(":")[-1]
    await state.update_data(credit_network=network)
    
    config = NETWORKS[network]
    text = f"➕ <b>Credit {config.icon} {config.symbol}</b>\n\nEnter amount:"
    
    await safe_edit(callback.message, text, get_cancel_keyboard())
    await state.set_state(AdminFinanceStates.manual_credit_amount)
    await safe_answer(callback)


@router.message(AdminFinanceStates.manual_credit_amount)
async def manual_credit_execute(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        amount = Decimal(message.text.strip())
        if amount <= 0:
            raise ValueError()
    except:
        await message.answer("❌ Invalid amount.", reply_markup=get_cancel_keyboard())
        return
    
    data = await state.get_data()
    user_id = data['credit_user_id']
    network = data['credit_network']
    config = NETWORKS[network]
    
    try:
        async with db_manager.session() as session:
            # Find wallet
            wallet = await session.scalar(
                select(Wallet).where(
                    Wallet.user_id == user_id,
                    Wallet.network == network
                )
            )
            
            if not wallet:
                await message.answer(f"❌ User has no {network} wallet.", reply_markup=get_back_keyboard())
                await state.clear()
                return
            
            # Find or create balance
            balance = await session.scalar(
                select(WalletBalance).where(
                    WalletBalance.wallet_id == wallet.id,
                    WalletBalance.token_symbol == config.symbol
                )
            )
            
            if balance:
                old_balance = balance.balance
                balance.balance += amount
            else:
                old_balance = Decimal("0")
                balance = WalletBalance(
                    wallet_id=wallet.id,
                    token_symbol=config.symbol,
                    balance=amount,
                    decimals=config.decimals
                )
                session.add(balance)
            
            # Log transaction
            tx = Transaction(
                user_id=user_id,
                wallet_id=wallet.id,
                tx_type=TransactionType.DEPOSIT,
                network=network,
                token_symbol=config.symbol,
                amount=amount,
                status=TransactionStatus.COMPLETED,
                from_address="ADMIN_MANUAL_CREDIT",
                to_address=wallet.address,
                note=f"Manual credit by admin {message.from_user.id}"
            )
            session.add(tx)
            await session.commit()
        
        logger.info("Manual credit", admin=message.from_user.id, user=data['credit_tg_id'], network=network, amount=str(amount))
        
        await message.answer(
            f"✅ <b>Credit Applied!</b>\n\n"
            f"User: <code>{data['credit_tg_id']}</code>\n"
            f"Network: {config.icon} {network.upper()}\n"
            f"Added: <b>+{amount} {config.symbol}</b>\n"
            f"New balance: <b>{old_balance + amount} {config.symbol}</b>",
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error("Manual credit failed", error=str(e))
        await message.answer(f"❌ Failed: {str(e)[:50]}", reply_markup=get_back_keyboard())
    
    await state.clear()


# ==================== MANUAL DEBIT ====================

@router.callback_query(F.data == "adm_fin:manual_debit")
async def manual_debit_start(callback: CallbackQuery, state: FSMContext):
    """Start manual debit"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    text = """
➖ <b>Manual Debit</b>

⚠️ This will SUBTRACT balance from a user's wallet.
All actions are logged.

Enter Telegram ID or @username:
"""
    await safe_edit(callback.message, text, get_cancel_keyboard())
    await state.set_state(AdminFinanceStates.manual_debit_user)
    await safe_answer(callback)


@router.message(AdminFinanceStates.manual_debit_user)
async def manual_debit_user(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    query = message.text.strip()
    
    async with db_manager.session() as session:
        user = None
        if query.isdigit():
            user = await session.scalar(select(User).where(User.telegram_id == int(query)))
        else:
            username = query[1:] if query.startswith("@") else query
            user = await session.scalar(select(User).where(User.username == username))
        
        if not user:
            await message.answer("❌ User not found.", reply_markup=get_cancel_keyboard())
            return
        
        await state.update_data(debit_user_id=str(user.id), debit_tg_id=user.telegram_id)
    
    buttons = []
    row = []
    for network, config in NETWORKS.items():
        row.append(InlineKeyboardButton(
            text=f"{config.icon} {config.symbol}",
            callback_data=f"adm_fin:debit_net:{network}"
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="adm_fin:menu")])
    
    await message.answer(
        f"User: <code>{user.telegram_id}</code>\n\nSelect network:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await state.set_state(AdminFinanceStates.manual_debit_network)


@router.callback_query(AdminFinanceStates.manual_debit_network, F.data.startswith("adm_fin:debit_net:"))
async def manual_debit_network(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    network = callback.data.split(":")[-1]
    await state.update_data(debit_network=network)
    
    config = NETWORKS[network]
    
    # Show current balance
    data = await state.get_data()
    user_id = data['debit_user_id']
    
    current_balance = Decimal("0")
    async with db_manager.session() as session:
        wallet = await session.scalar(
            select(Wallet).where(Wallet.user_id == user_id, Wallet.network == network)
        )
        if wallet:
            balance = await session.scalar(
                select(WalletBalance).where(
                    WalletBalance.wallet_id == wallet.id,
                    WalletBalance.token_symbol == config.symbol
                )
            )
            if balance:
                current_balance = balance.balance
    
    text = f"➖ <b>Debit {config.icon} {config.symbol}</b>\n\nCurrent balance: <b>{current_balance} {config.symbol}</b>\n\nEnter amount to subtract:"
    
    await safe_edit(callback.message, text, get_cancel_keyboard())
    await state.set_state(AdminFinanceStates.manual_debit_amount)
    await safe_answer(callback)


@router.message(AdminFinanceStates.manual_debit_amount)
async def manual_debit_execute(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        amount = Decimal(message.text.strip())
        if amount <= 0:
            raise ValueError()
    except:
        await message.answer("❌ Invalid amount.", reply_markup=get_cancel_keyboard())
        return
    
    data = await state.get_data()
    user_id = data['debit_user_id']
    network = data['debit_network']
    config = NETWORKS[network]
    
    try:
        async with db_manager.session() as session:
            wallet = await session.scalar(
                select(Wallet).where(Wallet.user_id == user_id, Wallet.network == network)
            )
            
            if not wallet:
                await message.answer(f"❌ User has no {network} wallet.", reply_markup=get_back_keyboard())
                await state.clear()
                return
            
            balance = await session.scalar(
                select(WalletBalance).where(
                    WalletBalance.wallet_id == wallet.id,
                    WalletBalance.token_symbol == config.symbol
                )
            )
            
            if not balance or balance.balance < amount:
                await message.answer("❌ Insufficient balance.", reply_markup=get_back_keyboard())
                await state.clear()
                return
            
            old_balance = balance.balance
            balance.balance -= amount
            
            # Log
            tx = Transaction(
                user_id=user_id,
                wallet_id=wallet.id,
                tx_type=TransactionType.WITHDRAWAL,
                network=network,
                token_symbol=config.symbol,
                amount=amount,
                status=TransactionStatus.COMPLETED,
                from_address=wallet.address,
                to_address="ADMIN_MANUAL_DEBIT",
                note=f"Manual debit by admin {message.from_user.id}"
            )
            session.add(tx)
            await session.commit()
        
        logger.info("Manual debit", admin=message.from_user.id, user=data['debit_tg_id'], network=network, amount=str(amount))
        
        await message.answer(
            f"✅ <b>Debit Applied!</b>\n\n"
            f"User: <code>{data['debit_tg_id']}</code>\n"
            f"Network: {config.icon} {network.upper()}\n"
            f"Subtracted: <b>-{amount} {config.symbol}</b>\n"
            f"New balance: <b>{old_balance - amount} {config.symbol}</b>",
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error("Manual debit failed", error=str(e))
        await message.answer(f"❌ Failed: {str(e)[:50]}", reply_markup=get_back_keyboard())
    
    await state.clear()


# ==================== DAILY REPORT ====================

@router.callback_query(F.data == "adm_fin:daily")
async def admin_daily_report(callback: CallbackQuery, state: FSMContext):
    """Daily report"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    await safe_answer(callback, "📊 Generating...")
    
    try:
        async with db_manager.session() as session:
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday = today - timedelta(days=1)
            
            # Today
            today_txs = await session.scalar(
                select(func.count(Transaction.id)).where(Transaction.created_at >= today)
            ) or 0
            
            today_volume = await session.scalar(
                select(func.sum(Transaction.amount_usd)).where(
                    and_(Transaction.created_at >= today, Transaction.status == TransactionStatus.COMPLETED)
                )
            ) or Decimal("0")
            
            today_fees = await session.scalar(
                select(func.sum(Transaction.fee_usd)).where(
                    and_(Transaction.created_at >= today, Transaction.status == TransactionStatus.COMPLETED)
                )
            ) or Decimal("0")
            
            today_users = await session.scalar(
                select(func.count(User.id)).where(User.created_at >= today)
            ) or 0
            
            # Yesterday comparison
            yesterday_volume = await session.scalar(
                select(func.sum(Transaction.amount_usd)).where(
                    and_(
                        Transaction.created_at >= yesterday,
                        Transaction.created_at < today,
                        Transaction.status == TransactionStatus.COMPLETED
                    )
                )
            ) or Decimal("0")
            
            # P2P
            try:
                from database.models import TradeStatus
                today_p2p = await session.scalar(
                    select(func.count(P2PTrade.id)).where(P2PTrade.created_at >= today)
                ) or 0
                
                today_p2p_volume = await session.scalar(
                    select(func.sum(P2PTrade.fiat_amount)).where(
                        and_(P2PTrade.created_at >= today, P2PTrade.status == TradeStatus.COMPLETED)
                    )
                ) or Decimal("0")
            except:
                today_p2p = 0
                today_p2p_volume = Decimal("0")
        
        # Calculate change
        if yesterday_volume > 0:
            change = ((float(today_volume) - float(yesterday_volume)) / float(yesterday_volume)) * 100
            change_str = f"{'📈' if change >= 0 else '📉'} {change:+.1f}%"
        else:
            change_str = "N/A"
        
        text = f"""
📊 <b>Daily Report - {today.strftime('%Y-%m-%d')}</b>

<b>Transactions:</b>
├ Count: <b>{today_txs}</b>
├ Volume: <b>{format_currency(today_volume)}</b>
├ Fees: <b>{format_currency(today_fees)}</b>
└ vs Yesterday: <b>{change_str}</b>

<b>P2P:</b>
├ Trades: <b>{today_p2p}</b>
└ Volume: <b>{format_currency(today_p2p_volume)}</b>

<b>Users:</b>
└ New Today: <b>+{today_users}</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh", callback_data="adm_fin:daily")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="adm_fin:menu")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("Daily report error", error=str(e))
        await safe_edit(callback.message, "❌ Failed to generate.", get_back_keyboard())


# ==================== FALLBACK ====================

@router.callback_query(F.data.startswith("adm_fin:"))
async def admin_finance_fallback(callback: CallbackQuery, state: FSMContext):
    """Fallback"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    logger.warning("Unhandled finance callback", data=callback.data)
    await admin_finance_menu(callback, state)
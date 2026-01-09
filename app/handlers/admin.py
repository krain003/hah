"""
NEXUS WALLET - Admin Panel (Production-Ready)
Complete admin functionality: user management, statistics, broadcasts,
system monitoring, maintenance mode, and financial controls
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any
from io import BytesIO, StringIO
import csv

from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, BufferedInputFile
)
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import text
from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from config.settings import settings
from database.connection import db_manager
from database.models import (
    User, Wallet, Transaction, P2POrder, P2PTrade, 
    Swap, UserStatus, TransactionStatus, TransactionType
)
from database.repositories.user_repository import UserRepository
from database.repositories.wallet_repository import WalletRepository
from services.price_service import price_service
from blockchain.wallet_manager import wallet_manager, NETWORKS

logger = structlog.get_logger(__name__)
router = Router(name="admin")


# ==================== ADMIN FILTER ====================

def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id in settings.ADMIN_IDS


# ==================== FSM STATES ====================

class AdminStates(StatesGroup):
    # Broadcast
    broadcast_message = State()
    broadcast_confirm = State()
    
    # User management
    search_user = State()
    user_action = State()
    ban_reason = State()
    message_user = State()
    
    # System
    maintenance_reason = State()
    
    # Financial
    manual_tx_user = State()
    manual_tx_amount = State()
    manual_tx_confirm = State()
    
    # Announcements
    announcement_text = State()
    announcement_confirm = State()


# ==================== UTILITY FUNCTIONS ====================

async def safe_edit(message: Message, text: str, keyboard: InlineKeyboardMarkup = None) -> bool:
    """
    Безопасное редактирование сообщения.
    Обрабатывает все возможные ошибки Telegram.
    """
    try:
        # Проверяем наличие медиа
        if message.photo or message.document or message.video or message.audio:
            chat_id = message.chat.id
            try:
                await message.delete()
            except Exception:
                pass
            await message.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return True
        
        # Обычное редактирование
        await message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return True
        
    except TelegramBadRequest as e:
        error_msg = str(e).lower()
        
        # Игнорируем "message is not modified"
        if "message is not modified" in error_msg:
            return True
        
        # Сообщение не найдено или не может быть отредактировано
        if any(x in error_msg for x in ["message to edit not found", "message can't be edited", "there is no text"]):
            try:
                await message.bot.send_message(
                    chat_id=message.chat.id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                return True
            except Exception as send_error:
                logger.error("Failed to send new message", error=str(send_error))
                return False
        
        logger.warning("Edit failed", error=str(e))
        return False
        
    except Exception as e:
        logger.error("Unexpected edit error", error=str(e), exc_info=True)
        return False


async def safe_answer_callback(callback: CallbackQuery, text: str = None, show_alert: bool = False):
    """Безопасный ответ на callback"""
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except TelegramBadRequest as e:
        if "query is too old" not in str(e).lower():
            logger.warning("Callback answer failed", error=str(e))
    except Exception as e:
        logger.error("Callback answer error", error=str(e))


async def safe_send_message(bot: Bot, user_id: int, text: str, **kwargs) -> bool:
    """Безопасная отправка сообщения пользователю"""
    try:
        await bot.send_message(user_id, text, parse_mode="HTML", **kwargs)
        return True
    except TelegramBadRequest as e:
        logger.warning("Failed to send message", user_id=user_id, error=str(e))
        return False
    except Exception as e:
        logger.error("Send message error", user_id=user_id, error=str(e))
        return False


async def safe_delete(message: Message) -> bool:
    """Безопасное удаление сообщения"""
    try:
        await message.delete()
        return True
    except Exception:
        return False


# ==================== KEYBOARDS ====================

def get_admin_main_keyboard() -> InlineKeyboardMarkup:
    """Main admin panel keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Statistics", callback_data="admin:stats"),
            InlineKeyboardButton(text="👥 Users", callback_data="admin:users")
        ],
        [
            InlineKeyboardButton(text="💰 Finance", callback_data="admin:finance"),
            InlineKeyboardButton(text="🔧 System", callback_data="admin:system")
        ],
        [
            InlineKeyboardButton(text="📢 Broadcast", callback_data="admin:broadcast"),
            InlineKeyboardButton(text="🤝 P2P Control", callback_data="admin:p2p")
        ],
        [
            InlineKeyboardButton(text="📝 Logs", callback_data="admin:logs"),
            InlineKeyboardButton(text="⚙️ Settings", callback_data="admin:settings")
        ],
        [
            InlineKeyboardButton(text="🧪 Test Mode", callback_data="admin_test:menu"),
            InlineKeyboardButton(text="🔍 Diagnostics", callback_data="admin_test:menu")
        ],
        [
            InlineKeyboardButton(text="🔙 Close", callback_data="admin:close")
        ]
    ])


def get_admin_stats_keyboard() -> InlineKeyboardMarkup:
    """Statistics sub-menu"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📈 Today", callback_data="admin:stats:today"),
            InlineKeyboardButton(text="📅 Week", callback_data="admin:stats:week"),
            InlineKeyboardButton(text="📆 Month", callback_data="admin:stats:month")
        ],
        [
            InlineKeyboardButton(text="💹 Volume", callback_data="admin:stats:volume"),
            InlineKeyboardButton(text="🪙 By Network", callback_data="admin:stats:networks")
        ],
        [
            InlineKeyboardButton(text="📊 Export CSV", callback_data="admin:stats:export"),
            InlineKeyboardButton(text="🔄 Refresh", callback_data="admin:stats")
        ],
        [
            InlineKeyboardButton(text="🔙 Back", callback_data="admin:main")
        ]
    ])


def get_admin_users_keyboard() -> InlineKeyboardMarkup:
    """Users management sub-menu"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 Search User", callback_data="admin:users:search"),
            InlineKeyboardButton(text="📋 Recent", callback_data="admin:users:recent")
        ],
        [
            InlineKeyboardButton(text="🏆 Top Traders", callback_data="admin:users:top"),
            InlineKeyboardButton(text="⚠️ Flagged", callback_data="admin:users:flagged")
        ],
        [
            InlineKeyboardButton(text="🚫 Banned", callback_data="admin:users:banned"),
            InlineKeyboardButton(text="✅ Verified", callback_data="admin:users:verified")
        ],
        [
            InlineKeyboardButton(text="🔙 Back", callback_data="admin:main")
        ]
    ])


def get_admin_system_keyboard() -> InlineKeyboardMarkup:
    """System management sub-menu"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔴 Maintenance ON", callback_data="admin:system:maintenance_on"),
            InlineKeyboardButton(text="🟢 Maintenance OFF", callback_data="admin:system:maintenance_off")
        ],
        [
            InlineKeyboardButton(text="🔄 Restart Bot", callback_data="admin:system:restart"),
            InlineKeyboardButton(text="🧹 Clear Cache", callback_data="admin:system:clear_cache")
        ],
        [
            InlineKeyboardButton(text="📡 RPC Status", callback_data="admin:system:rpc"),
            InlineKeyboardButton(text="💾 DB Status", callback_data="admin:system:db")
        ],
        [
            InlineKeyboardButton(text="🔙 Back", callback_data="admin:main")
        ]
    ])


def get_admin_finance_keyboard() -> InlineKeyboardMarkup:
    """Finance management sub-menu"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Hot Wallets", callback_data="admin:finance:hot"),
            InlineKeyboardButton(text="📊 Reserves", callback_data="admin:finance:reserves")
        ],
        [
            InlineKeyboardButton(text="📤 Pending Withdrawals", callback_data="admin:finance:pending"),
            InlineKeyboardButton(text="💸 Fee Revenue", callback_data="admin:finance:fees")
        ],
        [
            InlineKeyboardButton(text="➕ Manual Credit", callback_data="admin:finance:credit"),
            InlineKeyboardButton(text="➖ Manual Debit", callback_data="admin:finance:debit")
        ],
        [
            InlineKeyboardButton(text="⚙️ Full Finance Panel", callback_data="adm_fin:menu")
        ],
        [
            InlineKeyboardButton(text="🔙 Back", callback_data="admin:main")
        ]
    ])


def get_admin_p2p_keyboard() -> InlineKeyboardMarkup:
    """P2P management sub-menu"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ Active Disputes", callback_data="admin:p2p:disputes"),
            InlineKeyboardButton(text="🔄 Active Trades", callback_data="admin:p2p:active")
        ],
        [
            InlineKeyboardButton(text="📋 All Orders", callback_data="admin:p2p:orders"),
            InlineKeyboardButton(text="🏆 Top Merchants", callback_data="admin:p2p:merchants")
        ],
        [
            InlineKeyboardButton(text="⚙️ Full P2P Panel", callback_data="adm_p2p:menu")
        ],
        [
            InlineKeyboardButton(text="🔙 Back", callback_data="admin:main")
        ]
    ])


def get_user_action_keyboard(user_id: str, is_banned: bool, is_verified: bool) -> InlineKeyboardMarkup:
    """Actions for specific user"""
    buttons = [
        [
            InlineKeyboardButton(text="💬 Message User", callback_data=f"admin:user:msg:{user_id}"),
            InlineKeyboardButton(text="💰 View Wallets", callback_data=f"admin:user:wallets:{user_id}")
        ],
        [
            InlineKeyboardButton(text="📊 Transactions", callback_data=f"admin:user:txs:{user_id}"),
            InlineKeyboardButton(text="🤝 P2P History", callback_data=f"admin:user:p2p:{user_id}")
        ]
    ]
    
    # Ban/Unban button
    if is_banned:
        buttons.append([
            InlineKeyboardButton(text="✅ Unban User", callback_data=f"admin:user:unban:{user_id}")
        ])
    else:
        buttons.append([
            InlineKeyboardButton(text="🚫 Ban User", callback_data=f"admin:user:ban:{user_id}")
        ])
    
    # Verify button
    if not is_verified:
        buttons.append([
            InlineKeyboardButton(text="✅ Verify Merchant", callback_data=f"admin:user:verify:{user_id}")
        ])
    else:
        buttons.append([
            InlineKeyboardButton(text="❌ Revoke Verification", callback_data=f"admin:user:unverify:{user_id}")
        ])
    
    buttons.append([
        InlineKeyboardButton(text="🔙 Back", callback_data="admin:users")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_back_keyboard(callback_data: str = "admin:main") -> InlineKeyboardMarkup:
    """Simple back button"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data=callback_data)]
    ])


def get_cancel_keyboard(callback_data: str = "admin:main") -> InlineKeyboardMarkup:
    """Cancel button keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data=callback_data)]
    ])


def get_confirm_keyboard(confirm_callback: str, cancel_callback: str = "admin:main") -> InlineKeyboardMarkup:
    """Confirmation keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Confirm", callback_data=confirm_callback),
            InlineKeyboardButton(text="❌ Cancel", callback_data=cancel_callback)
        ]
    ])


# ==================== HELPER FUNCTIONS ====================

async def get_quick_stats(session: AsyncSession) -> Dict[str, Any]:
    """Get quick statistics for admin panel"""
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    
    try:
        total_users = await session.scalar(select(func.count(User.id))) or 0
        
        new_today = await session.scalar(
            select(func.count(User.id)).where(User.created_at >= today)
        ) or 0
        
        total_txs = await session.scalar(select(func.count(Transaction.id))) or 0
        
        volume_result = await session.scalar(
            select(func.sum(Transaction.amount_usd))
            .where(
                and_(
                    Transaction.created_at >= yesterday,
                    Transaction.status == TransactionStatus.COMPLETED
                )
            )
        )
        volume_24h = float(volume_result or 0)
        
        active_p2p = await session.scalar(
            select(func.count(P2PTrade.id))
            .where(P2PTrade.status.in_(["pending", "awaiting_payment", "paid"]))
        ) or 0
        
        return {
            "total_users": total_users,
            "new_today": new_today,
            "total_txs": total_txs,
            "volume_24h": volume_24h,
            "active_p2p": active_p2p
        }
    except Exception as e:
        logger.error("Get quick stats error", error=str(e))
        return {
            "total_users": 0,
            "new_today": 0,
            "total_txs": 0,
            "volume_24h": 0.0,
            "active_p2p": 0
        }


async def get_period_stats(session: AsyncSession, days: int) -> str:
    """Get statistics for a specific period"""
    start_date = datetime.utcnow() - timedelta(days=days)
    
    try:
        new_users = await session.scalar(
            select(func.count(User.id)).where(User.created_at >= start_date)
        ) or 0
        
        transactions = await session.scalar(
            select(func.count(Transaction.id)).where(Transaction.created_at >= start_date)
        ) or 0
        
        volume = await session.scalar(
            select(func.sum(Transaction.amount_usd))
            .where(
                and_(
                    Transaction.created_at >= start_date,
                    Transaction.status == TransactionStatus.COMPLETED
                )
            )
        ) or Decimal("0")
        
        p2p_trades = await session.scalar(
            select(func.count(P2PTrade.id)).where(P2PTrade.created_at >= start_date)
        ) or 0
        
        return f"""
<b>Period:</b> Last {days} day(s)

<b>Users:</b>
└ New Registrations: {new_users:,}

<b>Transactions:</b>
├ Total: {transactions:,}
└ Volume: ${float(volume):,.2f}

<b>P2P:</b>
└ Trades: {p2p_trades:,}
"""
    except Exception as e:
        logger.error("Get period stats error", error=str(e))
        return "<i>Failed to load statistics.</i>"


async def get_volume_stats(session: AsyncSession) -> str:
    """Get volume statistics by transaction type"""
    try:
        result = await session.execute(
            select(
                Transaction.tx_type,
                func.count(Transaction.id).label('count'),
                func.sum(Transaction.amount_usd).label('volume')
            )
            .where(Transaction.status == TransactionStatus.COMPLETED)
            .group_by(Transaction.tx_type)
        )
        
        stats = result.fetchall()
        
        text = "<b>Volume by Transaction Type:</b>\n\n"
        
        if not stats:
            text += "<i>No data available.</i>"
        else:
            for row in stats:
                tx_type = str(row.tx_type.value if hasattr(row.tx_type, 'value') else row.tx_type)
                count = row.count or 0
                volume = float(row.volume or 0)
                text += f"├ <b>{tx_type}</b>: {count:,} txs | ${volume:,.2f}\n"
        
        return text
    except Exception as e:
        logger.error("Get volume stats error", error=str(e))
        return "<i>Failed to load volume statistics.</i>"


async def get_network_stats(session: AsyncSession) -> str:
    """Get statistics by network"""
    try:
        result = await session.execute(
            select(
                Transaction.network,
                func.count(Transaction.id).label('count'),
                func.sum(Transaction.amount_usd).label('volume')
            )
            .where(Transaction.status == TransactionStatus.COMPLETED)
            .group_by(Transaction.network)
        )
        
        stats = result.fetchall()
        
        text = "<b>Volume by Network:</b>\n\n"
        
        if not stats:
            text += "<i>No data available.</i>"
        else:
            for row in stats:
                network = row.network or "Unknown"
                config = NETWORKS.get(network)
                icon = getattr(config, 'icon', '🔗') if config else '🔗'
                count = row.count or 0
                volume = float(row.volume or 0)
                text += f"{icon} <b>{network}</b>: {count:,} txs | ${volume:,.2f}\n"
        
        return text
    except Exception as e:
        logger.error("Get network stats error", error=str(e))
        return "<i>Failed to load network statistics.</i>"


async def generate_stats_csv(session: AsyncSession) -> str:
    """Generate CSV export of statistics"""
    output = StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "Date", "New Users", "Transactions", "Volume USD", 
        "P2P Trades", "Active Orders"
    ])
    
    try:
        # Last 30 days
        for i in range(30):
            date = datetime.utcnow().date() - timedelta(days=i)
            start = datetime.combine(date, datetime.min.time())
            end = datetime.combine(date, datetime.max.time())
            
            new_users = await session.scalar(
                select(func.count(User.id))
                .where(and_(User.created_at >= start, User.created_at <= end))
            ) or 0
            
            txs = await session.scalar(
                select(func.count(Transaction.id))
                .where(and_(Transaction.created_at >= start, Transaction.created_at <= end))
            ) or 0
            
            volume = await session.scalar(
                select(func.sum(Transaction.amount_usd))
                .where(and_(
                    Transaction.created_at >= start,
                    Transaction.created_at <= end,
                    Transaction.status == TransactionStatus.COMPLETED
                ))
            ) or 0
            
            p2p = await session.scalar(
                select(func.count(P2PTrade.id))
                .where(and_(P2PTrade.created_at >= start, P2PTrade.created_at <= end))
            ) or 0
            
            orders = await session.scalar(
                select(func.count(P2POrder.id))
                .where(and_(P2POrder.created_at >= start, P2POrder.created_at <= end))
            ) or 0
            
            writer.writerow([
                date.isoformat(), new_users, txs, float(volume), p2p, orders
            ])
    except Exception as e:
        logger.error("CSV generation error", error=str(e))
        writer.writerow(["Error generating data"])
    
    return output.getvalue()


# ==================== MAIN ADMIN COMMAND ====================

@router.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext):
    """Main admin panel entry point"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Access denied. You are not an administrator.")
        logger.warning("Unauthorized admin access attempt", user_id=message.from_user.id)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            stats = await get_quick_stats(session)
        
        text = f"""
🛡 <b>NEXUS WALLET Admin Panel</b>

📊 <b>Quick Stats:</b>
├ 👥 Total Users: <b>{stats['total_users']:,}</b>
├ 📈 Today's New: <b>+{stats['new_today']}</b>
├ 💰 Total Transactions: <b>{stats['total_txs']:,}</b>
├ 💵 24h Volume: <b>${stats['volume_24h']:,.2f}</b>
└ 🤝 Active P2P Trades: <b>{stats['active_p2p']}</b>

⏰ Server Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC
🟢 System Status: <b>Online</b>

Select an option below:
"""
        
        await message.answer(text, reply_markup=get_admin_main_keyboard(), parse_mode="HTML")
        
    except Exception as e:
        logger.error("Admin panel error", error=str(e), exc_info=True)
        await message.answer(
            "❌ Failed to load admin panel. Please try again.",
            reply_markup=get_back_keyboard()
        )


@router.callback_query(F.data == "admin:main")
async def admin_main_callback(callback: CallbackQuery, state: FSMContext):
    """Return to main admin panel"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            stats = await get_quick_stats(session)
        
        text = f"""
🛡 <b>NEXUS WALLET Admin Panel</b>

📊 <b>Quick Stats:</b>
├ 👥 Total Users: <b>{stats['total_users']:,}</b>
├ 📈 Today's New: <b>+{stats['new_today']}</b>
├ 💰 Total Transactions: <b>{stats['total_txs']:,}</b>
├ 💵 24h Volume: <b>${stats['volume_24h']:,.2f}</b>
└ 🤝 Active P2P Trades: <b>{stats['active_p2p']}</b>

⏰ Server Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC

Select an option below:
"""
        
        await safe_edit(callback.message, text, get_admin_main_keyboard())
        
    except Exception as e:
        logger.error("Admin main callback error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load admin panel.",
            get_back_keyboard()
        )
    
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:close")
async def admin_close(callback: CallbackQuery, state: FSMContext):
    """Close admin panel"""
    await state.clear()
    await safe_delete(callback.message)
    await safe_answer_callback(callback, "Admin panel closed")


# ==================== TEST MODE - ИСПРАВЛЕННЫЙ ====================

# В admin.py - ЗАМЕНИ существующий обработчик на этот:

@router.callback_query(F.data == "admin:test")
async def admin_test_redirect(callback: CallbackQuery, state: FSMContext):
    """Redirect to test mode panel in admin_test.py"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Access denied", show_alert=True)
        return
    
    # Просто меняем callback.data и вызываем обработчик из admin_test
    # Эмулируем нажатие на admin_test:menu
    callback.data = "admin_test:menu"
    
    try:
        from handlers.admin_test import admin_test_menu
        await admin_test_menu(callback, state)
    except Exception as e:
        logger.error("Failed to open test menu", error=str(e))
        await callback.message.edit_text(
            f"❌ Error loading test panel: {str(e)[:100]}",
            reply_markup=get_back_keyboard("admin:main"),
            parse_mode="HTML"
        )
    
    await callback.answer()

@router.callback_query(F.data == "admin:test:toggle_global")
async def admin_toggle_global_test(callback: CallbackQuery, state: FSMContext):
    """Toggle global test mode"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    try:
        from utils.config_manager import config_manager
        current = await config_manager.get("global_test_mode", False)
        new_value = not current
        await config_manager.set("global_test_mode", new_value)
        
        status = "ENABLED" if new_value else "DISABLED"
        logger.info(f"Global test mode {status}", admin_id=callback.from_user.id)
        
        await safe_answer_callback(callback, f"✅ Global test mode {status}")
        
    except ImportError:
        await safe_answer_callback(callback, "❌ Config manager not available", show_alert=True)
    except Exception as e:
        logger.error("Toggle test mode error", error=str(e))
        await safe_answer_callback(callback, f"❌ Error: {str(e)[:50]}", show_alert=True)


@router.callback_query(F.data == "admin:test:networks")
async def admin_test_networks_config(callback: CallbackQuery, state: FSMContext):
    """Configure test mode for specific networks"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        from utils.config_manager import config_manager
        test_networks = await config_manager.get("test_mode_networks", [])
    except ImportError:
        test_networks = []
    
    text = """
🔧 <b>Configure Test Mode for Networks</b>

Select networks to enable/disable test mode:

"""
    
    buttons = []
    
    for network, config in NETWORKS.items():
        # Skip testnet networks (they're always in test mode)
        if getattr(config, 'is_testnet', False):
            continue
        
        is_test = network in test_networks
        status = "🧪" if is_test else "🔵"
        action = "disable" if is_test else "enable"
        
        text += f"{status} {config.icon} <b>{network.upper()}</b>: {'Test Mode' if is_test else 'Live Mode'}\n"
        
        buttons.append([InlineKeyboardButton(
            text=f"{status} {network.upper()} - {'Disable Test' if is_test else 'Enable Test'}",
            callback_data=f"admin:test:net:{action}:{network}"
        )])
    
    buttons.append([
        InlineKeyboardButton(text="🧪 Enable All", callback_data="admin:test:net:enable_all"),
        InlineKeyboardButton(text="🔵 Disable All", callback_data="admin:test:net:disable_all")
    ])
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin:test")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer_callback(callback)


@router.callback_query(F.data.startswith("admin:test:net:"))
async def admin_toggle_network_test(callback: CallbackQuery, state: FSMContext):
    """Toggle test mode for specific network"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    parts = callback.data.split(":")
    action = parts[3]  # enable, disable, enable_all, disable_all
    
    try:
        from utils.config_manager import config_manager
        test_networks = await config_manager.get("test_mode_networks", [])
        
        if action == "enable_all":
            # Enable test for all mainnet networks
            test_networks = [n for n, c in NETWORKS.items() if not getattr(c, 'is_testnet', False)]
            await config_manager.set("test_mode_networks", test_networks)
            await safe_answer_callback(callback, "✅ Test mode enabled for all networks")
            
        elif action == "disable_all":
            await config_manager.set("test_mode_networks", [])
            await safe_answer_callback(callback, "✅ Test mode disabled for all networks")
            
        elif len(parts) > 4:
            network = parts[4]
            
            if action == "enable":
                if network not in test_networks:
                    test_networks.append(network)
                await safe_answer_callback(callback, f"✅ Test mode enabled for {network.upper()}")
            elif action == "disable":
                if network in test_networks:
                    test_networks.remove(network)
                await safe_answer_callback(callback, f"✅ Test mode disabled for {network.upper()}")
            
            await config_manager.set("test_mode_networks", test_networks)
        
        # Refresh menu
        await admin_test_networks_config(callback, state)
        
    except ImportError:
        await safe_answer_callback(callback, "❌ Config manager not available", show_alert=True)
    except Exception as e:
        logger.error("Toggle network test error", error=str(e))
        await safe_answer_callback(callback, f"❌ Error: {str(e)[:50]}", show_alert=True)


# ==================== DIAGNOSTICS - НОВАЯ ФУНКЦИЯ ====================

@router.callback_query(F.data == "admin:diagnostics")
async def admin_diagnostics_menu(callback: CallbackQuery, state: FSMContext):
    """System diagnostics menu"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    text = """
🔍 <b>System Diagnostics</b>

Automated system health checks and error detection.

Select diagnostic type:
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Full System Check", callback_data="admin:diag:full"),
        ],
        [
            InlineKeyboardButton(text="📡 Network Check", callback_data="admin:diag:networks"),
            InlineKeyboardButton(text="💾 Database Check", callback_data="admin:diag:database")
        ],
        [
            InlineKeyboardButton(text="💰 Finance Check", callback_data="admin:diag:finance"),
            InlineKeyboardButton(text="🤝 P2P Check", callback_data="admin:diag:p2p")
        ],
        [
            InlineKeyboardButton(text="🔧 Services Check", callback_data="admin:diag:services"),
            InlineKeyboardButton(text="📝 Error Logs", callback_data="admin:diag:errors")
        ],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin:main")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:diag:full")
async def admin_full_diagnostics(callback: CallbackQuery, state: FSMContext):
    """Run full system diagnostics"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    await safe_answer_callback(callback, "🔍 Running diagnostics...")
    
    # Start with loading message
    await safe_edit(callback.message, "🔍 <b>Running Full System Diagnostics...</b>\n\nPlease wait...")
    
    results = {
        "database": {"status": "checking", "issues": []},
        "networks": {"status": "checking", "issues": []},
        "services": {"status": "checking", "issues": []},
        "finance": {"status": "checking", "issues": []},
        "p2p": {"status": "checking", "issues": []}
    }
    
    # 1. Database check
    try:
        async with db_manager.session() as session:
            # Check basic queries
            await session.scalar(select(func.count(User.id)))
            await session.scalar(select(func.count(Wallet.id)))
            await session.scalar(select(func.count(Transaction.id)))
            
            # Check for orphaned records
            orphaned_wallets = await session.scalar(
                select(func.count(Wallet.id))
                .where(~Wallet.user_id.in_(select(User.id)))
            ) or 0
            
            if orphaned_wallets > 0:
                results["database"]["issues"].append(f"Found {orphaned_wallets} orphaned wallets")
            
            # Check for stuck transactions
            one_hour_ago = datetime.utcnow() - timedelta(hours=1)
            stuck_txs = await session.scalar(
                select(func.count(Transaction.id))
                .where(
                    and_(
                        Transaction.status == TransactionStatus.PENDING,
                        Transaction.created_at < one_hour_ago
                    )
                )
            ) or 0
            
            if stuck_txs > 0:
                results["database"]["issues"].append(f"Found {stuck_txs} stuck pending transactions (>1h)")
            
            results["database"]["status"] = "ok" if not results["database"]["issues"] else "warning"
            
    except Exception as e:
        results["database"]["status"] = "error"
        results["database"]["issues"].append(f"Database connection error: {str(e)[:50]}")
    
    # 2. Network check
    try:
        network_status = await wallet_manager.get_system_status()
        
        for network, info in network_status.items():
            if not info.get("online"):
                results["networks"]["issues"].append(f"{network}: OFFLINE - {info.get('error', 'Unknown')[:30]}")
        
        results["networks"]["status"] = "ok" if not results["networks"]["issues"] else "error"
        
    except Exception as e:
        results["networks"]["status"] = "error"
        results["networks"]["issues"].append(f"Network check failed: {str(e)[:50]}")
    
    # 3. Services check
    try:
        # Check price service
        try:
            await asyncio.wait_for(price_service.get_price("bitcoin"), timeout=5.0)
        except asyncio.TimeoutError:
            results["services"]["issues"].append("Price service timeout (>5s)")
        except Exception as e:
            results["services"]["issues"].append(f"Price service error: {str(e)[:30]}")
        
        # Check other services
        try:
            from services.p2p_service import p2p_service
            if not hasattr(p2p_service, 'platform_fee_percent'):
                results["services"]["issues"].append("P2P service not initialized")
        except ImportError:
            results["services"]["issues"].append("P2P service not available")
        
        results["services"]["status"] = "ok" if not results["services"]["issues"] else "warning"
        
    except Exception as e:
        results["services"]["status"] = "error"
        results["services"]["issues"].append(f"Services check failed: {str(e)[:50]}")
    
    # 4. Finance check
    try:
        async with db_manager.session() as session:
            # Check for negative balances
            from database.models import WalletBalance
            negative_balances = await session.scalar(
                select(func.count(WalletBalance.id))
                .where(WalletBalance.balance < 0)
            ) or 0
            
            if negative_balances > 0:
                results["finance"]["issues"].append(f"Found {negative_balances} negative balances")
            
            # Check pending withdrawals older than 24h
            one_day_ago = datetime.utcnow() - timedelta(days=1)
            old_pending = await session.scalar(
                select(func.count(Transaction.id))
                .where(
                    and_(
                        Transaction.tx_type == TransactionType.WITHDRAWAL,
                        Transaction.status == TransactionStatus.PENDING,
                        Transaction.created_at < one_day_ago
                    )
                )
            ) or 0
            
            if old_pending > 0:
                results["finance"]["issues"].append(f"Found {old_pending} withdrawals pending >24h")
        
        results["finance"]["status"] = "ok" if not results["finance"]["issues"] else "warning"
        
    except Exception as e:
        results["finance"]["status"] = "error"
        results["finance"]["issues"].append(f"Finance check failed: {str(e)[:50]}")
    
    # 5. P2P check
    try:
        async with db_manager.session() as session:
            from database.models import TradeStatus, DisputeStatus, Dispute
            
            # Check for old open disputes
            one_week_ago = datetime.utcnow() - timedelta(days=7)
            old_disputes = await session.scalar(
                select(func.count(Dispute.id))
                .where(
                    and_(
                        Dispute.status == DisputeStatus.OPEN,
                        Dispute.created_at < one_week_ago
                    )
                )
            ) or 0
            
            if old_disputes > 0:
                results["p2p"]["issues"].append(f"Found {old_disputes} disputes open >7 days")
            
            # Check for stuck trades
            stuck_trades = await session.scalar(
                select(func.count(P2PTrade.id))
                .where(
                    and_(
                        P2PTrade.status.in_([TradeStatus.PENDING, TradeStatus.AWAITING_PAYMENT]),
                        P2PTrade.created_at < one_day_ago
                    )
                )
            ) or 0
            
            if stuck_trades > 0:
                results["p2p"]["issues"].append(f"Found {stuck_trades} trades stuck >24h")
        
        results["p2p"]["status"] = "ok" if not results["p2p"]["issues"] else "warning"
        
    except Exception as e:
        results["p2p"]["status"] = "error"
        results["p2p"]["issues"].append(f"P2P check failed: {str(e)[:50]}")
    
    # Generate report
    status_icons = {"ok": "✅", "warning": "⚠️", "error": "❌", "checking": "🔄"}
    
    total_issues = sum(len(r["issues"]) for r in results.values())
    overall_status = "✅ HEALTHY" if total_issues == 0 else f"⚠️ {total_issues} ISSUES FOUND"
    
    text = f"""
🔍 <b>Full System Diagnostics</b>

<b>Overall Status:</b> {overall_status}
<b>Time:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC

━━━━━━━━━━━━━━━━━━━━

{status_icons[results['database']['status']]} <b>Database:</b> {results['database']['status'].upper()}
"""
    
    for issue in results['database']['issues'][:3]:
        text += f"   └ {issue}\n"
    
    text += f"""
{status_icons[results['networks']['status']]} <b>Networks:</b> {results['networks']['status'].upper()}
"""
    
    for issue in results['networks']['issues'][:3]:
        text += f"   └ {issue}\n"
    
    text += f"""
{status_icons[results['services']['status']]} <b>Services:</b> {results['services']['status'].upper()}
"""
    
    for issue in results['services']['issues'][:3]:
        text += f"   └ {issue}\n"
    
    text += f"""
{status_icons[results['finance']['status']]} <b>Finance:</b> {results['finance']['status'].upper()}
"""
    
    for issue in results['finance']['issues'][:3]:
        text += f"   └ {issue}\n"
    
    text += f"""
{status_icons[results['p2p']['status']]} <b>P2P:</b> {results['p2p']['status'].upper()}
"""
    
    for issue in results['p2p']['issues'][:3]:
        text += f"   └ {issue}\n"
    
    text += "\n━━━━━━━━━━━━━━━━━━━━"
    
    if total_issues > 0:
        text += f"\n\n⚠️ <b>Action Required:</b> Review and fix the issues above."
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Run Again", callback_data="admin:diag:full")],
        [InlineKeyboardButton(text="📝 Export Report", callback_data="admin:diag:export")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin:diagnostics")]
    ])
    
    await safe_edit(callback.message, text, keyboard)


@router.callback_query(F.data == "admin:diag:networks")
async def admin_network_diagnostics(callback: CallbackQuery, state: FSMContext):
    """Network-specific diagnostics"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    await safe_answer_callback(callback, "📡 Checking networks...")
    
    try:
        status = await wallet_manager.get_system_status()
        
        text = "📡 <b>Network Diagnostics</b>\n\n"
        
        online_count = 0
        offline_count = 0
        
        for network, info in status.items():
            config = NETWORKS.get(network)
            if not config:
                continue
            
            testnet = "🧪" if getattr(config, 'is_testnet', False) else ""
            
            if info.get("online"):
                online_count += 1
                status_emoji = "🟢"
                height = info.get("height", "N/A")
                latency = info.get("latency_ms")
                latency_str = f" | {latency:.0f}ms" if latency else ""
                text += f"{status_emoji} {config.icon} <b>{network}</b> {testnet}\n"
                text += f"   Block: #{height}{latency_str}\n"
                
                # Check for issues
                if latency and latency > 5000:
                    text += f"   ⚠️ High latency!\n"
            else:
                offline_count += 1
                error = info.get("error", "Unknown error")[:40]
                text += f"🔴 {config.icon} <b>{network}</b> {testnet}\n"
                text += f"   ❌ OFFLINE: {error}\n"
        
        text += f"\n━━━━━━━━━━━━━━━━━━━━\n"
        text += f"<b>Summary:</b> {online_count} online, {offline_count} offline"
        
        if offline_count > 0:
            text += f"\n\n⚠️ <b>Action:</b> Check RPC endpoints for offline networks."
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin:diag:networks")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin:diagnostics")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("Network diagnostics error", error=str(e))
        await safe_edit(
            callback.message,
            f"❌ Network check failed: {str(e)[:100]}",
            get_back_keyboard("admin:diagnostics")
        )


@router.callback_query(F.data == "admin:diag:database")
async def admin_database_diagnostics(callback: CallbackQuery, state: FSMContext):
    """Database diagnostics"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    await safe_answer_callback(callback, "💾 Checking database...")
    
    try:
        async with db_manager.session() as session:
            from database.models import WalletBalance
            
            # Table counts
            users = await session.scalar(select(func.count(User.id))) or 0
            wallets = await session.scalar(select(func.count(Wallet.id))) or 0
            transactions = await session.scalar(select(func.count(Transaction.id))) or 0
            balances = await session.scalar(select(func.count(WalletBalance.id))) or 0
            p2p_orders = await session.scalar(select(func.count(P2POrder.id))) or 0
            p2p_trades = await session.scalar(select(func.count(P2PTrade.id))) or 0
            
            # Data integrity checks
            issues = []
            
            # Orphaned wallets
            orphaned_wallets = await session.scalar(
                select(func.count(Wallet.id))
                .where(~Wallet.user_id.in_(select(User.id)))
            ) or 0
            
            if orphaned_wallets > 0:
                issues.append(f"❌ {orphaned_wallets} orphaned wallets (no user)")
            
            # Orphaned transactions
            orphaned_txs = await session.scalar(
                select(func.count(Transaction.id))
                .where(~Transaction.user_id.in_(select(User.id)))
            ) or 0
            
            if orphaned_txs > 0:
                issues.append(f"❌ {orphaned_txs} orphaned transactions (no user)")
            
            # Negative balances
            negative_balances = await session.scalar(
                select(func.count(WalletBalance.id))
                .where(WalletBalance.balance < 0)
            ) or 0
            
            if negative_balances > 0:
                issues.append(f"⚠️ {negative_balances} negative balances")
            
            # Stuck pending transactions (>1h)
            one_hour_ago = datetime.utcnow() - timedelta(hours=1)
            stuck_pending = await session.scalar(
                select(func.count(Transaction.id))
                .where(
                    and_(
                        Transaction.status == TransactionStatus.PENDING,
                        Transaction.created_at < one_hour_ago
                    )
                )
            ) or 0
            
            if stuck_pending > 0:
                issues.append(f"⚠️ {stuck_pending} transactions pending >1 hour")
        
        db_type = 'PostgreSQL' if 'postgresql' in str(db_manager.engine.url) else 'SQLite'
        
        text = f"""
💾 <b>Database Diagnostics</b>

<b>Connection:</b> 🟢 OK
<b>Type:</b> {db_type}

<b>Table Statistics:</b>
├ Users: {users:,}
├ Wallets: {wallets:,}
├ Wallet Balances: {balances:,}
├ Transactions: {transactions:,}
├ P2P Orders: {p2p_orders:,}
└ P2P Trades: {p2p_trades:,}

<b>Data Integrity:</b>
"""
        
        if not issues:
            text += "✅ All checks passed!\n"
        else:
            for issue in issues:
                text += f"{issue}\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin:diag:database")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin:diagnostics")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("Database diagnostics error", error=str(e))
        await safe_edit(
            callback.message,
            f"❌ Database check failed: {str(e)[:100]}",
            get_back_keyboard("admin:diagnostics")
        )


@router.callback_query(F.data == "admin:diag:services")
async def admin_services_diagnostics(callback: CallbackQuery, state: FSMContext):
    """Services health check"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    await safe_answer_callback(callback, "🔧 Checking services...")
    
    services_status = {}
    
    # Check price service
    try:
        start = datetime.utcnow()
        price = await asyncio.wait_for(price_service.get_price("bitcoin"), timeout=5.0)
        latency = (datetime.utcnow() - start).total_seconds() * 1000
        services_status["Price Service"] = {"status": "ok", "latency": latency, "info": f"BTC: ${price:,.0f}" if price else "N/A"}
    except asyncio.TimeoutError:
        services_status["Price Service"] = {"status": "error", "info": "Timeout (>5s)"}
    except Exception as e:
        services_status["Price Service"] = {"status": "error", "info": str(e)[:30]}
    
    # Check P2P service
    try:
        from services.p2p_service import p2p_service
        fee = getattr(p2p_service, 'platform_fee_percent', None)
        if fee is not None:
            services_status["P2P Service"] = {"status": "ok", "info": f"Fee: {fee}%"}
        else:
            services_status["P2P Service"] = {"status": "warning", "info": "Not configured"}
    except ImportError:
        services_status["P2P Service"] = {"status": "error", "info": "Not available"}
    
    # Check wallet manager
    try:
        from blockchain.wallet_manager import wallet_manager
        if wallet_manager:
            services_status["Wallet Manager"] = {"status": "ok", "info": f"{len(NETWORKS)} networks"}
        else:
            services_status["Wallet Manager"] = {"status": "error", "info": "Not initialized"}
    except Exception as e:
        services_status["Wallet Manager"] = {"status": "error", "info": str(e)[:30]}
    
    # Check config manager
    try:
        from utils.config_manager import config_manager
        test = await config_manager.get("test_key", "default")
        services_status["Config Manager"] = {"status": "ok", "info": "Working"}
    except ImportError:
        services_status["Config Manager"] = {"status": "warning", "info": "Not available"}
    except Exception as e:
        services_status["Config Manager"] = {"status": "error", "info": str(e)[:30]}
    
    # Check direct purchase service
    try:
        from services.direct_purchase_service import direct_purchase_service
        limits = direct_purchase_service.get_limits()
        services_status["Direct Purchase"] = {"status": "ok", "info": f"Limits: ${limits['buy']['min_usd']}-${limits['buy']['max_usd']}"}
    except ImportError:
        services_status["Direct Purchase"] = {"status": "warning", "info": "Not available"}
    except Exception as e:
        services_status["Direct Purchase"] = {"status": "error", "info": str(e)[:30]}
    
    status_icons = {"ok": "🟢", "warning": "⚠️", "error": "🔴"}
    
    text = "🔧 <b>Services Health Check</b>\n\n"
    
    for service, data in services_status.items():
        icon = status_icons.get(data["status"], "❓")
        text += f"{icon} <b>{service}</b>\n"
        text += f"   └ {data.get('info', 'N/A')}"
        if data.get("latency"):
            text += f" | {data['latency']:.0f}ms"
        text += "\n"
    
    ok_count = sum(1 for s in services_status.values() if s["status"] == "ok")
    total = len(services_status)
    
    text += f"\n━━━━━━━━━━━━━━━━━━━━\n"
    text += f"<b>Summary:</b> {ok_count}/{total} services healthy"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin:diag:services")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin:diagnostics")]
    ])
    
    await safe_edit(callback.message, text, keyboard)


@router.callback_query(F.data == "admin:diag:finance")
async def admin_finance_diagnostics(callback: CallbackQuery, state: FSMContext):
    """Finance diagnostics"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    await safe_answer_callback(callback, "💰 Checking finances...")
    
    try:
        async with db_manager.session() as session:
            from database.models import WalletBalance
            
            issues = []
            
            # Negative balances
            result = await session.execute(
                select(WalletBalance, Wallet, User)
                .join(Wallet)
                .join(User)
                .where(WalletBalance.balance < 0)
                .limit(10)
            )
            negative = result.fetchall()
            
            if negative:
                issues.append(f"❌ {len(negative)} negative balances found")
                for bal, wallet, user in negative[:3]:
                    issues.append(f"   User {user.telegram_id}: {bal.balance} {bal.token_symbol}")
            
            # Old pending withdrawals
            one_day_ago = datetime.utcnow() - timedelta(days=1)
            old_pending = await session.scalar(
                select(func.count(Transaction.id))
                .where(
                    and_(
                        Transaction.tx_type == TransactionType.WITHDRAWAL,
                        Transaction.status == TransactionStatus.PENDING,
                        Transaction.created_at < one_day_ago
                    )
                )
            ) or 0
            
            if old_pending > 0:
                issues.append(f"⚠️ {old_pending} withdrawals pending >24h")
            
            # Today's stats
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            
            today_deposits = await session.scalar(
                select(func.sum(Transaction.amount_usd))
                .where(
                    and_(
                        Transaction.tx_type == TransactionType.DEPOSIT,
                        Transaction.status == TransactionStatus.COMPLETED,
                        Transaction.created_at >= today
                    )
                )
            ) or Decimal("0")
            
            today_withdrawals = await session.scalar(
                select(func.sum(Transaction.amount_usd))
                .where(
                    and_(
                        Transaction.tx_type == TransactionType.WITHDRAWAL,
                        Transaction.status == TransactionStatus.COMPLETED,
                        Transaction.created_at >= today
                    )
                )
            ) or Decimal("0")
            
            today_fees = await session.scalar(
                select(func.sum(Transaction.fee_usd))
                .where(
                    and_(
                        Transaction.status == TransactionStatus.COMPLETED,
                        Transaction.created_at >= today
                    )
                )
            ) or Decimal("0")
            
            # Pending counts
            pending_deposits = await session.scalar(
                select(func.count(Transaction.id))
                .where(
                    and_(
                        Transaction.tx_type == TransactionType.DEPOSIT,
                        Transaction.status == TransactionStatus.PENDING
                    )
                )
            ) or 0
            
            pending_withdrawals = await session.scalar(
                select(func.count(Transaction.id))
                .where(
                    and_(
                        Transaction.tx_type == TransactionType.WITHDRAWAL,
                        Transaction.status == TransactionStatus.PENDING
                    )
                )
            ) or 0
        
        text = f"""
💰 <b>Finance Diagnostics</b>

<b>Today's Activity:</b>
├ Deposits: <b>${float(today_deposits):,.2f}</b>
├ Withdrawals: <b>${float(today_withdrawals):,.2f}</b>
├ Net Flow: <b>${float(today_deposits - today_withdrawals):,.2f}</b>
└ Fees Collected: <b>${float(today_fees):,.2f}</b>

<b>Pending Operations:</b>
├ Pending Deposits: {pending_deposits}
└ Pending Withdrawals: {pending_withdrawals}

<b>Health Check:</b>
"""
        
        if not issues:
            text += "✅ No issues detected!\n"
        else:
            for issue in issues:
                text += f"{issue}\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin:diag:finance")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin:diagnostics")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("Finance diagnostics error", error=str(e))
        await safe_edit(
            callback.message,
            f"❌ Finance check failed: {str(e)[:100]}",
            get_back_keyboard("admin:diagnostics")
        )


@router.callback_query(F.data == "admin:diag:p2p")
async def admin_p2p_diagnostics(callback: CallbackQuery, state: FSMContext):
    """P2P diagnostics"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    await safe_answer_callback(callback, "🤝 Checking P2P...")
    
    try:
        async with db_manager.session() as session:
            from database.models import TradeStatus, DisputeStatus, Dispute
            
            issues = []
            
            # Old open disputes
            one_week_ago = datetime.utcnow() - timedelta(days=7)
            one_day_ago = datetime.utcnow() - timedelta(days=1)
            
            old_disputes = await session.scalar(
                select(func.count(Dispute.id))
                .where(
                    and_(
                        Dispute.status == DisputeStatus.OPEN,
                        Dispute.created_at < one_week_ago
                    )
                )
            ) or 0
            
            if old_disputes > 0:
                issues.append(f"❌ {old_disputes} disputes open >7 days")
            
            # Stuck trades
            stuck_trades = await session.scalar(
                select(func.count(P2PTrade.id))
                .where(
                    and_(
                        P2PTrade.status.in_([TradeStatus.PENDING, TradeStatus.AWAITING_PAYMENT]),
                        P2PTrade.created_at < one_day_ago
                    )
                )
            ) or 0
            
            if stuck_trades > 0:
                issues.append(f"⚠️ {stuck_trades} trades stuck >24h")
            
            # Active stats
            active_orders = await session.scalar(
                select(func.count(P2POrder.id)).where(P2POrder.status == "active")
            ) or 0
            
            active_trades = await session.scalar(
                select(func.count(P2PTrade.id))
                .where(P2PTrade.status.in_([
                    TradeStatus.PENDING,
                    TradeStatus.AWAITING_PAYMENT,
                    TradeStatus.PAYMENT_SENT
                ]))
            ) or 0
            
            open_disputes = await session.scalar(
                select(func.count(Dispute.id))
                .where(Dispute.status.in_([DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW]))
            ) or 0
            
            # Today's completed trades
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_completed = await session.scalar(
                select(func.count(P2PTrade.id))
                .where(
                    and_(
                        P2PTrade.status == TradeStatus.COMPLETED,
                        P2PTrade.completed_at >= today
                    )
                )
            ) or 0
            
            today_volume = await session.scalar(
                select(func.sum(P2PTrade.fiat_amount))
                .where(
                    and_(
                        P2PTrade.status == TradeStatus.COMPLETED,
                        P2PTrade.completed_at >= today
                    )
                )
            ) or Decimal("0")
        
        text = f"""
🤝 <b>P2P Diagnostics</b>

<b>Current Activity:</b>
├ Active Orders: <b>{active_orders}</b>
├ Active Trades: <b>{active_trades}</b>
└ Open Disputes: <b>{open_disputes}</b>

<b>Today:</b>
├ Completed Trades: <b>{today_completed}</b>
└ Volume: <b>${float(today_volume):,.2f}</b>

<b>Health Check:</b>
"""
        
        if not issues:
            text += "✅ No issues detected!\n"
        else:
            for issue in issues:
                text += f"{issue}\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin:diag:p2p")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin:diagnostics")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("P2P diagnostics error", error=str(e))
        await safe_edit(
            callback.message,
            f"❌ P2P check failed: {str(e)[:100]}",
            get_back_keyboard("admin:diagnostics")
        )


@router.callback_query(F.data == "admin:diag:errors")
async def admin_error_logs(callback: CallbackQuery, state: FSMContext):
    """View recent error logs"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    text = """
📝 <b>Error Logs</b>

<i>Recent errors from the system:</i>

"""
    
    # Try to read from log file or audit service
    try:
        from services.audit_service import audit_service
        
        async with db_manager.session() as session:
            logs = await audit_service.get_logs(session, limit=15, action_filter="error")
        
        if not logs:
            text += "<i>No recent errors found. 🎉</i>"
        else:
            for log in logs:
                time_str = log.created_at.strftime('%m/%d %H:%M') if log.created_at else 'N/A'
                action = getattr(log, 'action', 'Unknown')
                details = str(getattr(log, 'details', ''))[:50]
                text += f"• <code>{time_str}</code> {action}\n"
                if details:
                    text += f"  └ {details}\n"
                    
    except ImportError:
        text += "<i>Audit service not available.</i>\n"
        text += "\n<b>Check server logs for errors:</b>\n"
        text += "<code>tail -f logs/nexus.log | grep ERROR</code>"
    except Exception as e:
        text += f"<i>Error loading logs: {str(e)[:50]}</i>"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin:diag:errors")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin:diagnostics")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:diag:export")
async def admin_export_diagnostics(callback: CallbackQuery):
    """Export diagnostics report"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await safe_answer_callback(callback, "📊 Generating report...")
    
    # Generate text report
    report = f"""NEXUS WALLET - DIAGNOSTICS REPORT
Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC
=========================================

"""
    
    # Add system info
    report += f"""SYSTEM INFO
-----------
Python Version: {sys.version}
Platform: {sys.platform}

"""
    
    # Add database stats
    try:
        async with db_manager.session() as session:
            users = await session.scalar(select(func.count(User.id))) or 0
            wallets = await session.scalar(select(func.count(Wallet.id))) or 0
            transactions = await session.scalar(select(func.count(Transaction.id))) or 0
            
            report += f"""DATABASE
--------
Users: {users}
Wallets: {wallets}
Transactions: {transactions}

"""
    except Exception as e:
        report += f"DATABASE: Error - {str(e)}\n\n"
    
    # Add network status
    try:
        status = await wallet_manager.get_system_status()
        report += "NETWORKS\n--------\n"
        for network, info in status.items():
            status_str = "ONLINE" if info.get("online") else "OFFLINE"
            report += f"{network}: {status_str}\n"
        report += "\n"
    except Exception as e:
        report += f"NETWORKS: Error - {str(e)}\n\n"
    
    # Send as file
    file = BufferedInputFile(
        report.encode('utf-8'),
        filename=f"nexus_diagnostics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    )
    
    await callback.message.answer_document(file, caption="📊 Diagnostics Report")


# ==================== STATISTICS ====================

@router.callback_query(F.data == "admin:stats")
async def admin_stats_menu(callback: CallbackQuery, state: FSMContext):
    """Statistics menu"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    text = """
📊 <b>Statistics Dashboard</b>

Select time period or category:
"""
    
    await safe_edit(callback.message, text, get_admin_stats_keyboard())
    await safe_answer_callback(callback)


# ==================== STATISTICS (продолжение) ====================

@router.callback_query(F.data.startswith("admin:stats:"))
async def admin_stats_detail(callback: CallbackQuery, state: FSMContext):
    """Detailed statistics"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    period = callback.data.split(":")[-1]
    
    await safe_answer_callback(callback, "📊 Loading statistics...")
    
    try:
        async with db_manager.session() as session:
            if period == "today":
                stats = await get_period_stats(session, days=1)
                title = "📈 Today's Statistics"
            elif period == "week":
                stats = await get_period_stats(session, days=7)
                title = "📅 This Week's Statistics"
            elif period == "month":
                stats = await get_period_stats(session, days=30)
                title = "📆 This Month's Statistics"
            elif period == "volume":
                stats = await get_volume_stats(session)
                title = "💹 Volume Statistics"
            elif period == "networks":
                stats = await get_network_stats(session)
                title = "🪙 Network Statistics"
            elif period == "export":
                # Generate and send CSV
                csv_data = await generate_stats_csv(session)
                file = BufferedInputFile(
                    csv_data.encode('utf-8'),
                    filename=f"nexus_stats_{datetime.now().strftime('%Y%m%d')}.csv"
                )
                await callback.message.answer_document(file, caption="📊 Statistics Export")
                await safe_answer_callback(callback, "Export generated!")
                return
            else:
                await safe_answer_callback(callback, "Unknown option", show_alert=True)
                return
        
        text = f"""
{title}

{stats}
"""
        
        await safe_edit(callback.message, text, get_back_keyboard("admin:stats"))
        
    except Exception as e:
        logger.error("Stats detail error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load statistics.",
            get_back_keyboard("admin:stats")
        )


# ==================== USER MANAGEMENT ====================

@router.callback_query(F.data == "admin:users")
async def admin_users_menu(callback: CallbackQuery, state: FSMContext):
    """Users management menu"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            total = await session.scalar(select(func.count(User.id))) or 0
            active = await session.scalar(
                select(func.count(User.id)).where(User.status == UserStatus.ACTIVE)
            ) or 0
            banned = await session.scalar(
                select(func.count(User.id)).where(User.status == UserStatus.BANNED)
            ) or 0
            verified = await session.scalar(
                select(func.count(User.id)).where(User.merchant_verified == True)
            ) or 0
        
        text = f"""
👥 <b>User Management</b>

📊 <b>Overview:</b>
├ Total Users: <b>{total:,}</b>
├ Active: <b>{active:,}</b>
├ Banned: <b>{banned:,}</b>
└ Verified Merchants: <b>{verified:,}</b>

Select an action:
"""
        
        await safe_edit(callback.message, text, get_admin_users_keyboard())
        
    except Exception as e:
        logger.error("Users menu error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load user data.",
            get_back_keyboard()
        )
    
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:users:search")
async def admin_search_user_start(callback: CallbackQuery, state: FSMContext):
    """Start user search"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    text = """
🔍 <b>Search User</b>

Enter one of the following:
• Telegram ID (number)
• Username (@username)
• Wallet address

Type your search query:
"""
    
    await safe_edit(callback.message, text, get_cancel_keyboard("admin:users"))
    await state.set_state(AdminStates.search_user)
    await safe_answer_callback(callback)


@router.message(AdminStates.search_user)
async def admin_search_user_process(message: Message, state: FSMContext):
    """Process user search"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    query = message.text.strip()
    
    try:
        async with db_manager.session() as session:
            user = None
            
            # Search by Telegram ID
            if query.isdigit():
                user = await session.scalar(
                    select(User).where(User.telegram_id == int(query))
                )
            
            # Search by username
            if not user and query.startswith("@"):
                user = await session.scalar(
                    select(User).where(User.username == query[1:])
                )
            
            # Search by username without @
            if not user:
                user = await session.scalar(
                    select(User).where(User.username == query)
                )
            
            # Search by wallet address
            if not user:
                wallet = await session.scalar(
                    select(Wallet).where(Wallet.address == query)
                )
                if wallet:
                    user = await session.scalar(
                        select(User).where(User.id == wallet.user_id)
                    )
            
            if not user:
                await message.answer(
                    "❌ User not found. Try another search query.",
                    reply_markup=get_back_keyboard("admin:users")
                )
                await state.clear()
                return
            
            # Get user stats
            wallet_count = await session.scalar(
                select(func.count(Wallet.id)).where(Wallet.user_id == user.id)
            ) or 0
            tx_count = await session.scalar(
                select(func.count(Transaction.id)).where(Transaction.user_id == user.id)
            ) or 0
            
            status_emoji = {
                UserStatus.ACTIVE: "🟢",
                UserStatus.BANNED: "🔴",
                UserStatus.SUSPENDED: "🟡",
                UserStatus.PENDING_VERIFICATION: "🟠"
            }
            
            # Safe access to attributes
            rating = getattr(user, 'rating', 0) or 0
            total_volume = getattr(user, 'total_volume_usd', 0) or 0
            total_trades = getattr(user, 'total_trades_count', 0) or 0
            successful_trades = getattr(user, 'successful_trades_count', 0) or 0
            vip_tier = getattr(user, 'vip_tier', 0) or 0
            referral_code = getattr(user, 'referral_code', 'N/A') or 'N/A'
            referral_bonus = getattr(user, 'referral_bonus_earned', 0) or 0
            
            text = f"""
👤 <b>User Profile</b>

<b>Basic Info:</b>
├ ID: <code>{user.id}</code>
├ Telegram ID: <code>{user.telegram_id}</code>
├ Username: @{user.username or 'None'}
├ Name: {user.first_name or ''} {user.last_name or ''}
├ Language: {user.language_code or 'en'}
└ Status: {status_emoji.get(user.status, '⚪')} {user.status.value if hasattr(user.status, 'value') else user.status}

<b>Trading Stats:</b>
├ Rating: ⭐ {rating:.1f}/100
├ Total Volume: ${float(total_volume):,.2f}
├ Total Trades: {total_trades}
├ Successful: {successful_trades}
└ VIP Tier: {vip_tier}

<b>Wallets & Activity:</b>
├ Wallets: {wallet_count}
├ Transactions: {tx_count}
├ Verified Merchant: {'✅' if getattr(user, 'merchant_verified', False) else '❌'}
└ 2FA Enabled: {'✅' if getattr(user, 'two_factor_enabled', False) else '❌'}

<b>Timestamps:</b>
├ Registered: {user.created_at.strftime('%Y-%m-%d %H:%M') if user.created_at else 'N/A'}
└ Last Active: {user.last_active_at.strftime('%Y-%m-%d %H:%M') if getattr(user, 'last_active_at', None) else 'N/A'}

<b>Referral:</b>
├ Code: <code>{referral_code}</code>
└ Earnings: ${float(referral_bonus):,.2f}
"""
            
            is_banned = user.status == UserStatus.BANNED
            is_verified = getattr(user, 'merchant_verified', False)
            keyboard = get_user_action_keyboard(str(user.id), is_banned, is_verified)
            
            await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        
    except Exception as e:
        logger.error("User search error", error=str(e), exc_info=True)
        await message.answer(
            "❌ Search failed. Please try again.",
            reply_markup=get_back_keyboard("admin:users")
        )
    
    await state.clear()


@router.callback_query(F.data == "admin:users:recent")
async def admin_recent_users(callback: CallbackQuery, state: FSMContext):
    """Show recent users"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(User)
                .order_by(desc(User.created_at))
                .limit(15)
            )
            users = result.scalars().all()
        
        text = "👥 <b>Recent Users (Last 15)</b>\n\n"
        
        for i, user in enumerate(users, 1):
            status = "🟢" if user.status == UserStatus.ACTIVE else "🔴"
            verified = "✓" if getattr(user, 'merchant_verified', False) else ""
            created = user.created_at.strftime('%m/%d %H:%M') if user.created_at else 'N/A'
            text += (
                f"{i}. {status} <code>{user.telegram_id}</code> "
                f"@{user.username or 'N/A'} {verified}\n"
                f"   └ {created}\n"
            )
        
        await safe_edit(callback.message, text, get_back_keyboard("admin:users"))
        
    except Exception as e:
        logger.error("Recent users error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load recent users.",
            get_back_keyboard("admin:users")
        )
    
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:users:top")
async def admin_top_traders(callback: CallbackQuery, state: FSMContext):
    """Show top traders by volume"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(User)
                .where(User.total_volume_usd > 0)
                .order_by(desc(User.total_volume_usd))
                .limit(15)
            )
            users = result.scalars().all()
        
        text = "🏆 <b>Top Traders by Volume</b>\n\n"
        
        if not users:
            text += "<i>No traders found.</i>"
        else:
            medals = ["🥇", "🥈", "🥉"]
            for i, user in enumerate(users, 1):
                medal = medals[i-1] if i <= 3 else f"{i}."
                verified = "✓" if getattr(user, 'merchant_verified', False) else ""
                volume = getattr(user, 'total_volume_usd', 0) or 0
                trades = getattr(user, 'total_trades_count', 0) or 0
                text += (
                    f"{medal} @{user.username or user.telegram_id} {verified}\n"
                    f"   └ ${float(volume):,.2f} | {trades} trades\n"
                )
        
        await safe_edit(callback.message, text, get_back_keyboard("admin:users"))
        
    except Exception as e:
        logger.error("Top traders error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load top traders.",
            get_back_keyboard("admin:users")
        )
    
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:users:banned")
async def admin_banned_users(callback: CallbackQuery, state: FSMContext):
    """Show banned users"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(User)
                .where(User.status == UserStatus.BANNED)
                .order_by(desc(User.updated_at))
                .limit(20)
            )
            users = result.scalars().all()
        
        if not users:
            text = "🚫 <b>Banned Users</b>\n\nNo banned users found."
        else:
            text = "🚫 <b>Banned Users</b>\n\n"
            for user in users:
                updated = user.updated_at.strftime('%Y-%m-%d') if user.updated_at else 'N/A'
                text += (
                    f"🔴 <code>{user.telegram_id}</code> @{user.username or 'N/A'}\n"
                    f"   └ Banned: {updated}\n"
                )
        
        await safe_edit(callback.message, text, get_back_keyboard("admin:users"))
        
    except Exception as e:
        logger.error("Banned users error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load banned users.",
            get_back_keyboard("admin:users")
        )
    
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:users:verified")
async def admin_verified_users(callback: CallbackQuery, state: FSMContext):
    """Show verified merchants"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(User)
                .where(User.merchant_verified == True)
                .order_by(desc(User.total_volume_usd))
                .limit(20)
            )
            users = result.scalars().all()
        
        if not users:
            text = "✅ <b>Verified Merchants</b>\n\nNo verified merchants found."
        else:
            text = "✅ <b>Verified Merchants</b>\n\n"
            for user in users:
                volume = getattr(user, 'total_volume_usd', 0) or 0
                rating = getattr(user, 'rating', 0) or 0
                text += (
                    f"✅ <code>{user.telegram_id}</code> @{user.username or 'N/A'}\n"
                    f"   └ ${float(volume):,.0f} | ⭐ {rating:.1f}\n"
                )
        
        await safe_edit(callback.message, text, get_back_keyboard("admin:users"))
        
    except Exception as e:
        logger.error("Verified users error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load verified merchants.",
            get_back_keyboard("admin:users")
        )
    
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:users:flagged")
async def admin_flagged_users(callback: CallbackQuery, state: FSMContext):
    """Show flagged users"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    text = """
⚠️ <b>Flagged Users</b>

<i>No flagged users at the moment.</i>

Users can be flagged for:
• Suspicious activity
• Multiple failed trades
• Dispute patterns
• KYC issues
"""
    
    await safe_edit(callback.message, text, get_back_keyboard("admin:users"))
    await safe_answer_callback(callback)


# ==================== USER ACTIONS ====================

@router.callback_query(F.data.startswith("admin:user:ban:"))
async def admin_ban_user_start(callback: CallbackQuery, state: FSMContext):
    """Start ban user process"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    user_id = callback.data.split(":")[-1]
    await state.update_data(target_user_id=user_id)
    
    text = """
🚫 <b>Ban User</b>

Please enter the reason for banning this user:
"""
    
    await safe_edit(callback.message, text, get_cancel_keyboard("admin:users"))
    await state.set_state(AdminStates.ban_reason)
    await safe_answer_callback(callback)


@router.message(AdminStates.ban_reason)
async def admin_ban_user_process(message: Message, state: FSMContext, bot: Bot):
    """Process user ban"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    reason = message.text.strip()
    if len(reason) < 5:
        await message.answer(
            "❌ Reason is too short. Please provide more details.",
            reply_markup=get_cancel_keyboard("admin:users")
        )
        return
    
    data = await state.get_data()
    user_id = data.get("target_user_id")
    
    if not user_id:
        await message.answer("❌ Session expired. Please try again.")
        await state.clear()
        return
    
    try:
        async with db_manager.session() as session:
            user = await session.scalar(select(User).where(User.id == user_id))
            
            if not user:
                await message.answer("❌ User not found")
                await state.clear()
                return
            
            user.status = UserStatus.BANNED
            await session.commit()
            
            # Notify user
            await safe_send_message(
                bot,
                user.telegram_id,
                f"⛔ <b>Account Suspended</b>\n\n"
                f"Your NEXUS WALLET account has been suspended.\n"
                f"Reason: {reason}\n\n"
                f"If you believe this is an error, please contact support."
            )
            
            logger.info(
                "User banned",
                admin_id=message.from_user.id,
                user_id=user_id,
                reason=reason
            )
        
        await message.answer(
            f"✅ User {user.telegram_id} has been banned.\nReason: {reason}",
            reply_markup=get_back_keyboard("admin:users")
        )
        
    except Exception as e:
        logger.error("Ban user error", error=str(e), exc_info=True)
        await message.answer(
            "❌ Failed to ban user. Please try again.",
            reply_markup=get_back_keyboard("admin:users")
        )
    
    await state.clear()


@router.callback_query(F.data.startswith("admin:user:unban:"))
async def admin_unban_user(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Unban user"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    user_id = callback.data.split(":")[-1]
    
    try:
        async with db_manager.session() as session:
            user = await session.scalar(select(User).where(User.id == user_id))
            
            if not user:
                await safe_answer_callback(callback, "❌ User not found", show_alert=True)
                return
            
            user.status = UserStatus.ACTIVE
            await session.commit()
            
            # Notify user
            await safe_send_message(
                bot,
                user.telegram_id,
                "✅ <b>Account Restored</b>\n\n"
                "Your NEXUS WALLET account has been restored.\n"
                "You can now use all features again."
            )
            
            logger.info("User unbanned", admin_id=callback.from_user.id, user_id=user_id)
        
        await safe_answer_callback(callback, "✅ User unbanned successfully")
        await admin_users_menu(callback, state)
        
    except Exception as e:
        logger.error("Unban user error", error=str(e), exc_info=True)
        await safe_answer_callback(callback, "❌ Failed to unban user", show_alert=True)


@router.callback_query(F.data.startswith("admin:user:verify:"))
async def admin_verify_merchant(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Verify user as merchant"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    user_id = callback.data.split(":")[-1]
    
    try:
        async with db_manager.session() as session:
            user = await session.scalar(select(User).where(User.id == user_id))
            
            if not user:
                await safe_answer_callback(callback, "❌ User not found", show_alert=True)
                return
            
            user.merchant_verified = True
            await session.commit()
            
            # Notify user
            await safe_send_message(
                bot,
                user.telegram_id,
                "🎉 <b>Congratulations!</b>\n\n"
                "Your account has been verified as a <b>Trusted Merchant</b>!\n\n"
                "Benefits:\n"
                "├ ✅ Verified badge on your profile\n"
                "├ 📈 Higher visibility in P2P market\n"
                "└ 💰 Reduced trading fees"
            )
            
            logger.info("Merchant verified", admin_id=callback.from_user.id, user_id=user_id)
        
        await safe_answer_callback(callback, "✅ User verified as merchant")
        await admin_users_menu(callback, state)
        
    except Exception as e:
        logger.error("Verify merchant error", error=str(e), exc_info=True)
        await safe_answer_callback(callback, "❌ Failed to verify user", show_alert=True)


@router.callback_query(F.data.startswith("admin:user:unverify:"))
async def admin_unverify_merchant(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Revoke merchant verification"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    user_id = callback.data.split(":")[-1]
    
    try:
        async with db_manager.session() as session:
            user = await session.scalar(select(User).where(User.id == user_id))
            
            if not user:
                await safe_answer_callback(callback, "❌ User not found", show_alert=True)
                return
            
            user.merchant_verified = False
            await session.commit()
            
            # Notify user
            await safe_send_message(
                bot,
                user.telegram_id,
                "⚠️ <b>Verification Revoked</b>\n\n"
                "Your merchant verification has been revoked.\n"
                "Please contact support for more information."
            )
            
            logger.info("Verification revoked", admin_id=callback.from_user.id, user_id=user_id)
        
        await safe_answer_callback(callback, "✅ Verification revoked")
        await admin_users_menu(callback, state)
        
    except Exception as e:
        logger.error("Unverify merchant error", error=str(e), exc_info=True)
        await safe_answer_callback(callback, "❌ Failed to revoke verification", show_alert=True)


@router.callback_query(F.data.startswith("admin:user:msg:"))
async def admin_message_user_start(callback: CallbackQuery, state: FSMContext):
    """Start messaging a user"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    user_id = callback.data.split(":")[-1]
    await state.update_data(message_target_user_id=user_id)
    
    text = """
💬 <b>Send Message to User</b>

Enter the message you want to send:
<i>This message will be sent from the bot.</i>
"""
    
    await safe_edit(callback.message, text, get_cancel_keyboard("admin:users"))
    await state.set_state(AdminStates.message_user)
    await safe_answer_callback(callback)


@router.message(AdminStates.message_user)
async def admin_message_user_process(message: Message, state: FSMContext, bot: Bot):
    """Process and send message to user"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    data = await state.get_data()
    user_id = data.get("message_target_user_id")
    
    if not user_id:
        await message.answer("❌ Session expired. Please try again.")
        await state.clear()
        return
    
    text_to_send = message.text.strip()
    if len(text_to_send) < 1:
        await message.answer(
            "❌ Message is empty. Please enter a message.",
            reply_markup=get_cancel_keyboard("admin:users")
        )
        return
    
    try:
        async with db_manager.session() as session:
            user = await session.scalar(select(User).where(User.id == user_id))
            
            if not user:
                await message.answer("❌ User not found")
                await state.clear()
                return
            
            # Format message from admin
            admin_message = f"""
📬 <b>Message from Support</b>

{text_to_send}

<i>Reply to this message if you have questions.</i>
"""
            
            success = await safe_send_message(bot, user.telegram_id, admin_message)
            
            if success:
                await message.answer(
                    f"✅ Message sent successfully to user <code>{user.telegram_id}</code>",
                    reply_markup=get_back_keyboard("admin:users"),
                    parse_mode="HTML"
                )
                logger.info("Admin message sent", admin_id=message.from_user.id, user_id=user.telegram_id)
            else:
                await message.answer(
                    "❌ Failed to send message. User may have blocked the bot.",
                    reply_markup=get_back_keyboard("admin:users")
                )
                
    except Exception as e:
        logger.error("Message user error", error=str(e), exc_info=True)
        await message.answer(
            "❌ Failed to send message.",
            reply_markup=get_back_keyboard("admin:users")
        )
    
    await state.clear()


@router.callback_query(F.data.startswith("admin:user:wallets:"))
async def admin_view_user_wallets(callback: CallbackQuery, state: FSMContext):
    """View user's wallets"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    user_id = callback.data.split(":")[-1]
    
    await safe_answer_callback(callback, "💰 Loading wallets...")
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(Wallet).where(Wallet.user_id == user_id)
            )
            wallets = result.scalars().all()
            
            user = await session.scalar(select(User).where(User.id == user_id))
        
        if not user:
            await safe_edit(
                callback.message,
                "❌ User not found.",
                get_back_keyboard("admin:users")
            )
            return
        
        text = f"💰 <b>Wallets for User {user.telegram_id}</b>\n\n"
        
        if not wallets:
            text += "<i>No wallets found.</i>"
        else:
            for wallet in wallets:
                config = NETWORKS.get(wallet.network)
                icon = getattr(config, 'icon', '🔗') if config else '🔗'
                
                # Get balance (with timeout)
                try:
                    balance = await asyncio.wait_for(
                        wallet_manager.get_balance(wallet.network, wallet.address),
                        timeout=5.0
                    )
                    balance_str = f"{float(balance):.8f}".rstrip('0').rstrip('.')
                except Exception:
                    balance_str = "Error"
                
                text += (
                    f"{icon} <b>{wallet.network.upper()}</b>\n"
                    f"   <code>{wallet.address}</code>\n"
                    f"   Balance: {balance_str}\n\n"
                )
        
        await safe_edit(callback.message, text, get_back_keyboard("admin:users"))
        
    except Exception as e:
        logger.error("View wallets error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load wallets.",
            get_back_keyboard("admin:users")
        )


@router.callback_query(F.data.startswith("admin:user:txs:"))
async def admin_view_user_transactions(callback: CallbackQuery, state: FSMContext):
    """View user's recent transactions"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    user_id = callback.data.split(":")[-1]
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(Transaction)
                .where(Transaction.user_id == user_id)
                .order_by(desc(Transaction.created_at))
                .limit(15)
            )
            txs = result.scalars().all()
            
            user = await session.scalar(select(User).where(User.id == user_id))
        
        if not user:
            await safe_edit(
                callback.message,
                "❌ User not found.",
                get_back_keyboard("admin:users")
            )
            return
        
        text = f"📊 <b>Transactions for User {user.telegram_id}</b>\n\n"
        
        if not txs:
            text += "<i>No transactions found.</i>"
        else:
            status_emoji = {
                TransactionStatus.COMPLETED: "✅",
                TransactionStatus.PENDING: "⏳",
                TransactionStatus.FAILED: "❌",
                TransactionStatus.CANCELLED: "🚫"
            }
            
            for tx in txs:
                emoji = status_emoji.get(tx.status, "❓")
                tx_type = str(tx.tx_type.value if hasattr(tx.tx_type, 'value') else tx.tx_type)
                created = tx.created_at.strftime('%m/%d %H:%M') if tx.created_at else 'N/A'
                
                text += (
                    f"{emoji} <b>{tx_type}</b> | {float(tx.amount):.6f} {tx.token_symbol}\n"
                    f"   {tx.network} | {created}\n"
                )
        
        await safe_edit(callback.message, text, get_back_keyboard("admin:users"))
        
    except Exception as e:
        logger.error("View transactions error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load transactions.",
            get_back_keyboard("admin:users")
        )
    
    await safe_answer_callback(callback)


@router.callback_query(F.data.startswith("admin:user:p2p:"))
async def admin_view_user_p2p(callback: CallbackQuery, state: FSMContext):
    """View user's P2P history"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    user_id = callback.data.split(":")[-1]
    
    try:
        async with db_manager.session() as session:
            user = await session.scalar(select(User).where(User.id == user_id))
            
            if not user:
                await safe_edit(
                    callback.message,
                    "❌ User not found.",
                    get_back_keyboard("admin:users")
                )
                return
            
            # Get P2P trades as buyer and seller
            trades_result = await session.execute(
                select(P2PTrade)
                .where(or_(P2PTrade.buyer_id == user_id, P2PTrade.seller_id == user_id))
                .order_by(desc(P2PTrade.created_at))
                .limit(15)
            )
            trades = trades_result.scalars().all()
            
            # Get P2P orders
            orders_result = await session.execute(
                select(P2POrder)
                .where(P2POrder.user_id == user_id)
                .order_by(desc(P2POrder.created_at))
                .limit(10)
            )
            orders = orders_result.scalars().all()
        
        text = f"🤝 <b>P2P History for User {user.telegram_id}</b>\n\n"
        
        text += "<b>Recent Trades:</b>\n"
        if not trades:
            text += "<i>No trades found.</i>\n"
        else:
            for trade in trades[:10]:
                role = "Buyer" if trade.buyer_id == user_id else "Seller"
                status = str(trade.status.value if hasattr(trade.status, 'value') else trade.status)
                created = trade.created_at.strftime('%m/%d') if trade.created_at else 'N/A'
                text += f"├ {role}: ${float(trade.fiat_amount):,.0f} | {status} | {created}\n"
        
        text += "\n<b>Active Orders:</b>\n"
        if not orders:
            text += "<i>No orders found.</i>\n"
        else:
            for order in orders[:5]:
                order_type = str(order.order_type.value if hasattr(order.order_type, 'value') else order.order_type)
                status = str(order.status.value if hasattr(order.status, 'value') else order.status)
                text += f"├ {order_type}: {order.token_symbol} | {status}\n"
        
        await safe_edit(callback.message, text, get_back_keyboard("admin:users"))
        
    except Exception as e:
        logger.error("View P2P history error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load P2P history.",
            get_back_keyboard("admin:users")
        )
    
    await safe_answer_callback(callback)


# ==================== SYSTEM MANAGEMENT ====================

@router.callback_query(F.data == "admin:system")
async def admin_system_menu(callback: CallbackQuery, state: FSMContext):
    """System management menu"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    # Get system status
    try:
        from utils.config_manager import config_manager
        maintenance = await config_manager.get("maintenance_mode", False)
    except ImportError:
        maintenance = False
    
    status = "🔴 MAINTENANCE" if maintenance else "🟢 ONLINE"
    
    text = f"""
🔧 <b>System Management</b>

<b>Current Status:</b> {status}

<b>System Info:</b>
├ Python: {sys.version.split()[0]}
├ Platform: {sys.platform}
├ Uptime: Running
└ Memory: OK

Select an action:
"""
    
    await safe_edit(callback.message, text, get_admin_system_keyboard())
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:system:maintenance_on")
async def admin_maintenance_on(callback: CallbackQuery, state: FSMContext):
    """Enable maintenance mode"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    text = """
🔴 <b>Enable Maintenance Mode</b>

Enter the reason for maintenance (will be shown to users):
"""
    
    await safe_edit(callback.message, text, get_cancel_keyboard("admin:system"))
    await state.set_state(AdminStates.maintenance_reason)
    await safe_answer_callback(callback)


@router.message(AdminStates.maintenance_reason)
async def admin_maintenance_process(message: Message, state: FSMContext):
    """Process maintenance mode activation"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    reason = message.text.strip()
    
    try:
        from utils.config_manager import config_manager
        await config_manager.set("maintenance_mode", True)
        await config_manager.set("maintenance_reason", reason)
        
        logger.warning("Maintenance mode enabled", admin_id=message.from_user.id, reason=reason)
        
        await message.answer(
            f"🔴 <b>Maintenance Mode Enabled</b>\n\nReason: {reason}",
            reply_markup=get_back_keyboard("admin:system"),
            parse_mode="HTML"
        )
    except ImportError:
        await message.answer(
            "❌ Config manager not available.",
            reply_markup=get_back_keyboard("admin:system")
        )
    except Exception as e:
        logger.error("Maintenance mode error", error=str(e))
        await message.answer(
            "❌ Failed to enable maintenance mode.",
            reply_markup=get_back_keyboard("admin:system")
        )
    
    await state.clear()


@router.callback_query(F.data == "admin:system:maintenance_off")
async def admin_maintenance_off(callback: CallbackQuery, state: FSMContext):
    """Disable maintenance mode"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        from utils.config_manager import config_manager
        await config_manager.set("maintenance_mode", False)
        await config_manager.set("maintenance_reason", "")
        
        logger.info("Maintenance mode disabled", admin_id=callback.from_user.id)
        
        await safe_answer_callback(callback, "🟢 Maintenance mode disabled")
        await admin_system_menu(callback, state)
    except ImportError:
        await safe_answer_callback(callback, "❌ Config manager not available", show_alert=True)
    except Exception as e:
        logger.error("Maintenance off error", error=str(e))
        await safe_answer_callback(callback, "❌ Failed to disable maintenance", show_alert=True)


@router.callback_query(F.data == "admin:system:rpc")
async def admin_rpc_status(callback: CallbackQuery, state: FSMContext):
    """Check RPC node status"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    await safe_answer_callback(callback, "📡 Checking RPC nodes...")
    
    try:
        status = await wallet_manager.get_system_status()
        
        text = "📡 <b>RPC Node Status</b>\n\n"
        
        if not status:
            text += "<i>No network data available.</i>"
        else:
            for network, info in status.items():
                config = NETWORKS.get(network)
                icon = getattr(config, 'icon', '🔗') if config else '🔗'
                
                if info.get("online"):
                    status_emoji = "🟢"
                    height = info.get("height", "N/A")
                    text += f"{status_emoji} {icon} <b>{network}</b>: Block #{height}\n"
                else:
                    text += f"🔴 {icon} <b>{network}</b>: Offline\n"
        
        await safe_edit(callback.message, text, get_back_keyboard("admin:system"))
        
    except Exception as e:
        logger.error("RPC status error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to check RPC status.",
            get_back_keyboard("admin:system")
        )


@router.callback_query(F.data == "admin:system:db")
async def admin_db_status(callback: CallbackQuery, state: FSMContext):
    """Check database status"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            users = await session.scalar(select(func.count(User.id))) or 0
            wallets = await session.scalar(select(func.count(Wallet.id))) or 0
            transactions = await session.scalar(select(func.count(Transaction.id))) or 0
            p2p_orders = await session.scalar(select(func.count(P2POrder.id))) or 0
            p2p_trades = await session.scalar(select(func.count(P2PTrade.id))) or 0
        
        db_type = 'PostgreSQL' if 'postgresql' in str(db_manager.engine.url) else 'SQLite'
        
        text = f"""
💾 <b>Database Status</b>

<b>Connection:</b> 🟢 Connected

<b>Table Statistics:</b>
├ Users: {users:,}
├ Wallets: {wallets:,}
├ Transactions: {transactions:,}
├ P2P Orders: {p2p_orders:,}
└ P2P Trades: {p2p_trades:,}

<b>Database:</b>
└ Type: {db_type}
"""
        
        await safe_edit(callback.message, text, get_back_keyboard("admin:system"))
        
    except Exception as e:
        logger.error("DB status error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ 🔴 Database connection failed.",
            get_back_keyboard("admin:system")
        )
    
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:system:clear_cache")
async def admin_clear_cache(callback: CallbackQuery, state: FSMContext):
    """Clear system cache"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        # Clear price cache
        if hasattr(price_service, '_cache'):
            price_service._cache.clear()
        
        # Clear wallet manager cache
        if hasattr(wallet_manager, 'clear_cache'):
            wallet_manager.clear_cache()
        
        logger.info("Cache cleared", admin_id=callback.from_user.id)
        
        await safe_answer_callback(callback, "🧹 All caches cleared!")
        
    except Exception as e:
        logger.error("Clear cache error", error=str(e))
        await safe_answer_callback(callback, "❌ Failed to clear cache", show_alert=True)


@router.callback_query(F.data == "admin:system:restart")
async def admin_restart_confirm(callback: CallbackQuery, state: FSMContext):
    """Confirm bot restart"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    text = """
🔄 <b>Restart Bot</b>

⚠️ This will restart the bot process.
All active sessions will be interrupted.

Are you sure?
"""
    
    keyboard = get_confirm_keyboard("admin:system:restart_confirm", "admin:system")
    await safe_edit(callback.message, text, keyboard)
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:system:restart_confirm")
async def admin_restart_execute(callback: CallbackQuery):
    """Execute bot restart"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await callback.message.edit_text("🔄 Restarting bot...")
    
    logger.warning("Bot restart initiated", admin_id=callback.from_user.id)
    
    # This will cause the bot to restart if running with auto-restart
    await asyncio.sleep(1)
    os._exit(0)


# ==================== BROADCAST ====================

@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_menu(callback: CallbackQuery, state: FSMContext):
    """Start broadcast process"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            total_users = await session.scalar(
                select(func.count(User.id)).where(User.status == UserStatus.ACTIVE)
            ) or 0
        
        text = f"""
📢 <b>Broadcast Message</b>

This will send a message to all <b>{total_users:,}</b> active users.

Please enter your message (HTML formatting supported):

<i>Supported tags: &lt;b&gt;, &lt;i&gt;, &lt;code&gt;, &lt;a&gt;</i>
"""
        
        await safe_edit(callback.message, text, get_cancel_keyboard("admin:main"))
        await state.set_state(AdminStates.broadcast_message)
        
    except Exception as e:
        logger.error("Broadcast menu error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load broadcast menu.",
            get_back_keyboard()
        )
    
    await safe_answer_callback(callback)


@router.message(AdminStates.broadcast_message)
async def admin_broadcast_preview(message: Message, state: FSMContext):
    """Preview broadcast message"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    broadcast_text = message.text.strip()
    
    if len(broadcast_text) < 5:
        await message.answer(
            "❌ Message is too short. Please enter a longer message.",
            reply_markup=get_cancel_keyboard("admin:main")
        )
        return
    
    if len(broadcast_text) > 4000:
        await message.answer(
            "❌ Message is too long (max 4000 characters).",
            reply_markup=get_cancel_keyboard("admin:main")
        )
        return
    
    await state.update_data(broadcast_text=broadcast_text)
    
    try:
        async with db_manager.session() as session:
            total_users = await session.scalar(
                select(func.count(User.id)).where(User.status == UserStatus.ACTIVE)
            ) or 0
        
        text = f"""
📢 <b>Broadcast Preview</b>

<b>Recipients:</b> {total_users:,} users

<b>Message:</b>
━━━━━━━━━━━━━━━
{broadcast_text}
━━━━━━━━━━━━━━━

Send this message to all users?
"""
        
        keyboard = get_confirm_keyboard("admin:broadcast:send", "admin:main")
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        await state.set_state(AdminStates.broadcast_confirm)
        
    except Exception as e:
        logger.error("Broadcast preview error", error=str(e))
        await message.answer(
            "❌ Failed to preview message.",
            reply_markup=get_back_keyboard()
        )
        await state.clear()


@router.callback_query(AdminStates.broadcast_confirm, F.data == "admin:broadcast:send")
async def admin_broadcast_send(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Send broadcast to all users"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    data = await state.get_data()
    broadcast_text = data.get("broadcast_text")
    
    if not broadcast_text:
        await safe_answer_callback(callback, "❌ No message to send", show_alert=True)
        await state.clear()
        return
    
    await safe_edit(callback.message, "📤 <b>Sending broadcast...</b>\n\nThis may take a while...")
    await safe_answer_callback(callback)
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(User.telegram_id).where(User.status == UserStatus.ACTIVE)
            )
            user_ids = [row[0] for row in result.fetchall()]
        
        success = 0
        failed = 0
        blocked = 0
        
        for i, user_id in enumerate(user_ids):
            try:
                await bot.send_message(user_id, broadcast_text, parse_mode="HTML")
                success += 1
            except TelegramBadRequest as e:
                if "blocked" in str(e).lower() or "deactivated" in str(e).lower():
                    blocked += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
            
            # Rate limiting - 30 messages per second
            if (i + 1) % 30 == 0:
                await asyncio.sleep(1)
            
            # Progress update every 100 users
            if (i + 1) % 100 == 0:
                try:
                    await callback.message.edit_text(
                        f"📤 <b>Sending broadcast...</b>\n\n"
                        f"Progress: {i + 1}/{len(user_ids)}\n"
                        f"✅ Sent: {success}\n"
                        f"❌ Failed: {failed}\n"
                        f"🚫 Blocked: {blocked}",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
        
        logger.info(
            "Broadcast sent",
            admin_id=callback.from_user.id,
            success=success,
            failed=failed,
            blocked=blocked
        )
        
        await callback.message.edit_text(
            f"✅ <b>Broadcast Complete</b>\n\n"
            f"📊 <b>Results:</b>\n"
            f"├ ✅ Sent: {success:,}\n"
            f"├ ❌ Failed: {failed:,}\n"
            f"└ 🚫 Blocked: {blocked:,}\n\n"
            f"<i>Total: {len(user_ids):,} users</i>",
            reply_markup=get_back_keyboard("admin:main"),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error("Broadcast send error", error=str(e), exc_info=True)
        await callback.message.edit_text(
            "❌ <b>Broadcast Failed</b>\n\n"
            f"Error: {str(e)[:100]}",
            reply_markup=get_back_keyboard("admin:main"),
            parse_mode="HTML"
        )
    
    await state.clear()


# ==================== P2P MANAGEMENT ====================

@router.callback_query(F.data == "admin:p2p")
async def admin_p2p_menu(callback: CallbackQuery, state: FSMContext):
    """P2P management menu"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            from database.models import OrderStatus
            
            active_orders = await session.scalar(
                select(func.count(P2POrder.id)).where(P2POrder.status == OrderStatus.ACTIVE)
            ) or 0
            
            active_trades = await session.scalar(
                select(func.count(P2PTrade.id)).where(
                    P2PTrade.status.in_(["pending", "awaiting_payment", "paid"])
                )
            ) or 0
            
            disputes = await session.scalar(
                select(func.count(P2PTrade.id)).where(P2PTrade.status == "disputed")
            ) or 0
        
        dispute_warning = "⚠️" if disputes > 0 else ""
        
        text = f"""
🤝 <b>P2P Management</b>

<b>Current Status:</b>
├ Active Orders: {active_orders:,}
├ Active Trades: {active_trades:,}
└ {dispute_warning} Disputes: {disputes}

Select an action:
"""
        
        await safe_edit(callback.message, text, get_admin_p2p_keyboard())
        
    except Exception as e:
        logger.error("P2P menu error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load P2P data.",
            get_back_keyboard()
        )
    
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:p2p:disputes")
async def admin_p2p_disputes(callback: CallbackQuery, state: FSMContext):
    """Show active disputes"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(P2PTrade)
                .where(P2PTrade.status == "disputed")
                .order_by(desc(P2PTrade.created_at))
                .limit(20)
            )
            disputes = result.scalars().all()
        
        if not disputes:
            text = "⚠️ <b>Active Disputes</b>\n\n✅ No active disputes found. 🎉"
        else:
            text = f"⚠️ <b>Active Disputes ({len(disputes)})</b>\n\n"
            for trade in disputes:
                created = trade.created_at.strftime('%m/%d %H:%M') if trade.created_at else 'N/A'
                text += (
                    f"🔴 Trade <code>{trade.id[:8]}</code>\n"
                    f"   Amount: ${float(trade.fiat_amount):,.0f}\n"
                    f"   Created: {created}\n\n"
                )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Full P2P Panel", callback_data="adm_p2p:disputes")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin:p2p")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("P2P disputes error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load disputes.",
            get_back_keyboard("admin:p2p")
        )
    
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:p2p:active")
async def admin_p2p_active_trades(callback: CallbackQuery, state: FSMContext):
    """Show active trades"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(P2PTrade)
                .where(P2PTrade.status.in_(["pending", "awaiting_payment", "paid"]))
                .order_by(desc(P2PTrade.created_at))
                .limit(15)
            )
            trades = result.scalars().all()
        
        if not trades:
            text = "🔄 <b>Active Trades</b>\n\n✅ No active trades at the moment."
        else:
            text = f"🔄 <b>Active Trades ({len(trades)})</b>\n\n"
            
            status_emoji = {
                "pending": "⏳",
                "awaiting_payment": "💳",
                "paid": "📤"
            }
            
            for trade in trades:
                emoji = status_emoji.get(str(trade.status), "❓")
                created = trade.created_at.strftime('%m/%d %H:%M') if trade.created_at else 'N/A'
                text += (
                    f"{emoji} <code>{trade.id[:8]}</code>\n"
                    f"   ${float(trade.fiat_amount):,.0f} | {trade.status}\n"
                    f"   {created}\n\n"
                )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Full P2P Panel", callback_data="adm_p2p:active_trades")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin:p2p")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("P2P active trades error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load active trades.",
            get_back_keyboard("admin:p2p")
        )
    
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:p2p:orders")
async def admin_p2p_orders(callback: CallbackQuery, state: FSMContext):
    """Show P2P orders"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            from database.models import OrderStatus
            
            result = await session.execute(
                select(P2POrder)
                .order_by(desc(P2POrder.created_at))
                .limit(15)
            )
            orders = result.scalars().all()
            
            active_count = await session.scalar(
                select(func.count(P2POrder.id)).where(P2POrder.status == OrderStatus.ACTIVE)
            ) or 0
        
        text = f"📋 <b>P2P Orders</b>\n\n"
        text += f"Active orders: <b>{active_count}</b>\n\n"
        
        if not orders:
            text += "<i>No orders found.</i>"
        else:
            for order in orders:
                status_emoji = "🟢" if str(order.status) == "active" else "⚪"
                order_type = str(order.order_type.value if hasattr(order.order_type, 'value') else order.order_type)
                text += (
                    f"{status_emoji} {order_type.upper()} {order.token_symbol}\n"
                    f"   {float(order.price_per_unit):,.2f} {order.fiat_currency}\n"
                )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Full P2P Panel", callback_data="adm_p2p:orders")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin:p2p")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("P2P orders error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load orders.",
            get_back_keyboard("admin:p2p")
        )
    
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:p2p:merchants")
async def admin_p2p_merchants(callback: CallbackQuery, state: FSMContext):
    """Show top merchants"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(User)
                .where(User.merchant_verified == True)
                .order_by(desc(User.total_volume_usd))
                .limit(15)
            )
            merchants = result.scalars().all()
        
        text = "🏆 <b>Top Merchants</b>\n\n"
        
        if not merchants:
            text += "<i>No verified merchants found.</i>"
        else:
            medals = ["🥇", "🥈", "🥉"]
            for i, merchant in enumerate(merchants, 1):
                medal = medals[i-1] if i <= 3 else f"{i}."
                volume = getattr(merchant, 'total_volume_usd', 0) or 0
                rating = getattr(merchant, 'rating', 0) or 0
                text += (
                    f"{medal} @{merchant.username or merchant.telegram_id}\n"
                    f"   ${float(volume):,.0f} | ⭐ {rating:.1f}\n"
                )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Full P2P Panel", callback_data="adm_p2p:top_traders")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin:p2p")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("P2P merchants error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load merchants.",
            get_back_keyboard("admin:p2p")
        )
    
    await safe_answer_callback(callback)


# ==================== FINANCE ====================

@router.callback_query(F.data == "admin:finance")
async def admin_finance_menu(callback: CallbackQuery, state: FSMContext):
    """Finance management menu"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            # Get pending withdrawals count
            pending_wd = await session.scalar(
                select(func.count(Transaction.id)).where(
                    and_(
                        Transaction.status == TransactionStatus.PENDING,
                        Transaction.tx_type == TransactionType.WITHDRAWAL
                    )
                )
            ) or 0
            
            # Today's fees
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_fees = await session.scalar(
                select(func.sum(Transaction.fee_usd)).where(
                    and_(
                        Transaction.created_at >= today,
                        Transaction.status == TransactionStatus.COMPLETED
                    )
                )
            ) or Decimal("0")
        
        text = f"""
💰 <b>Financial Management</b>

<b>Quick Stats:</b>
├ Today's Fees: <b>${float(today_fees):,.2f}</b>
└ Pending Withdrawals: <b>{pending_wd}</b>

Manage hot wallets, reserves, and manual transactions.

Select an action:
"""
        
        await safe_edit(callback.message, text, get_admin_finance_keyboard())
        
    except Exception as e:
        logger.error("Finance menu error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load finance data.",
            get_back_keyboard()
        )
    
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:finance:fees")
async def admin_fee_revenue(callback: CallbackQuery, state: FSMContext):
    """Show fee revenue"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            # Total fees all time
            total_fees = await session.scalar(
                select(func.sum(Transaction.fee_usd)).where(
                    Transaction.status == TransactionStatus.COMPLETED
                )
            ) or Decimal("0")
            
            # Last 24h fees
            yesterday = datetime.utcnow() - timedelta(days=1)
            fees_24h = await session.scalar(
                select(func.sum(Transaction.fee_usd)).where(
                    and_(
                        Transaction.status == TransactionStatus.COMPLETED,
                        Transaction.created_at >= yesterday
                    )
                )
            ) or Decimal("0")
            
            # Last 7 days
            week_ago = datetime.utcnow() - timedelta(days=7)
            fees_7d = await session.scalar(
                select(func.sum(Transaction.fee_usd)).where(
                    and_(
                        Transaction.status == TransactionStatus.COMPLETED,
                        Transaction.created_at >= week_ago
                    )
                )
            ) or Decimal("0")
        
        text = f"""
💸 <b>Fee Revenue</b>

<b>Summary:</b>
├ All Time: <b>${float(total_fees):,.2f}</b>
├ Last 7 Days: <b>${float(fees_7d):,.2f}</b>
└ Last 24 Hours: <b>${float(fees_24h):,.2f}</b>

<i>Note: Fees are collected in native tokens and converted to USD at time of transaction.</i>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Full Finance Panel", callback_data="adm_fin:revenue")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin:finance")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("Fee revenue error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load fee data.",
            get_back_keyboard("admin:finance")
        )
    
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:finance:pending")
async def admin_pending_withdrawals(callback: CallbackQuery, state: FSMContext):
    """Show pending withdrawals"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
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
                .limit(15)
            )
            withdrawals = result.scalars().all()
        
        if not withdrawals:
            text = "📤 <b>Pending Withdrawals</b>\n\n✅ No pending withdrawals!"
        else:
            text = f"📤 <b>Pending Withdrawals ({len(withdrawals)})</b>\n\n"
            
            for wd in withdrawals:
                age_minutes = (datetime.utcnow() - wd.created_at).total_seconds() / 60 if wd.created_at else 0
                
                to_addr = wd.to_address or "Unknown"
                if len(to_addr) > 16:
                    to_addr = f"{to_addr[:8]}...{to_addr[-6:]}"
                
                text += (
                    f"⏳ <code>{wd.id[:8]}</code>\n"
                    f"   {float(wd.amount):.6f} {wd.token_symbol}\n"
                    f"   To: <code>{to_addr}</code>\n"
                    f"   Age: {age_minutes:.0f} min\n\n"
                )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Full Finance Panel", callback_data="adm_fin:pending_wd")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin:finance")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("Pending withdrawals error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load pending withdrawals.",
            get_back_keyboard("admin:finance")
        )
    
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:finance:hot")
async def admin_hot_wallets(callback: CallbackQuery, state: FSMContext):
    """Show hot wallet status"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    await safe_answer_callback(callback, "🏦 Loading wallets...")
    
    try:
        status = await wallet_manager.get_system_status()
        
        text = "🏦 <b>Hot Wallet Status</b>\n\n"
        
        if not status:
            text += "<i>No network data available.</i>"
        else:
            for network, info in status.items():
                config = NETWORKS.get(network)
                icon = getattr(config, 'icon', '🔗') if config else '🔗'
                
                if info.get("online"):
                    text += f"🟢 {icon} <b>{network}</b>: Online\n"
                else:
                    text += f"🔴 {icon} <b>{network}</b>: Offline\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Full Finance Panel", callback_data="adm_fin:hot_wallets")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin:finance")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("Hot wallets error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load wallet status.",
            get_back_keyboard("admin:finance")
        )


@router.callback_query(F.data == "admin:finance:reserves")
async def admin_reserves(callback: CallbackQuery, state: FSMContext):
    """Show reserves"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    text = """
📊 <b>Reserves</b>

<i>Reserve management is available in the full finance panel.</i>

This includes:
• Cold wallet balances
• Reserve requirements
• Liquidity pools
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Full Finance Panel", callback_data="adm_fin:menu")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin:finance")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:finance:credit")
async def admin_manual_credit(callback: CallbackQuery, state: FSMContext):
    """Manual credit - redirect to full finance panel"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    # Redirect to admin_test for adding balance
    text = """
➕ <b>Manual Credit</b>

Use the Test Mode panel for adding balances to users.

⚠️ This feature should be used with caution.
All manual transactions are logged.
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Add Balance (Test Mode)", callback_data="admin_test:add_balance")],
        [InlineKeyboardButton(text="⚙️ Full Finance Panel", callback_data="adm_fin:menu")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin:finance")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer_callback(callback)


@router.callback_query(F.data == "admin:finance:debit")
async def admin_manual_debit(callback: CallbackQuery, state: FSMContext):
    """Manual debit - redirect to full finance panel"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    text = """
➖ <b>Manual Debit</b>

Use the Test Mode panel for setting exact balances.

⚠️ This feature should be used with caution.
All manual transactions are logged.
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Set Balance (Test Mode)", callback_data="admin_test:set_balance")],
        [InlineKeyboardButton(text="⚙️ Full Finance Panel", callback_data="adm_fin:menu")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin:finance")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer_callback(callback)


# ==================== LOGS ====================

@router.callback_query(F.data == "admin:logs")
async def admin_logs_view(callback: CallbackQuery, state: FSMContext):
    """View system audit logs"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        from services.audit_service import audit_service
        
        async with db_manager.session() as session:
            logs = await audit_service.get_logs(session, limit=15)
        
        text = "📝 <b>System Audit Logs</b>\n\n"
        
        if not logs:
            text += "<i>No logs found.</i>"
        else:
            for log in logs:
                time_str = log.created_at.strftime('%m/%d %H:%M') if log.created_at else 'N/A'
                action = getattr(log, 'action', 'Unknown')
                
                # Safe truncate details
                details = str(getattr(log, 'details', ''))[:30]
                if len(str(getattr(log, 'details', ''))) > 30:
                    details += '...'
                
                text += f"• <code>{time_str}</code> {action}\n"
                if details:
                    text += f"  └ {details}\n"
        
    except ImportError:
        text = "📝 <b>System Audit Logs</b>\n\n<i>Audit service not available.</i>"
    except Exception as e:
        logger.error("Logs view error", error=str(e), exc_info=True)
        text = "📝 <b>System Audit Logs</b>\n\n❌ Failed to load logs."
    
    await safe_edit(callback.message, text, get_back_keyboard("admin:main"))
    await safe_answer_callback(callback)


# ==================== SETTINGS ====================

@router.callback_query(F.data == "admin:settings")
async def admin_settings_menu(callback: CallbackQuery, state: FSMContext):
    """Admin settings menu"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    text = """
⚙️ <b>System Settings</b>

Use the specialized menus for detailed settings.
Here you can access global system controls.

<b>Available Panels:</b>
├ 💰 Financial Settings - fees, limits
├ 🤝 P2P Settings - trading parameters
└ 🔧 System - maintenance, cache
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Financial Settings", callback_data="adm_fin:menu"),
            InlineKeyboardButton(text="🤝 P2P Settings", callback_data="adm_p2p:settings")
        ],
        [
            InlineKeyboardButton(text="🔴 Maintenance ON", callback_data="admin:system:maintenance_on"),
            InlineKeyboardButton(text="🟢 Maintenance OFF", callback_data="admin:system:maintenance_off")
        ],
        [
            InlineKeyboardButton(text="🧹 Clear Cache", callback_data="admin:system:clear_cache")
        ],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin:main")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer_callback(callback)

# ==================== DATABASE CLEANUP COMMANDS (SQLite compatible) ====================

@router.message(Command("show_duplicates"))
async def show_duplicates(message: Message):
    """Показать все дубликаты балансов"""
    if not is_admin(message.from_user.id):
        return
    
    async with db_manager.session() as session:
        result = await session.execute(text("""
            SELECT wallet_id, token_symbol, COUNT(*) as cnt, 
                   SUM(balance) as total_balance,
                   MAX(balance) as max_balance
            FROM wallet_balances 
            GROUP BY wallet_id, token_symbol 
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC
            LIMIT 30
        """))
        duplicates = result.fetchall()
        
        if not duplicates:
            await message.answer("✅ No duplicates found!")
            return
        
        text_msg = "📊 <b>Duplicates found:</b>\n\n"
        for row in duplicates:
            max_bal = float(row.max_balance) if row.max_balance else 0
            text_msg += f"• {row.token_symbol}: {row.cnt}x (max: {max_bal:.6f})\n"
        
        text_msg += f"\n<b>Total groups: {len(duplicates)}</b>"
        text_msg += "\n\nUse /cleanup_balances to preview"
        
        await message.answer(text_msg, parse_mode="HTML")


@router.message(Command("cleanup_balances"))
async def cleanup_balances(message: Message):
    """Превью удаления дубликатов (SQLite compatible)"""
    if not is_admin(message.from_user.id):
        return
    
    async with db_manager.session() as session:
        # SQLite-совместимый запрос для подсчета дубликатов
        count_result = await session.execute(text("""
            SELECT COUNT(*) as cnt FROM wallet_balances
            WHERE id NOT IN (
                SELECT id FROM (
                    SELECT id, wallet_id, token_symbol, balance,
                           ROW_NUMBER() OVER (
                               PARTITION BY wallet_id, token_symbol 
                               ORDER BY balance DESC, id DESC
                           ) as rn
                    FROM wallet_balances
                ) ranked
                WHERE rn = 1
            )
        """))
        total_count = count_result.scalar()
        
        if not total_count or total_count == 0:
            await message.answer("✅ No duplicates found!")
            return
        
        preview = f"🗑 <b>Found {total_count} duplicates to delete</b>\n\n"
        preview += "⚠️ Records with MAX balance will be KEPT!\n\n"
        preview += "✅ Send /confirm_cleanup to proceed\n"
        preview += "❌ Or ignore to cancel"
        
        await message.answer(preview, parse_mode="HTML")


@router.message(Command("confirm_cleanup"))
async def confirm_cleanup(message: Message):
    """Выполнить удаление дубликатов (SQLite compatible)"""
    if not is_admin(message.from_user.id):
        return
    
    await message.answer("⏳ Cleaning...")
    
    async with db_manager.session() as session:
        # SQLite-совместимый DELETE
        result = await session.execute(text("""
            DELETE FROM wallet_balances
            WHERE id NOT IN (
                SELECT id FROM (
                    SELECT id, wallet_id, token_symbol, balance,
                           ROW_NUMBER() OVER (
                               PARTITION BY wallet_id, token_symbol 
                               ORDER BY balance DESC, id DESC
                           ) as rn
                    FROM wallet_balances
                ) ranked
                WHERE rn = 1
            )
        """))
        
        deleted_count = result.rowcount
        await session.commit()
    
    await message.answer(f"✅ Deleted {deleted_count} duplicates!", parse_mode="HTML")


@router.message(Command("db_stats"))
async def db_stats(message: Message):
    """Статистика базы данных"""
    if not is_admin(message.from_user.id):
        return
    
    async with db_manager.session() as session:
        users = await session.execute(text("SELECT COUNT(*) FROM users"))
        wallets = await session.execute(text("SELECT COUNT(*) FROM wallets"))
        balances = await session.execute(text("SELECT COUNT(*) FROM wallet_balances"))
        
        networks = await session.execute(text("""
            SELECT network, COUNT(*) as cnt 
            FROM wallets GROUP BY network ORDER BY cnt DESC LIMIT 10
        """))
        networks_list = networks.fetchall()
    
    text_msg = "📊 <b>Database Stats</b>\n\n"
    text_msg += f"👤 Users: {users.scalar()}\n"
    text_msg += f"💼 Wallets: {wallets.scalar()}\n"
    text_msg += f"💰 Balances: {balances.scalar()}\n"
    text_msg += f"\n<b>By network:</b>\n"
    for row in networks_list:
        text_msg += f"• {row.network}: {row.cnt}\n"
    
    await message.answer(text_msg, parse_mode="HTML")

# ==================== BALANCE MANAGEMENT COMMANDS ====================

@router.message(Command("check_balances"))
async def check_real_balances(message: Message):
    """Проверить реальные балансы из блокчейна и сравнить с БД"""
    if not is_admin(message.from_user.id):
        return
    
    await message.answer("⏳ Checking blockchain balances...")
    
    from blockchain.wallet_manager import wallet_manager, NETWORKS
    from database.repositories.wallet_repository import WalletRepository
    from database.repositories.user_repository import UserRepository
    
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, message.from_user.id)
        if not user:
            await message.answer("User not found")
            return
        
        wallets = await WalletRepository().get_user_wallets(session, user.id)
        
        if not wallets:
            await message.answer("No wallets found")
            return
        
        report = "📊 <b>Balance Check Report</b>\n\n"
        discrepancies = []
        
        for wallet in wallets:
            config = NETWORKS.get(wallet.network)
            if not config:
                continue
            
            try:
                # Получаем реальный баланс из блокчейна
                real_balance = await wallet_manager.get_balance(wallet.network, wallet.address)
                
                # Получаем баланс из БД
                result = await session.execute(text("""
                    SELECT token_symbol, balance FROM wallet_balances 
                    WHERE wallet_id = :wallet_id
                """), {"wallet_id": wallet.id})
                db_balances = result.fetchall()
                
                db_native_balance = 0
                for db_bal in db_balances:
                    if db_bal.token_symbol == config.symbol:
                        db_native_balance = float(db_bal.balance or 0)
                
                real_float = float(real_balance)
                
                # Проверяем расхождение
                diff = abs(real_float - db_native_balance)
                status = "✅" if diff < 0.000001 else "⚠️"
                
                if diff >= 0.000001:
                    discrepancies.append({
                        "network": wallet.network,
                        "symbol": config.symbol,
                        "wallet_id": wallet.id,
                        "db": db_native_balance,
                        "real": real_float
                    })
                
                report += f"{status} {config.icon} <b>{config.symbol}</b>\n"
                report += f"   DB: {db_native_balance:.6f}\n"
                report += f"   Real: {real_float:.6f}\n\n"
                
            except Exception as e:
                report += f"❌ {config.icon} <b>{config.symbol}</b>: {str(e)[:30]}\n\n"
        
        if discrepancies:
            report += f"━━━━━━━━━━━━━━━━━━\n"
            report += f"⚠️ <b>Found {len(discrepancies)} discrepancies!</b>\n"
            report += f"Use /sync_balances to fix"
        else:
            report += f"━━━━━━━━━━━━━━━━━━\n"
            report += f"✅ <b>All balances match!</b>"
        
        # Разбиваем если слишком длинный
        if len(report) > 4000:
            report = report[:4000] + "...\n\n(truncated)"
        
        await message.answer(report, parse_mode="HTML")


@router.message(Command("sync_balances"))
async def sync_real_balances(message: Message):
    """Синхронизировать балансы из блокчейна в БД"""
    if not is_admin(message.from_user.id):
        return
    
    await message.answer("⏳ Syncing balances from blockchain...")
    
    from blockchain.wallet_manager import wallet_manager, NETWORKS
    from database.repositories.wallet_repository import WalletRepository
    from database.repositories.user_repository import UserRepository
    from database.models import WalletBalance
    from decimal import Decimal
    import uuid
    
    updated = 0
    errors = 0
    
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, message.from_user.id)
        if not user:
            await message.answer("User not found")
            return
        
        wallets = await WalletRepository().get_user_wallets(session, user.id)
        
        for wallet in wallets:
            config = NETWORKS.get(wallet.network)
            if not config:
                continue
            
            try:
                # Получаем реальный баланс
                real_balance = await wallet_manager.get_balance(wallet.network, wallet.address)
                
                # Обновляем в БД
                result = await session.execute(text("""
                    SELECT id, balance FROM wallet_balances 
                    WHERE wallet_id = :wallet_id AND token_symbol = :symbol
                """), {"wallet_id": wallet.id, "symbol": config.symbol})
                existing = result.fetchone()
                
                if existing:
                    await session.execute(text("""
                        UPDATE wallet_balances 
                        SET balance = :balance, locked = 0
                        WHERE id = :id
                    """), {"balance": str(real_balance), "id": existing.id})
                else:
                    # Создаём новую запись
                    new_balance = WalletBalance(
                        id=str(uuid.uuid4()),
                        wallet_id=wallet.id,
                        token_symbol=config.symbol,
                        token_name=config.name,
                        token_decimals=config.decimals,
                        balance=Decimal(str(real_balance)),
                        locked=Decimal("0")
                    )
                    session.add(new_balance)
                
                updated += 1
                
            except Exception as e:
                logger.error("Sync failed", network=wallet.network, error=str(e))
                errors += 1
        
        await session.commit()
    
    await message.answer(
        f"✅ <b>Sync Complete!</b>\n\n"
        f"✅ Updated: {updated}\n"
        f"❌ Errors: {errors}",
        parse_mode="HTML"
    )


@router.message(Command("reset_balances"))
async def reset_all_balances(message: Message):
    """Сбросить все балансы в 0 (ОПАСНО!)"""
    if not is_admin(message.from_user.id):
        return
    
    await message.answer(
        "⚠️ <b>WARNING!</b>\n\n"
        "This will reset ALL balances to 0!\n\n"
        "Send /confirm_reset to proceed",
        parse_mode="HTML"
    )


@router.message(Command("confirm_reset"))
async def confirm_reset_balances(message: Message):
    """Подтвердить сброс балансов"""
    if not is_admin(message.from_user.id):
        return
    
    async with db_manager.session() as session:
        result = await session.execute(text("""
            UPDATE wallet_balances SET balance = 0, locked = 0
        """))
        await session.commit()
        
        count = result.rowcount
    
    await message.answer(f"✅ Reset {count} balance records to 0", parse_mode="HTML")


@router.message(Command("set_balance"))
async def set_balance_cmd(message: Message):
    """Установить баланс вручную. Формат: /set_balance network symbol amount"""
    if not is_admin(message.from_user.id):
        return
    
    parts = message.text.split()
    if len(parts) != 4:
        await message.answer(
            "Usage: /set_balance <network> <symbol> <amount>\n"
            "Example: /set_balance ethereum ETH 1.5",
            parse_mode="HTML"
        )
        return
    
    _, network, symbol, amount_str = parts
    
    try:
        amount = Decimal(amount_str)
    except:
        await message.answer("❌ Invalid amount")
        return
    
    from database.repositories.wallet_repository import WalletRepository
    from database.repositories.user_repository import UserRepository
    
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, message.from_user.id)
        wallet = await WalletRepository().get_user_wallet_by_network(session, user.id, network.lower())
        
        if not wallet:
            await message.answer(f"❌ No wallet for {network}")
            return
        
        result = await session.execute(text("""
            UPDATE wallet_balances 
            SET balance = :amount
            WHERE wallet_id = :wallet_id AND token_symbol = :symbol
        """), {"amount": str(amount), "wallet_id": wallet.id, "symbol": symbol.upper()})
        
        if result.rowcount == 0:
            await message.answer(f"❌ Balance record not found for {symbol}")
            return
        
        await session.commit()
    
    await message.answer(f"✅ Set {network} {symbol} balance to {amount}")


@router.message(Command("clear_fake_balances"))
async def clear_fake_balances(message: Message):
    """Очистить фейковые балансы - установить реальные из блокчейна"""
    if not is_admin(message.from_user.id):
        return
    
    # То же самое что sync_balances
    await sync_real_balances(message)

# ==================== DATABASE STATS ====================

@router.message(Command("db_stats"))
async def db_stats(message: Message):
    """Статистика базы данных"""
    if not is_admin(message.from_user.id):
        return
    
    async with db_manager.session() as session:
        users = await session.execute(text("SELECT COUNT(*) FROM users"))
        wallets = await session.execute(text("SELECT COUNT(*) FROM wallets"))
        balances = await session.execute(text("SELECT COUNT(*) FROM wallet_balances"))
        
        networks = await session.execute(text("""
            SELECT network, COUNT(*) as cnt 
            FROM wallets GROUP BY network ORDER BY cnt DESC LIMIT 10
        """))
    
    text_msg = "📊 <b>Database Stats</b>\n\n"
    text_msg += f"👤 Users: {users.scalar()}\n"
    text_msg += f"💼 Wallets: {wallets.scalar()}\n"
    text_msg += f"💰 Balances: {balances.scalar()}\n"
    
    await message.answer(text_msg, parse_mode="HTML")

# ==================== REDIRECT HANDLERS (ИСПРАВЛЕННЫЕ) ====================

@router.callback_query(F.data == "adm_fin:menu")
async def admin_finance_redirect(callback: CallbackQuery, state: FSMContext):
    """Redirect to finance panel - FIXED"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    # Импортируем и вызываем напрямую функцию из admin_finance
    try:
        from handlers.admin_finance import _show_finance_menu
        await _show_finance_menu(callback, state)
    except ImportError:
        # Fallback - показываем базовое меню
        await safe_answer_callback(callback, "Loading finance panel...")
        
        text = """
💰 <b>Financial Management</b>

<i>Loading full finance panel...</i>
"""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="💰 Revenue Overview", callback_data="adm_fin:revenue"),
                InlineKeyboardButton(text="📊 Transaction Stats", callback_data="adm_fin:tx_stats")
            ],
            [
                InlineKeyboardButton(text="💳 Purchase Settings", callback_data="adm_fin:purchase_settings"),
                InlineKeyboardButton(text="🤝 P2P Settings", callback_data="adm_fin:p2p_settings")
            ],
            [
                InlineKeyboardButton(text="🏦 Hot Wallets", callback_data="adm_fin:hot_wallets"),
                InlineKeyboardButton(text="📤 Pending Withdrawals", callback_data="adm_fin:pending_wd")
            ],
            [InlineKeyboardButton(text="🔙 Admin Menu", callback_data="admin:main")]
        ])
        
        await safe_edit(callback.message, text, keyboard)


@router.callback_query(F.data == "adm_p2p:menu")
async def admin_p2p_redirect(callback: CallbackQuery, state: FSMContext):
    """Redirect to P2P panel - FIXED"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    # Импортируем и вызываем напрямую
    try:
        from handlers.admin_p2p import _show_admin_p2p_menu
        await _show_admin_p2p_menu(callback, state)
    except ImportError:
        # Fallback
        await safe_answer_callback(callback, "Loading P2P panel...")
        
        text = """
🤝 <b>P2P Administration</b>

<i>Loading full P2P panel...</i>
"""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="⚠️ Disputes", callback_data="adm_p2p:disputes"),
                InlineKeyboardButton(text="🔄 Active Trades", callback_data="adm_p2p:active_trades")
            ],
            [
                InlineKeyboardButton(text="📋 All Orders", callback_data="adm_p2p:orders"),
                InlineKeyboardButton(text="🏆 Top Traders", callback_data="adm_p2p:top_traders")
            ],
            [
                InlineKeyboardButton(text="⚙️ P2P Settings", callback_data="adm_p2p:settings"),
                InlineKeyboardButton(text="📊 P2P Stats", callback_data="adm_p2p:stats")
            ],
            [InlineKeyboardButton(text="🔙 Admin Menu", callback_data="admin:main")]
        ])
        
        await safe_edit(callback.message, text, keyboard)


# ==================== FALLBACK HANDLER ====================

@router.callback_query(F.data.startswith("admin:"))
async def admin_fallback(callback: CallbackQuery, state: FSMContext):
    """Fallback for unhandled admin callbacks"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    logger.warning("Unhandled admin callback", data=callback.data, user_id=callback.from_user.id)
    
    # Return to main admin menu
    await admin_main_callback(callback, state)


# ==================== FORWARD HANDLERS FOR SUB-ROUTERS ====================

@router.callback_query(F.data.startswith("admin_test:"))
async def admin_test_forward(callback: CallbackQuery, state: FSMContext):
    """Forward to admin_test handlers"""
    if not is_admin(callback.from_user.id):
        await safe_answer_callback(callback, "⛔ Access denied", show_alert=True)
        return
    
    # These callbacks will be handled by admin_test router
    # This is a fallback in case the router isn't registered
    try:
        from handlers.admin_test import admin_test_menu
        await admin_test_menu(callback, state)
    except ImportError:
        await safe_answer_callback(callback, "❌ Test module not available", show_alert=True)
        await admin_main_callback(callback, state)
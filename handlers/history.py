"""
NEXUS WALLET - Transaction History Handler
Real transaction history from database
"""

from datetime import datetime, timedelta
from decimal import Decimal
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
import structlog

from database.connection import db_manager
from database.repositories.user_repository import UserRepository
from database.models import Transaction
from blockchain.wallet_manager import NETWORKS
from services.transaction_service import transaction_service
from locales.messages import get_text
from keyboards.inline import get_back_keyboard

logger = structlog.get_logger()
router = Router(name="history")

# Transaction type icons
TX_ICONS = {
    "deposit": "📥",
    "withdrawal": "📤",
    "send": "📤",
    "receive": "📥",
    "swap": "💱",
    "p2p_buy": "💰",
    "p2p_sell": "💸",
    "escrow_lock": "🔒",
    "escrow_release": "🔓",
}

# Status display
STATUS_TEXT = {
    "pending": "⏳ Pending",
    "confirming": "🔄 Confirming",
    "completed": "✅ Completed",
    "failed": "❌ Failed",
    "cancelled": "🚫 Cancelled",
}


def format_date(dt: datetime) -> str:
    """Format datetime nicely"""
    if not dt:
        return "Unknown"
    
    now = datetime.utcnow()
    diff = now - dt
    
    if diff.days == 0:
        if diff.seconds < 60:
            return "just now"
        elif diff.seconds < 3600:
            mins = diff.seconds // 60
            return f"{mins}m ago"
        else:
            hours = diff.seconds // 3600
            return f"{hours}h ago"
    elif diff.days == 1:
        return "yesterday"
    elif diff.days < 7:
        return f"{diff.days}d ago"
    else:
        return dt.strftime("%d %b %Y")


def format_address(address: str, length: int = 6) -> str:
    """Format address for display"""
    if not address:
        return "Unknown"
    if len(address) <= length * 2:
        return address
    return f"{address[:length]}...{address[-4:]}"


def format_transaction(tx: Transaction, lang: str) -> str:
    """Format single transaction for display"""
    icon = TX_ICONS.get(tx.tx_type, "📄")
    status = STATUS_TEXT.get(tx.status, tx.status)
    
    # Type text
    type_text = tx.tx_type.replace("_", " ").title()
    if tx.tx_type == "send":
        type_text = f"Sent to {format_address(tx.to_address)}"
    elif tx.tx_type == "receive":
        type_text = f"From {format_address(tx.from_address)}"
    elif tx.tx_type == "swap":
        if tx.swap_to_token:
            type_text = f"Swap → {tx.swap_to_token}"
        else:
            type_text = "Swap"
    elif tx.tx_type == "p2p_buy":
        type_text = "P2P Buy"
    elif tx.tx_type == "p2p_sell":
        type_text = "P2P Sell"
    
    # Amount formatting
    amount = tx.amount or Decimal("0")
    symbol = tx.token_symbol or "?"
    
    if tx.tx_type in ["send", "withdrawal", "p2p_sell", "escrow_lock"]:
        amount_str = f"-{amount:.6f}".rstrip('0').rstrip('.') + f" {symbol}"
    elif tx.tx_type in ["receive", "deposit", "p2p_buy", "escrow_release"]:
        amount_str = f"+{amount:.6f}".rstrip('0').rstrip('.') + f" {symbol}"
    elif tx.tx_type == "swap" and tx.swap_to_amount:
        amount_str = f"{amount:.4f}".rstrip('0').rstrip('.') + f" {symbol} → {tx.swap_to_amount:.4f}".rstrip('0').rstrip('.') + f" {tx.swap_to_token}"
    else:
        amount_str = f"{amount:.6f}".rstrip('0').rstrip('.') + f" {symbol}"
    
    # USD value
    usd = tx.amount_usd or Decimal("0")
    usd_str = f" (${usd:,.2f})" if usd > 0 else ""
    
    # Time
    time_str = format_date(tx.created_at)
    
    # Network icon
    network = NETWORKS.get(tx.network)
    net_icon = network.icon if network else "🔗"
    
    # Format line
    line = f"{icon} <b>{amount_str}</b>{usd_str}\n"
    line += f"   {net_icon} {type_text}\n"
    line += f"   {status} • {time_str}"
    
    return line


@router.callback_query(F.data == "history")
async def show_history(callback: CallbackQuery, state: FSMContext):
    """Show transaction history"""
    await state.clear()
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
        
        # Get real transactions from database
        transactions = await transaction_service.get_user_transactions(
            session, user.id, limit=20
        )
        
        if not transactions:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="💼 " + get_text("btn_wallet", lang),
                    callback_data="wallet"
                )],
                [InlineKeyboardButton(
                    text=get_text("btn_back", lang),
                    callback_data="main_menu"
                )]
            ])
            
            try:
                await callback.message.edit_text(
                    get_text("history_empty", lang),
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except Exception:
                pass
            await callback.answer()
            return
        
        text = get_text("history_title", lang) + "\n\n"
        
        # Group by date
        today = []
        yesterday = []
        older = []
        
        now = datetime.utcnow()
        for tx in transactions:
            if not tx.created_at:
                older.append(tx)
                continue
                
            diff = now - tx.created_at
            
            if diff.days == 0:
                today.append(tx)
            elif diff.days == 1:
                yesterday.append(tx)
            else:
                older.append(tx)
        
        # Format transactions
        if today:
            text += "📅 <b>Today</b>\n"
            for tx in today[:5]:
                text += format_transaction(tx, lang) + "\n\n"
        
        if yesterday:
            text += "📅 <b>Yesterday</b>\n"
            for tx in yesterday[:5]:
                text += format_transaction(tx, lang) + "\n\n"
        
        if older:
            text += "📅 <b>Earlier</b>\n"
            for tx in older[:5]:
                text += format_transaction(tx, lang) + "\n\n"
        
        # Create filter buttons
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 All", callback_data="history:filter:all"),
                InlineKeyboardButton(text="📤 Sent", callback_data="history:filter:send"),
                InlineKeyboardButton(text="📥 Received", callback_data="history:filter:receive"),
            ],
            [
                InlineKeyboardButton(text="💱 Swaps", callback_data="history:filter:swap"),
                InlineKeyboardButton(text="🤝 P2P", callback_data="history:filter:p2p"),
            ],
            [
                InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="main_menu")
            ]
        ])
        
        try:
            await callback.message.edit_text(
                text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception:
            pass
    
    await callback.answer()


@router.callback_query(F.data.startswith("history:filter:"))
async def filter_history(callback: CallbackQuery):
    """Filter transaction history"""
    filter_type = callback.data.split(":")[2]
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
        
        # Get filtered transactions
        tx_type = None if filter_type == "all" else filter_type
        
        transactions = await transaction_service.get_user_transactions(
            session, user.id, tx_type=tx_type, limit=20
        )
        
        # Title based on filter
        titles = {
            "all": get_text("history_title", lang),
            "send": "📤 <b>Sent Transactions</b>",
            "receive": "📥 <b>Received Transactions</b>",
            "swap": "💱 <b>Swap History</b>",
            "p2p": "🤝 <b>P2P History</b>",
        }
        title = titles.get(filter_type, get_text("history_title", lang))
        
        if not transactions:
            text = title + "\n\n📭 No transactions found."
        else:
            text = title + "\n\n"
            for tx in transactions[:15]:
                text += format_transaction(tx, lang) + "\n\n"
        
        # Keep the same keyboard with active filter highlighted
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="• All •" if filter_type == "all" else "🔄 All",
                    callback_data="history:filter:all"
                ),
                InlineKeyboardButton(
                    text="• Sent •" if filter_type == "send" else "📤 Sent",
                    callback_data="history:filter:send"
                ),
                InlineKeyboardButton(
                    text="• Received •" if filter_type == "receive" else "📥 Received",
                    callback_data="history:filter:receive"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="• Swaps •" if filter_type == "swap" else "💱 Swaps",
                    callback_data="history:filter:swap"
                ),
                InlineKeyboardButton(
                    text="• P2P •" if filter_type == "p2p" else "🤝 P2P",
                    callback_data="history:filter:p2p"
                ),
            ],
            [
                InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="main_menu")
            ]
        ])
        
        try:
            await callback.message.edit_text(
                text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception:
            pass
    
    await callback.answer()


@router.callback_query(F.data.startswith("tx:"))
async def show_transaction_details(callback: CallbackQuery):
    """Show detailed transaction info"""
    tx_id = callback.data.split(":")[1]
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
        
        # Get transaction
        tx = await transaction_service.get_transaction(session, tx_id)
        
        if not tx or tx.user_id != user.id:
            await callback.answer("Transaction not found", show_alert=True)
            return
        
        network = NETWORKS.get(tx.network)
        
        text = "📄 <b>Transaction Details</b>\n\n"
        
        # Status
        text += f"Status: {STATUS_TEXT.get(tx.status, tx.status)}\n"
        
        # Type & Amount
        icon = TX_ICONS.get(tx.tx_type, "📄")
        text += f"Type: {icon} {tx.tx_type.replace('_', ' ').title()}\n"
        text += f"Amount: <b>{tx.amount:.8f} {tx.token_symbol}</b>\n"
        
        if tx.amount_usd:
            text += f"Value: ${tx.amount_usd:,.2f}\n"
        
        # Swap details
        if tx.tx_type == "swap" and tx.swap_to_token:
            text += f"Received: <b>{tx.swap_to_amount:.8f} {tx.swap_to_token}</b>\n"
        
        # Network
        if network:
            text += f"Network: {network.icon} {network.name}\n"
        
        # Addresses
        if tx.from_address:
            text += f"\nFrom: <code>{tx.from_address}</code>\n"
        if tx.to_address:
            text += f"To: <code>{tx.to_address}</code>\n"
        
        # Transaction hash
        if tx.tx_hash:
            text += f"\nTx Hash:\n<code>{tx.tx_hash}</code>\n"
        
        # Block info
        if tx.block_number:
            text += f"Block: {tx.block_number}\n"
        if tx.confirmations:
            text += f"Confirmations: {tx.confirmations}\n"
        
        # Fees
        if tx.fee_amount:
            text += f"\nFee: {tx.fee_amount:.8f} {tx.fee_token or ''}"
            if tx.fee_usd:
                text += f" (${tx.fee_usd:.2f})"
            text += "\n"
        
        # Times
        text += f"\nCreated: {tx.created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        if tx.confirmed_at:
            text += f"Confirmed: {tx.confirmed_at.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        
        # Error
        if tx.error_message:
            text += f"\n⚠️ Error: {tx.error_message}\n"
        
        # Explorer link
        buttons = []
        if tx.tx_hash and network:
            explorer_url = f"{network.explorer_url}/tx/{tx.tx_hash}"
            buttons.append([InlineKeyboardButton(
                text="🔗 View on Explorer",
                url=explorer_url
            )])
        
        buttons.append([InlineKeyboardButton(
            text=get_text("btn_back", lang),
            callback_data="history"
        )])
        
        try:
            await callback.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode="HTML"
            )
        except Exception:
            pass
    
    await callback.answer()
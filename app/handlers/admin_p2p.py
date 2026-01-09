"""
NEXUS WALLET - Admin P2P Panel (FIXED)
Complete P2P management functionality
"""

from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import structlog

from sqlalchemy import select, func, desc, and_, or_, update
from database.connection import db_manager
from database.models import (
    User, P2POrder, P2PTrade, Wallet, WalletBalance,
    UserStatus, TransactionStatus
)
from config.settings import settings
from blockchain.wallet_manager import NETWORKS

logger = structlog.get_logger(__name__)
router = Router(name="admin_p2p")

# Pagination
ITEMS_PER_PAGE = 10


# ==================== TRY IMPORT ENUMS ====================

try:
    from database.models import OrderStatus, TradeStatus, DisputeStatus, Dispute
    HAS_DISPUTE_MODEL = True
except ImportError:
    HAS_DISPUTE_MODEL = False
    # Fallback enums
    class OrderStatus:
        ACTIVE = "active"
        FILLED = "filled"
        CANCELLED = "cancelled"
        PAUSED = "paused"
    
    class TradeStatus:
        PENDING = "pending"
        AWAITING_PAYMENT = "awaiting_payment"
        PAYMENT_SENT = "paid"
        COMPLETED = "completed"
        CANCELLED = "cancelled"
        DISPUTED = "disputed"
        REFUNDED = "refunded"
    
    class DisputeStatus:
        OPEN = "open"
        UNDER_REVIEW = "under_review"
        RESOLVED_BUYER = "resolved_buyer"
        RESOLVED_SELLER = "resolved_seller"


# ==================== P2P SETTINGS ====================

class P2PSettings:
    """P2P settings storage"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_defaults()
        return cls._instance
    
    def _init_defaults(self):
        self.platform_fee_percent = Decimal("0.5")
        self.min_order_usd = 10
        self.max_order_usd = 50000
        self.escrow_timeout_minutes = 30
        self.trade_timeout_minutes = 60
        self.supported_cryptos = ["TON", "ETH", "BNB", "USDT"]
        self.supported_fiats = ["USD", "EUR", "RUB", "UAH"]


p2p_settings = P2PSettings()


# ==================== ADMIN CHECK ====================

def is_admin(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS


# ==================== FSM STATES ====================

class AdminP2PStates(StatesGroup):
    # Dispute
    resolve_dispute = State()
    dispute_message = State()
    
    # Settings
    set_fee = State()
    set_min_trade = State()
    set_max_trade = State()
    set_escrow_timeout = State()
    set_trade_timeout = State()
    
    # Messaging
    message_user_text = State()


# ==================== UTILITY FUNCTIONS ====================

async def safe_edit(message: Message, text: str, keyboard: InlineKeyboardMarkup = None) -> bool:
    try:
        if message.photo or message.document or message.video:
            try:
                await message.delete()
            except:
                pass
            await message.bot.send_message(
                chat_id=message.chat.id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return True
        
        await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
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
            except:
                pass
        return False
    except:
        return False


async def safe_answer(callback: CallbackQuery, text: str = None, show_alert: bool = False):
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except:
        pass


async def safe_send(bot: Bot, user_id: int, text: str, **kwargs) -> bool:
    try:
        await bot.send_message(user_id, text, parse_mode="HTML", **kwargs)
        return True
    except:
        return False


def get_back_keyboard(callback_data: str = "adm_p2p:menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data=callback_data)]
    ])


def get_cancel_keyboard(callback_data: str = "adm_p2p:menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data=callback_data)]
    ])


def format_timedelta(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}s"
    elif total_seconds < 3600:
        return f"{total_seconds // 60}m"
    elif total_seconds < 86400:
        hours = total_seconds // 3600
        mins = (total_seconds % 3600) // 60
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    else:
        days = total_seconds // 86400
        return f"{days}d"


# ==================== KEYBOARDS ====================

def get_admin_p2p_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ Disputes", callback_data="adm_p2p:disputes"),
            InlineKeyboardButton(text="🔄 Active Trades", callback_data="adm_p2p:active_trades")
        ],
        [
            InlineKeyboardButton(text="📋 Orders", callback_data="adm_p2p:orders"),
            InlineKeyboardButton(text="🏆 Top Traders", callback_data="adm_p2p:top_traders")
        ],
        [
            InlineKeyboardButton(text="⚙️ Settings", callback_data="adm_p2p:settings"),
            InlineKeyboardButton(text="📊 Stats", callback_data="adm_p2p:stats")
        ],
        [InlineKeyboardButton(text="🔙 Admin Menu", callback_data="admin:main")]
    ])


# ==================== MAIN MENU ====================

@router.callback_query(F.data == "adm_p2p:menu")
async def admin_p2p_menu(callback: CallbackQuery, state: FSMContext):
    """P2P admin main menu"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            # Active orders
            try:
                active_orders = await session.scalar(
                    select(func.count(P2POrder.id)).where(
                        P2POrder.status == "active"
                    )
                ) or 0
            except:
                active_orders = await session.scalar(
                    select(func.count(P2POrder.id))
                ) or 0
            
            # Active trades
            active_trades = await session.scalar(
                select(func.count(P2PTrade.id)).where(
                    P2PTrade.status.in_(["pending", "awaiting_payment", "paid"])
                )
            ) or 0
            
            # Disputes
            disputed_trades = await session.scalar(
                select(func.count(P2PTrade.id)).where(
                    P2PTrade.status == "disputed"
                )
            ) or 0
        
        dispute_icon = "🔴" if disputed_trades > 0 else "🟢"
        
        text = f"""
🤝 <b>P2P Administration</b>

<b>Current Status:</b>
├ Active Orders: <b>{active_orders}</b>
├ Active Trades: <b>{active_trades}</b>
└ {dispute_icon} Disputes: <b>{disputed_trades}</b>

<b>Settings:</b>
├ Fee: <b>{p2p_settings.platform_fee_percent}%</b>
├ Min: <b>${p2p_settings.min_order_usd}</b>
└ Max: <b>${p2p_settings.max_order_usd:,}</b>

Select an option:
"""
        
        await safe_edit(callback.message, text, get_admin_p2p_keyboard())
        
    except Exception as e:
        logger.error("P2P menu error", error=str(e))
        await safe_edit(callback.message, "❌ Failed to load.", get_back_keyboard("admin:main"))
    
    await safe_answer(callback)


# ==================== DISPUTES ====================

@router.callback_query(F.data == "adm_p2p:disputes")
async def admin_disputes(callback: CallbackQuery, state: FSMContext):
    """View disputes"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            # Get disputed trades
            result = await session.execute(
                select(P2PTrade)
                .where(P2PTrade.status == "disputed")
                .order_by(desc(P2PTrade.created_at))
                .limit(20)
            )
            disputes = result.scalars().all()
        
        if not disputes:
            text = "⚠️ <b>Disputes</b>\n\n✅ No active disputes! 🎉"
            keyboard = get_back_keyboard()
        else:
            text = f"⚠️ <b>Active Disputes ({len(disputes)})</b>\n\n"
            buttons = []
            
            for d in disputes:
                age = datetime.utcnow() - d.created_at if d.created_at else timedelta(0)
                age_str = format_timedelta(age)
                
                text += f"🔴 <code>{d.id[:8]}</code>\n"
                text += f"   ${float(d.fiat_amount):,.0f} | {age_str} ago\n\n"
                
                buttons.append([InlineKeyboardButton(
                    text=f"🔴 {d.id[:8]} - ${float(d.fiat_amount):,.0f}",
                    callback_data=f"adm_p2p:dispute:{d.id[:8]}"
                )])
            
            buttons.append([InlineKeyboardButton(text="🔄 Refresh", callback_data="adm_p2p:disputes")])
            buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="adm_p2p:menu")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("Disputes error", error=str(e))
        await safe_edit(callback.message, "❌ Failed to load disputes.", get_back_keyboard())
    
    await safe_answer(callback)


@router.callback_query(F.data.startswith("adm_p2p:dispute:"))
async def admin_dispute_detail(callback: CallbackQuery, state: FSMContext):
    """Dispute detail"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    trade_id_short = callback.data.split(":")[2]
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(P2PTrade).where(P2PTrade.id.like(f"{trade_id_short}%"))
            )
            trade = result.scalar_one_or_none()
            
            if not trade:
                await safe_answer(callback, "❌ Trade not found", show_alert=True)
                return
            
            buyer = await session.get(User, trade.buyer_id) if trade.buyer_id else None
            seller = await session.get(User, trade.seller_id) if trade.seller_id else None
        
        buyer_name = f"@{buyer.username}" if buyer and buyer.username else str(buyer.telegram_id if buyer else "Unknown")
        seller_name = f"@{seller.username}" if seller and seller.username else str(seller.telegram_id if seller else "Unknown")
        
        text = f"""
⚠️ <b>Dispute Details</b>

<b>Trade:</b> <code>{trade.id[:8]}</code>
<b>Status:</b> {trade.status}
<b>Created:</b> {trade.created_at.strftime('%Y-%m-%d %H:%M') if trade.created_at else 'N/A'}

<b>Amount:</b>
├ Crypto: {float(trade.crypto_amount):.6f} {trade.token_symbol}
└ Fiat: ${float(trade.fiat_amount):,.2f} {trade.fiat_currency}

<b>Buyer:</b> {buyer_name}
├ ID: <code>{buyer.telegram_id if buyer else 'N/A'}</code>
└ Rating: ⭐ {buyer.rating:.1f if buyer else 0}

<b>Seller:</b> {seller_name}
├ ID: <code>{seller.telegram_id if seller else 'N/A'}</code>
└ Rating: ⭐ {seller.rating:.1f if seller else 0}

<b>Actions:</b>
"""
        
        buttons = [
            [
                InlineKeyboardButton(
                    text="✅ Resolve for Buyer",
                    callback_data=f"adm_p2p:resolve:buyer:{trade.id[:8]}"
                ),
                InlineKeyboardButton(
                    text="✅ Resolve for Seller", 
                    callback_data=f"adm_p2p:resolve:seller:{trade.id[:8]}"
                )
            ]
        ]
        
        if buyer:
            buttons.append([
                InlineKeyboardButton(
                    text="💬 Msg Buyer",
                    callback_data=f"adm_p2p:msg:{buyer.telegram_id}"
                ),
                InlineKeyboardButton(
                    text="💬 Msg Seller",
                    callback_data=f"adm_p2p:msg:{seller.telegram_id if seller else 0}"
                )
            ])
        
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="adm_p2p:disputes")])
        
        await safe_edit(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
        
    except Exception as e:
        logger.error("Dispute detail error", error=str(e))
        await safe_edit(callback.message, "❌ Failed to load.", get_back_keyboard("adm_p2p:disputes"))
    
    await safe_answer(callback)


@router.callback_query(F.data.startswith("adm_p2p:resolve:"))
async def admin_resolve_dispute(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Resolve dispute"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    parts = callback.data.split(":")
    if len(parts) < 4:
        await safe_answer(callback, "❌ Invalid data", show_alert=True)
        return
    
    winner = parts[2]  # buyer or seller
    trade_id_short = parts[3]
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(P2PTrade).where(P2PTrade.id.like(f"{trade_id_short}%"))
            )
            trade = result.scalar_one_or_none()
            
            if not trade:
                await safe_answer(callback, "❌ Trade not found", show_alert=True)
                return
            
            buyer = await session.get(User, trade.buyer_id) if trade.buyer_id else None
            seller = await session.get(User, trade.seller_id) if trade.seller_id else None
            
            # Update trade status
            if winner == "buyer":
                trade.status = "refunded"
                winner_user = buyer
                loser_user = seller
                
                # Refund crypto to buyer if possible
                if buyer and trade.token_symbol:
                    try:
                        wallet = await session.scalar(
                            select(Wallet).where(
                                Wallet.user_id == buyer.id,
                                Wallet.network == trade.network
                            )
                        )
                        if wallet:
                            balance = await session.scalar(
                                select(WalletBalance).where(
                                    WalletBalance.wallet_id == wallet.id,
                                    WalletBalance.token_symbol == trade.token_symbol
                                )
                            )
                            if balance:
                                balance.balance += trade.crypto_amount
                            else:
                                new_balance = WalletBalance(
                                    wallet_id=wallet.id,
                                    token_symbol=trade.token_symbol,
                                    balance=trade.crypto_amount,
                                    decimals=9
                                )
                                session.add(new_balance)
                    except Exception as e:
                        logger.warning("Refund failed", error=str(e))
                
            else:  # seller wins
                trade.status = "completed"
                winner_user = seller
                loser_user = buyer
                
                # Release crypto to seller
                if seller and trade.token_symbol:
                    try:
                        wallet = await session.scalar(
                            select(Wallet).where(
                                Wallet.user_id == seller.id,
                                Wallet.network == trade.network
                            )
                        )
                        if wallet:
                            balance = await session.scalar(
                                select(WalletBalance).where(
                                    WalletBalance.wallet_id == wallet.id,
                                    WalletBalance.token_symbol == trade.token_symbol
                                )
                            )
                            if balance:
                                balance.balance += trade.crypto_amount
                    except Exception as e:
                        logger.warning("Release failed", error=str(e))
            
            # Update ratings
            if loser_user:
                loser_user.rating = max(0, loser_user.rating - 5)
            
            await session.commit()
            
            # Notify users
            if winner_user:
                await safe_send(
                    bot, winner_user.telegram_id,
                    f"✅ <b>Dispute Resolved</b>\n\n"
                    f"The dispute for trade <code>{trade.id[:8]}</code> was resolved in your favor."
                )
            
            if loser_user:
                await safe_send(
                    bot, loser_user.telegram_id,
                    f"❌ <b>Dispute Resolved</b>\n\n"
                    f"The dispute for trade <code>{trade.id[:8]}</code> was resolved.\n"
                    f"Unfortunately, the decision was not in your favor."
                )
            
            logger.info("Dispute resolved", trade=trade_id_short, winner=winner, admin=callback.from_user.id)
        
        await safe_answer(callback, f"✅ Resolved for {winner}")
        
        text = f"""
✅ <b>Dispute Resolved!</b>

Trade: <code>{trade.id[:8]}</code>
Winner: <b>{winner.title()}</b>

Both parties have been notified.
"""
        await safe_edit(callback.message, text, get_back_keyboard("adm_p2p:disputes"))
        
    except Exception as e:
        logger.error("Resolve error", error=str(e))
        await safe_answer(callback, "❌ Failed to resolve", show_alert=True)


# ==================== ACTIVE TRADES ====================

@router.callback_query(F.data == "adm_p2p:active_trades")
@router.callback_query(F.data.startswith("adm_p2p:active_trades:"))
async def admin_active_trades(callback: CallbackQuery, state: FSMContext):
    """Active trades"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(P2PTrade)
                .where(P2PTrade.status.in_(["pending", "awaiting_payment", "paid", "disputed"]))
                .order_by(desc(P2PTrade.created_at))
                .offset(page * ITEMS_PER_PAGE)
                .limit(ITEMS_PER_PAGE + 1)
            )
            trades = result.scalars().all()
        
        has_more = len(trades) > ITEMS_PER_PAGE
        trades = trades[:ITEMS_PER_PAGE]
        
        if not trades and page == 0:
            text = "🔄 <b>Active Trades</b>\n\n✅ No active trades!"
            keyboard = get_back_keyboard()
        else:
            text = f"🔄 <b>Active Trades</b>"
            if page > 0:
                text += f" (Page {page + 1})"
            text += "\n\n"
            
            status_emoji = {
                "pending": "⏳",
                "awaiting_payment": "💳",
                "paid": "📤",
                "disputed": "⚠️"
            }
            
            for t in trades:
                emoji = status_emoji.get(str(t.status), "❓")
                age = datetime.utcnow() - t.created_at if t.created_at else timedelta(0)
                
                text += f"{emoji} <code>{t.id[:8]}</code>\n"
                text += f"   {float(t.crypto_amount):.4f} {t.token_symbol} | ${float(t.fiat_amount):,.0f}\n"
                text += f"   {format_timedelta(age)} ago\n\n"
            
            # Pagination
            buttons = []
            nav_row = []
            if page > 0:
                nav_row.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"adm_p2p:active_trades:{page-1}"))
            if has_more:
                nav_row.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"adm_p2p:active_trades:{page+1}"))
            if nav_row:
                buttons.append(nav_row)
            
            buttons.append([InlineKeyboardButton(text="🔄 Refresh", callback_data="adm_p2p:active_trades")])
            buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="adm_p2p:menu")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("Active trades error", error=str(e))
        await safe_edit(callback.message, "❌ Failed to load.", get_back_keyboard())
    
    await safe_answer(callback)


# ==================== ORDERS ====================

@router.callback_query(F.data == "adm_p2p:orders")
@router.callback_query(F.data.startswith("adm_p2p:orders:"))
async def admin_orders(callback: CallbackQuery, state: FSMContext):
    """P2P orders"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    parts = callback.data.split(":")
    filter_type = parts[2] if len(parts) > 2 else "all"
    page = 0
    
    if filter_type.isdigit():
        page = int(filter_type)
        filter_type = "all"
    
    try:
        async with db_manager.session() as session:
            # Counts
            total_orders = await session.scalar(select(func.count(P2POrder.id))) or 0
            
            try:
                active_count = await session.scalar(
                    select(func.count(P2POrder.id)).where(P2POrder.status == "active")
                ) or 0
            except:
                active_count = 0
            
            # Query
            query = select(P2POrder)
            
            if filter_type == "active":
                query = query.where(P2POrder.status == "active")
            
            query = query.order_by(desc(P2POrder.created_at))
            query = query.offset(page * ITEMS_PER_PAGE).limit(ITEMS_PER_PAGE + 1)
            
            result = await session.execute(query)
            orders = result.scalars().all()
        
        has_more = len(orders) > ITEMS_PER_PAGE
        orders = orders[:ITEMS_PER_PAGE]
        
        text = f"""
📋 <b>P2P Orders</b>

<b>Summary:</b>
├ Total: <b>{total_orders}</b>
└ Active: <b>{active_count}</b>

"""
        
        if not orders:
            text += "<i>No orders found.</i>"
        else:
            for o in orders:
                status_emoji = "🟢" if str(o.status) == "active" else "⚪"
                order_type = str(o.order_type).upper() if o.order_type else "?"
                
                text += f"{status_emoji} {order_type} {o.token_symbol}\n"
                text += f"   {float(o.price_per_unit):,.2f} {o.fiat_currency}\n"
        
        # Buttons
        buttons = [
            [
                InlineKeyboardButton(
                    text="• Active •" if filter_type == "active" else "🟢 Active Only",
                    callback_data="adm_p2p:orders:active"
                ),
                InlineKeyboardButton(
                    text="📋 All",
                    callback_data="adm_p2p:orders:all"
                )
            ]
        ]
        
        if page > 0 or has_more:
            nav_row = []
            if page > 0:
                nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_p2p:orders:{page-1}"))
            if has_more:
                nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_p2p:orders:{page+1}"))
            buttons.append(nav_row)
        
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="adm_p2p:menu")])
        
        await safe_edit(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
        
    except Exception as e:
        logger.error("Orders error", error=str(e))
        await safe_edit(callback.message, "❌ Failed to load.", get_back_keyboard())
    
    await safe_answer(callback)


# ==================== TOP TRADERS ====================

@router.callback_query(F.data == "adm_p2p:top_traders")
async def admin_top_traders(callback: CallbackQuery, state: FSMContext):
    """Top P2P traders"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            result = await session.execute(
                select(User)
                .where(User.total_trades_count > 0)
                .order_by(desc(User.total_volume_usd))
                .limit(20)
            )
            traders = result.scalars().all()
        
        text = "🏆 <b>Top P2P Traders</b>\n\n"
        
        if not traders:
            text += "<i>No traders yet.</i>"
        else:
            medals = ["🥇", "🥈", "🥉"]
            
            for i, t in enumerate(traders):
                medal = medals[i] if i < 3 else f"{i+1}."
                verified = "✅" if getattr(t, 'merchant_verified', False) else ""
                
                volume = getattr(t, 'total_volume_usd', 0) or 0
                trades = getattr(t, 'total_trades_count', 0) or 0
                success = getattr(t, 'successful_trades_count', 0) or 0
                
                rate = (success / trades * 100) if trades > 0 else 0
                
                text += f"{medal} @{t.username or t.telegram_id} {verified}\n"
                text += f"   ${float(volume):,.0f} | {trades} trades | {rate:.0f}%\n"
                text += f"   ⭐ {t.rating:.1f}\n\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh", callback_data="adm_p2p:top_traders")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="adm_p2p:menu")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("Top traders error", error=str(e))
        await safe_edit(callback.message, "❌ Failed to load.", get_back_keyboard())
    
    await safe_answer(callback)


# ==================== STATS ====================

@router.callback_query(F.data == "adm_p2p:stats")
async def admin_p2p_stats(callback: CallbackQuery, state: FSMContext):
    """P2P statistics"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    await safe_answer(callback, "📊 Loading...")
    
    try:
        async with db_manager.session() as session:
            # Total stats
            total_orders = await session.scalar(select(func.count(P2POrder.id))) or 0
            total_trades = await session.scalar(select(func.count(P2PTrade.id))) or 0
            
            completed_trades = await session.scalar(
                select(func.count(P2PTrade.id)).where(P2PTrade.status == "completed")
            ) or 0
            
            total_volume = await session.scalar(
                select(func.sum(P2PTrade.fiat_amount)).where(P2PTrade.status == "completed")
            ) or Decimal("0")
            
            # 24h
            yesterday = datetime.utcnow() - timedelta(days=1)
            trades_24h = await session.scalar(
                select(func.count(P2PTrade.id)).where(P2PTrade.created_at >= yesterday)
            ) or 0
            
            volume_24h = await session.scalar(
                select(func.sum(P2PTrade.fiat_amount)).where(
                    and_(
                        P2PTrade.status == "completed",
                        P2PTrade.created_at >= yesterday
                    )
                )
            ) or Decimal("0")
            
            # 7d
            week_ago = datetime.utcnow() - timedelta(days=7)
            volume_7d = await session.scalar(
                select(func.sum(P2PTrade.fiat_amount)).where(
                    and_(
                        P2PTrade.status == "completed",
                        P2PTrade.created_at >= week_ago
                    )
                )
            ) or Decimal("0")
            
            # Disputes
            total_disputes = await session.scalar(
                select(func.count(P2PTrade.id)).where(P2PTrade.status == "disputed")
            ) or 0
            
            # Unique traders
            unique_traders = await session.scalar(
                select(func.count(func.distinct(P2POrder.user_id)))
            ) or 0
        
        completion_rate = (completed_trades / total_trades * 100) if total_trades > 0 else 0
        dispute_rate = (total_disputes / total_trades * 100) if total_trades > 0 else 0
        
        text = f"""
📊 <b>P2P Statistics</b>

<b>All Time:</b>
├ Orders: <b>{total_orders:,}</b>
├ Trades: <b>{total_trades:,}</b>
├ Completed: <b>{completed_trades:,}</b>
├ Completion Rate: <b>{completion_rate:.1f}%</b>
├ Volume: <b>${float(total_volume):,.0f}</b>
└ Unique Traders: <b>{unique_traders:,}</b>

<b>Last 24h:</b>
├ Trades: <b>{trades_24h}</b>
└ Volume: <b>${float(volume_24h):,.0f}</b>

<b>Last 7 Days:</b>
└ Volume: <b>${float(volume_7d):,.0f}</b>

<b>Disputes:</b>
├ Active: <b>{total_disputes}</b>
└ Rate: <b>{dispute_rate:.2f}%</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh", callback_data="adm_p2p:stats")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="adm_p2p:menu")]
        ])
        
        await safe_edit(callback.message, text, keyboard)
        
    except Exception as e:
        logger.error("P2P stats error", error=str(e))
        await safe_edit(callback.message, "❌ Failed to load.", get_back_keyboard())


# ==================== SETTINGS ====================

@router.callback_query(F.data == "adm_p2p:settings")
async def admin_p2p_settings(callback: CallbackQuery, state: FSMContext):
    """P2P settings"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    await state.clear()
    
    text = f"""
⚙️ <b>P2P Settings</b>

<b>Current:</b>
├ Fee: <b>{p2p_settings.platform_fee_percent}%</b>
├ Min Order: <b>${p2p_settings.min_order_usd}</b>
├ Max Order: <b>${p2p_settings.max_order_usd:,}</b>
├ Escrow Timeout: <b>{p2p_settings.escrow_timeout_minutes} min</b>
└ Trade Timeout: <b>{p2p_settings.trade_timeout_minutes} min</b>

<b>Supported:</b>
├ Cryptos: {', '.join(p2p_settings.supported_cryptos)}
└ Fiats: {', '.join(p2p_settings.supported_fiats)}

Select to modify:
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Platform Fee", callback_data="adm_p2p:set:fee")],
        [
            InlineKeyboardButton(text="📉 Min Order", callback_data="adm_p2p:set:min"),
            InlineKeyboardButton(text="📈 Max Order", callback_data="adm_p2p:set:max")
        ],
        [
            InlineKeyboardButton(text="🔒 Escrow Time", callback_data="adm_p2p:set:escrow"),
            InlineKeyboardButton(text="⏱ Trade Time", callback_data="adm_p2p:set:trade")
        ],
        [InlineKeyboardButton(text="🔙 Back", callback_data="adm_p2p:menu")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer(callback)


@router.callback_query(F.data == "adm_p2p:set:fee")
async def set_fee_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    text = f"💰 <b>Set P2P Fee</b>\n\nCurrent: <b>{p2p_settings.platform_fee_percent}%</b>\n\nEnter new fee (0-5):"
    await safe_edit(callback.message, text, get_cancel_keyboard("adm_p2p:settings"))
    await state.set_state(AdminP2PStates.set_fee)
    await safe_answer(callback)


@router.message(AdminP2PStates.set_fee)
async def set_fee_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        fee = Decimal(message.text.strip())
        if fee < 0 or fee > 5:
            raise ValueError()
        
        p2p_settings.platform_fee_percent = fee
        logger.info("P2P fee updated", fee=str(fee), admin=message.from_user.id)
        
        await message.answer(f"✅ Fee set to <b>{fee}%</b>", reply_markup=get_back_keyboard("adm_p2p:settings"), parse_mode="HTML")
    except:
        await message.answer("❌ Invalid. Enter 0-5.", reply_markup=get_cancel_keyboard("adm_p2p:settings"))
        return
    
    await state.clear()


@router.callback_query(F.data == "adm_p2p:set:min")
async def set_min_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    text = f"📉 <b>Set Min Order</b>\n\nCurrent: <b>${p2p_settings.min_order_usd}</b>\n\nEnter amount (1-1000):"
    await safe_edit(callback.message, text, get_cancel_keyboard("adm_p2p:settings"))
    await state.set_state(AdminP2PStates.set_min_trade)
    await safe_answer(callback)


@router.message(AdminP2PStates.set_min_trade)
async def set_min_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        amount = int(message.text.strip().replace("$", "").replace(",", ""))
        if amount < 1 or amount > 1000:
            raise ValueError()
        
        p2p_settings.min_order_usd = amount
        await message.answer(f"✅ Min set to <b>${amount}</b>", reply_markup=get_back_keyboard("adm_p2p:settings"), parse_mode="HTML")
    except:
        await message.answer("❌ Invalid.", reply_markup=get_cancel_keyboard("adm_p2p:settings"))
        return
    
    await state.clear()


@router.callback_query(F.data == "adm_p2p:set:max")
async def set_max_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    text = f"📈 <b>Set Max Order</b>\n\nCurrent: <b>${p2p_settings.max_order_usd:,}</b>\n\nEnter amount (100-1000000):"
    await safe_edit(callback.message, text, get_cancel_keyboard("adm_p2p:settings"))
    await state.set_state(AdminP2PStates.set_max_trade)
    await safe_answer(callback)


@router.message(AdminP2PStates.set_max_trade)
async def set_max_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        amount = int(message.text.strip().replace("$", "").replace(",", ""))
        if amount < 100 or amount > 1000000:
            raise ValueError()
        
        p2p_settings.max_order_usd = amount
        await message.answer(f"✅ Max set to <b>${amount:,}</b>", reply_markup=get_back_keyboard("adm_p2p:settings"), parse_mode="HTML")
    except:
        await message.answer("❌ Invalid.", reply_markup=get_cancel_keyboard("adm_p2p:settings"))
        return
    
    await state.clear()


@router.callback_query(F.data == "adm_p2p:set:escrow")
async def set_escrow_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    text = f"🔒 <b>Set Escrow Timeout</b>\n\nCurrent: <b>{p2p_settings.escrow_timeout_minutes} min</b>\n\nEnter minutes (5-120):"
    await safe_edit(callback.message, text, get_cancel_keyboard("adm_p2p:settings"))
    await state.set_state(AdminP2PStates.set_escrow_timeout)
    await safe_answer(callback)


@router.message(AdminP2PStates.set_escrow_timeout)
async def set_escrow_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        minutes = int(message.text.strip())
        if minutes < 5 or minutes > 120:
            raise ValueError()
        
        p2p_settings.escrow_timeout_minutes = minutes
        await message.answer(f"✅ Escrow timeout set to <b>{minutes} min</b>", reply_markup=get_back_keyboard("adm_p2p:settings"), parse_mode="HTML")
    except:
        await message.answer("❌ Invalid.", reply_markup=get_cancel_keyboard("adm_p2p:settings"))
        return
    
    await state.clear()


@router.callback_query(F.data == "adm_p2p:set:trade")
async def set_trade_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    text = f"⏱ <b>Set Trade Timeout</b>\n\nCurrent: <b>{p2p_settings.trade_timeout_minutes} min</b>\n\nEnter minutes (15-480):"
    await safe_edit(callback.message, text, get_cancel_keyboard("adm_p2p:settings"))
    await state.set_state(AdminP2PStates.set_trade_timeout)
    await safe_answer(callback)


@router.message(AdminP2PStates.set_trade_timeout)
async def set_trade_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        minutes = int(message.text.strip())
        if minutes < 15 or minutes > 480:
            raise ValueError()
        
        p2p_settings.trade_timeout_minutes = minutes
        await message.answer(f"✅ Trade timeout set to <b>{minutes} min</b>", reply_markup=get_back_keyboard("adm_p2p:settings"), parse_mode="HTML")
    except:
        await message.answer("❌ Invalid.", reply_markup=get_cancel_keyboard("adm_p2p:settings"))
        return
    
    await state.clear()


# ==================== MESSAGE USER ====================

@router.callback_query(F.data.startswith("adm_p2p:msg:"))
async def message_user_start(callback: CallbackQuery, state: FSMContext):
    """Start messaging user"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    try:
        user_tg_id = int(callback.data.split(":")[2])
    except:
        await safe_answer(callback, "❌ Invalid user", show_alert=True)
        return
    
    if user_tg_id == 0:
        await safe_answer(callback, "❌ User not found", show_alert=True)
        return
    
    await state.update_data(msg_user_id=user_tg_id)
    
    text = f"💬 <b>Message User</b>\n\nUser ID: <code>{user_tg_id}</code>\n\nEnter message:"
    await safe_edit(callback.message, text, get_cancel_keyboard("adm_p2p:menu"))
    await state.set_state(AdminP2PStates.message_user_text)
    await safe_answer(callback)


@router.message(AdminP2PStates.message_user_text)
async def message_user_send(message: Message, state: FSMContext, bot: Bot):
    """Send message to user"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    data = await state.get_data()
    user_tg_id = data.get('msg_user_id')
    
    if not user_tg_id:
        await message.answer("❌ Session expired.", reply_markup=get_back_keyboard())
        await state.clear()
        return
    
    text_to_send = message.text.strip()
    if not text_to_send:
        await message.answer("❌ Empty message.", reply_markup=get_cancel_keyboard())
        return
    
    admin_msg = f"""
📬 <b>Message from Support</b>

{text_to_send}

<i>Reply to this message if you have questions.</i>
"""
    
    success = await safe_send(bot, user_tg_id, admin_msg)
    
    if success:
        await message.answer(
            f"✅ Message sent to <code>{user_tg_id}</code>",
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
        logger.info("Admin message sent", admin=message.from_user.id, user=user_tg_id)
    else:
        await message.answer(
            "❌ Failed. User may have blocked the bot.",
            reply_markup=get_back_keyboard()
        )
    
    await state.clear()


# ==================== FALLBACK ====================

@router.callback_query(F.data.startswith("adm_p2p:"))
async def admin_p2p_fallback(callback: CallbackQuery, state: FSMContext):
    """Fallback"""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ Access denied", show_alert=True)
        return
    
    logger.warning("Unhandled P2P callback", data=callback.data)
    await admin_p2p_menu(callback, state)
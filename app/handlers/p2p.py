"""
NEXUS WALLET - P2P Handler (Complete Edition)
Full P2P trading interface: buy, sell, orders, trades, chat
"""

from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select, desc, func, or_, and_
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Optional, List
import structlog

from database.connection import db_manager
from database.repositories.user_repository import UserRepository
from database.models import OrderStatus, TradeStatus
from services.p2p_service import (
    p2p_service, SUPPORTED_CRYPTOS, SUPPORTED_FIATS,
    PAYMENT_METHOD_TYPES
)
from services.price_service import price_service
from locales.messages import get_text

logger = structlog.get_logger(__name__)
router = Router(name="p2p")


# ==================== FSM STATES ====================

class P2PStates(StatesGroup):
    # Order creation
    create_type = State()          # buy/sell
    create_crypto = State()        # select crypto
    create_fiat = State()          # select fiat
    create_amount = State()        # enter amount
    create_price = State()         # enter price
    create_limits = State()        # min/max limits
    create_payment = State()       # select payment methods
    create_terms = State()         # optional terms
    create_confirm = State()       # confirm order
    
    # Trade
    trade_amount = State()         # enter trade amount
    trade_payment = State()        # select payment
    trade_confirm = State()        # confirm trade
    
    # Chat
    trade_chat = State()           # in trade chat
    
    # Payment method
    pm_type = State()              # payment method type
    pm_details = State()           # payment details
    pm_name = State()              # custom name


# ==================== KEYBOARDS ====================

def get_p2p_main_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Main P2P menu"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Buy Crypto", callback_data="p2p:buy"),
            InlineKeyboardButton(text="💸 Sell Crypto", callback_data="p2p:sell")
        ],
        [
            InlineKeyboardButton(text="📋 My Orders", callback_data="p2p:my_orders"),
            InlineKeyboardButton(text="🔄 My Trades", callback_data="p2p:my_trades")
        ],
        [
            InlineKeyboardButton(text="💳 Payment Methods", callback_data="p2p:payments"),
            InlineKeyboardButton(text="👤 My Profile", callback_data="p2p:profile")
        ],
        [
            InlineKeyboardButton(text="📊 Market Stats", callback_data="p2p:stats"),
            InlineKeyboardButton(text="❓ Help", callback_data="p2p:help")
        ],
        [InlineKeyboardButton(text="🔙 Main Menu", callback_data="main_menu")]
    ])


def get_crypto_keyboard(callback_prefix: str) -> InlineKeyboardMarkup:
    """Crypto selection keyboard"""
    buttons = []
    row = []
    
    for network, info in SUPPORTED_CRYPTOS.items():
        row.append(InlineKeyboardButton(
            text=f"{info['icon']} {info['symbol']}",
            callback_data=f"{callback_prefix}:{network}"
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="p2p:menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_fiat_keyboard(callback_prefix: str) -> InlineKeyboardMarkup:
    """Fiat selection keyboard"""
    buttons = []
    row = []
    
    for code, info in SUPPORTED_FIATS.items():
        row.append(InlineKeyboardButton(
            text=f"{info['symbol']} {code}",
            callback_data=f"{callback_prefix}:{code}"
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="p2p:menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_payment_type_keyboard() -> InlineKeyboardMarkup:
    """Payment method type selection"""
    buttons = []
    
    for type_key, info in PAYMENT_METHOD_TYPES.items():
        buttons.append([InlineKeyboardButton(
            text=f"{info['icon']} {info['name']}",
            callback_data=f"p2p:pm_type:{type_key}"
        )])
    
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="p2p:payments")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_back_keyboard(callback_data: str = "p2p:menu") -> InlineKeyboardMarkup:
    """Simple back keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data=callback_data)]
    ])


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Cancel keyboard for FSM"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="p2p:cancel")]
    ])


# ==================== MAIN MENU ====================

@router.callback_query(F.data == "p2p")
@router.callback_query(F.data == "p2p:menu")
async def p2p_main_menu(callback: CallbackQuery, state: FSMContext):
    """Show P2P main menu"""
    await state.clear()
    
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code if user else "en"
        
        stats = await p2p_service.get_market_stats(session)
    
    text = f"""
🤝 <b>P2P Trading</b>

Buy and sell crypto directly with other users.
No intermediaries, secure escrow protection.

📊 <b>Market Overview:</b>
├ Active Orders: <b>{stats['active_orders']}</b>
├ 24h Volume: <b>${stats['volume_24h_usd']:,.0f}</b>
├ 24h Trades: <b>{stats['trades_24h']}</b>
└ Active Traders: <b>{stats['active_traders']}</b>

Select an option below:
"""
    
    await safe_edit(callback.message, text, get_p2p_main_keyboard(lang))
    await callback.answer()


# ==================== BUY FLOW ====================

@router.callback_query(F.data == "p2p:buy")
async def p2p_buy_select_crypto(callback: CallbackQuery, state: FSMContext):
    """Start buy flow - select crypto"""
    await state.update_data(order_type="buy")
    
    text = """
💰 <b>Buy Crypto</b>

Select the cryptocurrency you want to buy:
"""
    
    await safe_edit(callback.message, text, get_crypto_keyboard("p2p:buy_c"))
    await callback.answer()


@router.callback_query(F.data.startswith("p2p:buy_c:"))
async def p2p_buy_select_fiat(callback: CallbackQuery, state: FSMContext):
    """Select fiat currency for buying"""
    network = callback.data.split(":")[2]
    crypto_info = SUPPORTED_CRYPTOS.get(network)
    
    if not crypto_info:
        await callback.answer("Invalid selection", show_alert=True)
        return
    
    await state.update_data(network=network, token_symbol=crypto_info['symbol'])
    
    text = f"""
💰 <b>Buy {crypto_info['icon']} {crypto_info['symbol']}</b>

Select your payment currency:
"""
    
    await safe_edit(callback.message, text, get_fiat_keyboard("p2p:buy_f"))
    await callback.answer()


@router.callback_query(F.data.startswith("p2p:buy_f:"))
async def p2p_buy_show_orders(callback: CallbackQuery, state: FSMContext):
    """Show available sell orders"""
    fiat = callback.data.split(":")[2]
    data = await state.get_data()
    network = data.get("network")
    token_symbol = data.get("token_symbol")
    
    await state.update_data(fiat=fiat)
    
    async with db_manager.session() as session:
        # Get sell orders (user wants to buy, so show sells)
        orders = await p2p_service.get_market_orders(
            session,
            order_type="sell",
            network=network,
            fiat_currency=fiat,
            limit=10
        )
    
    crypto_info = SUPPORTED_CRYPTOS.get(network, {})
    fiat_info = SUPPORTED_FIATS.get(fiat, {})
    
    if not orders:
        text = f"""
💰 <b>Buy {crypto_info.get('icon', '')} {token_symbol}</b>

No sellers available for {fiat} at the moment.

Try a different currency or check back later.
"""
        keyboard = get_back_keyboard("p2p:buy")
    else:
        text = f"""
💰 <b>Buy {crypto_info.get('icon', '')} {token_symbol}</b>
💵 Pay with: <b>{fiat_info.get('symbol', '')} {fiat}</b>

📋 <b>Available Sellers:</b>
"""
        buttons = []
        
        for order in orders:
            user = order.user
            verified = "✅" if user.merchant_verified else ""
            rating = f"⭐{user.rating:.0f}" if user.rating else ""
            trades = f"({user.successful_trades_count} trades)"
            
            price_text = f"{order.price_per_unit:,.2f} {fiat}"
            limit_text = f"{order.min_limit:,.0f}-{order.max_limit:,.0f}"
            
            text += f"\n{verified} @{user.username or 'Anonymous'} {rating} {trades}"
            text += f"\n   💵 {price_text} | 📊 {limit_text} {fiat}\n"
            
            buttons.append([InlineKeyboardButton(
                text=f"Buy @ {price_text}",
                callback_data=f"p2p:trade:{order.id[:8]}"
            )])
        
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="p2p:buy")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await safe_edit(callback.message, text, keyboard)
    await callback.answer()


# ==================== SELL FLOW ====================

@router.callback_query(F.data == "p2p:sell")
async def p2p_sell_select_crypto(callback: CallbackQuery, state: FSMContext):
    """Start sell flow - select crypto"""
    await state.update_data(order_type="sell")
    
    text = """
💸 <b>Sell Crypto</b>

Select the cryptocurrency you want to sell:
"""
    
    await safe_edit(callback.message, text, get_crypto_keyboard("p2p:sell_c"))
    await callback.answer()


@router.callback_query(F.data.startswith("p2p:sell_c:"))
async def p2p_sell_select_fiat(callback: CallbackQuery, state: FSMContext):
    """Select fiat currency for selling"""
    network = callback.data.split(":")[2]
    crypto_info = SUPPORTED_CRYPTOS.get(network)
    
    if not crypto_info:
        await callback.answer("Invalid selection", show_alert=True)
        return
    
    await state.update_data(network=network, token_symbol=crypto_info['symbol'])
    
    text = f"""
💸 <b>Sell {crypto_info['icon']} {crypto_info['symbol']}</b>

Select the currency you want to receive:
"""
    
    await safe_edit(callback.message, text, get_fiat_keyboard("p2p:sell_f"))
    await callback.answer()


@router.callback_query(F.data.startswith("p2p:sell_f:"))
async def p2p_sell_show_orders(callback: CallbackQuery, state: FSMContext):
    """Show available buy orders"""
    fiat = callback.data.split(":")[2]
    data = await state.get_data()
    network = data.get("network")
    token_symbol = data.get("token_symbol")
    
    await state.update_data(fiat=fiat)
    
    async with db_manager.session() as session:
        # Get buy orders (user wants to sell, so show buys)
        orders = await p2p_service.get_market_orders(
            session,
            order_type="buy",
            network=network,
            fiat_currency=fiat,
            limit=10
        )
    
    crypto_info = SUPPORTED_CRYPTOS.get(network, {})
    fiat_info = SUPPORTED_FIATS.get(fiat, {})
    
    if not orders:
        text = f"""
💸 <b>Sell {crypto_info.get('icon', '')} {token_symbol}</b>

No buyers available for {fiat} at the moment.

💡 <b>Tip:</b> Create your own sell order!
"""
        buttons = [
            [InlineKeyboardButton(text="➕ Create Sell Order", callback_data="p2p:create:sell")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="p2p:sell")]
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    else:
        text = f"""
💸 <b>Sell {crypto_info.get('icon', '')} {token_symbol}</b>
💵 Receive: <b>{fiat_info.get('symbol', '')} {fiat}</b>

📋 <b>Available Buyers:</b>
"""
        buttons = []
        
        for order in orders:
            user = order.user
            verified = "✅" if user.merchant_verified else ""
            rating = f"⭐{user.rating:.0f}" if user.rating else ""
            
            price_text = f"{order.price_per_unit:,.2f} {fiat}"
            limit_text = f"{order.min_limit:,.0f}-{order.max_limit:,.0f}"
            
            text += f"\n{verified} @{user.username or 'Anonymous'} {rating}"
            text += f"\n   💵 {price_text} | 📊 {limit_text} {fiat}\n"
            
            buttons.append([InlineKeyboardButton(
                text=f"Sell @ {price_text}",
                callback_data=f"p2p:trade:{order.id[:8]}"
            )])
        
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="p2p:sell")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await safe_edit(callback.message, text, keyboard)
    await callback.answer()


# ==================== INITIATE TRADE ====================

@router.callback_query(F.data.startswith("p2p:trade:"))
async def p2p_trade_start(callback: CallbackQuery, state: FSMContext):
    """Start a trade with an order"""
    order_id_short = callback.data.split(":")[2]
    
    async with db_manager.session() as session:
        # Find order by short ID
        from sqlalchemy import select
        from database.models import P2POrder
        result = await session.execute(
            select(P2POrder).where(P2POrder.id.like(f"{order_id_short}%"))
        )
        order = result.scalar_one_or_none()
        
        if not order:
            await callback.answer("Order not found", show_alert=True)
            return
        
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        
        if order.user_id == user.id:
            await callback.answer("Cannot trade with your own order", show_alert=True)
            return
        
        crypto_info = SUPPORTED_CRYPTOS.get(order.network, {})
        fiat_info = SUPPORTED_FIATS.get(order.fiat_currency, {})
        
        await state.update_data(
            trade_order_id=order.id,
            trade_network=order.network,
            trade_symbol=order.token_symbol,
            trade_fiat=order.fiat_currency,
            trade_price=str(order.price_per_unit),
            trade_min=str(order.min_limit),
            trade_max=str(order.max_limit),
            trade_available=str(order.available_amount)
        )
    
    text = f"""
🔄 <b>Start Trade</b>

{crypto_info.get('icon', '')} <b>{order.token_symbol}</b> @ {order.price_per_unit:,.2f} {order.fiat_currency}

📊 <b>Order Details:</b>
├ Available: <b>{order.available_amount:.6f} {order.token_symbol}</b>
├ Limits: <b>{order.min_limit:,.0f} - {order.max_limit:,.0f} {order.fiat_currency}</b>
└ Time Limit: <b>{order.payment_time_limit} min</b>

💵 Enter the amount in <b>{order.fiat_currency}</b> you want to trade:

<i>Example: 1000</i>
"""
    
    await safe_edit(callback.message, text, get_cancel_keyboard())
    await state.set_state(P2PStates.trade_amount)
    await callback.answer()


@router.message(P2PStates.trade_amount)
async def p2p_trade_enter_amount(message: Message, state: FSMContext):
    """Process trade amount"""
    data = await state.get_data()
    
    try:
        fiat_amount = Decimal(message.text.strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        await message.answer("❌ Invalid amount. Enter a number.", reply_markup=get_cancel_keyboard())
        return
    
    min_limit = Decimal(data['trade_min'])
    max_limit = Decimal(data['trade_max'])
    price = Decimal(data['trade_price'])
    available = Decimal(data['trade_available'])
    
    if fiat_amount < min_limit:
        await message.answer(f"❌ Minimum is {min_limit} {data['trade_fiat']}", reply_markup=get_cancel_keyboard())
        return
    
    if fiat_amount > max_limit:
        await message.answer(f"❌ Maximum is {max_limit} {data['trade_fiat']}", reply_markup=get_cancel_keyboard())
        return
    
    crypto_amount = fiat_amount / price
    
    if crypto_amount > available:
        await message.answer(f"❌ Not enough available. Max: {available:.6f}", reply_markup=get_cancel_keyboard())
        return
    
    await state.update_data(
        trade_fiat_amount=str(fiat_amount),
        trade_crypto_amount=str(crypto_amount)
    )
    
    crypto_info = SUPPORTED_CRYPTOS.get(data['trade_network'], {})
    
    text = f"""
✅ <b>Confirm Trade</b>

You will receive:
<b>{crypto_amount:.6f} {data['trade_symbol']}</b>

You will pay:
<b>{fiat_amount:,.2f} {data['trade_fiat']}</b>

Rate: {price:,.2f} {data['trade_fiat']}/{data['trade_symbol']}
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm Trade", callback_data="p2p:trade_confirm")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="p2p:menu")]
    ])
    
    await message.answer(text, reply_markup=keyboard)
    await state.set_state(P2PStates.trade_confirm)


@router.callback_query(P2PStates.trade_confirm, F.data == "p2p:trade_confirm")
async def p2p_trade_confirm(callback: CallbackQuery, state: FSMContext):
    """Confirm and create trade"""
    data = await state.get_data()
    
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        
        trade, message = await p2p_service.initiate_trade(
            session=session,
            taker_id=user.id,
            order_id=data['trade_order_id'],
            crypto_amount=Decimal(data['trade_crypto_amount'])
        )
        
        if not trade:
            await callback.answer(f"❌ {message}", show_alert=True)
            await state.clear()
            return
        
        await session.commit()
    
    await state.clear()
    
    text = f"""
🎉 <b>Trade Created!</b>

Trade ID: <code>{trade.id[:8]}</code>

⏰ You have <b>{60} minutes</b> to complete this trade.

<b>Next Steps:</b>
1. Contact the seller
2. Make payment to their account
3. Mark as "Paid" after payment
4. Wait for seller to release crypto

⚠️ Never release payment outside this platform!
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Open Trade Chat", callback_data=f"p2p:chat:{trade.id[:8]}")],
        [InlineKeyboardButton(text="📋 My Trades", callback_data="p2p:my_trades")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await callback.answer("Trade created!")


# ==================== MY ORDERS ====================

@router.callback_query(F.data == "p2p:my_orders")
async def p2p_my_orders(callback: CallbackQuery):
    """Show user's orders"""
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        orders = await p2p_service.get_user_orders(session, user.id)
    
    if not orders:
        text = """
📋 <b>My Orders</b>

You don't have any orders yet.
Create your first order to start trading!
"""
        buttons = [
            [
                InlineKeyboardButton(text="➕ Create Buy Order", callback_data="p2p:create:buy"),
                InlineKeyboardButton(text="➕ Create Sell Order", callback_data="p2p:create:sell")
            ],
            [InlineKeyboardButton(text="🔙 Back", callback_data="p2p:menu")]
        ]
    else:
        text = "📋 <b>My Orders</b>\n\n"
        buttons = []
        
        for order in orders[:10]:
            crypto = SUPPORTED_CRYPTOS.get(order.network, {})
            status_emoji = {
                OrderStatus.ACTIVE: "🟢",
                OrderStatus.PAUSED: "⏸",
                OrderStatus.FILLED: "✅",
                OrderStatus.CANCELLED: "❌"
            }
            emoji = status_emoji.get(order.status, "⚪")
            
            text += f"{emoji} {order.order_type.upper()} {crypto.get('icon', '')} {order.token_symbol}\n"
            text += f"   {order.price_per_unit:,.2f} {order.fiat_currency} | "
            text += f"{order.available_amount:.4f} left\n\n"
            
            if order.status == OrderStatus.ACTIVE:
                buttons.append([InlineKeyboardButton(
                    text=f"Manage: {order.order_type.upper()} {order.token_symbol}",
                    callback_data=f"p2p:order:{order.id[:8]}"
                )])
        
        buttons.append([
            InlineKeyboardButton(text="➕ New Order", callback_data="p2p:create:choose"),
        ])
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="p2p:menu")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await safe_edit(callback.message, text, keyboard)
    await callback.answer()


# ==================== MY TRADES ====================

@router.callback_query(F.data == "p2p:my_trades")
async def p2p_my_trades(callback: CallbackQuery):
    """Show user's active trades"""
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        trades = await p2p_service.get_user_trades(session, user.id, limit=15)
    
    if not trades:
        text = """
🔄 <b>My Trades</b>

No trades yet. Start trading from the P2P market!
"""
        keyboard = get_back_keyboard("p2p:menu")
    else:
        text = "🔄 <b>My Trades</b>\n\n"
        buttons = []
        
        for trade in trades:
            crypto = SUPPORTED_CRYPTOS.get(trade.network, {})
            
            status_emoji = {
                TradeStatus.PENDING: "⏳",
                TradeStatus.AWAITING_PAYMENT: "💳",
                TradeStatus.PAYMENT_SENT: "📤",
                TradeStatus.COMPLETED: "✅",
                TradeStatus.CANCELLED: "❌",
                TradeStatus.DISPUTED: "⚠️"
            }
            emoji = status_emoji.get(trade.status, "❓")
            
            role = "Buy" if trade.buyer_id == user.id else "Sell"
            partner_id = trade.seller_id if trade.buyer_id == user.id else trade.buyer_id
            
            text += f"{emoji} {role} {crypto.get('icon', '')} {trade.crypto_amount:.4f} {trade.token_symbol}\n"
            text += f"   {trade.fiat_amount:,.2f} {trade.fiat_currency}\n\n"
            
            if trade.status not in [TradeStatus.COMPLETED, TradeStatus.CANCELLED]:
                buttons.append([InlineKeyboardButton(
                    text=f"💬 {role} {trade.token_symbol} - {trade.status.value}",
                    callback_data=f"p2p:chat:{trade.id[:8]}"
                )])
        
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="p2p:menu")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await safe_edit(callback.message, text, keyboard)
    await callback.answer()


# ==================== TRADE CHAT ====================

@router.callback_query(F.data.startswith("p2p:chat:"))
async def p2p_trade_chat(callback: CallbackQuery, state: FSMContext):
    """Open trade chat"""
    trade_id_short = callback.data.split(":")[2]
    
    async with db_manager.session() as session:
        from sqlalchemy import select
        from database.models import P2PTrade
        
        result = await session.execute(
            select(P2PTrade).where(P2PTrade.id.like(f"{trade_id_short}%"))
        )
        trade = result.scalar_one_or_none()
        
        if not trade:
            await callback.answer("Trade not found", show_alert=True)
            return
        
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        
        if trade.buyer_id != user.id and trade.seller_id != user.id:
            await callback.answer("Access denied", show_alert=True)
            return
        
        is_buyer = trade.buyer_id == user.id
        partner = trade.seller if is_buyer else trade.buyer
        
        # Get messages
        messages = await p2p_service.get_trade_messages(session, trade.id)
        
        await state.update_data(current_trade_id=trade.id)
    
    crypto = SUPPORTED_CRYPTOS.get(trade.network, {})
    
    status_text = {
        TradeStatus.PENDING: "⏳ Waiting for buyer's payment",
        TradeStatus.AWAITING_PAYMENT: "💳 Make payment and click 'I Paid'",
        TradeStatus.PAYMENT_SENT: "📤 Waiting for seller to confirm",
        TradeStatus.COMPLETED: "✅ Trade completed",
        TradeStatus.CANCELLED: "❌ Trade cancelled",
        TradeStatus.DISPUTED: "⚠️ Under dispute"
    }
    
    text = f"""
💬 <b>Trade Chat</b>

{crypto.get('icon', '')} <b>{trade.crypto_amount:.6f} {trade.token_symbol}</b>
💵 <b>{trade.fiat_amount:,.2f} {trade.fiat_currency}</b>

Partner: @{partner.username or 'Anonymous'}
Status: {status_text.get(trade.status, str(trade.status))}

{'━' * 20}
"""
    
    # Show last 5 messages
    for msg in messages[-5:]:
        sender = "You" if msg.sender_id == user.id else "Partner"
        if msg.is_system:
            text += f"\n🔔 {msg.content}"
        else:
            text += f"\n<b>{sender}:</b> {msg.content}"
    
    text += f"\n{'━' * 20}"
    
    # Build action buttons based on status and role
    buttons = []
    
    if trade.status in [TradeStatus.PENDING, TradeStatus.AWAITING_PAYMENT]:
        if is_buyer:
            buttons.append([InlineKeyboardButton(
                text="💸 I've Paid",
                callback_data=f"p2p:paid:{trade.id[:8]}"
            )])
            buttons.append([InlineKeyboardButton(
                text="❌ Cancel Trade",
                callback_data=f"p2p:cancel_trade:{trade.id[:8]}"
            )])
    
    if trade.status == TradeStatus.PAYMENT_SENT:
        if not is_buyer:  # Seller
            buttons.append([InlineKeyboardButton(
                text="✅ Release Crypto",
                callback_data=f"p2p:release:{trade.id[:8]}"
            )])
        buttons.append([InlineKeyboardButton(
            text="⚠️ Open Dispute",
            callback_data=f"p2p:dispute:{trade.id[:8]}"
        )])
    
    if trade.status not in [TradeStatus.COMPLETED, TradeStatus.CANCELLED]:
        buttons.append([InlineKeyboardButton(
            text="🔄 Refresh",
            callback_data=f"p2p:chat:{trade.id[:8]}"
        )])
    
    buttons.append([InlineKeyboardButton(text="🔙 My Trades", callback_data="p2p:my_trades")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await safe_edit(callback.message, text, keyboard)
    await callback.answer()


# ==================== TRADE ACTIONS ====================

@router.callback_query(F.data.startswith("p2p:paid:"))
async def p2p_mark_paid(callback: CallbackQuery):
    """Buyer marks payment as sent"""
    trade_id_short = callback.data.split(":")[2]
    
    async with db_manager.session() as session:
        from sqlalchemy import select
        from database.models import P2PTrade
        
        result = await session.execute(
            select(P2PTrade).where(P2PTrade.id.like(f"{trade_id_short}%"))
        )
        trade = result.scalar_one_or_none()
        
        if not trade:
            await callback.answer("Trade not found", show_alert=True)
            return
        
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        
        success, message = await p2p_service.mark_payment_sent(
            session, trade.id, user.id
        )
        
        if success:
            await session.commit()
            await callback.answer("✅ Payment marked as sent!")
            # Refresh chat
            callback.data = f"p2p:chat:{trade_id_short}"
            await p2p_trade_chat(callback, None)
        else:
            await callback.answer(f"❌ {message}", show_alert=True)


@router.callback_query(F.data.startswith("p2p:release:"))
async def p2p_release_crypto(callback: CallbackQuery):
    """Seller releases crypto to buyer"""
    trade_id_short = callback.data.split(":")[2]
    
    # Confirmation step
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Yes, Release Crypto",
            callback_data=f"p2p:release_confirm:{trade_id_short}"
        )],
        [InlineKeyboardButton(
            text="❌ Cancel",
            callback_data=f"p2p:chat:{trade_id_short}"
        )]
    ])
    
    text = """
⚠️ <b>Confirm Release</b>

Are you sure you received the payment?

Once you release, crypto will be sent to the buyer.
<b>This action cannot be undone!</b>
"""
    
    await safe_edit(callback.message, text, keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("p2p:release_confirm:"))
async def p2p_release_confirm(callback: CallbackQuery):
    """Confirm crypto release"""
    trade_id_short = callback.data.split(":")[2]
    
    async with db_manager.session() as session:
        from sqlalchemy import select
        from database.models import P2PTrade
        
        result = await session.execute(
            select(P2PTrade).where(P2PTrade.id.like(f"{trade_id_short}%"))
        )
        trade = result.scalar_one_or_none()
        
        if not trade:
            await callback.answer("Trade not found", show_alert=True)
            return
        
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        
        success, message = await p2p_service.confirm_payment_received(
            session, trade.id, user.id
        )
        
        if success:
            await session.commit()
            await callback.answer("🎉 Trade completed!")
            
            text = """
🎉 <b>Trade Completed!</b>

Crypto has been released to the buyer.
Thank you for using NEXUS P2P!

Don't forget to leave a review.
"""
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⭐ Leave Review", callback_data=f"p2p:review:{trade_id_short}")],
                [InlineKeyboardButton(text="📋 My Trades", callback_data="p2p:my_trades")]
            ])
            await safe_edit(callback.message, text, keyboard)
        else:
            await callback.answer(f"❌ {message}", show_alert=True)


@router.callback_query(F.data.startswith("p2p:cancel_trade:"))
async def p2p_cancel_trade(callback: CallbackQuery):
    """Cancel a trade"""
    trade_id_short = callback.data.split(":")[2]
    
    async with db_manager.session() as session:
        from sqlalchemy import select
        from database.models import P2PTrade
        
        result = await session.execute(
            select(P2PTrade).where(P2PTrade.id.like(f"{trade_id_short}%"))
        )
        trade = result.scalar_one_or_none()
        
        if not trade:
            await callback.answer("Trade not found", show_alert=True)
            return
        
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        
        success, message = await p2p_service.cancel_trade(
            session, trade.id, user.id, "Cancelled by user"
        )
        
        if success:
            await session.commit()
            await callback.answer("Trade cancelled")
            
            text = """
❌ <b>Trade Cancelled</b>

The trade has been cancelled.
Funds have been returned to the seller.
"""
            keyboard = get_back_keyboard("p2p:my_trades")
            await safe_edit(callback.message, text, keyboard)
        else:
            await callback.answer(f"❌ {message}", show_alert=True)


@router.callback_query(F.data.startswith("p2p:dispute:"))
async def p2p_open_dispute(callback: CallbackQuery, state: FSMContext):
    """Open dispute for a trade"""
    trade_id_short = callback.data.split(":")[2]
    
    await state.update_data(dispute_trade_id=trade_id_short)
    
    text = """
⚠️ <b>Open Dispute</b>

Please describe the issue with this trade.
An admin will review your case.

Type your reason below:
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data=f"p2p:chat:{trade_id_short}")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await state.set_state(P2PStates.trade_chat)
    await callback.answer()


# ==================== PAYMENT METHODS ====================

@router.callback_query(F.data == "p2p:payments")
async def p2p_payment_methods(callback: CallbackQuery):
    """Show user's payment methods"""
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        methods = await p2p_service.get_user_payment_methods(session, user.id)
    
    if not methods:
        text = """
💳 <b>Payment Methods</b>

You haven't added any payment methods yet.
Add one to start trading on P2P market.
"""
    else:
        text = "💳 <b>Payment Methods</b>\n\n"
        
        for m in methods:
            verified = "✅" if m.is_verified else ""
            text += f"{m.icon} <b>{m.name}</b> {verified}\n"
            if m.bank_name:
                text += f"   🏦 {m.bank_name}\n"
            if m.account_number:
                text += f"   💳 {m.account_number}\n"
            text += "\n"
    
    buttons = [
        [InlineKeyboardButton(text="➕ Add Payment Method", callback_data="p2p:pm_add")],
    ]
    
    if methods:
        buttons.append([InlineKeyboardButton(
            text="🗑 Remove Method", 
            callback_data="p2p:pm_remove"
        )])
    
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="p2p:menu")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await safe_edit(callback.message, text, keyboard)
    await callback.answer()


@router.callback_query(F.data == "p2p:pm_add")
async def p2p_add_payment_method(callback: CallbackQuery, state: FSMContext):
    """Start adding payment method"""
    text = """
➕ <b>Add Payment Method</b>

Select the type of payment method:
"""
    
    await safe_edit(callback.message, text, get_payment_type_keyboard())
    await state.set_state(P2PStates.pm_type)
    await callback.answer()


@router.callback_query(P2PStates.pm_type, F.data.startswith("p2p:pm_type:"))
async def p2p_pm_type_selected(callback: CallbackQuery, state: FSMContext):
    """Payment type selected, ask for details"""
    pm_type = callback.data.split(":")[2]
    
    method_config = PAYMENT_METHOD_TYPES.get(pm_type)
    if not method_config:
        await callback.answer("Invalid type", show_alert=True)
        return
    
    await state.update_data(pm_type=pm_type, pm_fields={}, pm_field_index=0)
    
    fields = method_config['fields']
    
    if not fields:
        # No fields required, just add it
        await _save_payment_method(callback, state)
        return
    
    # Ask for first field
    field = fields[0]
    field_name = field.replace("_", " ").title()
    
    text = f"""
{method_config['icon']} <b>Add {method_config['name']}</b>

Enter your <b>{field_name}</b>:
"""
    
    await safe_edit(callback.message, text, get_cancel_keyboard())
    await state.set_state(P2PStates.pm_details)
    await callback.answer()


@router.message(P2PStates.pm_details)
async def p2p_pm_enter_details(message: Message, state: FSMContext):
    """Process payment method field input"""
    data = await state.get_data()
    pm_type = data['pm_type']
    pm_fields = data.get('pm_fields', {})
    field_index = data.get('pm_field_index', 0)
    
    method_config = PAYMENT_METHOD_TYPES.get(pm_type)
    fields = method_config['fields']
    
    # Save current field
    current_field = fields[field_index]
    pm_fields[current_field] = message.text.strip()
    
    # Validate if validator exists
    validators = method_config.get('validators', {})
    if current_field in validators:
        from services.p2p_service import PaymentValidator
        is_valid, error = PaymentValidator.validate_field(
            current_field, message.text.strip(), validators[current_field]
        )
        if not is_valid:
            await message.answer(f"❌ {error}\n\nTry again:", reply_markup=get_cancel_keyboard())
            return
    
    # Move to next field or finish
    field_index += 1
    
    if field_index >= len(fields):
        # All fields collected, save
        await state.update_data(pm_fields=pm_fields)
        await _finish_payment_method(message, state)
    else:
        # Ask for next field
        next_field = fields[field_index]
        field_name = next_field.replace("_", " ").title()
        
        await state.update_data(pm_fields=pm_fields, pm_field_index=field_index)
        
        text = f"""
{method_config['icon']} <b>Add {method_config['name']}</b>

Enter your <b>{field_name}</b>:
"""
        await message.answer(text, reply_markup=get_cancel_keyboard())


async def _finish_payment_method(message: Message, state: FSMContext):
    """Finish adding payment method"""
    data = await state.get_data()
    pm_type = data['pm_type']
    pm_fields = data['pm_fields']
    
    method_config = PAYMENT_METHOD_TYPES.get(pm_type)
    
    # Ask for custom name
    text = f"""
{method_config['icon']} <b>Almost done!</b>

Enter a name for this payment method (or send "skip"):

<i>Example: My Sberbank Card</i>
"""
    
    await message.answer(text, reply_markup=get_cancel_keyboard())
    await state.set_state(P2PStates.pm_name)


@router.message(P2PStates.pm_name)
async def p2p_pm_save(message: Message, state: FSMContext):
    """Save payment method"""
    data = await state.get_data()
    pm_type = data['pm_type']
    pm_fields = data['pm_fields']
    
    custom_name = message.text.strip()
    if custom_name.lower() == "skip":
        custom_name = None
    
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, message.from_user.id)
        
        method, errors = await p2p_service.add_payment_method(
            session=session,
            user_id=user.id,
            method_type=pm_type,
            name=custom_name,
            details=pm_fields
        )
        
        if errors:
            text = "❌ <b>Failed to add:</b>\n\n" + "\n".join(f"• {e}" for e in errors)
            await message.answer(text, reply_markup=get_back_keyboard("p2p:payments"))
        else:
            await session.commit()
            text = f"✅ <b>Payment method added!</b>\n\n{method.icon} {method.name}"
            await message.answer(text, reply_markup=get_back_keyboard("p2p:payments"))
    
    await state.clear()


@router.callback_query(F.data == "p2p:pm_remove")
async def p2p_remove_payment_select(callback: CallbackQuery):
    """Show payment methods to remove"""
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        methods = await p2p_service.get_user_payment_methods(session, user.id)
    
    if not methods:
        await callback.answer("No payment methods", show_alert=True)
        return
    
    buttons = []
    for m in methods:
        buttons.append([InlineKeyboardButton(
            text=f"🗑 {m.icon} {m.name}",
            callback_data=f"p2p:pm_del:{m.id[:8]}"
        )])
    
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="p2p:payments")])
    
    text = "🗑 <b>Remove Payment Method</b>\n\nSelect method to remove:"
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await safe_edit(callback.message, text, keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("p2p:pm_del:"))
async def p2p_delete_payment_method(callback: CallbackQuery):
    """Delete a payment method"""
    method_id_short = callback.data.split(":")[2]
    
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        
        # Find full ID
        from database.models import PaymentMethod
        result = await session.execute(
            select(PaymentMethod).where(
                PaymentMethod.id.like(f"{method_id_short}%"),
                PaymentMethod.user_id == user.id
            )
        )
        method = result.scalar_one_or_none()
        
        if not method:
            await callback.answer("Method not found", show_alert=True)
            return
        
        success = await p2p_service.delete_payment_method(session, user.id, method.id)
        
        if success:
            await session.commit()
            await callback.answer("✅ Deleted!")
            # Refresh list
            await p2p_payment_methods(callback)
        else:
            await callback.answer("❌ Failed to delete", show_alert=True)


# ==================== USER PROFILE ====================

@router.callback_query(F.data == "p2p:profile")
async def p2p_user_profile(callback: CallbackQuery):
    """Show user's P2P profile"""
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        stats = await p2p_service.get_user_p2p_stats(session, user.id)
    
    verified = "✅ Verified Merchant" if stats['is_verified'] else "❌ Not Verified"
    vip = f"⭐ VIP {stats['vip_tier']}" if stats['vip_tier'] > 0 else ""
    
    text = f"""
👤 <b>P2P Profile</b>

<b>@{stats['username'] or 'Anonymous'}</b> {vip}
{verified}

📊 <b>Trading Stats:</b>
├ Rating: ⭐ <b>{stats['rating']:.1f}</b>/100
├ Trust Score: <b>{stats['trust_score']:.1f}%</b>
├ Total Trades: <b>{stats['total_trades']}</b>
├ Successful: <b>{stats['successful_trades']}</b> ✅
├ Cancelled: <b>{stats['cancelled_trades']}</b> ❌
├ Disputed: <b>{stats['disputed_trades']}</b> ⚠️
└ Success Rate: <b>{stats['success_rate']}%</b>

💰 <b>Volume:</b>
└ Total: <b>${stats['total_volume_usd']:,.2f}</b>

📈 <b>Activity:</b>
├ Active Orders: <b>{stats['active_orders']}</b>
├ Active Trades: <b>{stats['active_trades']}</b>
└ Completed: <b>{stats['completed_trades']}</b>

⭐ <b>Reviews:</b>
├ 👍 Positive: <b>{stats['positive_reviews']}</b>
└ 👎 Negative: <b>{stats['negative_reviews']}</b>

📅 Member since: {stats['member_since']}
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Full Statistics", callback_data="p2p:full_stats")],
        [InlineKeyboardButton(text="⭐ My Reviews", callback_data="p2p:my_reviews")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="p2p:menu")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await callback.answer()


@router.callback_query(F.data == "p2p:full_stats")
async def p2p_full_stats(callback: CallbackQuery):
    """Show detailed statistics (SQLite compatible)"""
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        
        # 1. Простая статистика по сетям
        from database.models import P2PTrade
        
        # Получаем все сделки пользователя
        trades_result = await session.execute(
            select(P2PTrade)
            .where(
                or_(P2PTrade.buyer_id == user.id, P2PTrade.seller_id == user.id),
                P2PTrade.status == TradeStatus.COMPLETED
            )
        )
        all_trades = trades_result.scalars().all()
        
        # Считаем в Python (чтобы не зависеть от типа БД)
        network_stats = {}
        monthly_stats = {}
        
        for trade in all_trades:
            # По сетям
            net = trade.network
            if net not in network_stats:
                network_stats[net] = {"count": 0, "volume": 0.0}
            network_stats[net]["count"] += 1
            network_stats[net]["volume"] += float(trade.fiat_amount)
            
            # По месяцам
            month_key = trade.completed_at.strftime("%b %Y")
            if month_key not in monthly_stats:
                monthly_stats[month_key] = {"count": 0, "volume": 0.0}
            monthly_stats[month_key]["count"] += 1
            monthly_stats[month_key]["volume"] += float(trade.fiat_amount)
    
    text = "📊 <b>Full Statistics</b>\n\n"
    
    text += "<b>By Network:</b>\n"
    if network_stats:
        for net, data in network_stats.items():
            crypto = SUPPORTED_CRYPTOS.get(net, {})
            text += f"{crypto.get('icon', '🔗')} {net}: {data['count']} trades | ${data['volume']:,.0f}\n"
    else:
        text += "<i>No completed trades yet</i>\n"
    
    text += "\n<b>Monthly History:</b>\n"
    if monthly_stats:
        # Сортируем (просто по ключам для примера)
        for month, data in monthly_stats.items():
            text += f"📅 {month}: {data['count']} trades | ${data['volume']:,.0f}\n"
    else:
        text += "<i>No data available</i>\n"
    
    keyboard = get_back_keyboard("p2p:profile")
    await safe_edit(callback.message, text, keyboard)
    await callback.answer()


@router.callback_query(F.data == "p2p:my_reviews")
async def p2p_my_reviews(callback: CallbackQuery):
    """Show user's received reviews"""
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        
        from database.models import Review
        result = await session.execute(
            select(Review)
            .where(Review.reviewed_id == user.id)
            .order_by(Review.created_at.desc())
            .limit(20)
        )
        reviews = result.scalars().all()
    
    if not reviews:
        text = "⭐ <b>My Reviews</b>\n\nNo reviews yet."
    else:
        text = "⭐ <b>My Reviews</b>\n\n"
        for r in reviews:
            emoji = "👍" if r.is_positive else "👎"
            stars = "⭐" * r.rating
            text += f"{emoji} {stars}\n"
            if r.comment:
                text += f"   <i>\"{r.comment[:50]}...\"</i>\n"
            text += f"   {r.created_at.strftime('%Y-%m-%d')}\n\n"
    
    keyboard = get_back_keyboard("p2p:profile")
    await safe_edit(callback.message, text, keyboard)
    await callback.answer()


# ==================== CREATE ORDER ====================

@router.callback_query(F.data == "p2p:create:choose")
async def p2p_create_choose_type(callback: CallbackQuery):
    """Choose order type to create"""
    text = """
➕ <b>Create Order</b>

What type of order do you want to create?
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Buy Order", callback_data="p2p:create:buy"),
            InlineKeyboardButton(text="💸 Sell Order", callback_data="p2p:create:sell")
        ],
        [InlineKeyboardButton(text="🔙 Back", callback_data="p2p:my_orders")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("p2p:create:"))
async def p2p_create_start(callback: CallbackQuery, state: FSMContext):
    """Start order creation"""
    order_type = callback.data.split(":")[2]
    
    if order_type not in ["buy", "sell"]:
        await callback.answer("Invalid type", show_alert=True)
        return
    
    await state.update_data(create_type=order_type)
    
    type_text = "Buy" if order_type == "buy" else "Sell"
    
    text = f"""
➕ <b>Create {type_text} Order</b>

Select the cryptocurrency:
"""
    
    await safe_edit(callback.message, text, get_crypto_keyboard(f"p2p:cr_c"))
    await state.set_state(P2PStates.create_crypto)
    await callback.answer()


@router.callback_query(P2PStates.create_crypto, F.data.startswith("p2p:cr_c:"))
async def p2p_create_select_fiat(callback: CallbackQuery, state: FSMContext):
    """Select fiat for order creation"""
    network = callback.data.split(":")[2]
    crypto = SUPPORTED_CRYPTOS.get(network)
    
    if not crypto:
        await callback.answer("Invalid", show_alert=True)
        return
    
    await state.update_data(network=network, token_symbol=crypto['symbol'])
    
    text = f"""
{crypto['icon']} <b>{crypto['symbol']}</b>

Select your fiat currency:
"""
    
    await safe_edit(callback.message, text, get_fiat_keyboard("p2p:cr_f"))
    await state.set_state(P2PStates.create_fiat)
    await callback.answer()


@router.callback_query(P2PStates.create_fiat, F.data.startswith("p2p:cr_f:"))
async def p2p_create_enter_amount(callback: CallbackQuery, state: FSMContext):
    """Enter amount for order"""
    fiat = callback.data.split(":")[2]
    data = await state.get_data()
    
    await state.update_data(fiat=fiat)
    
    crypto = SUPPORTED_CRYPTOS.get(data['network'], {})
    order_type = data['create_type']
    
    text = f"""
{crypto.get('icon', '')} <b>{data['token_symbol']}</b> / {fiat}

Enter the total amount of <b>{data['token_symbol']}</b> you want to {order_type}:

<i>Example: 0.5</i>
"""
    
    await safe_edit(callback.message, text, get_cancel_keyboard())
    await state.set_state(P2PStates.create_amount)
    await callback.answer()


@router.message(P2PStates.create_amount)
async def p2p_create_enter_price(message: Message, state: FSMContext):
    """Enter price per unit"""
    try:
        amount = Decimal(message.text.strip().replace(",", "."))
        if amount <= 0:
            raise ValueError()
    except:
        await message.answer("❌ Invalid amount. Enter a positive number:", reply_markup=get_cancel_keyboard())
        return
    
    data = await state.get_data()
    await state.update_data(amount=str(amount))
    
    # Get current market price for reference
    try:
        from services.price_service import price_service
        market_price = await price_service.get_price(data['token_symbol'])
        price_hint = f"\n\n💡 Current market price: ~{float(market_price):,.2f} {data['fiat']}"
    except:
        price_hint = ""
    
    text = f"""
📊 <b>Set Your Price</b>

Amount: <b>{amount} {data['token_symbol']}</b>
Currency: <b>{data['fiat']}</b>

Enter your price per 1 {data['token_symbol']} in {data['fiat']}:{price_hint}

<i>Example: 2500.50</i>
"""
    
    await message.answer(text, reply_markup=get_cancel_keyboard())
    await state.set_state(P2PStates.create_price)


@router.message(P2PStates.create_price)
async def p2p_create_enter_limits(message: Message, state: FSMContext):
    """Enter min/max limits"""
    try:
        price = Decimal(message.text.strip().replace(",", "."))
        if price <= 0:
            raise ValueError()
    except:
        await message.answer("❌ Invalid price. Enter a positive number:", reply_markup=get_cancel_keyboard())
        return
    
    data = await state.get_data()
    await state.update_data(price=str(price))
    
    amount = Decimal(data['amount'])
    total_value = amount * price
    
    text = f"""
📊 <b>Set Trade Limits</b>

Your order: <b>{amount} {data['token_symbol']}</b>
Price: <b>{price:,.2f} {data['fiat']}</b>
Total value: <b>{total_value:,.2f} {data['fiat']}</b>

Enter minimum and maximum trade limits in {data['fiat']}:
Format: <code>min-max</code>

<i>Example: 100-5000</i>
"""
    
    await message.answer(text, reply_markup=get_cancel_keyboard())
    await state.set_state(P2PStates.create_limits)


@router.message(P2PStates.create_limits)
async def p2p_create_select_payment(message: Message, state: FSMContext):
    """Select payment methods for order"""
    text_input = message.text.strip().replace(" ", "")
    
    try:
        parts = text_input.split("-")
        min_limit = Decimal(parts[0])
        max_limit = Decimal(parts[1])
        
        if min_limit <= 0 or max_limit <= 0 or min_limit > max_limit:
            raise ValueError()
    except:
        await message.answer(
            "❌ Invalid format. Use: min-max\nExample: 100-5000",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await state.update_data(min_limit=str(min_limit), max_limit=str(max_limit))
    
    # Get user's payment methods
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, message.from_user.id)
        methods = await p2p_service.get_user_payment_methods(session, user.id)
    
    if not methods:
        text = """
❌ <b>No Payment Methods</b>

You need to add at least one payment method before creating an order.
"""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Add Payment Method", callback_data="p2p:pm_add")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="p2p:menu")]
        ])
        await message.answer(text, reply_markup=keyboard)
        await state.clear()
        return
    
    # Store methods for selection
    await state.update_data(
        available_methods=[{"id": m.id, "name": m.name, "icon": m.icon} for m in methods],
        selected_methods=[]
    )
    
    text = """
💳 <b>Select Payment Methods</b>

Choose which payment methods you accept:
<i>(You can select multiple)</i>
"""
    
    buttons = []
    for m in methods:
        buttons.append([InlineKeyboardButton(
            text=f"⬜ {m.icon} {m.name}",
            callback_data=f"p2p:cr_pm:{m.id[:8]}"
        )])
    
    buttons.append([InlineKeyboardButton(text="✅ Done", callback_data="p2p:cr_pm_done")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="p2p:menu")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard)
    await state.set_state(P2PStates.create_payment)


@router.callback_query(P2PStates.create_payment, F.data.startswith("p2p:cr_pm:"))
async def p2p_create_toggle_payment(callback: CallbackQuery, state: FSMContext):
    """Toggle payment method selection"""
    method_id_short = callback.data.split(":")[2]
    data = await state.get_data()
    
    selected = data.get('selected_methods', [])
    available = data.get('available_methods', [])
    
    # Find full method
    full_method = None
    for m in available:
        if m['id'].startswith(method_id_short):
            full_method = m
            break
    
    if not full_method:
        await callback.answer("Method not found", show_alert=True)
        return
    
    # Toggle selection
    if full_method['id'] in selected:
        selected.remove(full_method['id'])
    else:
        selected.append(full_method['id'])
    
    await state.update_data(selected_methods=selected)
    
    # Rebuild keyboard
    buttons = []
    for m in available:
        is_selected = m['id'] in selected
        prefix = "✅" if is_selected else "⬜"
        buttons.append([InlineKeyboardButton(
            text=f"{prefix} {m['icon']} {m['name']}",
            callback_data=f"p2p:cr_pm:{m['id'][:8]}"
        )])
    
    buttons.append([InlineKeyboardButton(text="✅ Done", callback_data="p2p:cr_pm_done")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="p2p:menu")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except:
        pass
    
    await callback.answer()


@router.callback_query(P2PStates.create_payment, F.data == "p2p:cr_pm_done")
async def p2p_create_confirm(callback: CallbackQuery, state: FSMContext):
    """Show order confirmation"""
    data = await state.get_data()
    selected = data.get('selected_methods', [])
    
    if not selected:
        await callback.answer("Select at least one payment method", show_alert=True)
        return
    
    crypto = SUPPORTED_CRYPTOS.get(data['network'], {})
    fiat_info = SUPPORTED_FIATS.get(data['fiat'], {})
    
    amount = Decimal(data['amount'])
    price = Decimal(data['price'])
    total_value = amount * price
    
    order_type = data['create_type'].upper()
    
    # Get method names
    available = data.get('available_methods', [])
    method_names = [m['name'] for m in available if m['id'] in selected]
    
    text = f"""
✅ <b>Confirm Order</b>

<b>Type:</b> {order_type}
<b>Crypto:</b> {crypto.get('icon', '')} {data['token_symbol']}
<b>Amount:</b> {amount} {data['token_symbol']}
<b>Price:</b> {price:,.2f} {data['fiat']}
<b>Total:</b> {total_value:,.2f} {data['fiat']}
<b>Limits:</b> {data['min_limit']} - {data['max_limit']} {data['fiat']}

<b>Payment Methods:</b>
{chr(10).join('• ' + n for n in method_names)}

Create this order?
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Create Order", callback_data="p2p:cr_confirm")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="p2p:menu")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await state.set_state(P2PStates.create_confirm)
    await callback.answer()


@router.callback_query(P2PStates.create_confirm, F.data == "p2p:cr_confirm")
async def p2p_create_execute(callback: CallbackQuery, state: FSMContext):
    """Execute order creation"""
    data = await state.get_data()
    
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        
        order, errors = await p2p_service.create_order(
            session=session,
            user_id=user.id,
            order_type=data['create_type'],
            network=data['network'],
            token_symbol=data['token_symbol'],
            total_amount=Decimal(data['amount']),
            price_per_unit=Decimal(data['price']),
            fiat_currency=data['fiat'],
            min_limit=Decimal(data['min_limit']),
            max_limit=Decimal(data['max_limit']),
            payment_method_ids=data['selected_methods']
        )
        
        if errors:
            text = "❌ <b>Failed to create order:</b>\n\n" + "\n".join(f"• {e}" for e in errors)
            keyboard = get_back_keyboard("p2p:menu")
        else:
            await session.commit()
            
            text = f"""
🎉 <b>Order Created!</b>

Your {data['create_type']} order is now live.
Order ID: <code>{order.id[:8]}</code>

Other users can now trade with you.
You'll be notified when someone starts a trade.
"""
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 My Orders", callback_data="p2p:my_orders")],
                [InlineKeyboardButton(text="🔙 P2P Menu", callback_data="p2p:menu")]
            ])
    
    await safe_edit(callback.message, text, keyboard)
    await state.clear()
    await callback.answer()


# ==================== MARKET STATS ====================

@router.callback_query(F.data == "p2p:stats")
async def p2p_market_stats(callback: CallbackQuery):
    """Show market statistics"""
    async with db_manager.session() as session:
        stats = await p2p_service.get_market_stats(session)
        
        # Get top traders
        from database.models import User
        top_traders = await session.execute(
            select(User)
            .where(User.total_trades_count > 0)
            .order_by(desc(User.total_volume_usd))
            .limit(5)
        )
        top = top_traders.scalars().all()
    
    text = f"""
📊 <b>P2P Market Statistics</b>

<b>Current Activity:</b>
├ Active Orders: <b>{stats['active_orders']}</b>
├ Active Traders: <b>{stats['active_traders']}</b>
└ 24h Trades: <b>{stats['trades_24h']}</b>

💰 <b>24h Volume:</b> <b>${stats['volume_24h_usd']:,.0f}</b>

🏆 <b>Top Traders:</b>
"""
    
    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    for i, trader in enumerate(top):
        verified = "✅" if trader.merchant_verified else ""
        text += f"{medals[i]} @{trader.username or 'Anonymous'} {verified}\n"
        text += f"   ${float(trader.total_volume_usd):,.0f} | {trader.total_trades_count} trades\n"
    
    keyboard = get_back_keyboard("p2p:menu")
    await safe_edit(callback.message, text, keyboard)
    await callback.answer()


# ==================== HELP ====================

@router.callback_query(F.data == "p2p:help")
async def p2p_help(callback: CallbackQuery):
    """Show P2P help"""
    text = """
❓ <b>P2P Trading Help</b>

<b>What is P2P?</b>
P2P (Peer-to-Peer) allows you to buy and sell crypto directly with other users using your preferred payment methods.

<b>How it works:</b>

<b>Buying Crypto:</b>
1. Select "Buy Crypto"
2. Choose cryptocurrency and currency
3. Pick a seller from the list
4. Enter amount and confirm
5. Pay the seller via their payment method
6. Click "I've Paid"
7. Receive crypto after seller confirms

<b>Selling Crypto:</b>
1. Add your payment methods
2. Create a sell order
3. Wait for buyers
4. When buyer pays, confirm receipt
5. Crypto is released automatically

<b>Safety Tips:</b>
• Never share your seed phrase
• Only trade within the platform
• Check trader ratings before trading
• Open dispute if something goes wrong
• Keep payment proofs

<b>Escrow Protection:</b>
When a trade starts, seller's crypto is locked in escrow. It's released to buyer only after seller confirms payment.
"""
    
    keyboard = get_back_keyboard("p2p:menu")
    await safe_edit(callback.message, text, keyboard)
    await callback.answer()


# ==================== CANCEL STATE ====================

@router.callback_query(F.data == "p2p:cancel")
async def p2p_cancel_state(callback: CallbackQuery, state: FSMContext):
    """Cancel current operation"""
    await state.clear()
    await p2p_main_menu(callback, state)


# ==================== UTILITIES ====================

async def safe_edit(message, text: str, keyboard: InlineKeyboardMarkup = None):
    """Safely edit message"""
    try:
        await message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.warning("Edit failed", error=str(e))
    except Exception as e:
        logger.error("Edit error", error=str(e))


# ==================== NOTIFICATIONS (для внешнего вызова) ====================

async def notify_trade_partner(bot: Bot, trade_id: str, message: str):
    """Send notification to trade partner"""
    async with db_manager.session() as session:
        trade = await p2p_service.get_trade_by_id(session, trade_id)
        if not trade:
            return
        
        # Notify both parties
        for user_id in [trade.buyer_id, trade.seller_id]:
            user = await session.get(User, user_id)
            if user and user.notifications_enabled:
                try:
                    await bot.send_message(
                        user.telegram_id,
                        message,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.warning("Notification failed", user_id=user_id, error=str(e))
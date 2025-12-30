"""
NEXUS WALLET - P2P Trading Handler
Real P2P trading with database storage and escrow
"""

import json
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import structlog

from database.connection import db_manager
from database.repositories.user_repository import UserRepository
from database.repositories.wallet_repository import WalletRepository
from database.models import P2POrder, P2PTrade
from blockchain.wallet_manager import NETWORKS
from services.p2p_service import p2p_service, PAYMENT_METHODS
from services.price_service import price_service
from locales.messages import get_text
from keyboards.inline import get_back_keyboard

logger = structlog.get_logger()
router = Router(name="p2p")


class P2PStates(StatesGroup):
    # Create order
    selecting_order_type = State()
    selecting_crypto = State()
    entering_amount = State()
    entering_price = State()
    selecting_fiat = State()
    selecting_payment = State()
    entering_terms = State()
    confirming_order = State()
    # Trade
    entering_trade_amount = State()
    confirming_trade = State()
    # Chat
    in_trade_chat = State()


# Supported cryptos for P2P
P2P_CRYPTOS = ["USDT", "BTC", "ETH", "BNB", "USDC"]

# Supported fiats
FIAT_CURRENCIES = {
    "USD": "🇺🇸 USD",
    "EUR": "🇪🇺 EUR",
    "RUB": "🇷🇺 RUB",
    "UAH": "🇺🇦 UAH",
    "CNY": "🇨🇳 CNY",
    "TRY": "🇹🇷 TRY",
    "GBP": "🇬🇧 GBP",
    "AED": "🇦🇪 AED",
}


async def get_user_and_lang(callback_or_message) -> tuple:
    """Helper to get user and language"""
    user_id = callback_or_message.from_user.id
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, user_id)
        lang = user.language_code if user else "en"
        return user, lang


@router.callback_query(F.data == "p2p")
async def p2p_menu(callback: CallbackQuery, state: FSMContext):
    """Show P2P main menu"""
    await state.clear()
    user, lang = await get_user_and_lang(callback)
    
    text = get_text("p2p_menu", lang)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="💰 " + get_text("p2p_buy", lang),
                callback_data="p2p:buy"
            ),
            InlineKeyboardButton(
                text="💸 " + get_text("p2p_sell", lang),
                callback_data="p2p:sell"
            ),
        ],
        [
            InlineKeyboardButton(
                text="📋 " + get_text("p2p_my_orders", lang),
                callback_data="p2p:my_orders"
            ),
            InlineKeyboardButton(
                text="🔄 " + get_text("p2p_my_trades", lang),
                callback_data="p2p:my_trades"
            ),
        ],
        [
            InlineKeyboardButton(
                text="➕ " + get_text("p2p_create_order", lang),
                callback_data="p2p:create"
            ),
        ],
        [
            InlineKeyboardButton(
                text=get_text("btn_back", lang),
                callback_data="main_menu"
            )
        ]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()


# ==================== BROWSE ORDERS ====================

@router.callback_query(F.data == "p2p:buy")
async def p2p_buy_list(callback: CallbackQuery, state: FSMContext):
    """Show sell orders (user wants to buy)"""
    user, lang = await get_user_and_lang(callback)
    await state.update_data(lang=lang, action="buy")
    
    async with db_manager.session() as session:
        # Get active sell orders (excluding user's own)
        orders = await p2p_service.get_active_orders(
            session,
            order_type="sell",
            exclude_user_id=user.id if user else None,
            limit=20
        )
        
        if not orders:
            text = "💰 <b>Buy Crypto</b>\n\n"
            text += "📭 No sell orders available.\n\n"
            text += "Check back later or create your own buy order!"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="➕ Create Buy Order",
                    callback_data="p2p:create:buy"
                )],
                [InlineKeyboardButton(
                    text=get_text("btn_back", lang),
                    callback_data="p2p"
                )]
            ])
        else:
            text = "💰 <b>Buy Crypto</b>\n\n"
            text += f"📋 {len(orders)} offers available:\n\n"
            
            buttons = []
            for order in orders[:10]:
                # Get seller info
                seller_info = await p2p_service.get_user_with_stats(session, order.user_id)
                seller_name = seller_info["username"] or f"User#{order.user_id}"
                rating = seller_info["rating"]
                trades = seller_info["total_trades"]
                
                # Format order info
                text += f"👤 <b>{seller_name}</b> ⭐ {rating:.0f}% ({trades} trades)\n"
                text += f"   💎 {order.token_symbol} @ {order.price_per_unit:,.2f} {order.fiat_currency}\n"
                text += f"   📊 {order.min_trade_amount or 0:.0f} - {order.max_trade_amount or order.available_amount:.0f} {order.fiat_currency}\n"
                
                methods = json.loads(order.payment_methods)
                method_icons = " ".join([PAYMENT_METHODS.get(m, {}).get("icon", "💳") for m in methods[:3]])
                text += f"   {method_icons}\n\n"
                
                buttons.append([InlineKeyboardButton(
                    text=f"Buy {order.token_symbol} from {seller_name}",
                    callback_data=f"p2p:order:{order.id}"
                )])
            
            buttons.append([InlineKeyboardButton(
                text=get_text("btn_back", lang),
                callback_data="p2p"
            )])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "p2p:sell")
async def p2p_sell_list(callback: CallbackQuery, state: FSMContext):
    """Show buy orders (user wants to sell)"""
    user, lang = await get_user_and_lang(callback)
    await state.update_data(lang=lang, action="sell")
    
    async with db_manager.session() as session:
        orders = await p2p_service.get_active_orders(
            session,
            order_type="buy",
            exclude_user_id=user.id if user else None,
            limit=20
        )
        
        if not orders:
            text = "💸 <b>Sell Crypto</b>\n\n"
            text += "📭 No buy orders available.\n\n"
            text += "Check back later or create your own sell order!"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="➕ Create Sell Order",
                    callback_data="p2p:create:sell"
                )],
                [InlineKeyboardButton(
                    text=get_text("btn_back", lang),
                    callback_data="p2p"
                )]
            ])
        else:
            text = "💸 <b>Sell Crypto</b>\n\n"
            text += f"📋 {len(orders)} offers available:\n\n"
            
            buttons = []
            for order in orders[:10]:
                buyer_info = await p2p_service.get_user_with_stats(session, order.user_id)
                buyer_name = buyer_info["username"] or f"User#{order.user_id}"
                rating = buyer_info["rating"]
                trades = buyer_info["total_trades"]
                
                text += f"👤 <b>{buyer_name}</b> ⭐ {rating:.0f}% ({trades} trades)\n"
                text += f"   💎 {order.token_symbol} @ {order.price_per_unit:,.2f} {order.fiat_currency}\n"
                text += f"   📊 {order.min_trade_amount or 0:.0f} - {order.max_trade_amount or order.available_amount:.0f} {order.fiat_currency}\n"
                
                methods = json.loads(order.payment_methods)
                method_icons = " ".join([PAYMENT_METHODS.get(m, {}).get("icon", "💳") for m in methods[:3]])
                text += f"   {method_icons}\n\n"
                
                buttons.append([InlineKeyboardButton(
                    text=f"Sell {order.token_symbol} to {buyer_name}",
                    callback_data=f"p2p:order:{order.id}"
                )])
            
            buttons.append([InlineKeyboardButton(
                text=get_text("btn_back", lang),
                callback_data="p2p"
            )])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()


# ==================== VIEW ORDER ====================

@router.callback_query(F.data.startswith("p2p:order:"))
async def view_order(callback: CallbackQuery, state: FSMContext):
    """View order details"""
    order_id = callback.data.split(":")[2]
    user, lang = await get_user_and_lang(callback)
    
    async with db_manager.session() as session:
        order = await p2p_service.get_order(session, order_id)
        
        if not order:
            await callback.answer("Order not found", show_alert=True)
            return
        
        trader_info = await p2p_service.get_user_with_stats(session, order.user_id)
        trader_name = trader_info["username"] or f"User#{order.user_id}"
        
        action = "Buy from" if order.order_type == "sell" else "Sell to"
        
        text = f"📋 <b>Order Details</b>\n\n"
        text += f"👤 Trader: <b>{trader_name}</b>\n"
        text += f"⭐ Rating: {trader_info['rating']:.0f}% ({trader_info['total_trades']} trades)\n\n"
        text += f"💎 {action}: <b>{order.token_symbol}</b>\n"
        text += f"💵 Price: <b>{order.price_per_unit:,.2f} {order.fiat_currency}</b>\n"
        text += f"📊 Available: <b>{order.available_amount:.4f} {order.token_symbol}</b>\n"
        text += f"📏 Limits: {order.min_trade_amount or 0:,.0f} - {order.max_trade_amount or order.available_amount:,.0f} {order.fiat_currency}\n\n"
        
        text += "🏦 <b>Payment Methods:</b>\n"
        methods = json.loads(order.payment_methods)
        for m in methods:
            info = PAYMENT_METHODS.get(m, {"name": m, "icon": "💳"})
            text += f"   {info['icon']} {info['name']}\n"
        
        if order.terms:
            text += f"\n📝 <b>Terms:</b>\n{order.terms}\n"
        
        text += f"\n⏱ Time limit: {order.time_limit_minutes} minutes"
        
        await state.update_data(order_id=order_id, lang=lang)
        
        # Check if it's user's own order
        if user and order.user_id == user.id:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="❌ Cancel Order",
                    callback_data=f"p2p:cancel_order:{order_id}"
                )],
                [InlineKeyboardButton(
                    text=get_text("btn_back", lang),
                    callback_data="p2p:my_orders"
                )]
            ])
        else:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"✅ {action} {trader_name}",
                    callback_data=f"p2p:start_trade:{order_id}"
                )],
                [InlineKeyboardButton(
                    text=get_text("btn_back", lang),
                    callback_data="p2p:buy" if order.order_type == "sell" else "p2p:sell"
                )]
            ])
        
        try:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass
    await callback.answer()


# ==================== START TRADE ====================

@router.callback_query(F.data.startswith("p2p:start_trade:"))
async def start_trade(callback: CallbackQuery, state: FSMContext):
    """Start a trade"""
    order_id = callback.data.split(":")[2]
    user, lang = await get_user_and_lang(callback)
    
    async with db_manager.session() as session:
        order = await p2p_service.get_order(session, order_id)
        
        if not order or order.status != "active":
            await callback.answer("Order not available", show_alert=True)
            return
        
        methods = json.loads(order.payment_methods)
        
        await state.update_data(
            order_id=order_id,
            order_type=order.order_type,
            token=order.token_symbol,
            fiat=order.fiat_currency,
            price=str(order.price_per_unit),
            available=str(order.available_amount),
            min_amount=str(order.min_trade_amount or 0),
            max_amount=str(order.max_trade_amount or order.available_amount),
            payment_methods=methods,
            lang=lang
        )
        
        text = f"💱 <b>Start Trade</b>\n\n"
        text += f"💎 {order.token_symbol} @ {order.price_per_unit:,.2f} {order.fiat_currency}\n"
        text += f"📊 Limits: {order.min_trade_amount or 0:,.0f} - {order.max_trade_amount or order.available_amount:,.0f} {order.fiat_currency}\n\n"
        text += f"Enter amount in <b>{order.fiat_currency}</b>:"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=get_text("btn_cancel", lang),
                callback_data=f"p2p:order:{order_id}"
            )]
        ])
        
        try:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass
        
        await state.set_state(P2PStates.entering_trade_amount)
    await callback.answer()


@router.message(P2PStates.entering_trade_amount)
async def process_trade_amount(message: Message, state: FSMContext):
    """Process trade amount"""
    data = await state.get_data()
    lang = data.get("lang", "en")
    
    try:
        fiat_amount = Decimal(message.text.strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        await message.answer("❌ Invalid amount. Please enter a number:")
        return
    
    min_amount = Decimal(data.get("min_amount", "0"))
    max_amount = Decimal(data.get("max_amount", "999999999"))
    fiat = data.get("fiat", "USD")
    
    if fiat_amount < min_amount or fiat_amount > max_amount:
        await message.answer(
            f"❌ Amount must be between {min_amount:,.0f} and {max_amount:,.0f} {fiat}"
        )
        return
    
    price = Decimal(data.get("price", "1"))
    crypto_amount = fiat_amount / price
    token = data.get("token", "USDT")
    order_type = data.get("order_type", "sell")
    
    await state.update_data(
        fiat_amount=str(fiat_amount),
        crypto_amount=str(crypto_amount)
    )
    
    # Select payment method
    methods = data.get("payment_methods", [])
    
    if len(methods) == 1:
        # Only one method, skip selection
        await state.update_data(selected_payment=methods[0])
        await show_trade_confirmation(message, state)
    else:
        text = f"💳 <b>Select Payment Method</b>\n\n"
        text += f"💎 {crypto_amount:.6f} {token}\n"
        text += f"💵 {fiat_amount:,.2f} {fiat}\n\n"
        text += "Choose how you'll pay/receive:"
        
        buttons = []
        for m in methods:
            info = PAYMENT_METHODS.get(m, {"name": m, "icon": "💳"})
            buttons.append([InlineKeyboardButton(
                text=f"{info['icon']} {info['name']}",
                callback_data=f"p2p:payment:{m}"
            )])
        
        buttons.append([InlineKeyboardButton(
            text=get_text("btn_cancel", lang),
            callback_data="p2p"
        )])
        
        await message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("p2p:payment:"))
async def select_payment_method(callback: CallbackQuery, state: FSMContext):
    """Select payment method"""
    payment = callback.data.split(":")[2]
    await state.update_data(selected_payment=payment)
    await show_trade_confirmation(callback.message, state)
    await callback.answer()


async def show_trade_confirmation(message, state: FSMContext):
    """Show trade confirmation"""
    data = await state.get_data()
    lang = data.get("lang", "en")
    order_type = data.get("order_type", "sell")
    token = data.get("token", "USDT")
    fiat = data.get("fiat", "USD")
    crypto_amount = Decimal(data.get("crypto_amount", "0"))
    fiat_amount = Decimal(data.get("fiat_amount", "0"))
    price = Decimal(data.get("price", "1"))
    payment = data.get("selected_payment", "bank_transfer")
    payment_info = PAYMENT_METHODS.get(payment, {"name": payment, "icon": "💳"})
    
    action = "Buy" if order_type == "sell" else "Sell"
    
    text = f"📋 <b>Confirm Trade</b>\n\n"
    text += f"💎 {action}: <b>{crypto_amount:.6f} {token}</b>\n"
    text += f"💵 For: <b>{fiat_amount:,.2f} {fiat}</b>\n"
    text += f"💹 Rate: {price:,.2f} {fiat}/{token}\n"
    text += f"💳 Payment: {payment_info['icon']} {payment_info['name']}\n\n"
    text += "🔒 Crypto will be held in escrow until payment is confirmed."
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Confirm", callback_data="p2p:confirm_trade"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="p2p"),
        ]
    ])
    
    if hasattr(message, 'edit_text'):
        await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    
    await state.set_state(P2PStates.confirming_trade)


@router.callback_query(F.data == "p2p:confirm_trade", P2PStates.confirming_trade)
async def confirm_trade(callback: CallbackQuery, state: FSMContext):
    """Confirm and create trade"""
    data = await state.get_data()
    lang = data.get("lang", "en")
    user, _ = await get_user_and_lang(callback)
    
    order_id = data.get("order_id")
    crypto_amount = Decimal(data.get("crypto_amount", "0"))
    payment = data.get("selected_payment", "bank_transfer")
    
    async with db_manager.session() as session:
        try:
            trade = await p2p_service.create_trade(
                session,
                order_id=order_id,
                initiator_id=user.id,
                crypto_amount=crypto_amount,
                payment_method=payment
            )
            await session.commit()
            
            order = await p2p_service.get_order(session, order_id)
            other_user_id = order.user_id
            other_info = await p2p_service.get_user_with_stats(session, other_user_id)
            other_name = other_info["username"] or f"User#{other_user_id}"
            
            action = "buying from" if order.order_type == "sell" else "selling to"
            
            text = f"✅ <b>Trade Created!</b>\n\n"
            text += f"🆔 Trade ID: <code>{trade.id[:8]}</code>\n"
            text += f"👤 You are {action}: <b>{other_name}</b>\n\n"
            text += f"💎 Amount: <b>{trade.crypto_amount:.6f} {trade.token_symbol}</b>\n"
            text += f"💵 Total: <b>{trade.fiat_amount:,.2f} {trade.fiat_currency}</b>\n\n"
            
            if order.order_type == "sell":
                text += "📝 <b>Next Steps:</b>\n"
                text += "1️⃣ Contact seller for payment details\n"
                text += "2️⃣ Send payment\n"
                text += "3️⃣ Click 'I've Paid'\n"
                text += "4️⃣ Wait for seller to release crypto\n"
            else:
                text += "📝 <b>Next Steps:</b>\n"
                text += "1️⃣ Your crypto is now in escrow\n"
                text += "2️⃣ Wait for buyer's payment\n"
                text += "3️⃣ Verify payment received\n"
                text += "4️⃣ Release crypto to buyer\n"
            
            text += f"\n⏱ Time limit: {order.time_limit_minutes} minutes"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="💬 Trade Chat",
                    callback_data=f"p2p:chat:{trade.id}"
                )],
                [
                    InlineKeyboardButton(
                        text="✅ I've Paid" if order.order_type == "sell" else "✅ Release Crypto",
                        callback_data=f"p2p:complete:{trade.id}"
                    ),
                ],
                [InlineKeyboardButton(
                    text="❌ Cancel Trade",
                    callback_data=f"p2p:cancel_trade:{trade.id}"
                )],
                [InlineKeyboardButton(
                    text=get_text("btn_back", lang),
                    callback_data="p2p:my_trades"
                )]
            ])
            
            try:
                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                pass
            
            await state.clear()
            await callback.answer("Trade created! 🎉")
            
        except ValueError as e:
            await callback.answer(str(e), show_alert=True)
        except Exception as e:
            logger.error("Trade creation failed", error=str(e))
            await callback.answer("Failed to create trade. Try again.", show_alert=True)


# ==================== MY ORDERS ====================

@router.callback_query(F.data == "p2p:my_orders")
async def my_orders(callback: CallbackQuery):
    """Show user's orders"""
    user, lang = await get_user_and_lang(callback)
    
    async with db_manager.session() as session:
        orders = await p2p_service.get_user_orders(session, user.id, limit=20)
        
        if not orders:
            text = "📋 <b>My Orders</b>\n\n"
            text += "📭 You don't have any orders.\n\n"
            text += "Create an order to start trading!"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="➕ Create Order",
                    callback_data="p2p:create"
                )],
                [InlineKeyboardButton(
                    text=get_text("btn_back", lang),
                    callback_data="p2p"
                )]
            ])
        else:
            text = "📋 <b>My Orders</b>\n\n"
            
            buttons = []
            for order in orders[:10]:
                status_icon = "✅" if order.status == "active" else "⏸" if order.status == "completed" else "❌"
                type_icon = "💰" if order.order_type == "buy" else "💸"
                
                text += f"{status_icon} {type_icon} {order.order_type.upper()} {order.token_symbol}\n"
                text += f"   💵 {order.price_per_unit:,.2f} {order.fiat_currency}\n"
                text += f"   📊 {order.available_amount:.4f} / {order.total_amount:.4f}\n\n"
                
                if order.status == "active":
                    buttons.append([InlineKeyboardButton(
                        text=f"{type_icon} {order.order_type.upper()} {order.token_symbol} @ {order.price_per_unit:,.0f}",
                        callback_data=f"p2p:order:{order.id}"
                    )])
            
            buttons.append([InlineKeyboardButton(
                text="➕ Create Order",
                callback_data="p2p:create"
            )])
            buttons.append([InlineKeyboardButton(
                text=get_text("btn_back", lang),
                callback_data="p2p"
            )])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        try:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass
    await callback.answer()


# ==================== MY TRADES ====================

@router.callback_query(F.data == "p2p:my_trades")
async def my_trades(callback: CallbackQuery):
    """Show user's trades"""
    user, lang = await get_user_and_lang(callback)
    
    async with db_manager.session() as session:
        trades = await p2p_service.get_user_trades(session, user.id, limit=20)
        
        if not trades:
            text = "🔄 <b>My Trades</b>\n\n"
            text += "📭 No active trades.\n\n"
            text += "Browse offers to start trading!"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="💰 Buy", callback_data="p2p:buy"),
                    InlineKeyboardButton(text="💸 Sell", callback_data="p2p:sell"),
                ],
                [InlineKeyboardButton(
                    text=get_text("btn_back", lang),
                    callback_data="p2p"
                )]
            ])
        else:
            text = "🔄 <b>My Trades</b>\n\n"
            
            buttons = []
            for trade in trades[:10]:
                status_icons = {
                    "pending": "⏳",
                    "paid": "💵",
                    "completed": "✅",
                    "cancelled": "❌",
                    "disputed": "⚠️",
                }
                status_icon = status_icons.get(trade.status, "❓")
                
                role = "Buy" if trade.buyer_id == user.id else "Sell"
                
                text += f"{status_icon} {role} {trade.crypto_amount:.4f} {trade.token_symbol}\n"
                text += f"   💵 {trade.fiat_amount:,.2f} {trade.fiat_currency}\n"
                text += f"   📅 {trade.created_at.strftime('%d %b %H:%M')}\n\n"
                
                if trade.status in ["pending", "paid"]:
                    buttons.append([InlineKeyboardButton(
                        text=f"{status_icon} {role} {trade.token_symbol} - {trade.status.upper()}",
                        callback_data=f"p2p:trade:{trade.id}"
                    )])
            
            buttons.append([InlineKeyboardButton(
                text=get_text("btn_back", lang),
                callback_data="p2p"
            )])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        try:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass
    await callback.answer()


# ==================== TRADE ACTIONS ====================

@router.callback_query(F.data.startswith("p2p:trade:"))
async def view_trade(callback: CallbackQuery):
    """View trade details"""
    trade_id = callback.data.split(":")[2]
    user, lang = await get_user_and_lang(callback)
    
    async with db_manager.session() as session:
        trade = await p2p_service.get_trade(session, trade_id)
        
        if not trade:
            await callback.answer("Trade not found", show_alert=True)
            return
        
        is_buyer = trade.buyer_id == user.id
        other_id = trade.seller_id if is_buyer else trade.buyer_id
        other_info = await p2p_service.get_user_with_stats(session, other_id)
        other_name = other_info["username"] or f"User#{other_id}"
        
        status_text = {
            "pending": "⏳ Waiting for payment",
            "paid": "💵 Payment sent, waiting confirmation",
            "completed": "✅ Completed",
            "cancelled": "❌ Cancelled",
            "disputed": "⚠️ Disputed",
        }
        
        text = f"🔄 <b>Trade Details</b>\n\n"
        text += f"🆔 ID: <code>{trade.id[:8]}</code>\n"
        text += f"📊 Status: {status_text.get(trade.status, trade.status)}\n\n"
        text += f"👤 {'Seller' if is_buyer else 'Buyer'}: <b>{other_name}</b>\n"
        text += f"💎 Amount: <b>{trade.crypto_amount:.6f} {trade.token_symbol}</b>\n"
        text += f"💵 Total: <b>{trade.fiat_amount:,.2f} {trade.fiat_currency}</b>\n"
        text += f"💳 Payment: {PAYMENT_METHODS.get(trade.payment_method, {}).get('name', trade.payment_method)}\n"
        text += f"📅 Created: {trade.created_at.strftime('%d %b %Y %H:%M')}\n"
        
        if trade.expires_at:
            remaining = trade.expires_at - datetime.utcnow()
            if remaining.total_seconds() > 0:
                mins = int(remaining.total_seconds() // 60)
                text += f"⏱ Expires in: {mins} minutes\n"
        
        buttons = []
        
        if trade.status in ["pending", "paid"]:
            buttons.append([InlineKeyboardButton(
                text="💬 Chat",
                callback_data=f"p2p:chat:{trade.id}"
            )])
            
            if is_buyer and trade.status == "pending":
                buttons.append([InlineKeyboardButton(
                    text="✅ I've Paid",
                    callback_data=f"p2p:mark_paid:{trade.id}"
                )])
            elif not is_buyer and trade.status in ["pending", "paid"]:
                buttons.append([InlineKeyboardButton(
                    text="✅ Release Crypto",
                    callback_data=f"p2p:release:{trade.id}"
                )])
            
            buttons.append([InlineKeyboardButton(
                text="⚠️ Open Dispute",
                callback_data=f"p2p:dispute:{trade.id}"
            )])
            
            if trade.status == "pending":
                buttons.append([InlineKeyboardButton(
                    text="❌ Cancel",
                    callback_data=f"p2p:cancel_trade:{trade.id}"
                )])
        
        elif trade.status == "completed":
            # Rating
            if is_buyer and not trade.buyer_rating:
                buttons.append([
                    InlineKeyboardButton(text="⭐ Rate", callback_data=f"p2p:rate:{trade.id}")
                ])
            elif not is_buyer and not trade.seller_rating:
                buttons.append([
                    InlineKeyboardButton(text="⭐ Rate", callback_data=f"p2p:rate:{trade.id}")
                ])
        
        buttons.append([InlineKeyboardButton(
            text=get_text("btn_back", lang),
            callback_data="p2p:my_trades"
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


@router.callback_query(F.data.startswith("p2p:mark_paid:"))
async def mark_paid(callback: CallbackQuery):
    """Mark trade as paid"""
    trade_id = callback.data.split(":")[2]
    user, lang = await get_user_and_lang(callback)
    
    async with db_manager.session() as session:
        success = await p2p_service.mark_as_paid(session, trade_id, user.id)
        await session.commit()
        
        if success:
            await callback.answer("✅ Marked as paid!", show_alert=True)
            # Refresh trade view
            callback.data = f"p2p:trade:{trade_id}"
            await view_trade(callback)
        else:
            await callback.answer("❌ Cannot mark as paid", show_alert=True)


@router.callback_query(F.data.startswith("p2p:release:"))
async def release_crypto(callback: CallbackQuery):
    """Release crypto to buyer"""
    trade_id = callback.data.split(":")[2]
    user, lang = await get_user_and_lang(callback)
    
    async with db_manager.session() as session:
        success = await p2p_service.release_crypto(session, trade_id, user.id)
        await session.commit()
        
        if success:
            await callback.answer("✅ Crypto released! Trade completed.", show_alert=True)
            callback.data = f"p2p:trade:{trade_id}"
            await view_trade(callback)
        else:
            await callback.answer("❌ Cannot release crypto", show_alert=True)


@router.callback_query(F.data.startswith("p2p:cancel_trade:"))
async def cancel_trade(callback: CallbackQuery):
    """Cancel trade"""
    trade_id = callback.data.split(":")[2]
    user, lang = await get_user_and_lang(callback)
    
    async with db_manager.session() as session:
        success = await p2p_service.cancel_trade(session, trade_id, user.id)
        await session.commit()
        
        if success:
            await callback.answer("Trade cancelled", show_alert=True)
            await my_trades(callback)
        else:
            await callback.answer("❌ Cannot cancel trade", show_alert=True)


# ==================== CREATE ORDER ====================

@router.callback_query(F.data == "p2p:create")
async def create_order_start(callback: CallbackQuery, state: FSMContext):
    """Start order creation"""
    user, lang = await get_user_and_lang(callback)
    await state.update_data(lang=lang)
    
    text = "➕ <b>Create Order</b>\n\n"
    text += "What do you want to do?"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 I want to BUY crypto", callback_data="p2p:create:buy"),
            InlineKeyboardButton(text="💸 I want to SELL crypto", callback_data="p2p:create:sell"),
        ],
        [InlineKeyboardButton(
            text=get_text("btn_back", lang),
            callback_data="p2p"
        )]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.in_(["p2p:create:buy", "p2p:create:sell"]))
async def create_order_select_crypto(callback: CallbackQuery, state: FSMContext):
    """Select crypto for order"""
    order_type = callback.data.split(":")[2]
    data = await state.get_data()
    lang = data.get("lang", "en")
    
    await state.update_data(new_order_type=order_type)
    
    text = f"{'💰 BUY' if order_type == 'buy' else '💸 SELL'} <b>Order</b>\n\n"
    text += "Select cryptocurrency:"
    
    buttons = []
    row = []
    for crypto in P2P_CRYPTOS:
        row.append(InlineKeyboardButton(text=crypto, callback_data=f"p2p:new:crypto:{crypto}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="p2p:create")])
    
    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("p2p:new:crypto:"))
async def create_order_select_fiat(callback: CallbackQuery, state: FSMContext):
    """Select fiat currency"""
    crypto = callback.data.split(":")[3]
    data = await state.get_data()
    lang = data.get("lang", "en")
    
    await state.update_data(new_crypto=crypto)
    
    text = f"💎 <b>{crypto}</b>\n\n"
    text += "Select fiat currency:"
    
    buttons = []
    row = []
    for code, name in FIAT_CURRENCIES.items():
        row.append(InlineKeyboardButton(text=name, callback_data=f"p2p:new:fiat:{code}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="p2p:create")])
    
    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("p2p:new:fiat:"))
async def create_order_enter_amount(callback: CallbackQuery, state: FSMContext):
    """Enter order amount"""
    fiat = callback.data.split(":")[3]
    data = await state.get_data()
    lang = data.get("lang", "en")
    crypto = data.get("new_crypto", "USDT")
    
    await state.update_data(new_fiat=fiat)
    
    # Get current price
    price = await price_service.get_price(crypto)
    price_str = f"${price:,.2f}" if price else "N/A"
    
    text = f"💎 <b>{crypto}</b> → {fiat}\n"
    text += f"📊 Market price: {price_str}\n\n"
    text += f"Enter amount of <b>{crypto}</b> to trade:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_cancel", lang), callback_data="p2p:create")]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    
    await state.set_state(P2PStates.entering_amount)
    await callback.answer()


@router.message(P2PStates.entering_amount)
async def create_order_process_amount(message: Message, state: FSMContext):
    """Process order amount"""
    data = await state.get_data()
    lang = data.get("lang", "en")
    
    try:
        amount = Decimal(message.text.strip().replace(",", "."))
        if amount <= 0:
            raise ValueError()
    except (InvalidOperation, ValueError):
        await message.answer("❌ Invalid amount. Enter a positive number:")
        return
    
    await state.update_data(new_amount=str(amount))
    
    crypto = data.get("new_crypto", "USDT")
    fiat = data.get("new_fiat", "USD")
    
    # Get suggested price
    market_price = await price_service.get_price(crypto)
    suggested = market_price if market_price else Decimal("1")
    
    text = f"💵 <b>Set Your Price</b>\n\n"
    text += f"💎 Amount: {amount} {crypto}\n"
    text += f"📊 Market price: ${suggested:,.2f}\n\n"
    text += f"Enter your price per {crypto} in {fiat}:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"📊 Use market price ({suggested:,.2f})",
            callback_data=f"p2p:new:price:market"
        )],
        [InlineKeyboardButton(text=get_text("btn_cancel", lang), callback_data="p2p:create")]
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(P2PStates.entering_price)


@router.callback_query(F.data == "p2p:new:price:market", P2PStates.entering_price)
async def use_market_price(callback: CallbackQuery, state: FSMContext):
    """Use market price"""
    data = await state.get_data()
    crypto = data.get("new_crypto", "USDT")
    
    price = await price_service.get_price(crypto)
    if price:
        await state.update_data(new_price=str(price))
        await select_payment_methods(callback, state)
    else:
        await callback.answer("Cannot get market price. Enter manually.", show_alert=True)


@router.message(P2PStates.entering_price)
async def create_order_process_price(message: Message, state: FSMContext):
    """Process order price"""
    data = await state.get_data()
    lang = data.get("lang", "en")
    
    try:
        price = Decimal(message.text.strip().replace(",", "."))
        if price <= 0:
            raise ValueError()
    except (InvalidOperation, ValueError):
        await message.answer("❌ Invalid price. Enter a positive number:")
        return
    
    await state.update_data(new_price=str(price))
    
    # Create a fake callback to proceed
    class FakeCallback:
        def __init__(self, msg):
            self.message = msg
            self.from_user = msg.from_user
            self.data = ""
        async def answer(self, *args, **kwargs):
            pass
    
    await select_payment_methods(FakeCallback(message), state)


async def select_payment_methods(callback, state: FSMContext):
    """Select payment methods"""
    data = await state.get_data()
    lang = data.get("lang", "en")
    
    text = "💳 <b>Select Payment Methods</b>\n\n"
    text += "Choose at least one method:"
    
    buttons = []
    for code, info in PAYMENT_METHODS.items():
        buttons.append([InlineKeyboardButton(
            text=f"{info['icon']} {info['name']}",
            callback_data=f"p2p:new:method:{code}"
        )])
    
    buttons.append([InlineKeyboardButton(
        text="✅ Done - Create Order",
        callback_data="p2p:new:finalize"
    )])
    buttons.append([InlineKeyboardButton(text=get_text("btn_cancel", lang), callback_data="p2p:create")])
    
    await state.update_data(new_methods=[])
    
    if hasattr(callback.message, 'edit_text'):
        try:
            await callback.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        await callback.message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML"
        )
    
    await state.set_state(P2PStates.selecting_payment)


@router.callback_query(F.data.startswith("p2p:new:method:"), P2PStates.selecting_payment)
async def toggle_payment_method(callback: CallbackQuery, state: FSMContext):
    """Toggle payment method selection"""
    method = callback.data.split(":")[3]
    data = await state.get_data()
    
    methods = data.get("new_methods", [])
    if method in methods:
        methods.remove(method)
    else:
        methods.append(method)
    
    await state.update_data(new_methods=methods)
    
    # Update button text to show selection
    selected = "✓ " if method in methods else ""
    await callback.answer(f"{selected}{PAYMENT_METHODS[method]['name']}")


@router.callback_query(F.data == "p2p:new:finalize", P2PStates.selecting_payment)
async def finalize_order(callback: CallbackQuery, state: FSMContext):
    """Create the order"""
    data = await state.get_data()
    lang = data.get("lang", "en")
    user, _ = await get_user_and_lang(callback)
    
    methods = data.get("new_methods", [])
    if not methods:
        await callback.answer("Select at least one payment method!", show_alert=True)
        return
    
    order_type = data.get("new_order_type", "sell")
    crypto = data.get("new_crypto", "USDT")
    fiat = data.get("new_fiat", "USD")
    amount = Decimal(data.get("new_amount", "0"))
    price = Decimal(data.get("new_price", "1"))
    
    # Determine network (simplified - use ethereum for most)
    network_map = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "BNB": "bsc",
        "USDT": "ethereum",
        "USDC": "ethereum",
    }
    network = network_map.get(crypto, "ethereum")
    
    async with db_manager.session() as session:
        try:
            order = await p2p_service.create_order(
                session,
                user_id=user.id,
                order_type=order_type,
                network=network,
                token_symbol=crypto,
                total_amount=amount,
                price_per_unit=price,
                fiat_currency=fiat,
                payment_methods=methods,
            )
            await session.commit()
            
            total_fiat = amount * price
            
            text = f"✅ <b>Order Created!</b>\n\n"
            text += f"🆔 Order ID: <code>{order.id[:8]}</code>\n\n"
            text += f"📋 Type: {'BUY' if order_type == 'buy' else 'SELL'}\n"
            text += f"💎 Crypto: {crypto}\n"
            text += f"📊 Amount: {amount} {crypto}\n"
            text += f"💵 Price: {price:,.2f} {fiat}/{crypto}\n"
            text += f"💰 Total: {total_fiat:,.2f} {fiat}\n\n"
            text += "⚡ Your order is now live!"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 My Orders", callback_data="p2p:my_orders")],
                [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="p2p")]
            ])
            
            try:
                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                pass
            
            await state.clear()
            await callback.answer("Order created! 🎉")
            
        except Exception as e:
            logger.error("Order creation failed", error=str(e))
            await callback.answer(f"Failed: {str(e)}", show_alert=True)


# ==================== CANCEL ORDER ====================

@router.callback_query(F.data.startswith("p2p:cancel_order:"))
async def cancel_order(callback: CallbackQuery):
    """Cancel an order"""
    order_id = callback.data.split(":")[2]
    user, lang = await get_user_and_lang(callback)
    
    async with db_manager.session() as session:
        success = await p2p_service.cancel_order(session, order_id, user.id)
        await session.commit()
        
        if success:
            await callback.answer("Order cancelled", show_alert=True)
            await my_orders(callback)
        else:
            await callback.answer("Cannot cancel order", show_alert=True)


# ==================== CHAT (simplified) ====================

@router.callback_query(F.data.startswith("p2p:chat:"))
async def trade_chat(callback: CallbackQuery, state: FSMContext):
    """Trade chat"""
    trade_id = callback.data.split(":")[2]
    user, lang = await get_user_and_lang(callback)
    
    async with db_manager.session() as session:
        trade = await p2p_service.get_trade(session, trade_id)
        messages = await p2p_service.get_trade_messages(session, trade_id, limit=20)
        
        if not trade:
            await callback.answer("Trade not found", show_alert=True)
            return
        
        text = f"💬 <b>Trade Chat</b>\n"
        text += f"🆔 {trade_id[:8]}\n\n"
        
        if messages:
            for msg in messages[-10:]:
                sender = "🤖" if msg.is_system else ("👤" if msg.sender_id == user.id else "👥")
                time = msg.created_at.strftime("%H:%M")
                text += f"{sender} [{time}] {msg.message}\n"
        else:
            text += "No messages yet.\n"
        
        text += "\n💡 Send a message to chat:"
        
        await state.update_data(chat_trade_id=trade_id, lang=lang)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🔄 Refresh",
                callback_data=f"p2p:chat:{trade_id}"
            )],
            [InlineKeyboardButton(
                text=get_text("btn_back", lang),
                callback_data=f"p2p:trade:{trade_id}"
            )]
        ])
        
        try:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass
        
        await state.set_state(P2PStates.in_trade_chat)
    await callback.answer()


@router.message(P2PStates.in_trade_chat)
async def send_chat_message(message: Message, state: FSMContext):
    """Send chat message"""
    data = await state.get_data()
    trade_id = data.get("chat_trade_id")
    user, lang = await get_user_and_lang(message)
    
    if not trade_id:
        await state.clear()
        return
    
    async with db_manager.session() as session:
        await p2p_service.add_message(
            session,
            trade_id=trade_id,
            sender_id=user.id,
            message=message.text[:500]  # Limit message length
        )
        await session.commit()
    
    await message.answer("✅ Message sent!")


# ==================== RATING ====================

@router.callback_query(F.data.startswith("p2p:rate:"))
async def rate_trade(callback: CallbackQuery):
    """Show rating options"""
    trade_id = callback.data.split(":")[2]
    user, lang = await get_user_and_lang(callback)
    
    text = "⭐ <b>Rate This Trade</b>\n\n"
    text += "How was your experience?"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐", callback_data=f"p2p:rate_submit:{trade_id}:1"),
            InlineKeyboardButton(text="⭐⭐", callback_data=f"p2p:rate_submit:{trade_id}:2"),
            InlineKeyboardButton(text="⭐⭐⭐", callback_data=f"p2p:rate_submit:{trade_id}:3"),
            InlineKeyboardButton(text="⭐⭐⭐⭐", callback_data=f"p2p:rate_submit:{trade_id}:4"),
            InlineKeyboardButton(text="⭐⭐⭐⭐⭐", callback_data=f"p2p:rate_submit:{trade_id}:5"),
        ],
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data=f"p2p:trade:{trade_id}")]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("p2p:rate_submit:"))
async def submit_rating(callback: CallbackQuery):
    """Submit rating"""
    parts = callback.data.split(":")
    trade_id = parts[2]
    rating = int(parts[3])
    user, lang = await get_user_and_lang(callback)
    
    async with db_manager.session() as session:
        success = await p2p_service.rate_trade(session, trade_id, user.id, rating)
        await session.commit()
        
        if success:
            await callback.answer(f"Thanks for rating! {'⭐' * rating}", show_alert=True)
        else:
            await callback.answer("Rating failed", show_alert=True)
    
    # Return to trade view
    callback.data = f"p2p:trade:{trade_id}"
    await view_trade(callback)
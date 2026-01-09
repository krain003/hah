"""
NEXUS WALLET - Spot Exchange Handler
"""

import uuid
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Optional, List, Tuple
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, and_
import structlog

from database.connection import db_manager
from database.repositories.user_repository import UserRepository
from database.models import ExchangeOrder, Trade, User
from services.wallet_service import wallet_service
from services.price_service import price_service

logger = structlog.get_logger(__name__)
router = Router(name="exchange")


class ExchangeStates(StatesGroup):
    enter_price = State()
    enter_amount = State()
    confirm = State()


TRADING_PAIRS = {
    "TON/USDT": {"base": "TON", "quote": "USDT", "base_network": "ton", "quote_network": "ton"},
    "BTC/USDT": {"base": "BTC", "quote": "USDT", "base_network": "btc", "quote_network": "ton"},
    "ETH/USDT": {"base": "ETH", "quote": "USDT", "base_network": "eth", "quote_network": "ton"},
}

TRADING_FEE = Decimal("0.001")


def get_exchange_menu_keyboard(pair: str = "TON/USDT") -> InlineKeyboardMarkup:
    base = pair.split("/")[0]
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"📈 Buy {base}", callback_data=f"ex:buy:{pair}"),
            InlineKeyboardButton(text=f"📉 Sell {base}", callback_data=f"ex:sell:{pair}")
        ],
        [
            InlineKeyboardButton(text="📊 Order Book", callback_data=f"ex:book:{pair}"),
            InlineKeyboardButton(text="📋 My Orders", callback_data="ex:my_orders")
        ],
        [InlineKeyboardButton(text="🔄 Change Pair", callback_data="ex:pairs")],
        [InlineKeyboardButton(text="🔙 Main Menu", callback_data="main_menu")]
    ])


@router.callback_query(F.data == "exchange")
async def exchange_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    pair = "TON/USDT"
    try:
        price = await price_service.get_price("TON")
        price_text = f"${price:.4f}"
    except:
        price_text = "N/A"
    
    text = f"📊 <b>Nexus Exchange</b>\n\n<b>Pair:</b> {pair}\n<b>Price:</b> {price_text}"
    await callback.message.edit_text(text, reply_markup=get_exchange_menu_keyboard(pair), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "ex:pairs")
async def exchange_pairs(callback: CallbackQuery):
    buttons = [[InlineKeyboardButton(text=p, callback_data=f"ex:select:{p}")] for p in TRADING_PAIRS]
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="exchange")])
    await callback.message.edit_text("💱 <b>Select Pair:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("ex:select:"))
async def select_pair(callback: CallbackQuery):
    pair = callback.data.split(":")[2]
    if pair not in TRADING_PAIRS:
        await callback.answer("Invalid pair!", show_alert=True)
        return
    try:
        price = await price_service.get_price(pair.split("/")[0])
        price_text = f"${price:.4f}"
    except:
        price_text = "N/A"
    text = f"📊 <b>Nexus Exchange</b>\n\n<b>Pair:</b> {pair}\n<b>Price:</b> {price_text}"
    await callback.message.edit_text(text, reply_markup=get_exchange_menu_keyboard(pair), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("ex:book:"))
async def show_order_book(callback: CallbackQuery):
    pair = callback.data.split(":")[2]
    async with db_manager.session() as session:
        asks = await session.execute(
            select(ExchangeOrder).where(and_(
                ExchangeOrder.pair == pair, ExchangeOrder.side == "sell", ExchangeOrder.status == "open"
            )).order_by(ExchangeOrder.price.asc()).limit(5)
        )
        bids = await session.execute(
            select(ExchangeOrder).where(and_(
                ExchangeOrder.pair == pair, ExchangeOrder.side == "buy", ExchangeOrder.status == "open"
            )).order_by(ExchangeOrder.price.desc()).limit(5)
        )
    
    text = f"📊 <b>Order Book - {pair}</b>\n\n<b>🔴 Asks</b>\n"
    for o in reversed(asks.scalars().all()):
        text += f"<code>{float(o.price):.4f} | {float(o.remaining):.4f}</code>\n"
    text += "\n<b>🟢 Bids</b>\n"
    for o in bids.scalars().all():
        text += f"<code>{float(o.price):.4f} | {float(o.remaining):.4f}</code>\n"
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Refresh", callback_data=f"ex:book:{pair}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"ex:select:{pair}")]
    ]), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("ex:buy:") | F.data.startswith("ex:sell:"))
async def order_start(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    side, pair = parts[1], parts[2]
    await state.update_data(side=side, pair=pair, order_type="limit")
    
    base = pair.split("/")[0]
    try:
        price = await price_service.get_price(base)
    except:
        price = 0
    
    await callback.message.edit_text(
        f"📊 <b>{side.upper()} {base}</b>\n\nCurrent: ${price:.4f}\n\nEnter price:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data=f"ex:select:{pair}")]]),
        parse_mode="HTML"
    )
    await state.set_state(ExchangeStates.enter_price)
    await callback.answer()


@router.message(ExchangeStates.enter_price)
async def order_price(message: Message, state: FSMContext):
    try:
        price = Decimal(message.text.strip().replace(",", "."))
        if price <= 0: raise ValueError
    except:
        await message.answer("❌ Invalid price")
        return
    
    data = await state.get_data()
    await state.update_data(price=str(price))
    base = data['pair'].split("/")[0]
    await message.answer(f"Enter amount of {base}:")
    await state.set_state(ExchangeStates.enter_amount)


@router.message(ExchangeStates.enter_amount)
async def order_amount(message: Message, state: FSMContext):
    try:
        amount = Decimal(message.text.strip().replace(",", "."))
        if amount <= 0: raise ValueError
    except:
        await message.answer("❌ Invalid amount")
        return
    
    data = await state.get_data()
    price = Decimal(data['price'])
    pair = data['pair']
    side = data['side']
    pair_info = TRADING_PAIRS[pair]
    base, quote = pair_info["base"], pair_info["quote"]
    total = price * amount
    fee = total * TRADING_FEE
    
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, message.from_user.id)
        balances = await wallet_service.get_user_balances(session, user.id)
    
    req_token = quote if side == "buy" else base
    req_amount = (total + fee) if side == "buy" else amount
    user_bal = next((Decimal(str(b['balance'])) for b in balances if b['symbol'] == req_token), Decimal("0"))
    
    if user_bal < req_amount:
        await message.answer(f"❌ Insufficient balance!\nNeed: {req_amount:.4f} {req_token}\nHave: {user_bal:.4f}")
        return
    
    await state.update_data(amount=str(amount))
    text = f"{'📈' if side == 'buy' else '📉'} <b>Confirm Order</b>\n\n<b>Pair:</b> {pair}\n<b>Side:</b> {side.upper()}\n<b>Price:</b> {price}\n<b>Amount:</b> {amount} {base}\n<b>Total:</b> {total:.4f} {quote}\n<b>Fee:</b> {fee:.4f}"
    
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm", callback_data="ex:confirm")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data=f"ex:select:{pair}")]
    ]), parse_mode="HTML")
    await state.set_state(ExchangeStates.confirm)


@router.callback_query(ExchangeStates.confirm, F.data == "ex:confirm")
async def order_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    pair, side = data['pair'], data['side']
    price, amount = Decimal(data['price']), Decimal(data['amount'])
    pair_info = TRADING_PAIRS[pair]
    base, quote = pair_info["base"], pair_info["quote"]
    
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        total = price * amount
        fee = total * TRADING_FEE
        
        if side == "buy":
            success = await wallet_service.lock_balance(session, user.id, pair_info["quote_network"], quote, total + fee, "exchange")
        else:
            success = await wallet_service.lock_balance(session, user.id, pair_info["base_network"], base, amount, "exchange")
        
        if not success:
            await callback.answer("❌ Insufficient balance!", show_alert=True)
            await state.clear()
            return
        
        order = ExchangeOrder(
            id=str(uuid.uuid4()), user_id=user.id, pair=pair, side=side,
            order_type="limit", price=price, amount=amount,
            remaining=amount, filled=Decimal("0"), status="open"
        )
        session.add(order)
        await session.commit()
        
        filled, _ = await match_order(session, order)
        await session.commit()
    
    await state.clear()
    await callback.message.edit_text(
        f"✅ <b>Order Created!</b>\n\n<b>ID:</b> <code>{order.id[:8]}...</code>\n<b>Filled:</b> {order.filled}/{amount}",
        reply_markup=get_exchange_menu_keyboard(pair), parse_mode="HTML"
    )
    await callback.answer("✅ Order placed!")


async def match_order(session, order: ExchangeOrder) -> Tuple[Decimal, list]:
    """Match order against order book"""
    filled = Decimal("0")
    trades = []
    
    if order.pair not in TRADING_PAIRS:
        return filled, trades
    
    if order.side == "buy":
        matches = await session.execute(
            select(ExchangeOrder).where(and_(
                ExchangeOrder.pair == order.pair, ExchangeOrder.side == "sell",
                ExchangeOrder.status == "open", ExchangeOrder.price <= order.price,
                ExchangeOrder.id != order.id
            )).order_by(ExchangeOrder.price.asc(), ExchangeOrder.created_at.asc())
        )
    else:
        matches = await session.execute(
            select(ExchangeOrder).where(and_(
                ExchangeOrder.pair == order.pair, ExchangeOrder.side == "buy",
                ExchangeOrder.status == "open", ExchangeOrder.price >= order.price,
                ExchangeOrder.id != order.id
            )).order_by(ExchangeOrder.price.desc(), ExchangeOrder.created_at.asc())
        )
    
    for match in matches.scalars():
        if order.remaining <= 0:
            break
        
        fill_amount = min(order.remaining, match.remaining)
        fill_price = match.price
        
        order.remaining -= fill_amount
        order.filled += fill_amount
        match.remaining -= fill_amount
        match.filled += fill_amount
        
        if order.remaining <= 0:
            order.status = "filled"
        if match.remaining <= 0:
            match.status = "filled"
        
        trade = Trade(
            id=str(uuid.uuid4()), pair=order.pair,
            buyer_order_id=order.id if order.side == "buy" else match.id,
            seller_order_id=match.id if order.side == "buy" else order.id,
            buyer_id=order.user_id if order.side == "buy" else match.user_id,
            seller_id=match.user_id if order.side == "buy" else order.user_id,
            price=fill_price, amount=fill_amount,
            total=fill_price * fill_amount, fee=fill_price * fill_amount * TRADING_FEE
        )
        session.add(trade)
        trades.append(trade)
        filled += fill_amount
    
    return filled, trades


@router.callback_query(F.data == "ex:my_orders")
async def my_orders(callback: CallbackQuery):
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        result = await session.execute(
            select(ExchangeOrder).where(and_(
                ExchangeOrder.user_id == user.id, ExchangeOrder.status == "open"
            )).order_by(ExchangeOrder.created_at.desc()).limit(10)
        )
        orders = result.scalars().all()
    
    text = "📋 <b>My Orders</b>\n\n"
    buttons = []
    if not orders:
        text += "<i>No open orders</i>"
    else:
        for o in orders:
            emoji = "📈" if o.side == "buy" else "📉"
            text += f"{emoji} {o.pair} | {o.price} | {o.remaining}/{o.amount}\n"
            buttons.append([InlineKeyboardButton(text=f"❌ Cancel {o.pair}", callback_data=f"ex:cancel:{o.id}")])
    
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="exchange")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("ex:cancel:"))
async def cancel_order(callback: CallbackQuery):
    order_id = callback.data.split(":")[2]
    
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        result = await session.execute(select(ExchangeOrder).where(ExchangeOrder.id == order_id))
        order = result.scalar_one_or_none()
        
        if not order or order.user_id != user.id:
            await callback.answer("Order not found!", show_alert=True)
            return
        if order.status != "open":
            await callback.answer("Order not open!", show_alert=True)
            return
        
        pair_info = TRADING_PAIRS.get(order.pair)
        if pair_info:
            if order.side == "buy":
                refund = order.price * order.remaining * (1 + TRADING_FEE)
                await wallet_service.unlock_balance(session, user.id, pair_info["quote_network"], pair_info["quote"], refund, "cancelled")
            else:
                await wallet_service.unlock_balance(session, user.id, pair_info["base_network"], pair_info["base"], order.remaining, "cancelled")
        
        order.status = "cancelled"
        await session.commit()
    
    await callback.answer("✅ Cancelled!", show_alert=True)
    await my_orders(callback)
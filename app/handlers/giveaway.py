"""
NEXUS WALLET - Giveaways
"""

import uuid
import random
import secrets
from decimal import Decimal
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, and_, func
import structlog

from database.connection import db_manager
from database.repositories.user_repository import UserRepository
from database.models import Giveaway, GiveawayParticipant, GiveawayWinner
from services.wallet_service import wallet_service

logger = structlog.get_logger(__name__)
router = Router(name="giveaway")


class GiveawayStates(StatesGroup):
    select_token = State()
    enter_amount = State()
    enter_winners_count = State()
    enter_duration = State()
    enter_caption = State()
    confirm = State()


DURATION_OPTIONS = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "12h": timedelta(hours=12),
    "24h": timedelta(days=1),
    "48h": timedelta(days=2),
    "7d": timedelta(days=7),
}


def safe_float(value, default=0.0):
    """Safely convert value to float"""
    try:
        if isinstance(value, str):
            return float(value)
        return float(value) if value else default
    except (ValueError, TypeError):
        return default


def get_giveaway_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Create Giveaway", callback_data="giveaway:create")],
        [InlineKeyboardButton(text="📋 My Giveaways", callback_data="giveaway:my_list")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
    ])


def get_duration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1h", callback_data="giveaway:duration:1h"),
            InlineKeyboardButton(text="6h", callback_data="giveaway:duration:6h"),
            InlineKeyboardButton(text="12h", callback_data="giveaway:duration:12h"),
        ],
        [
            InlineKeyboardButton(text="24h", callback_data="giveaway:duration:24h"),
            InlineKeyboardButton(text="48h", callback_data="giveaway:duration:48h"),
            InlineKeyboardButton(text="7 days", callback_data="giveaway:duration:7d"),
        ],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="giveaways")]
    ])


@router.callback_query(F.data == "giveaways")
async def giveaway_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text = """
🎁 <b>Nexus Giveaways</b>

Create giveaways for your community!
"""
    await callback.message.edit_text(text, reply_markup=get_giveaway_menu_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "giveaway:create")
async def giveaway_create_start(callback: CallbackQuery, state: FSMContext):
    """Step 1: Select token"""
    try:
        async with db_manager.session() as session:
            user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
            if not user:
                await callback.answer("Please register first!", show_alert=True)
                return
            
            balances = await wallet_service.get_user_balances(session, user.id)
        
        buttons = []
        for b in balances:
            balance_val = safe_float(b.get('balance', 0))
            if balance_val > 0:
                symbol = b.get('symbol', 'TOKEN')
                network = b.get('network', 'unknown')
                icon = b.get('icon', '💰')
                buttons.append([InlineKeyboardButton(
                    text=f"{icon} {symbol} ({balance_val:.4f})",
                    callback_data=f"giveaway:token:{symbol}:{network}"
                )])
        
        if not buttons:
            await callback.answer("❌ No tokens available!", show_alert=True)
            return
        
        buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="giveaways")])
        
        await callback.message.edit_text(
            "🎁 <b>Create Giveaway</b>\n\nSelect token:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML"
        )
        await state.set_state(GiveawayStates.select_token)
        
    except Exception as e:
        logger.error("giveaway_create_start error", error=str(e))
        await callback.answer("Error loading balances", show_alert=True)
    
    await callback.answer()


@router.callback_query(GiveawayStates.select_token, F.data.startswith("giveaway:token:"))
async def giveaway_token_selected(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    symbol, network = parts[2], parts[3]
    
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        balances = await wallet_service.get_user_balances(session, user.id)
    
    token_balance = next(
        (b for b in balances if b.get('symbol') == symbol and b.get('network') == network),
        None
    )
    
    max_balance = safe_float(token_balance.get('balance', 0)) if token_balance else 0
    
    await state.update_data(symbol=symbol, network=network, max_balance=max_balance)
    
    await callback.message.edit_text(
        f"🎁 <b>Create Giveaway</b>\n\n"
        f"Token: <b>{symbol}</b>\n"
        f"Available: <code>{max_balance:.6f}</code>\n\n"
        f"Enter amount:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="giveaways")]
        ]),
        parse_mode="HTML"
    )
    await state.set_state(GiveawayStates.enter_amount)
    await callback.answer()


@router.message(GiveawayStates.enter_amount)
async def giveaway_amount_entered(message: Message, state: FSMContext):
    try:
        amount = Decimal(message.text.strip().replace(",", "."))
        if amount <= 0:
            raise ValueError
    except:
        await message.answer("❌ Invalid amount")
        return
    
    data = await state.get_data()
    max_balance = Decimal(str(data.get('max_balance', 0)))
    
    if amount > max_balance:
        await message.answer(f"❌ Insufficient balance! Max: {max_balance:.6f}")
        return
    
    await state.update_data(amount=str(amount))
    
    await message.answer(
        "Enter number of winners (1-100):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="giveaways")]
        ])
    )
    await state.set_state(GiveawayStates.enter_winners_count)


@router.message(GiveawayStates.enter_winners_count)
async def giveaway_winners_entered(message: Message, state: FSMContext):
    try:
        winners_count = int(message.text.strip())
        if not 1 <= winners_count <= 100:
            raise ValueError
    except:
        await message.answer("❌ Enter a number from 1 to 100")
        return
    
    await state.update_data(winners_count=winners_count)
    
    await message.answer(
        "Select duration:",
        reply_markup=get_duration_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(GiveawayStates.enter_duration)


@router.callback_query(GiveawayStates.enter_duration, F.data.startswith("giveaway:duration:"))
async def giveaway_duration_selected(callback: CallbackQuery, state: FSMContext):
    duration_key = callback.data.split(":")[2]
    
    if duration_key not in DURATION_OPTIONS:
        await callback.answer("Invalid duration!", show_alert=True)
        return
    
    await state.update_data(duration_key=duration_key)
    
    await callback.message.edit_text(
        "Enter description (or send '-' for default):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="giveaways")]
        ]),
        parse_mode="HTML"
    )
    await state.set_state(GiveawayStates.enter_caption)
    await callback.answer()


@router.message(GiveawayStates.enter_caption)
async def giveaway_caption_entered(message: Message, state: FSMContext):
    caption = message.text.strip()
    if caption == "-":
        caption = None
    elif len(caption) > 500:
        await message.answer("❌ Too long (max 500 chars)")
        return
    
    await state.update_data(caption=caption)
    data = await state.get_data()
    
    amount = Decimal(data['amount'])
    per_winner = amount / data['winners_count']
    
    text = f"""
🎁 <b>Confirm Giveaway</b>

💰 Amount: <b>{amount} {data['symbol']}</b>
👥 Winners: <b>{data['winners_count']}</b>
💵 Each gets: <b>{per_winner:.6f} {data['symbol']}</b>
⏱ Duration: <b>{data['duration_key']}</b>
"""
    
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Create", callback_data="giveaway:confirm")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="giveaways")]
        ]),
        parse_mode="HTML"
    )
    await state.set_state(GiveawayStates.confirm)


@router.callback_query(GiveawayStates.confirm, F.data == "giveaway:confirm")
async def giveaway_create_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        
        amount = Decimal(data['amount'])
        
        # Lock funds
        success = await wallet_service.lock_balance(
            session=session,
            user_id=user.id,
            network=data['network'],
            token_symbol=data['symbol'],
            amount=amount,
            reason="giveaway"
        )
        
        if not success:
            await callback.answer("❌ Insufficient balance!", show_alert=True)
            await state.clear()
            return
        
        duration = DURATION_OPTIONS[data['duration_key']]
        end_time = datetime.utcnow() + duration
        code = secrets.token_urlsafe(8)
        
        giveaway = Giveaway(
            id=str(uuid.uuid4()),
            creator_id=user.id,
            network=data['network'],
            token_symbol=data['symbol'],
            total_amount=float(amount),
            amount_per_winner=float(amount / data['winners_count']),
            winners_count=data['winners_count'],
            code=code,
            caption=data.get('caption'),
            status="active",
            ends_at=end_time,
            chat_id=callback.message.chat.id
        )
        session.add(giveaway)
        await session.commit()
        
        giveaway_id = giveaway.id
    
    await state.clear()
    
    bot_info = await callback.bot.get_me()
    
    giveaway_text = f"""
🎁 <b>GIVEAWAY!</b>

💰 Prize: {data['amount']} {data['symbol']}
👥 Winners: {data['winners_count']}
⏱ Ends: {end_time.strftime('%d.%m.%Y %H:%M')} UTC

Press the button below to participate!
"""
    
    await callback.message.edit_text(
        giveaway_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎉 Participate!", callback_data=f"giveaway:join:{giveaway_id}")],
            [InlineKeyboardButton(text="📊 Participants", callback_data=f"giveaway:participants:{giveaway_id}")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer("✅ Giveaway created!")


@router.callback_query(F.data.startswith("giveaway:join:"))
async def giveaway_join(callback: CallbackQuery):
    giveaway_id = callback.data.split(":")[2]
    
    async with db_manager.session() as session:
        result = await session.execute(
            select(Giveaway).where(Giveaway.id == giveaway_id)
        )
        giveaway = result.scalar_one_or_none()
        
        if not giveaway or giveaway.status != "active":
            await callback.answer("❌ Giveaway not available!", show_alert=True)
            return
        
        if datetime.utcnow() > giveaway.ends_at:
            await callback.answer("❌ Giveaway ended!", show_alert=True)
            return
        
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        if not user:
            await callback.answer("❌ Please register first: /start", show_alert=True)
            return
        
        if giveaway.creator_id == user.id:
            await callback.answer("❌ Can't join your own giveaway!", show_alert=True)
            return
        
        # Check if already joined
        existing = await session.execute(
            select(GiveawayParticipant).where(
                and_(
                    GiveawayParticipant.giveaway_id == giveaway_id,
                    GiveawayParticipant.user_id == user.id
                )
            )
        )
        if existing.scalar_one_or_none():
            await callback.answer("✅ Already participating!", show_alert=True)
            return
        
        # Join
        participant = GiveawayParticipant(
            id=str(uuid.uuid4()),
            giveaway_id=giveaway_id,
            user_id=user.id
        )
        session.add(participant)
        await session.commit()
        
        # Count
        count_result = await session.execute(
            select(func.count(GiveawayParticipant.id))
            .where(GiveawayParticipant.giveaway_id == giveaway_id)
        )
        count = count_result.scalar()
    
    await callback.answer(f"🎉 You're in! Participants: {count}", show_alert=True)


@router.callback_query(F.data.startswith("giveaway:participants:"))
async def giveaway_participants(callback: CallbackQuery):
    giveaway_id = callback.data.split(":")[2]
    
    async with db_manager.session() as session:
        count_result = await session.execute(
            select(func.count(GiveawayParticipant.id))
            .where(GiveawayParticipant.giveaway_id == giveaway_id)
        )
        count = count_result.scalar()
    
    await callback.answer(f"👥 Participants: {count}", show_alert=True)


@router.callback_query(F.data == "giveaway:my_list")
async def my_giveaways(callback: CallbackQuery):
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        
        result = await session.execute(
            select(Giveaway)
            .where(Giveaway.creator_id == user.id)
            .order_by(Giveaway.created_at.desc())
            .limit(10)
        )
        giveaways = result.scalars().all()
    
    if not giveaways:
        text = "📋 <b>My Giveaways</b>\n\nNo giveaways yet."
    else:
        text = "📋 <b>My Giveaways</b>\n\n"
        for g in giveaways:
            status_emoji = {"active": "🟢", "completed": "✅", "cancelled": "❌"}.get(g.status, "⚪")
            text += f"{status_emoji} {g.total_amount} {g.token_symbol} | {g.winners_count}👥\n"
    
    buttons = []
    for g in giveaways:
        if g.status == "active":
            buttons.append([InlineKeyboardButton(
                text=f"❌ Cancel {g.total_amount} {g.token_symbol}",
                callback_data=f"giveaway:cancel:{g.id}"
            )])
    
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="giveaways")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("giveaway:cancel:"))
async def cancel_giveaway(callback: CallbackQuery):
    giveaway_id = callback.data.split(":")[2]
    
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        
        result = await session.execute(
            select(Giveaway).where(Giveaway.id == giveaway_id)
        )
        giveaway = result.scalar_one_or_none()
        
        if not giveaway or giveaway.creator_id != user.id:
            await callback.answer("❌ Not found!", show_alert=True)
            return
        
        if giveaway.status != "active":
            await callback.answer("❌ Already finished!", show_alert=True)
            return
        
        # Refund
        await wallet_service.unlock_balance(
            session=session,
            user_id=user.id,
            network=giveaway.network,
            token_symbol=giveaway.token_symbol,
            amount=Decimal(str(giveaway.total_amount)),
            reason="giveaway_cancelled"
        )
        
        giveaway.status = "cancelled"
        await session.commit()
    
    await callback.answer("✅ Cancelled & refunded!", show_alert=True)
    await my_giveaways(callback)
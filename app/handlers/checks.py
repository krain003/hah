"""
NEXUS WALLET - Checks
"""

import uuid
import secrets
from decimal import Decimal
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, and_, func
import structlog

from database.connection import db_manager
from database.repositories.user_repository import UserRepository
from database.models import NexusCheck, CheckActivation
from services.wallet_service import wallet_service
from security.encryption_manager import encryption_manager

logger = structlog.get_logger(__name__)
router = Router(name="checks")


class CheckStates(StatesGroup):
    select_token = State()
    enter_amount = State()
    enter_password = State()
    enter_activations = State()
    confirm = State()


class CheckActivationStates(StatesGroup):
    enter_password = State()


def safe_float(value, default=0.0):
    """Safely convert to float"""
    try:
        if isinstance(value, str):
            return float(value)
        return float(value) if value else default
    except:
        return default


def get_checks_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Create Check", callback_data="check:create")],
        [InlineKeyboardButton(text="📋 My Checks", callback_data="check:list")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
    ])


@router.callback_query(F.data == "checks")
async def checks_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text = """
🧾 <b>Nexus Checks</b>

Create crypto checks to send via link.
Send to anyone - even without a wallet!
"""
    await callback.message.edit_text(text, reply_markup=get_checks_menu_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "check:create")
async def check_create_start(callback: CallbackQuery, state: FSMContext):
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
                    callback_data=f"check:token:{symbol}:{network}"
                )])
        
        if not buttons:
            await callback.answer("❌ No tokens!", show_alert=True)
            return
        
        buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="checks")])
        
        await callback.message.edit_text(
            "🧾 <b>Create Check</b>\n\nSelect token:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML"
        )
        await state.set_state(CheckStates.select_token)
        
    except Exception as e:
        logger.error("check_create error", error=str(e))
        await callback.answer("Error", show_alert=True)
    
    await callback.answer()


@router.callback_query(CheckStates.select_token, F.data.startswith("check:token:"))
async def check_token_selected(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    symbol, network = parts[2], parts[3]
    
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        balances = await wallet_service.get_user_balances(session, user.id)
    
    token = next((b for b in balances if b.get('symbol') == symbol and b.get('network') == network), None)
    max_bal = safe_float(token.get('balance', 0)) if token else 0
    
    await state.update_data(symbol=symbol, network=network, max_balance=max_bal)
    
    await callback.message.edit_text(
        f"🧾 <b>Create Check</b>\n\n"
        f"Token: <b>{symbol}</b>\n"
        f"Available: <code>{max_bal:.6f}</code>\n\n"
        f"Enter amount:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="checks")]
        ]),
        parse_mode="HTML"
    )
    await state.set_state(CheckStates.enter_amount)
    await callback.answer()


@router.message(CheckStates.enter_amount)
async def check_amount_entered(message: Message, state: FSMContext):
    try:
        amount = Decimal(message.text.strip().replace(",", "."))
        if amount <= 0:
            raise ValueError
    except:
        await message.answer("❌ Invalid amount")
        return
    
    data = await state.get_data()
    max_bal = Decimal(str(data.get('max_balance', 0)))
    
    if amount > max_bal:
        await message.answer(f"❌ Max: {max_bal:.6f}")
        return
    
    await state.update_data(amount=str(amount), activations=1, password=None)
    
    text = f"""
🧾 <b>Create Check</b>

💰 Amount: <b>{amount} {data['symbol']}</b>

Options:
"""
    
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Add Password", callback_data="check:add_password")],
            [InlineKeyboardButton(text="👥 Multi-use", callback_data="check:multi_use")],
            [InlineKeyboardButton(text="✅ Create Now", callback_data="check:confirm")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="checks")]
        ]),
        parse_mode="HTML"
    )
    await state.set_state(CheckStates.confirm)


@router.callback_query(CheckStates.confirm, F.data == "check:add_password")
async def check_add_password(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🔐 Enter password (4-20 chars):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Skip", callback_data="check:skip_password")]
        ])
    )
    await state.set_state(CheckStates.enter_password)
    await callback.answer()


@router.message(CheckStates.enter_password)
async def check_password_entered(message: Message, state: FSMContext):
    try:
        await message.delete()
    except:
        pass
    
    password = message.text.strip()
    if not 4 <= len(password) <= 20:
        await message.answer("❌ 4-20 characters required")
        return
    
    await state.update_data(password=password)
    data = await state.get_data()
    
    await message.answer(
        f"🧾 Password set!\n\n"
        f"💰 {data['amount']} {data['symbol']}\n\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Multi-use", callback_data="check:multi_use")],
            [InlineKeyboardButton(text="✅ Create Now", callback_data="check:confirm")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="checks")]
        ]),
        parse_mode="HTML"
    )
    await state.set_state(CheckStates.confirm)


@router.callback_query(F.data == "check:skip_password")
async def check_skip_password(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await callback.message.edit_text(
        f"🧾 <b>Create Check</b>\n\n💰 {data['amount']} {data['symbol']}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Multi-use", callback_data="check:multi_use")],
            [InlineKeyboardButton(text="✅ Create Now", callback_data="check:confirm")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="checks")]
        ]),
        parse_mode="HTML"
    )
    await state.set_state(CheckStates.confirm)
    await callback.answer()


@router.callback_query(CheckStates.confirm, F.data == "check:multi_use")
async def check_multi_use(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "👥 Enter activations count (2-100):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="checks")]
        ])
    )
    await state.set_state(CheckStates.enter_activations)
    await callback.answer()


@router.message(CheckStates.enter_activations)
async def check_activations_entered(message: Message, state: FSMContext):
    try:
        count = int(message.text.strip())
        if not 2 <= count <= 100:
            raise ValueError
    except:
        await message.answer("❌ Enter 2-100")
        return
    
    await state.update_data(activations=count)
    data = await state.get_data()
    amount = Decimal(data['amount'])
    per = amount / count
    
    await message.answer(
        f"🧾 <b>Check Settings</b>\n\n"
        f"💰 Total: {amount} {data['symbol']}\n"
        f"👥 Activations: {count}\n"
        f"💵 Each: {per:.6f}\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Create", callback_data="check:confirm")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="checks")]
        ]),
        parse_mode="HTML"
    )
    await state.set_state(CheckStates.confirm)


@router.callback_query(CheckStates.confirm, F.data == "check:confirm")
async def check_create_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        
        amount = Decimal(data['amount'])
        activations = data.get('activations', 1)
        password = data.get('password')
        
        # Lock funds
        success = await wallet_service.lock_balance(
            session, user.id, data['network'], data['symbol'], amount, "check"
        )
        
        if not success:
            await callback.answer("❌ Insufficient balance!", show_alert=True)
            await state.clear()
            return
        
        code = secrets.token_urlsafe(10)
        pw_hash = encryption_manager.hash_pin(password) if password else None
        
        check = NexusCheck(
            id=str(uuid.uuid4()),
            creator_id=user.id,
            network=data['network'],
            token_symbol=data['symbol'],
            amount=float(amount),
            amount_per_activation=float(amount / activations),
            max_activations=activations,
            activated_count=0,
            code=code,
            password_hash=pw_hash,
            status="active"
        )
        session.add(check)
        await session.commit()
    
    await state.clear()
    
    bot_info = await callback.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=c_{code}"
    
    text = f"""
✅ <b>Check Created!</b>

💰 Amount: <b>{amount} {data['symbol']}</b>
👥 Activations: <b>{activations}</b>
🔐 Password: {'Yes' if password else 'No'}

🔗 Link:
<code>{link}</code>
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Share", switch_inline_query=f"check_{code}")],
            [InlineKeyboardButton(text="📋 My Checks", callback_data="check:list")],
            [InlineKeyboardButton(text="🔙 Menu", callback_data="checks")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer("✅ Created!")


@router.callback_query(F.data == "check:list")
async def check_list(callback: CallbackQuery):
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        
        result = await session.execute(
            select(NexusCheck)
            .where(NexusCheck.creator_id == user.id)
            .order_by(NexusCheck.created_at.desc())
            .limit(10)
        )
        checks = result.scalars().all()
    
    if not checks:
        text = "📋 <b>My Checks</b>\n\nNo checks yet."
    else:
        text = "📋 <b>My Checks</b>\n\n"
        for c in checks:
            status_emoji = {"active": "🟢", "depleted": "✅", "cancelled": "❌"}.get(c.status, "⚪")
            text += f"{status_emoji} {c.amount} {c.token_symbol} | {c.activated_count}/{c.max_activations}\n"
    
    buttons = []
    for c in checks:
        if c.status == "active":
            buttons.append([InlineKeyboardButton(
                text=f"❌ Cancel {c.amount} {c.token_symbol}",
                callback_data=f"check:cancel:{c.id}"
            )])
    
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="checks")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("check:cancel:"))
async def check_cancel(callback: CallbackQuery):
    check_id = callback.data.split(":")[2]
    
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        
        result = await session.execute(
            select(NexusCheck).where(NexusCheck.id == check_id)
        )
        check = result.scalar_one_or_none()
        
        if not check or check.creator_id != user.id:
            await callback.answer("Not found!", show_alert=True)
            return
        
        if check.status != "active":
            await callback.answer("Already inactive!", show_alert=True)
            return
        
        remaining = check.max_activations - check.activated_count
        refund = Decimal(str(check.amount_per_activation)) * remaining
        
        await wallet_service.unlock_balance(
            session, user.id, check.network, check.token_symbol, refund, "cancelled"
        )
        
        check.status = "cancelled"
        await session.commit()
    
    await callback.answer(f"✅ Refunded {refund}!", show_alert=True)
    await check_list(callback)


# Activation handler - called from start.py
async def activate_check(message: Message, code: str, state: FSMContext):
    async with db_manager.session() as session:
        result = await session.execute(
            select(NexusCheck).where(NexusCheck.code == code)
        )
        check = result.scalar_one_or_none()
        
        if not check:
            await message.answer("❌ Check not found")
            return
        
        if check.status != "active":
            await message.answer("❌ Check unavailable")
            return
        
        user = await UserRepository().get_by_telegram_id(session, message.from_user.id)
        if not user:
            await message.answer("Please /start first")
            return
        
        if check.creator_id == user.id:
            await message.answer("❌ Can't activate own check")
            return
        
        # Check already used
        existing = await session.execute(
            select(CheckActivation).where(and_(
                CheckActivation.check_id == check.id,
                CheckActivation.user_id == user.id
            ))
        )
        if existing.scalar_one_or_none():
            await message.answer("❌ Already activated")
            return
        
        # Password check
        if check.password_hash:
            await state.update_data(check_code=code, check_id=check.id)
            await message.answer("🔐 Enter password:")
            await state.set_state(CheckActivationStates.enter_password)
            return
        
        # Activate
        await _do_activate(session, check, user, message)


@router.message(CheckActivationStates.enter_password)
async def verify_check_password(message: Message, state: FSMContext):
    try:
        await message.delete()
    except:
        pass
    
    data = await state.get_data()
    
    async with db_manager.session() as session:
        result = await session.execute(
            select(NexusCheck).where(NexusCheck.id == data['check_id'])
        )
        check = result.scalar_one_or_none()
        
        if not check or check.status != "active":
            await message.answer("❌ Check unavailable")
            await state.clear()
            return
        
        if not encryption_manager.verify_pin(message.text.strip(), check.password_hash):
            await message.answer("❌ Wrong password. Try again:")
            return
        
        user = await UserRepository().get_by_telegram_id(session, message.from_user.id)
        await _do_activate(session, check, user, message)
    
    await state.clear()


async def _do_activate(session, check, user, message):
    amount = Decimal(str(check.amount_per_activation))
    
    await wallet_service.credit_balance(
        session, user.id, check.network, check.token_symbol, amount
    )
    
    activation = CheckActivation(
        id=str(uuid.uuid4()),
        check_id=check.id,
        user_id=user.id,
        amount=float(amount)
    )
    session.add(activation)
    
    check.activated_count += 1
    if check.activated_count >= check.max_activations:
        check.status = "depleted"
    
    await session.commit()
    
    await message.answer(
        f"🎉 <b>Received {amount} {check.token_symbol}!</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💼 Wallet", callback_data="wallet")],
            [InlineKeyboardButton(text="🏠 Menu", callback_data="main_menu")]
        ]),
        parse_mode="HTML"
    )
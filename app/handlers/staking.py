"""
NEXUS WALLET - Staking Handler
Earn passive income by locking tokens
"""

import asyncio
from decimal import Decimal
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import structlog

from database.connection import db_manager
from database.models import User, WalletBalance
from database.repositories.user_repository import UserRepository
from services.wallet_service import wallet_service
from blockchain.wallet_manager import NETWORKS

logger = structlog.get_logger(__name__)
router = Router(name="staking")


class StakingStates(StatesGroup):
    enter_amount = State()
    confirm = State()


# Mock staking APY rates
STAKING_RATES = {
    "ton": {"apy": 5.0, "min": 10, "lock": "30 days"},
    "solana": {"apy": 7.5, "min": 1, "lock": "14 days"},
    "ethereum": {"apy": 3.8, "min": 0.1, "lock": "Flexible"},
    "bsc": {"apy": 4.2, "min": 0.5, "lock": "7 days"},
    "tron": {"apy": 5.5, "min": 100, "lock": "3 days"}
}


@router.callback_query(F.data == "staking")
async def staking_menu(callback: CallbackQuery):
    """Staking dashboard"""
    text = """
📈 <b>Staking Earn</b>

Lock your assets to earn passive rewards.
Interest is paid daily.

<b>Available Pools:</b>
"""
    buttons = []
    for net, info in STAKING_RATES.items():
        config = NETWORKS.get(net)
        if config:
            text += f"\n{config.icon} <b>{config.symbol}</b>: {info['apy']}% APY | Min {info['min']}"
            buttons.append([
                InlineKeyboardButton(
                    text=f"Stake {config.symbol} ({info['apy']}%)", 
                    callback_data=f"stake:start:{net}"
                )
            ])
    
    buttons.append([InlineKeyboardButton(text="🔙 Main Menu", callback_data="main_menu")])
    
    await callback.message.edit_text(
        text, 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), 
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stake:start:"))
async def staking_start(callback: CallbackQuery, state: FSMContext):
    """Start staking flow"""
    network = callback.data.split(":")[-1]
    info = STAKING_RATES[network]
    config = NETWORKS[network]
    
    await state.update_data(network=network, min_amount=info['min'], symbol=config.symbol, apy=info['apy'])
    
    text = f"""
📈 <b>Stake {config.symbol}</b>

<b>APY:</b> {info['apy']}%
<b>Lock Period:</b> {info['lock']}
<b>Minimum:</b> {info['min']} {config.symbol}

Enter amount to stake:
"""
    await callback.message.edit_text(text, parse_mode="HTML")
    await state.set_state(StakingStates.enter_amount)
    await callback.answer()


@router.message(StakingStates.enter_amount)
async def staking_amount(message: Message, state: FSMContext):
    """Process staking amount"""
    data = await state.get_data()
    try:
        amount = float(message.text.strip())
        if amount < data['min_amount']:
            await message.answer(f"❌ Minimum is {data['min_amount']} {data['symbol']}")
            return
        
        await state.update_data(amount=amount)
        
        # Calculate rewards
        daily_reward = (amount * (data['apy'] / 100)) / 365
        
        text = f"""
✅ <b>Confirm Staking</b>

<b>Amount:</b> {amount} {data['symbol']}
<b>Est. Daily Reward:</b> {daily_reward:.6f} {data['symbol']}

Funds will be locked for the duration.
"""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Confirm", callback_data="stake:confirm")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="staking")]
        ])
        
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        await state.set_state(StakingStates.confirm)
        
    except ValueError:
        await message.answer("❌ Invalid amount")


@router.callback_query(StakingStates.confirm, F.data == "stake:confirm")
async def staking_confirm(callback: CallbackQuery, state: FSMContext):
    """Execute staking"""
    # In real app: Lock funds in DB, create Staking record
    await callback.message.edit_text("✅ <b>Staked Successfully!</b>\n\nYour rewards will start accruing tomorrow.", parse_mode="HTML")
    await callback.answer()
    await state.clear()
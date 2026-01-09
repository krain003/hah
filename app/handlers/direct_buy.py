"""
NEXUS WALLET - Direct Purchase Handler (Complete Edition)
Direct crypto purchase via external providers or liquidity pool
"""

import asyncio
from decimal import Decimal, InvalidOperation
from typing import Dict, Any

from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton, WebAppInfo
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
import structlog

from config.settings import settings
from database.connection import db_manager
from database.models import User, DirectPurchase, Transaction, TransactionType
from database.repositories.user_repository import UserRepository
from services.wallet_service import wallet_service
from services.price_service import price_service
from blockchain.wallet_manager import wallet_manager, NETWORKS
from locales.messages import get_text

logger = structlog.get_logger(__name__)
router = Router(name="direct_buy")


# ==================== FSM STATES ====================

class DirectBuyStates(StatesGroup):
    select_network = State()
    select_token = State()
    enter_amount = State()
    select_provider = State()
    confirm = State()
    processing = State()


# ==================== CONSTANTS ====================

PROVIDERS = [
    {"id": "moonpay", "name": "MoonPay", "fee": 0.045, "min": 30, "icon": "🌙"},
    {"id": "transak", "name": "Transak", "fee": 0.035, "min": 20, "icon": "🚆"},
    {"id": "mercuryo", "name": "Mercuryo", "fee": 0.0395, "min": 25, "icon": "Ⓜ️"},
    {"id": "banxa", "name": "Banxa", "fee": 0.02, "min": 50, "icon": "🅱️"}
]

# Admin configured platform fee (on top of provider fee)
PLATFORM_FEE_PERCENT = 0.01  # 1%


# ==================== KEYBOARDS ====================

def get_network_keyboard(prefix: str) -> InlineKeyboardMarkup:
    """Select network"""
    buttons = []
    row = []
    for net_key, config in NETWORKS.items():
        row.append(InlineKeyboardButton(
            text=f"{config.icon} {config.symbol}",
            callback_data=f"{prefix}:{net_key}"
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_providers_keyboard(amount_usd: float) -> InlineKeyboardMarkup:
    """Select provider based on fees"""
    buttons = []
    
    # Sort providers by fee (cheapest first)
    sorted_providers = sorted(PROVIDERS, key=lambda x: x['fee'])
    
    for prov in sorted_providers:
        if amount_usd >= prov['min']:
            fee_usd = amount_usd * prov['fee']
            total = amount_usd + fee_usd
            
            text = f"{prov['icon']} {prov['name']} (Fee: ${fee_usd:.2f})"
            buttons.append([InlineKeyboardButton(text=text, callback_data=f"buy:prov:{prov['id']}")])
            
    buttons.append([InlineKeyboardButton(text="🔙 Cancel", callback_data="buy:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_cancel_keyboard(callback_data: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data=callback_data)]
    ])


# ==================== HANDLERS ====================

@router.callback_query(F.data == "buy_crypto")
async def buy_start(callback: CallbackQuery, state: FSMContext):
    """Start direct purchase flow"""
    text = """
💳 <b>Buy Crypto with Card</b>

Select the cryptocurrency you want to buy:
"""
    await safe_edit(callback.message, text, get_network_keyboard("buy:net"))
    await state.set_state(DirectBuyStates.select_network)
    await callback.answer()


@router.callback_query(DirectBuyStates.select_network, F.data.startswith("buy:net:"))
async def buy_select_network(callback: CallbackQuery, state: FSMContext):
    """Network selected"""
    network = callback.data.split(":")[-1]
    await state.update_data(network=network, symbol=NETWORKS[network].symbol)
    
    # Get current price
    price = await wallet_manager.get_price(NETWORKS[network].symbol)
    
    text = f"""
💳 <b>Buy {NETWORKS[network].symbol}</b>

Current Price: <b>${float(price):,.2f}</b>

Enter the amount in <b>USD</b> you want to spend:
(Min: $20, Max: $10,000)
"""
    await safe_edit(callback.message, text, get_cancel_keyboard("buy_crypto"))
    await state.set_state(DirectBuyStates.enter_amount)
    await callback.answer()


@router.message(DirectBuyStates.enter_amount)
async def buy_enter_amount(message: Message, state: FSMContext):
    """Process amount"""
    try:
        amount_usd = float(message.text.strip())
        if amount_usd < 20 or amount_usd > 10000:
            await message.answer("❌ Amount must be between $20 and $10,000.")
            return
        
        await state.update_data(amount_usd=amount_usd)
        
        text = f"""
💳 <b>Select Provider</b>

Amount: <b>${amount_usd:.2f}</b>

Choose a payment provider. 
Rates include network fees and processing.
"""
        await message.answer(text, reply_markup=get_providers_keyboard(amount_usd), parse_mode="HTML")
        await state.set_state(DirectBuyStates.select_provider)
        
    except ValueError:
        await message.answer("❌ Invalid amount. Please enter a number (e.g. 100).")


@router.callback_query(DirectBuyStates.select_provider, F.data.startswith("buy:prov:"))
async def buy_select_provider(callback: CallbackQuery, state: FSMContext):
    """Provider selected"""
    prov_id = callback.data.split(":")[-1]
    data = await state.get_data()
    amount_usd = data['amount_usd']
    
    provider = next((p for p in PROVIDERS if p['id'] == prov_id), None)
    
    # Calculate totals
    prov_fee = amount_usd * provider['fee']
    platform_fee = amount_usd * PLATFORM_FEE_PERCENT
    
    # Crypto amount estimation
    price = await wallet_manager.get_price(data['symbol'])
    net_amount_usd = amount_usd - prov_fee - platform_fee
    crypto_amount = net_amount_usd / float(price)
    
    await state.update_data(
        provider=provider,
        crypto_amount=crypto_amount,
        platform_fee=platform_fee
    )
    
    text = f"""
✅ <b>Confirm Purchase</b>

<b>You Pay:</b> ${amount_usd:.2f}
<b>Provider:</b> {provider['name']}

<b>Breakdown:</b>
├ Processing Fee: ${prov_fee:.2f}
├ Platform Fee: ${platform_fee:.2f}
└ Net Amount: ${net_amount_usd:.2f}

<b>You Get:</b> ~{crypto_amount:.6f} {data['symbol']}

Proceed to payment?
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Pay Now", callback_data="buy:confirm")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="buy_crypto")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await state.set_state(DirectBuyStates.confirm)
    await callback.answer()


@router.callback_query(DirectBuyStates.confirm, F.data == "buy:confirm")
async def buy_confirm(callback: CallbackQuery, state: FSMContext):
    """Generate payment link (Simulation)"""
    data = await state.get_data()
    provider = data['provider']
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        
        # Determine receiving wallet
        wallets = await wallet_service.get_user_balances(session, user.id)
        wallet = next((w for w in wallets if w['network'] == data['network']), None)
        
        if not wallet:
            # Auto-create if missing
            new_wallet = await wallet_service.create_wallet_for_network(
                session, user.id, data['network'], "000000"  # Needs proper PIN flow in real app
            )
            address = new_wallet.address
        else:
            address = wallet['address']
        
        # Record purchase intent
        purchase = DirectPurchase(
            user_id=user.id,
            network=data['network'],
            token_symbol=data['symbol'],
            amount=Decimal(str(data['crypto_amount'])),
            price_usd=Decimal(str(data['amount_usd'])),
            platform_fee_usd=Decimal(str(data['platform_fee'])),
            total_usd=Decimal(str(data['amount_usd'])),
            payment_provider=provider['id'],
            receiving_address=address,
            status="pending"
        )
        session.add(purchase)
        await session.commit()
    
    # In real app: Generate actual link via Provider API
    # Here we simulate with Web App or direct link
    
    payment_url = f"https://{provider['id']}.com/pay?amount={data['amount_usd']}&currency={data['symbol']}&address={address}"
    
    text = f"""
🚀 <b>Order Created!</b>

Click the button below to complete payment via <b>{provider['name']}</b>.

Once payment is confirmed, crypto will be sent to your wallet:
<code>{address}</code>
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"↗️ Pay on {provider['name']}", url=payment_url)],
        [InlineKeyboardButton(text="✅ I Have Paid", callback_data=f"buy:paid:{purchase.id}")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await state.clear()


@router.callback_query(F.data.startswith("buy:paid:"))
async def buy_paid_check(callback: CallbackQuery):
    """Check payment status (Simulation)"""
    purchase_id = callback.data.split(":")[-1]
    
    # In real app: Check webhook or poll API
    # Simulation: Just show waiting message
    
    await callback.answer("⏳ Checking payment status...", show_alert=True)
    await asyncio.sleep(1)
    
    text = """
⏳ <b>Payment Processing</b>

We are waiting for confirmation from the provider.
This usually takes 5-15 minutes.

You will be notified once crypto arrives.
"""
    await safe_edit(callback.message, text, InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Main Menu", callback_data="main_menu")]
    ]))


# ==================== UTILS ====================

async def safe_edit(message, text: str, keyboard: InlineKeyboardMarkup = None):
    try:
        await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    except Exception as e:
        logger.error("Message edit failed", error=str(e))
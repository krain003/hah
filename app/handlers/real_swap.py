"""
NEXUS WALLET - Real Cross-Chain Swap Handler
"""

import uuid
from decimal import Decimal
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
import structlog

from database.connection import db_manager
from database.repositories.user_repository import UserRepository
from database.repositories.wallet_repository import WalletRepository
from database.models import Transaction, TransactionType, TransactionStatus
from services.swap_service import swap_service
from services.wallet_service import wallet_service
from blockchain.wallet_manager import NETWORKS, wallet_manager

logger = structlog.get_logger(__name__)
router = Router(name="real_swap")


class RealSwapStates(StatesGroup):
    select_from = State()
    select_to = State()
    enter_amount = State()
    confirm = State()
    processing = State()


# ==================== CURRENCY MAPPING ====================

# Map our network names to ChangeNOW tickers
NETWORK_TO_TICKER = {
    "ton": "ton",
    "bitcoin": "btc",
    "ethereum": "eth",
    "bsc": "bnb",
    "polygon": "matic",
    "solana": "sol",
    "tron": "trx",
    "arbitrum": "eth",  # ETH on Arbitrum
    "optimism": "eth",
    "avalanche": "avax",
}


def get_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
    ])


@router.callback_query(F.data == "real_swap")
async def real_swap_start(callback: CallbackQuery, state: FSMContext):
    """Start real cross-chain swap"""
    await state.clear()
    
    # Check if API key is configured
    if not swap_service.api_key:
        await callback.message.edit_text(
            "❌ <b>Swap service not configured</b>\n\n"
            "Please contact administrator.",
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
        await callback.answer()
        return
    
    try:
        async with db_manager.session() as session:
            user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
            if not user:
                await callback.answer("Please register first!", show_alert=True)
                return
            
            balances = await wallet_service.get_user_balances(session, user.id)
        
        # Filter balances > 0
        buttons = []
        for b in balances:
            balance_val = float(b.get('balance', 0))
            if balance_val > 0:
                symbol = b.get('symbol', 'TOKEN')
                network = b.get('network', 'unknown')
                icon = b.get('icon', '💰')
                
                buttons.append([InlineKeyboardButton(
                    text=f"{icon} {symbol} ({balance_val:.6f})",
                    callback_data=f"rswap:from:{network}:{symbol}"
                )])
        
        if not buttons:
            await callback.message.edit_text(
                "❌ <b>No tokens for swap</b>\n\n"
                "Deposit some crypto first!",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📥 Deposit", callback_data="receive_menu")],
                    [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
                ]),
                parse_mode="HTML"
            )
            await callback.answer()
            return
        
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")])
        
        await callback.message.edit_text(
            "🌐 <b>Cross-Chain Swap</b>\n\n"
            "Exchange crypto between different blockchains!\n\n"
            "Select token to swap FROM:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML"
        )
        await state.set_state(RealSwapStates.select_from)
        
    except Exception as e:
        logger.error("real_swap_start error", error=str(e))
        await callback.answer("Error", show_alert=True)
    
    await callback.answer()


@router.callback_query(RealSwapStates.select_from, F.data.startswith("rswap:from:"))
async def select_destination(callback: CallbackQuery, state: FSMContext):
    """Select destination currency"""
    parts = callback.data.split(":")
    from_network = parts[2]
    from_symbol = parts[3]
    
    await state.update_data(from_network=from_network, from_symbol=from_symbol)
    
    # Get available destination currencies
    buttons = []
    
    for network, config in NETWORKS.items():
        # Skip same network+symbol
        if network == from_network and config.symbol == from_symbol:
            continue
        
        buttons.append([InlineKeyboardButton(
            text=f"{config.icon} {config.symbol} ({config.name})",
            callback_data=f"rswap:to:{network}:{config.symbol}"
        )])
    
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="main_menu")])
    
    await callback.message.edit_text(
        f"🌐 <b>Cross-Chain Swap</b>\n\n"
        f"From: <b>{from_symbol}</b>\n\n"
        f"Select token to receive:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await state.set_state(RealSwapStates.select_to)
    await callback.answer()


@router.callback_query(RealSwapStates.select_to, F.data.startswith("rswap:to:"))
async def enter_amount(callback: CallbackQuery, state: FSMContext):
    """Enter swap amount"""
    parts = callback.data.split(":")
    to_network = parts[2]
    to_symbol = parts[3]
    
    data = await state.get_data()
    from_network = data['from_network']
    from_symbol = data['from_symbol']
    
    await state.update_data(to_network=to_network, to_symbol=to_symbol)
    
    # Get user balance
    async with db_manager.session() as session:
        user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
        balances = await wallet_service.get_user_balances(session, user.id)
    
    balance = next(
        (b for b in balances if b['network'] == from_network and b['symbol'] == from_symbol),
        None
    )
    max_balance = Decimal(str(balance['balance'])) if balance else Decimal("0")
    
    await state.update_data(max_balance=str(max_balance))
    
    # Get minimum amount from API
    from_ticker = NETWORK_TO_TICKER.get(from_network, from_symbol.lower())
    to_ticker = NETWORK_TO_TICKER.get(to_network, to_symbol.lower())
    
    min_amount = await swap_service.get_min_amount(from_ticker, to_ticker)
    min_text = f"\n⚠️ Minimum: <b>{min_amount}</b> {from_symbol}" if min_amount else ""
    
    await state.update_data(min_amount=str(min_amount or 0))
    
    await callback.message.edit_text(
        f"🌐 <b>Cross-Chain Swap</b>\n\n"
        f"📤 From: <b>{from_symbol}</b>\n"
        f"📥 To: <b>{to_symbol}</b>\n\n"
        f"💰 Available: <code>{max_balance:.6f}</code> {from_symbol}"
        f"{min_text}\n\n"
        f"Enter amount (or 'max'):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="main_menu")]
        ]),
        parse_mode="HTML"
    )
    await state.set_state(RealSwapStates.enter_amount)
    await callback.answer()


@router.message(RealSwapStates.enter_amount)
async def confirm_swap(message: Message, state: FSMContext):
    """Calculate and confirm swap"""
    data = await state.get_data()
    max_balance = Decimal(data.get('max_balance', '0'))
    min_amount = Decimal(data.get('min_amount', '0'))
    
    # Parse amount
    amount_text = message.text.strip().lower()
    
    if amount_text in ['max', 'all']:
        amount = max_balance
    else:
        try:
            amount = Decimal(amount_text.replace(",", "."))
        except:
            await message.answer("❌ Invalid amount")
            return
    
    if amount <= 0:
        await message.answer("❌ Amount must be greater than 0")
        return
    
    if amount > max_balance:
        await message.answer(f"❌ Max available: {max_balance}")
        return
    
    if min_amount > 0 and amount < min_amount:
        await message.answer(f"❌ Minimum: {min_amount} {data['from_symbol']}")
        return
    
    await state.update_data(amount=str(amount))
    
    # Get estimate from API
    from_ticker = NETWORK_TO_TICKER.get(data['from_network'], data['from_symbol'].lower())
    to_ticker = NETWORK_TO_TICKER.get(data['to_network'], data['to_symbol'].lower())
    
    estimate = await swap_service.get_estimated_amount(
        from_ticker, to_ticker, amount
    )
    
    if not estimate:
        await message.answer(
            "❌ Unable to get exchange rate. Try again later.",
            reply_markup=get_back_keyboard()
        )
        return
    
    receive_amount = Decimal(str(estimate.get('toAmount', 0)))
    rate = receive_amount / amount if amount > 0 else Decimal("0")
    
    await state.update_data(
        receive_amount=str(receive_amount),
        rate=str(rate)
    )
    
    text = f"""
🌐 <b>Confirm Cross-Chain Swap</b>

📤 <b>You Send:</b>
   {amount} {data['from_symbol']} ({data['from_network'].upper()})

📥 <b>You Receive:</b>
   ~{receive_amount:.6f} {data['to_symbol']} ({data['to_network'].upper()})

━━━━━━━━━━━━━━━
📊 <b>Rate:</b> 1 {data['from_symbol']} ≈ {rate:.6f} {data['to_symbol']}
⏱ <b>Time:</b> ~10-30 minutes
━━━━━━━━━━━━━━━

⚠️ <b>Important:</b>
• This is a REAL blockchain transaction
• Funds will be sent to external exchange
• Cannot be cancelled after confirmation
"""
    
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Confirm & Execute", callback_data="rswap:execute")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="main_menu")]
        ]),
        parse_mode="HTML"
    )
    await state.set_state(RealSwapStates.confirm)


@router.callback_query(RealSwapStates.confirm, F.data == "rswap:execute")
async def execute_swap(callback: CallbackQuery, state: FSMContext):
    """Execute the real swap"""
    data = await state.get_data()
    
    await callback.message.edit_text(
        "⏳ <b>Processing swap...</b>\n\n"
        "Creating exchange transaction...",
        parse_mode="HTML"
    )
    
    try:
        async with db_manager.session() as session:
            user = await UserRepository().get_by_telegram_id(session, callback.from_user.id)
            
            # Get destination wallet address
            to_wallet = await WalletRepository().get_user_wallet_by_network(
                session, user.id, data['to_network']
            )
            
            if not to_wallet:
                # Create wallet if not exists
                result = await wallet_service.create_wallet_for_network(
                    session, user.id, data['to_network']
                )
                to_address = result['address']
            else:
                to_address = to_wallet.address
            
            # Get source wallet for refund
            from_wallet = await WalletRepository().get_user_wallet_by_network(
                session, user.id, data['from_network']
            )
            
            # Create exchange via API
            from_ticker = NETWORK_TO_TICKER.get(data['from_network'], data['from_symbol'].lower())
            to_ticker = NETWORK_TO_TICKER.get(data['to_network'], data['to_symbol'].lower())
            
            exchange = await swap_service.create_exchange(
                from_currency=from_ticker,
                to_currency=to_ticker,
                from_amount=Decimal(data['amount']),
                to_address=to_address,
                refund_address=from_wallet.address if from_wallet else None
            )
            
            if not exchange:
                await callback.message.edit_text(
                    "❌ <b>Failed to create exchange</b>\n\n"
                    "Please try again later.",
                    reply_markup=get_back_keyboard(),
                    parse_mode="HTML"
                )
                await state.clear()
                return
            
            # Save transaction
            tx = Transaction(
                id=str(uuid.uuid4()),
                user_id=user.id,
                wallet_id=from_wallet.id if from_wallet else None,
                tx_type=TransactionType.SWAP,
                status=TransactionStatus.PENDING,
                network=data['from_network'],
                token_symbol=data['from_symbol'],
                amount=Decimal(data['amount']),
                swap_to_token=data['to_symbol'],
                swap_to_amount=Decimal(data['receive_amount']),
                internal_ref=exchange.get('id'),  # ✅ Используем internal_ref
                memo=f"ChangeNOW: {exchange.get('id')}"
            )
            session.add(tx)
            await session.commit()
            
            # Show deposit instructions
            deposit_address = exchange.get('payinAddress')
            exchange_id = exchange.get('id')
            
            text = f"""
✅ <b>Exchange Created!</b>

<b>Exchange ID:</b> <code>{exchange_id}</code>

━━━━━━━━━━━━━━━

<b>Step 1:</b> Send exactly:
<code>{data['amount']}</code> {data['from_symbol']}

<b>Step 2:</b> To this address:
<code>{deposit_address}</code>

━━━━━━━━━━━━━━━

<b>You will receive:</b>
~{data['receive_amount']} {data['to_symbol']}

<b>To address:</b>
<code>{to_address}</code>

━━━━━━━━━━━━━━━

⏱ Exchange usually takes 10-30 minutes.
Use the button below to check status.
"""
            
            await callback.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🔄 Check Status",
                        callback_data=f"rswap:status:{exchange_id}"
                    )],
                    [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")]
                ]),
                parse_mode="HTML"
            )
            
    except Exception as e:
        logger.error("execute_swap error", error=str(e))
        await callback.message.edit_text(
            "❌ <b>Swap failed</b>\n\n"
            f"Error: {str(e)}",
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
    
    await state.clear()
    await callback.answer()


@router.callback_query(F.data.startswith("rswap:status:"))
async def check_swap_status(callback: CallbackQuery):
    """Check swap status"""
    exchange_id = callback.data.split(":")[2]
    
    status = await swap_service.get_exchange_status(exchange_id)
    
    if not status:
        await callback.answer("Unable to get status", show_alert=True)
        return
    
    status_emoji = {
        "waiting": "⏳",
        "confirming": "🔄",
        "exchanging": "💱",
        "sending": "📤",
        "finished": "✅",
        "failed": "❌",
        "refunded": "↩️"
    }
    
    emoji = status_emoji.get(status.status, "❓")
    
    text = f"""
{emoji} <b>Swap Status</b>

<b>ID:</b> <code>{status.id}</code>
<b>Status:</b> {status.status.upper()}

📤 Sent: {status.from_amount} {status.from_currency.upper()}
📥 Receive: {status.to_amount or 'pending'} {status.to_currency.upper()}

"""
    
    if status.tx_from:
        text += f"📝 Deposit TX: <code>{status.tx_from[:20]}...</code>\n"
    
    if status.tx_to:
        text += f"📝 Payout TX: <code>{status.tx_to[:20]}...</code>\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🔄 Refresh",
                callback_data=f"rswap:status:{exchange_id}"
            )],
            [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()
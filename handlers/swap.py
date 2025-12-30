"""
NEXUS WALLET - Swap Handler
Real token swaps via 1inch API
"""

from decimal import Decimal, InvalidOperation
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import structlog

from database.connection import db_manager
from database.repositories.user_repository import UserRepository
from database.repositories.wallet_repository import WalletRepository
from blockchain.wallet_manager import NETWORKS, wallet_manager
from services.swap_service import swap_service, TOKEN_ADDRESSES
from services.price_service import price_service
from security.encryption_manager import encryption_manager
from locales.messages import get_text
from keyboards.inline import get_back_keyboard

logger = structlog.get_logger()
router = Router(name="swap")


class SwapStates(StatesGroup):
    selecting_network = State()
    selecting_from_token = State()
    selecting_to_token = State()
    entering_amount = State()
    confirming = State()
    entering_pin = State()


async def get_user_and_lang(callback_or_message) -> tuple:
    """Helper to get user and language"""
    user_id = callback_or_message.from_user.id
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, user_id)
        lang = user.language_code if user else "en"
        return user, lang


@router.callback_query(F.data == "swap")
async def swap_menu(callback: CallbackQuery, state: FSMContext):
    """Show swap menu - select network"""
    await state.clear()
    user, lang = await get_user_and_lang(callback)
    
    if not user:
        await callback.answer("Please /start first", show_alert=True)
        return
    
    async with db_manager.session() as session:
        wallet_repo = WalletRepository()
        wallets = await wallet_repo.get_user_wallets(session, user.id)
        
        if not wallets:
            try:
                await callback.message.edit_text(
                    get_text("wallet_empty", lang),
                    reply_markup=get_back_keyboard("main_menu", lang),
                    parse_mode="HTML"
                )
            except Exception:
                pass
            await callback.answer()
            return
        
        # Filter to networks that support swaps
        swap_networks = [w for w in wallets if w.network in TOKEN_ADDRESSES]
        
        if not swap_networks:
            try:
                await callback.message.edit_text(
                    "❌ <b>Swap Not Available</b>\n\n"
                    "No wallets on supported networks.\n"
                    "Supported: Ethereum, BSC, Polygon, Arbitrum, Avalanche",
                    reply_markup=get_back_keyboard("main_menu", lang),
                    parse_mode="HTML"
                )
            except Exception:
                pass
            await callback.answer()
            return
        
        text = get_text("swap_title", lang) + "\n\n"
        text += "Select network for swap:"
        
        buttons = []
        for wallet in swap_networks:
            config = NETWORKS.get(wallet.network)
            if config:
                buttons.append([InlineKeyboardButton(
                    text=f"{config.icon} {config.name}",
                    callback_data=f"swap:network:{wallet.network}"
                )])
        
        buttons.append([InlineKeyboardButton(
            text=get_text("btn_back", lang),
            callback_data="main_menu"
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


@router.callback_query(F.data.startswith("swap:network:"))
async def select_network(callback: CallbackQuery, state: FSMContext):
    """Network selected, show from token selection"""
    network = callback.data.split(":")[2]
    user, lang = await get_user_and_lang(callback)
    
    await state.update_data(network=network, lang=lang, user_id=user.id)
    
    config = NETWORKS.get(network)
    tokens = await swap_service.get_supported_tokens(network)
    
    if not tokens:
        await callback.answer("No tokens available for this network", show_alert=True)
        return
    
    text = f"{config.icon} <b>{config.name}</b>\n\n"
    text += get_text("swap_select_from", lang)
    
    buttons = []
    row = []
    for token in tokens:
        row.append(InlineKeyboardButton(
            text=token,
            callback_data=f"swap:from:{token}"
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(
        text=get_text("btn_back", lang),
        callback_data="swap"
    )])
    
    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML"
        )
    except Exception:
        pass
    
    await state.set_state(SwapStates.selecting_from_token)
    await callback.answer()


@router.callback_query(F.data.startswith("swap:from:"), SwapStates.selecting_from_token)
async def select_from_token(callback: CallbackQuery, state: FSMContext):
    """From token selected, show to token selection"""
    from_token = callback.data.split(":")[2]
    data = await state.get_data()
    lang = data.get("lang", "en")
    network = data.get("network")
    
    await state.update_data(from_token=from_token)
    
    tokens = await swap_service.get_supported_tokens(network)
    config = NETWORKS.get(network)
    
    text = f"{config.icon} <b>{config.name}</b>\n\n"
    text += f"📤 From: <b>{from_token}</b>\n\n"
    text += get_text("swap_select_to", lang)
    
    buttons = []
    row = []
    for token in tokens:
        if token != from_token:
            row.append(InlineKeyboardButton(
                text=token,
                callback_data=f"swap:to:{token}"
            ))
            if len(row) == 3:
                buttons.append(row)
                row = []
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(
        text=get_text("btn_back", lang),
        callback_data=f"swap:network:{network}"
    )])
    
    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML"
        )
    except Exception:
        pass
    
    await state.set_state(SwapStates.selecting_to_token)
    await callback.answer()


@router.callback_query(F.data.startswith("swap:to:"), SwapStates.selecting_to_token)
async def select_to_token(callback: CallbackQuery, state: FSMContext):
    """To token selected, show amount input"""
    to_token = callback.data.split(":")[2]
    data = await state.get_data()
    lang = data.get("lang", "en")
    network = data.get("network")
    from_token = data.get("from_token")
    user_id = data.get("user_id")
    
    await state.update_data(to_token=to_token)
    
    # Get wallet and balance
    async with db_manager.session() as session:
        wallet_repo = WalletRepository()
        wallet = await wallet_repo.get_user_wallet_by_network(session, user_id, network)
        
        if not wallet:
            await callback.answer("Wallet not found", show_alert=True)
            return
        
        await state.update_data(wallet_id=wallet.id)
        
        # Get balance
        try:
            if from_token == NETWORKS[network].symbol:
                balance = await wallet_manager.get_balance(network, wallet.address)
            else:
                token_address = swap_service.get_token_address(network, from_token)
                if token_address:
                    balance = await wallet_manager.get_token_balance(
                        network, wallet.address, token_address
                    )
                else:
                    balance = Decimal("0")
        except Exception:
            balance = Decimal("0")
        
        await state.update_data(balance=str(balance))
    
    # Get prices for display
    from_price = await price_service.get_price(from_token)
    to_price = await price_service.get_price(to_token)
    
    rate_str = ""
    if from_price and to_price and to_price > 0:
        rate = from_price / to_price
        rate_str = f"\n💹 Rate: 1 {from_token} ≈ {rate:.6f} {to_token}"
    
    text = get_text("swap_enter_amount", lang,
                   from_symbol=from_token,
                   to_symbol=to_token,
                   balance=f"{balance:.6f}")
    text += rate_str
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="25%", callback_data="swap:pct:25"),
            InlineKeyboardButton(text="50%", callback_data="swap:pct:50"),
            InlineKeyboardButton(text="75%", callback_data="swap:pct:75"),
            InlineKeyboardButton(text="MAX", callback_data="swap:pct:100"),
        ],
        [InlineKeyboardButton(text=get_text("btn_cancel", lang), callback_data="swap")]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    
    await state.set_state(SwapStates.entering_amount)
    await callback.answer()


@router.callback_query(F.data.startswith("swap:pct:"), SwapStates.entering_amount)
async def swap_percentage(callback: CallbackQuery, state: FSMContext):
    """Use percentage of balance"""
    pct = int(callback.data.split(":")[2])
    data = await state.get_data()
    balance = Decimal(data.get("balance", "0"))
    network = data.get("network")
    from_token = data.get("from_token")
    
    # For native tokens, reserve some for gas
    native_symbol = NETWORKS[network].symbol
    if from_token == native_symbol and pct == 100:
        # Reserve ~0.01 for gas
        amount = max(balance - Decimal("0.01"), Decimal("0"))
    else:
        amount = balance * Decimal(pct) / Decimal("100")
    
    if amount <= 0:
        await callback.answer("Insufficient balance", show_alert=True)
        return
    
    await state.update_data(amount=str(amount))
    await show_swap_quote(callback, state)
    await callback.answer()


@router.message(SwapStates.entering_amount)
async def process_swap_amount(message: Message, state: FSMContext):
    """Process entered amount"""
    data = await state.get_data()
    lang = data.get("lang", "en")
    balance = Decimal(data.get("balance", "0"))
    from_token = data.get("from_token")
    
    try:
        amount = Decimal(message.text.strip().replace(",", "."))
        if amount <= 0:
            raise ValueError()
    except (InvalidOperation, ValueError):
        await message.answer(get_text("send_invalid_amount", lang))
        return
    
    if amount > balance:
        await message.answer(
            get_text("send_insufficient_balance", lang,
                    symbol=from_token,
                    balance=f"{balance:.6f}")
        )
        return
    
    await state.update_data(amount=str(amount))
    
    # Create fake callback
    class FakeCallback:
        def __init__(self, msg):
            self.message = msg
            self.from_user = msg.from_user
        async def answer(self, *args, **kwargs):
            pass
    
    await show_swap_quote(FakeCallback(message), state)


async def show_swap_quote(callback, state: FSMContext):
    """Get and show real quote from 1inch"""
    data = await state.get_data()
    lang = data.get("lang", "en")
    network = data.get("network")
    from_token = data.get("from_token")
    to_token = data.get("to_token")
    amount = Decimal(data.get("amount", "0"))
    
    # Show loading
    loading_text = "⏳ <b>Getting best rate...</b>\n\nFetching quote from 1inch..."
    
    try:
        if hasattr(callback.message, 'edit_text'):
            await callback.message.edit_text(loading_text, parse_mode="HTML")
        else:
            loading_msg = await callback.message.answer(loading_text, parse_mode="HTML")
    except Exception:
        pass
    
    # Get real quote
    quote = await swap_service.get_quote(
        network=network,
        from_token=from_token,
        to_token=to_token,
        amount=amount,
        slippage=0.5
    )
    
    if not quote:
        error_text = "❌ <b>Quote Failed</b>\n\n"
        error_text += "Could not get swap quote. Try:\n"
        error_text += "• Different amount\n"
        error_text += "• Different token pair\n"
        error_text += "• Try again later"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Try Again", callback_data="swap")],
            [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="main_menu")]
        ])
        
        try:
            if hasattr(callback.message, 'edit_text'):
                await callback.message.edit_text(error_text, reply_markup=keyboard, parse_mode="HTML")
            else:
                await loading_msg.edit_text(error_text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass
        return
    
    # Store quote data
    await state.update_data(
        to_amount=str(quote["to_amount"]),
        rate=str(quote["rate"]),
        fee_amount=str(quote["fee_amount"]),
        fee_token=quote["fee_token"],
        fee_usd=str(quote["fee_usd"]),
    )
    
    # Format quote
    config = NETWORKS.get(network)
    
    text = get_text("swap_quote", lang,
                   from_amount=f"{amount:.6f}",
                   from_symbol=from_token,
                   to_amount=f"{quote['to_amount']:.6f}",
                   to_symbol=to_token,
                   rate=f"{quote['rate']:.6f}",
                   fee_usd=f"{quote['fee_usd']:.2f}",
                   slippage="0.5")
    
    text += f"\n\n{config.icon} Network: {config.name}"
    
    if quote.get("price_impact", 0) > 1:
        text += f"\n⚠️ Price impact: {quote['price_impact']:.2f}%"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ " + get_text("swap_confirm", lang),
            callback_data="swap:execute"
        )],
        [InlineKeyboardButton(
            text="🔄 Refresh Quote",
            callback_data="swap:refresh"
        )],
        [InlineKeyboardButton(
            text=get_text("btn_cancel", lang),
            callback_data="swap"
        )]
    ])
    
    try:
        if hasattr(callback.message, 'edit_text'):
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await loading_msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    
    await state.set_state(SwapStates.confirming)


@router.callback_query(F.data == "swap:refresh", SwapStates.confirming)
async def refresh_quote(callback: CallbackQuery, state: FSMContext):
    """Refresh the quote"""
    await show_swap_quote(callback, state)
    await callback.answer("Quote refreshed!")


@router.callback_query(F.data == "swap:execute", SwapStates.confirming)
async def request_pin_for_swap(callback: CallbackQuery, state: FSMContext):
    """Request PIN before executing swap"""
    data = await state.get_data()
    lang = data.get("lang", "en")
    
    text = get_text("enter_pin", lang)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_cancel", lang), callback_data="swap")]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    
    await state.set_state(SwapStates.entering_pin)
    await callback.answer()


@router.message(SwapStates.entering_pin)
async def execute_swap(message: Message, state: FSMContext):
    """Verify PIN and execute swap"""
    pin = message.text.strip()
    data = await state.get_data()
    lang = data.get("lang", "en")
    
    # Delete PIN message
    try:
        await message.delete()
    except Exception:
        pass
    
    # Verify PIN
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, message.from_user.id)
        
        if not encryption_manager.verify_pin(pin, user.pin_hash):
            await message.answer(
                get_text("pin_incorrect", lang),
                reply_markup=get_back_keyboard("swap", lang),
                parse_mode="HTML"
            )
            await state.clear()
            return
        
        # Get data
        network = data.get("network")
        from_token = data.get("from_token")
        to_token = data.get("to_token")
        amount = Decimal(data.get("amount", "0"))
        wallet_id = data.get("wallet_id")
        
        # Show processing
        status_msg = await message.answer(
            get_text("swap_processing", lang),
            parse_mode="HTML"
        )
        
        try:
            # Execute real swap
            result = await swap_service.execute_swap(
                session=session,
                user_id=user.id,
                wallet_id=wallet_id,
                network=network,
                from_token=from_token,
                to_token=to_token,
                amount=amount,
                slippage=0.5
            )
            
            await session.commit()
            
            if result.get("success"):
                text = get_text("swap_success", lang,
                               from_amount=f"{result['from_amount']:.6f}",
                               from_symbol=result['from_token'],
                               to_amount=f"{result['to_amount']:.6f}",
                               to_symbol=result['to_token'],
                               explorer=result['explorer_url'])
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🔗 View Transaction",
                        url=result['explorer_url']
                    )],
                    [InlineKeyboardButton(
                        text="💱 Swap More",
                        callback_data="swap"
                    )],
                    [InlineKeyboardButton(
                        text=get_text("btn_back", lang),
                        callback_data="main_menu"
                    )]
                ])
                
                await status_msg.edit_text(
                    text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                
                logger.info(
                    "Swap executed",
                    user_id=user.id,
                    from_token=from_token,
                    to_token=to_token,
                    amount=str(amount),
                    tx_hash=result.get('tx_hash')
                )
            else:
                error = result.get("error", "Unknown error")
                
                text = f"❌ <b>Swap Failed</b>\n\n"
                text += f"Error: {error}\n\n"
                text += "Please try again or contact support."
                
                if result.get("tx_hash"):
                    text += f"\n\nTx: <code>{result['tx_hash']}</code>"
                
                await status_msg.edit_text(
                    text,
                    reply_markup=get_back_keyboard("swap", lang),
                    parse_mode="HTML"
                )
                
        except Exception as e:
            logger.error("Swap execution error", error=str(e))
            
            await status_msg.edit_text(
                f"❌ <b>Swap Failed</b>\n\nError: {str(e)[:200]}",
                reply_markup=get_back_keyboard("swap", lang),
                parse_mode="HTML"
            )
    
    await state.clear()


# ==================== SWAP HISTORY ====================

@router.callback_query(F.data == "swap:history")
async def swap_history(callback: CallbackQuery):
    """Show swap history"""
    user, lang = await get_user_and_lang(callback)
    
    async with db_manager.session() as session:
        swaps = await swap_service.get_user_swaps(session, user.id, limit=10)
        
        if not swaps:
            text = "💱 <b>Swap History</b>\n\n"
            text += "📭 No swaps yet."
        else:
            text = "💱 <b>Swap History</b>\n\n"
            
            for swap in swaps:
                status_icon = "✅" if swap.status == "completed" else "❌" if swap.status == "failed" else "⏳"
                
                text += f"{status_icon} {swap.from_amount:.4f} {swap.from_token} → "
                text += f"{swap.to_amount or swap.to_amount_expected:.4f} {swap.to_token}\n"
                text += f"   📅 {swap.created_at.strftime('%d %b %H:%M')}\n\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💱 New Swap", callback_data="swap")],
            [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="main_menu")]
        ])
        
        try:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass
    
    await callback.answer()
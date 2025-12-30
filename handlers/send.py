"""
NEXUS WALLET - Send Handler
Real crypto transactions on blockchain
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
from blockchain.wallet_manager import wallet_manager, NETWORKS
from services.transaction_service import transaction_service
from services.price_service import price_service
from security.encryption_manager import encryption_manager
from locales.messages import get_text
from keyboards.inline import get_back_keyboard, get_networks_keyboard

logger = structlog.get_logger()
router = Router(name="send")


class SendStates(StatesGroup):
    choosing_network = State()
    entering_address = State()
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


@router.callback_query(F.data == "send")
async def send_menu(callback: CallbackQuery, state: FSMContext):
    """Show send menu - select network"""
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
        
        await state.update_data(user_id=user.id, lang=lang)
        
        text = get_text("send_choose_network", lang)
        
        try:
            await callback.message.edit_text(
                text,
                reply_markup=get_networks_keyboard(lang, "send", wallets),
                parse_mode="HTML"
            )
        except Exception:
            pass
    
    await callback.answer()


@router.callback_query(F.data.startswith("send:"))
async def select_network_for_send(callback: CallbackQuery, state: FSMContext):
    """Network selected for sending"""
    network = callback.data.split(":")[1]
    
    # Skip if it's not a network selection
    if network in ["confirm", "max"]:
        return
    
    data = await state.get_data()
    user_id = data.get("user_id")
    lang = data.get("lang", "en")
    
    if not user_id:
        user, lang = await get_user_and_lang(callback)
        user_id = user.id
        await state.update_data(user_id=user_id, lang=lang)
    
    async with db_manager.session() as session:
        wallet_repo = WalletRepository()
        wallet = await wallet_repo.get_user_wallet_by_network(session, user_id, network)
        
        if not wallet:
            await callback.answer("Wallet not found", show_alert=True)
            return
        
        config = NETWORKS.get(network)
        
        # Get real balance from blockchain
        try:
            balance = await wallet_manager.get_balance(network, wallet.address)
        except Exception as e:
            logger.error(f"Failed to get balance", error=str(e))
            balance = Decimal("0")
        
        # Get USD value
        price = await price_service.get_price(config.symbol)
        balance_usd = float(balance) * float(price) if price else 0
        
        await state.update_data(
            network=network,
            wallet_id=wallet.id,
            wallet_address=wallet.address,
            balance=str(balance),
            balance_usd=str(balance_usd),
            token_symbol=config.symbol
        )
        
        text = get_text("send_enter_address", lang,
                       symbol=config.symbol,
                       icon=config.icon,
                       network=config.name,
                       balance=f"{balance:.6f}")
        
        if balance_usd > 0:
            text += f"\n💵 ≈ ${balance_usd:,.2f}"
        
        try:
            await callback.message.edit_text(
                text,
                reply_markup=get_back_keyboard("send", lang),
                parse_mode="HTML"
            )
        except Exception:
            pass
        
        await state.set_state(SendStates.entering_address)
    
    await callback.answer()


@router.message(SendStates.entering_address)
async def process_address(message: Message, state: FSMContext):
    """Process recipient address"""
    address = message.text.strip()
    data = await state.get_data()
    lang = data.get("lang", "en")
    network = data.get("network")
    
    config = NETWORKS.get(network)
    
    # Validate address based on network type
    is_valid = False
    error_msg = ""
    
    if config.network_type.value == "evm":
        if address.startswith("0x") and len(address) == 42:
            # Check if valid hex
            try:
                int(address, 16)
                is_valid = True
            except ValueError:
                error_msg = "Invalid hexadecimal address"
        else:
            error_msg = "Address must start with 0x and be 42 characters"
    elif network == "bitcoin":
        # Basic Bitcoin address validation
        if len(address) >= 26 and len(address) <= 62:
            if address.startswith(("1", "3", "bc1")):
                is_valid = True
            else:
                error_msg = "Invalid Bitcoin address format"
        else:
            error_msg = "Invalid Bitcoin address length"
    elif network == "solana":
        if len(address) >= 32 and len(address) <= 44:
            is_valid = True
        else:
            error_msg = "Invalid Solana address"
    elif network == "tron":
        if address.startswith("T") and len(address) == 34:
            is_valid = True
        else:
            error_msg = "TRON address must start with T and be 34 characters"
    elif network == "ton":
        if len(address) >= 48:
            is_valid = True
        else:
            error_msg = "Invalid TON address"
    else:
        # Generic validation
        if len(address) > 20:
            is_valid = True
    
    if not is_valid:
        await message.answer(
            get_text("send_invalid_address", lang, network=config.name) + 
            (f"\n\n{error_msg}" if error_msg else ""),
            reply_markup=get_back_keyboard("send", lang),
            parse_mode="HTML"
        )
        return
    
    # Check if sending to self
    wallet_address = data.get("wallet_address", "")
    if address.lower() == wallet_address.lower():
        await message.answer(
            "❌ Cannot send to your own address",
            reply_markup=get_back_keyboard("send", lang),
            parse_mode="HTML"
        )
        return
    
    await state.update_data(to_address=address)
    
    balance = data.get("balance", "0")
    token_symbol = data.get("token_symbol", "")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="25%", callback_data="send:pct:25"),
            InlineKeyboardButton(text="50%", callback_data="send:pct:50"),
            InlineKeyboardButton(text="75%", callback_data="send:pct:75"),
            InlineKeyboardButton(text="MAX", callback_data="send:pct:100"),
        ],
        [InlineKeyboardButton(text=get_text("btn_cancel", lang), callback_data="send")]
    ])
    
    short_addr = f"{address[:10]}...{address[-6:]}"
    
    text = get_text("send_enter_amount", lang,
                   symbol=token_symbol,
                   address=short_addr,
                   balance=balance)
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(SendStates.entering_amount)


@router.callback_query(F.data.startswith("send:pct:"), SendStates.entering_amount)
async def send_percentage(callback: CallbackQuery, state: FSMContext):
    """Send percentage of balance"""
    pct = int(callback.data.split(":")[2])
    data = await state.get_data()
    balance = Decimal(data.get("balance", "0"))
    network = data.get("network")
    
    # For native tokens, reserve gas
    config = NETWORKS.get(network)
    if config.network_type.value == "evm":
        gas_reserve = Decimal("0.005")  # Reserve for gas
    else:
        gas_reserve = Decimal("0.001")
    
    if pct == 100:
        amount = max(balance - gas_reserve, Decimal("0"))
    else:
        amount = balance * Decimal(pct) / Decimal("100")
    
    if amount <= 0:
        await callback.answer("Insufficient balance", show_alert=True)
        return
    
    await state.update_data(amount=str(amount))
    await show_confirmation(callback, state)
    await callback.answer()


@router.message(SendStates.entering_amount)
async def process_amount(message: Message, state: FSMContext):
    """Process send amount"""
    data = await state.get_data()
    lang = data.get("lang", "en")
    balance = Decimal(data.get("balance", "0"))
    token_symbol = data.get("token_symbol", "")
    
    try:
        amount = Decimal(message.text.strip().replace(",", "."))
        if amount <= 0:
            raise ValueError("Amount must be positive")
    except (InvalidOperation, ValueError):
        await message.answer(get_text("send_invalid_amount", lang), parse_mode="HTML")
        return
    
    if amount > balance:
        await message.answer(
            get_text("send_insufficient_balance", lang,
                    symbol=token_symbol,
                    balance=f"{balance:.6f}"),
            parse_mode="HTML"
        )
        return
    
    await state.update_data(amount=str(amount))
    
    # Create fake callback for confirmation
    class FakeCallback:
        def __init__(self, msg):
            self.message = msg
            self.from_user = msg.from_user
        async def answer(self, *args, **kwargs):
            pass
    
    await show_confirmation(FakeCallback(message), state)


async def show_confirmation(callback, state: FSMContext):
    """Show transaction confirmation"""
    data = await state.get_data()
    lang = data.get("lang", "en")
    network = data.get("network")
    to_address = data.get("to_address")
    amount = Decimal(data.get("amount", "0"))
    token_symbol = data.get("token_symbol", "")
    wallet_address = data.get("wallet_address", "")
    
    config = NETWORKS.get(network)
    
    # Estimate real gas fee
    try:
        fee_info = await wallet_manager.estimate_gas(
            network, wallet_address, to_address, amount
        )
        fee = fee_info.get("total_fee", Decimal("0"))
        fee_gwei = fee_info.get("gas_price_gwei", 0)
    except Exception:
        fee = Decimal("0.001")
        fee_gwei = 0
    
    # Get USD values
    price = await price_service.get_price(token_symbol)
    amount_usd = float(amount) * float(price) if price else 0
    fee_usd = float(fee) * float(price) if price else 0
    
    await state.update_data(
        fee=str(fee),
        fee_usd=str(fee_usd),
        amount_usd=str(amount_usd)
    )
    
    short_addr = f"{to_address[:10]}...{to_address[-6:]}"
    
    text = get_text("send_confirm", lang,
                   icon=config.icon,
                   network=config.name,
                   address=short_addr,
                   amount=f"{amount:.8f}".rstrip('0').rstrip('.'),
                   symbol=token_symbol,
                   fee=f"{fee:.6f}")
    
    text += f"\n\n💵 Value: ${amount_usd:,.2f}"
    text += f"\n⛽ Fee: ${fee_usd:.4f}"
    
    if fee_gwei:
        text += f" ({fee_gwei:.1f} Gwei)"
    
    total = amount + fee
    text += f"\n📊 Total: {total:.8f}".rstrip('0').rstrip('.') + f" {token_symbol}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ " + get_text("confirm", lang),
                callback_data="send:confirm"
            ),
            InlineKeyboardButton(
                text="❌ " + get_text("cancel", lang),
                callback_data="send"
            )
        ]
    ])
    
    if hasattr(callback.message, 'edit_text'):
        try:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass
    else:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    
    await state.set_state(SendStates.confirming)


@router.callback_query(F.data == "send:confirm", SendStates.confirming)
async def request_pin_for_send(callback: CallbackQuery, state: FSMContext):
    """Request PIN to confirm transaction"""
    data = await state.get_data()
    lang = data.get("lang", "en")
    
    try:
        await callback.message.edit_text(
            get_text("enter_pin", lang),
            reply_markup=get_back_keyboard("send", lang),
            parse_mode="HTML"
        )
    except Exception:
        pass
    
    await state.set_state(SendStates.entering_pin)
    await callback.answer()


@router.message(SendStates.entering_pin)
async def process_pin_and_send(message: Message, state: FSMContext):
    """Verify PIN and send real transaction"""
    pin = message.text.strip()
    data = await state.get_data()
    lang = data.get("lang", "en")
    
    # Delete PIN message immediately
    try:
        await message.delete()
    except Exception:
        pass
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, message.from_user.id)
        
        # Verify PIN
        if not encryption_manager.verify_pin(pin, user.pin_hash):
            await message.answer(
                get_text("pin_incorrect", lang),
                reply_markup=get_back_keyboard("main_menu", lang),
                parse_mode="HTML"
            )
            await state.clear()
            return
        
        # Get wallet
        wallet_repo = WalletRepository()
        wallet = await wallet_repo.get_by_id(session, data.get("wallet_id"))
        
        if not wallet:
            await message.answer(
                get_text("error_generic", lang),
                reply_markup=get_back_keyboard("main_menu", lang),
                parse_mode="HTML"
            )
            await state.clear()
            return
        
        network = data.get("network")
        to_address = data.get("to_address")
        amount = Decimal(data.get("amount", "0"))
        token_symbol = data.get("token_symbol", "")
        amount_usd = Decimal(data.get("amount_usd", "0"))
        fee = Decimal(data.get("fee", "0"))
        fee_usd = Decimal(data.get("fee_usd", "0"))
        
        config = NETWORKS.get(network)
        
        # Show processing
        status_msg = await message.answer(
            get_text("send_processing", lang),
            parse_mode="HTML"
        )
        
        # Create pending transaction record
        tx_record = await transaction_service.create_transaction(
            session,
            user_id=user.id,
            wallet_id=wallet.id,
            tx_type="send",
            network=network,
            token_symbol=token_symbol,
            amount=amount,
            from_address=wallet.address,
            to_address=to_address,
            fee_amount=fee,
            fee_token=token_symbol,
            status="pending"
        )
        await session.commit()
        
        try:
            # Decrypt private key
            private_key = encryption_manager.decrypt_private_key(wallet.encrypted_private_key)
            
            # Send real transaction
            tx_hash = await wallet_manager.send_transaction(
                network=network,
                private_key=private_key,
                to_address=to_address,
                amount=amount
            )
            
            # Update transaction record
            await transaction_service.confirm_transaction(
                session, tx_record.id, tx_hash
            )
            
            # Update user volume
            await user_repo.increment_volume(session, user.id, float(amount_usd))
            
            await session.commit()
            
            explorer_url = f"{config.explorer_url}/tx/{tx_hash}"
            short_addr = f"{to_address[:8]}...{to_address[-6:]}"
            
            text = get_text("send_success", lang,
                           amount=f"{amount:.8f}".rstrip('0').rstrip('.'),
                           symbol=token_symbol,
                           address=short_addr,
                           explorer=explorer_url,
                           tx_hash=f"{tx_hash[:20]}...")
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔗 View on Explorer",
                    url=explorer_url
                )],
                [InlineKeyboardButton(
                    text="📤 Send More",
                    callback_data="send"
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
                "Transaction sent",
                user_id=user.id,
                network=network,
                amount=str(amount),
                to=to_address,
                tx_hash=tx_hash
            )
            
        except Exception as e:
            error_msg = str(e)[:200]
            
            # Update transaction as failed
            await transaction_service.fail_transaction(
                session, tx_record.id, error_msg
            )
            await session.commit()
            
            logger.error("Transaction failed", error=str(e))
            
            await status_msg.edit_text(
                get_text("send_failed", lang, error=error_msg),
                reply_markup=get_back_keyboard("main_menu", lang),
                parse_mode="HTML"
            )
    
    await state.clear()
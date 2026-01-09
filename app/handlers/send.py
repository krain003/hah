"""
NEXUS WALLET - Send Handler (Production-Ready)
Complete send flow with validation, gas estimation, and confirmation
"""

import asyncio
from decimal import Decimal, InvalidOperation
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
import structlog

from database.connection import db_manager
from database.repositories.user_repository import UserRepository
from database.repositories.wallet_repository import WalletRepository
from services.wallet_service import (
    wallet_service, WalletServiceError, 
    InsufficientFundsError, WalletNotFoundError, InvalidPinError,
    TransactionFailedError  # ← Добавить!
)
from services.transaction_service import transaction_service
from blockchain.wallet_manager import wallet_manager, NETWORKS
from security.encryption_manager import encryption_manager
from locales.messages import get_text

logger = structlog.get_logger(__name__)
router = Router(name="send")


class SendStates(StatesGroup):
    choosing_network = State()
    entering_address = State()
    entering_amount = State()
    confirming = State()
    entering_pin = State()
    processing = State()


# ==================== KEYBOARDS ====================

def get_send_network_keyboard(lang: str, networks: list) -> InlineKeyboardMarkup:
    """Generate network selection keyboard for send"""
    buttons = []
    row = []
    
    for net in networks:
        config = NETWORKS.get(net)
        if not config:
            continue
        
        row.append(InlineKeyboardButton(
            text=f"{config.icon} {config.symbol}",
            callback_data=f"send:{net}"
        ))
        
        if len(row) == 3:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    buttons.append([
        InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="main_menu")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_amount_keyboard(lang: str, balance: str) -> InlineKeyboardMarkup:
    """Keyboard with preset amounts and MAX button"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="25%", callback_data="amount_pct:25"),
            InlineKeyboardButton(text="50%", callback_data="amount_pct:50"),
            InlineKeyboardButton(text="75%", callback_data="amount_pct:75"),
            InlineKeyboardButton(text=get_text("send_max", lang), callback_data="amount_pct:100"),
        ],
        [InlineKeyboardButton(text=get_text("btn_cancel", lang), callback_data="main_menu")]
    ])


def get_confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Confirmation keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ {get_text('confirm', lang)}", callback_data="send_confirm")],
        [InlineKeyboardButton(text=f"❌ {get_text('cancel', lang)}", callback_data="main_menu")]
    ])


def get_cancel_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Cancel keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_cancel", lang), callback_data="main_menu")]
    ])


# ==================== SEND FLOW ====================

@router.callback_query(F.data == "send")
async def send_start(callback: CallbackQuery, state: FSMContext):
    """Start send flow - show network selection"""
    # Сначала отвечаем на callback чтобы избежать timeout!
    try:
        await callback.answer()
    except Exception:
        pass  # Игнорируем если уже expired
    
    await state.clear()
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        
        if not user:
            try:
                await callback.answer("Please /start first", show_alert=True)
            except Exception:
                await callback.message.answer("Please /start first")
            return
        
        lang = user.language_code or "en"
        await state.update_data(lang=lang, user_id=user.id)
        
        wallet_repo = WalletRepository()
        wallets = await wallet_repo.get_user_wallets(session, user.id)
        
        if not wallets:
            try:
                await callback.answer(get_text("wallet_empty", lang), show_alert=True)
            except Exception:
                await callback.message.answer(get_text("wallet_empty", lang))
            return
        
        networks = [w.network for w in wallets]
        keyboard = get_send_network_keyboard(lang, networks)
        
        await safe_edit(callback.message, get_text("send_choose_network", lang), keyboard)
        await state.set_state(SendStates.choosing_network)

@router.callback_query(SendStates.choosing_network, F.data.startswith("send:"))
async def send_select_network(callback: CallbackQuery, state: FSMContext):
    """Network selected - prompt for address"""
    network = callback.data.split(":")[1]
    data = await state.get_data()
    lang = data.get("lang", "en")
    user_id = data.get("user_id")
    
    async with db_manager.session() as session:
        wallet_repo = WalletRepository()
        wallet = await wallet_repo.get_user_wallet_by_network(session, user_id, network)
        
        if not wallet:
            await callback.answer("Wallet not found", show_alert=True)
            return
        
        # Get balance
        balance = await wallet_manager.get_balance(network, wallet.address)
        
        config = NETWORKS[network]
        await state.update_data(
            network=network,
            wallet_id=wallet.id,
            wallet_address=wallet.address,
            balance=str(balance),
            symbol=config.symbol,
            icon=config.icon,
            network_name=config.name,
            explorer_url=config.explorer_url
        )
        
        text = get_text("send_enter_address", lang,
            symbol=config.symbol,
            icon=config.icon,
            network=config.name,
            balance=f"{balance:.8f}".rstrip('0').rstrip('.')
        )
        
        await safe_edit(callback.message, text, get_cancel_keyboard(lang))
        await state.set_state(SendStates.entering_address)
    
    await callback.answer()


@router.message(SendStates.entering_address)
async def send_process_address(message: Message, state: FSMContext):
    """Process recipient address"""
    address = message.text.strip()
    data = await state.get_data()
    lang = data.get("lang", "en")
    network = data.get("network")
    
    # Validate address
    is_valid = await wallet_manager.validate_address(network, address)
    
    if not is_valid:
        await message.answer(
            get_text("send_invalid_address", lang, network=data.get("network_name")),
            reply_markup=get_cancel_keyboard(lang)
        )
        return
    
    await state.update_data(to_address=address)
    
    text = get_text("send_enter_amount", lang,
        symbol=data.get("symbol"),
        address=f"{address[:10]}...{address[-8:]}",
        balance=data.get("balance")
    )
    
    await message.answer(
        text, 
        reply_markup=get_amount_keyboard(lang, data.get("balance")),
        parse_mode="HTML"
    )
    await state.set_state(SendStates.entering_amount)


@router.callback_query(SendStates.entering_amount, F.data.startswith("amount_pct:"))
async def send_amount_percentage(callback: CallbackQuery, state: FSMContext):
    """Handle percentage amount selection"""
    percentage = int(callback.data.split(":")[1])
    data = await state.get_data()
    lang = data.get("lang", "en")
    balance = Decimal(data.get("balance", "0"))
    network = data.get("network")
    
    # Calculate amount
    amount = balance * Decimal(percentage) / Decimal(100)
    
    # For MAX, we need to subtract estimated gas
    if percentage == 100:
        try:
            gas_info = await wallet_manager.estimate_gas(
                network, 
                data.get("wallet_address"), 
                data.get("to_address"),
                amount
            )
            fee = gas_info.get("total_fee", Decimal("0"))
            amount = max(Decimal("0"), amount - fee)
        except Exception:
            # Fallback: use 95% for safety
            amount = balance * Decimal("0.95")
    
    if amount <= 0:
        await callback.answer("Insufficient balance for gas fees", show_alert=True)
        return
    
    await state.update_data(amount=str(amount))
    
    # Show confirmation
    await show_send_confirmation(callback.message, state, data, amount, lang)
    await state.set_state(SendStates.confirming)
    await callback.answer()


@router.message(SendStates.entering_amount)
async def send_process_amount(message: Message, state: FSMContext):
    """Process entered amount"""
    data = await state.get_data()
    lang = data.get("lang", "en")
    balance = Decimal(data.get("balance", "0"))
    
    try:
        amount = Decimal(message.text.strip().replace(",", "."))
        
        if amount <= 0:
            raise InvalidOperation("Amount must be positive")
        
        if amount > balance:
            await message.answer(
                get_text("send_insufficient_balance", lang,
                    symbol=data.get("symbol"),
                    balance=data.get("balance")
                ),
                reply_markup=get_cancel_keyboard(lang)
            )
            return
        
        await state.update_data(amount=str(amount))
        
        # Show confirmation
        await show_send_confirmation(message, state, data, amount, lang, is_callback=False)
        await state.set_state(SendStates.confirming)
        
    except (InvalidOperation, ValueError):
        await message.answer(
            get_text("send_invalid_amount", lang),
            reply_markup=get_cancel_keyboard(lang)
        )


async def show_send_confirmation(
    message_or_callback, 
    state: FSMContext, 
    data: dict, 
    amount: Decimal, 
    lang: str,
    is_callback: bool = True
):
    """Show send confirmation with gas estimation"""
    network = data.get("network")
    from_address = data.get("wallet_address")
    to_address = data.get("to_address")
    
    # 1. Инициализируем значения по умолчанию на случай ошибки
    fee = Decimal("0.001")
    fee_formatted = "~0.001"
    
    # Estimate gas
    try:
        # Теперь это объект GasEstimate, а не словарь
        gas_info = await wallet_manager.estimate_gas(network, from_address, to_address, amount)
        
        # 2. Используем доступ через точку (атрибуты dataclass)
        fee = gas_info.total_fee
        fee_formatted = f"{fee:.8f}".rstrip('0').rstrip('.')
        
    except Exception as e:
        logger.warning("Gas estimation failed, using default fee", error=str(e))
        # Здесь fee остается 0.001, а fee_formatted остается "~0.001"
    
    # 3. Теперь fee гарантированно существует и ассоциирован со значением
    await state.update_data(estimated_fee=str(fee))
    
    text = get_text("send_confirm", lang,
        icon=data.get("icon"),
        network=data.get("network_name"),
        address=to_address,
        amount=f"{amount:.8f}".rstrip('0').rstrip('.'),
        symbol=data.get("symbol"),
        fee=fee_formatted
    )
    
    # Определяем сообщение для редактирования
    msg = message_or_callback.message if is_callback else message_or_callback
    
    if is_callback:
        await safe_edit(msg, text, get_confirm_keyboard(lang))
    else:
        await message_or_callback.answer(text, reply_markup=get_confirm_keyboard(lang), parse_mode="HTML")


@router.callback_query(SendStates.confirming, F.data == "send_confirm")
async def send_request_pin(callback: CallbackQuery, state: FSMContext):
    """Request PIN for transaction confirmation"""
    data = await state.get_data()
    lang = data.get("lang", "en")
    
    await safe_edit(callback.message, get_text("enter_pin", lang), get_cancel_keyboard(lang))
    await state.set_state(SendStates.entering_pin)
    await callback.answer()


@router.message(SendStates.entering_pin)
async def send_execute(message: Message, state: FSMContext):
    """Verify PIN and execute transaction"""
    pin = message.text.strip()
    data = await state.get_data()
    lang = data.get("lang", "en")
    
    # Delete PIN message
    await safe_delete(message)
    
    # Prevent double execution
    current_state = await state.get_state()
    if current_state == SendStates.processing:
        return
    await state.set_state(SendStates.processing)
    
    # Show processing
    processing_msg = await message.answer(
        get_text("send_processing", lang),
        parse_mode="HTML"
    )
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, message.from_user.id)
        
        if not user:
            await state.clear()
            return
        
        # Verify PIN
        if not encryption_manager.verify_pin(pin, user.pin_hash):
            await processing_msg.edit_text(
                get_text("pin_incorrect", lang),
                reply_markup=get_back_keyboard(lang)
            )
            await state.clear()
            return
        
        try:
            # Execute transaction - возвращает TransactionResult, не строку!
            tx_result = await wallet_service.execute_send(
                session=session,
                user_id=user.id,
                wallet_id=data.get("wallet_id"),
                to_address=data.get("to_address"),
                amount=Decimal(data.get("amount")),
                pin=pin
            )
            
            # ============ ИСПРАВЛЕНИЕ: Проверяем результат ============
            # Проверяем, является ли результат объектом TransactionResult
            if hasattr(tx_result, 'success'):
                # Это TransactionResult объект
                if not tx_result.success:
                    # Транзакция не удалась
                    error_msg = tx_result.error or "Transaction failed"
                    await processing_msg.edit_text(
                        get_text("send_failed", lang, error=error_msg),
                        reply_markup=get_back_keyboard(lang)
                    )
                    await state.clear()
                    return
                
                # Успешная транзакция - извлекаем tx_hash
                tx_hash = tx_result.tx_hash
                tx_status = "completed"
                fee_paid = tx_result.fee_paid
            else:
                # Если это строка (tx_hash напрямую) - для обратной совместимости
                tx_hash = tx_result
                tx_status = "completed"
                fee_paid = None
            
            # Проверяем, что tx_hash существует
            if not tx_hash:
                await processing_msg.edit_text(
                    get_text("send_failed", lang, error="No transaction hash returned"),
                    reply_markup=get_back_keyboard(lang)
                )
                await state.clear()
                return
            
            # Record transaction - теперь передаём строку tx_hash, а не объект
            await transaction_service.create_transaction(
                session=session,
                user_id=user.id,
                tx_type="send",
                network=data.get("network"),
                token_symbol=data.get("symbol"),
                amount=Decimal(data.get("amount")),
                wallet_id=data.get("wallet_id"),
                tx_hash=tx_hash,  # ← Теперь это строка!
                from_address=data.get("wallet_address"),
                to_address=data.get("to_address"),
                fee_amount=Decimal(str(fee_paid)) if fee_paid else Decimal(data.get("estimated_fee", "0")),
                fee_token=data.get("symbol"),
                status=tx_status
            )
            
            await session.commit()
            
            # Build explorer link
            explorer_url = data.get("explorer_url", "")
            tx_link = f"{explorer_url}/tx/{tx_hash}"
            
            success_text = get_text("send_success", lang,
                amount=data.get("amount"),
                symbol=data.get("symbol"),
                address=data.get("to_address"),
                explorer=tx_link,
                tx_hash=f"{tx_hash[:16]}...{tx_hash[-8:]}"
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 View Transaction", url=tx_link)],
                [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="main_menu")]
            ])
            
            await processing_msg.edit_text(success_text, reply_markup=keyboard, parse_mode="HTML")
            
            logger.info(
                "Transaction sent",
                user_id=user.id,
                network=data.get("network"),
                amount=data.get("amount"),
                tx_hash=tx_hash
            )
            
        except InvalidPinError:
            await processing_msg.edit_text(
                get_text("pin_incorrect", lang),
                reply_markup=get_back_keyboard(lang)
            )
        except InsufficientFundsError as e:
            await processing_msg.edit_text(
                get_text("send_insufficient_balance", lang,
                    symbol=data.get("symbol"),
                    balance=data.get("balance")
                ),
                reply_markup=get_back_keyboard(lang)
            )
        except WalletServiceError as e:
            await processing_msg.edit_text(
                get_text("send_failed", lang, error=str(e)),
                reply_markup=get_back_keyboard(lang)
            )
        except Exception as e:
            logger.error("Send failed", error=str(e), exc_info=True)
            await processing_msg.edit_text(
                get_text("send_failed", lang, error="Transaction failed. Please try again."),
                reply_markup=get_back_keyboard(lang)
            )
    
    await state.clear()


# ==================== UTILITY FUNCTIONS ====================

def get_back_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Back to main menu keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="main_menu")]
    ])


async def safe_edit(message, text: str, keyboard: InlineKeyboardMarkup = None):
    """Safely edit message"""
    try:
        await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    except Exception as e:
        logger.error("Message edit failed", error=str(e))


async def safe_delete(message: Message):
    """Safely delete message"""
    try:
        await message.delete()
    except Exception:
        pass
"""
NEXUS WALLET - Start Handler (Production-Ready)
User registration and main menu with enhanced UX
"""

import asyncio
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, WebAppInfo
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
import structlog

from config.settings import settings
from database.connection import db_manager
from database.models import User
from database.repositories.user_repository import UserRepository
from security.encryption_manager import encryption_manager
from services.wallet_service import wallet_service
from locales.messages import get_text, get_user_lang

logger = structlog.get_logger(__name__)
router = Router(name="start")


class RegistrationStates(StatesGroup):
    choosing_language = State()
    setting_pin = State()
    confirming_pin = State()
    processing = State()


class PinVerificationStates(StatesGroup):
    entering_pin = State()


# ==================== KEYBOARDS ====================

def get_language_keyboard() -> InlineKeyboardMarkup:
    """Language selection keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇺🇸 English", callback_data="lang:en"),
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru")
        ],
        [
            InlineKeyboardButton(text="🇨🇳 中文", callback_data="lang:zh"),
            InlineKeyboardButton(text="🇪🇸 Español", callback_data="lang:es")
        ]
    ])


def get_main_menu_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Main menu with all features"""
    web_app_url = settings.WEB_APP_URL
    
    return InlineKeyboardMarkup(inline_keyboard=[
        # Web App
        [
            InlineKeyboardButton(
                text="💎 " + get_text("btn_open_wallet", lang).upper(),
                web_app=WebAppInfo(url=web_app_url)
            )
        ],
        # Main actions
        [
            InlineKeyboardButton(text=get_text("btn_wallet", lang), callback_data="wallet"),
            InlineKeyboardButton(text=get_text("btn_send", lang), callback_data="send"),
            InlineKeyboardButton(text=get_text("btn_receive", lang), callback_data="receive_menu")
        ],
        
        [
            InlineKeyboardButton(text="🌐 Cross-Chain", callback_data="real_swap"),  # Реальный
        ],

        # NEW: Checks & Giveaways
        [
            InlineKeyboardButton(text="🧾 Checks", callback_data="checks"),
            InlineKeyboardButton(text="🎁 Giveaways", callback_data="giveaways"),
        ],
        # Other features
        [
            InlineKeyboardButton(text="🤝 P2P Trading", callback_data="p2p"),
            InlineKeyboardButton(text="🏪 Shops", callback_data="shop"),
            InlineKeyboardButton(text="💳 Buy/Sell", callback_data="buy_crypto")
        ],
        # Settings & History
        [
            InlineKeyboardButton(text=get_text("btn_history", lang), callback_data="history"),
            InlineKeyboardButton(text=get_text("btn_settings", lang), callback_data="settings")
        ],
        [
            InlineKeyboardButton(text=get_text("btn_help", lang), callback_data="help")
        ]
    ])


def get_welcome_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Welcome keyboard after registration"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🚀 " + get_text("btn_open_wallet", lang), 
            web_app=WebAppInfo(url=settings.WEB_APP_URL)
        )],
        [
            InlineKeyboardButton(text="💼 " + get_text("btn_wallet", lang), callback_data="wallet"),
            InlineKeyboardButton(text=get_text("btn_tutorial", lang), callback_data="tutorial")
        ]
    ])


def get_back_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Back button keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="main_menu")]
    ])


def get_cancel_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Cancel button for FSM states"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_cancel", lang), callback_data="cancel_action")]
    ])


# ==================== COMMAND HANDLERS ====================

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Handle /start command"""
    # Clear any existing state
    await state.clear()
    
    user_id = message.from_user.id
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, user_id)
        
        if user:
            # Existing user - show main menu
            lang = user.language_code or "en"
            
            # Update last activity
            await user_repo.update(session, user.id, last_active_at=message.date)
            await session.commit()
            
            await show_main_menu(message, user, lang)
        else:
            # New user - start registration
            await start_registration(message, state)


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    """Handle /menu command"""
    await state.clear()
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, message.from_user.id)
        
        if user:
            lang = user.language_code or "en"
            await show_main_menu(message, user, lang)
        else:
            await message.answer(get_text("not_registered", "en"))


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Handle /help command"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, message.from_user.id)
        lang = user.language_code if user else "en"
        
        await message.answer(
            get_text("help", lang), 
            reply_markup=get_back_keyboard(lang),
            parse_mode="HTML"
        )


# ==================== REGISTRATION FLOW ====================

async def start_registration(message: Message, state: FSMContext):
    """Start registration for new user"""
    lang = get_user_lang(message.from_user)
    
    await message.answer(
        get_text("welcome", lang),
        reply_markup=get_language_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(RegistrationStates.choosing_language)


@router.callback_query(RegistrationStates.choosing_language, F.data.startswith("lang:"))
async def process_language(callback: CallbackQuery, state: FSMContext):
    """Process language selection"""
    lang = callback.data.split(":")[1]
    await state.update_data(language=lang)
    
    await callback.message.edit_text(
        get_text("pin_setup", lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML"
    )
    await state.set_state(RegistrationStates.setting_pin)
    await callback.answer()


@router.message(RegistrationStates.setting_pin)
async def process_pin_setup(message: Message, state: FSMContext):
    """Process PIN setup"""
    pin = message.text.strip()
    data = await state.get_data()
    lang = data.get("language", "en")
    
    # Delete the PIN message for security
    await safe_delete_message(message)
    
    # Validate PIN
    if not pin.isdigit() or len(pin) != 6:
        await message.answer(
            get_text("pin_invalid", lang),
            reply_markup=get_cancel_keyboard(lang)
        )
        return
    
    await state.update_data(pin=pin)
    await message.answer(
        get_text("pin_confirm", lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML"
    )
    await state.set_state(RegistrationStates.confirming_pin)


@router.message(RegistrationStates.confirming_pin)
async def process_pin_confirm(message: Message, state: FSMContext):
    """Confirm PIN and create user with wallets"""
    confirm_pin = message.text.strip()
    data = await state.get_data()
    lang = data.get("language", "en")
    original_pin = data.get("pin")
    
    # Delete the PIN message for security
    await safe_delete_message(message)
    
    # Verify PIN match
    if confirm_pin != original_pin:
        await message.answer(get_text("pin_mismatch", lang))
        await state.set_state(RegistrationStates.setting_pin)
        return
    
    # Prevent double-submission
    await state.set_state(RegistrationStates.processing)
    
    # Show progress
    creating_msg = await message.answer(
        get_text("creating_wallet", lang),
        parse_mode="HTML"
    )
    
    try:
        async with db_manager.session() as session:
            user_repo = UserRepository()
            
            # Hash PIN
            pin_hash = encryption_manager.hash_pin(original_pin)
            referral_code = encryption_manager.generate_referral_code()
            
            # Create user
            user = await user_repo.create(
                session=session,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                language_code=lang,
                pin_hash=pin_hash,
                referral_code=referral_code,
            )
            
            # Create initial wallets (TON, BSC, ETH)
            wallets = await wallet_service.create_initial_wallets(
                session=session,
                user_id=user.id,
                pin=original_pin
            )
            
            await session.commit()
        
        # Show success message
        networks_created = ", ".join([w.network.upper() for w in wallets])
        success_text = get_text("wallet_created", lang, referral_code=user.referral_code)
        success_text += f"\n\n🌐 <b>Созданные сети:</b> {networks_created}"
        
        await creating_msg.edit_text(
            success_text,
            reply_markup=get_welcome_keyboard(lang),
            parse_mode="HTML"
        )
        
        await state.clear()
        
        logger.info(
            "User registered",
            user_id=user.id,
            telegram_id=message.from_user.id,
            wallets_count=len(wallets)
        )
        
    except Exception as e:
        logger.error("Registration failed", error=str(e), exc_info=True)
        await creating_msg.edit_text(
            get_text("error_generic", lang),
            reply_markup=get_back_keyboard(lang),
            parse_mode="HTML"
        )
        await state.clear()


# ==================== CALLBACK HANDLERS ====================

@router.callback_query(F.data == "cancel_action")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    """Cancel current action and return to start"""
    await state.clear()
    await callback.message.edit_text(
        "❌ Action cancelled.\n\nUse /start to begin again.",
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: CallbackQuery, state: FSMContext):
    """Return to main menu"""
    await state.clear()
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        
        if user:
            lang = user.language_code or "en"
            await show_main_menu(callback.message, user, lang, edit=True)
        else:
            await callback.answer("Please /start first", show_alert=True)
    
    await callback.answer()


@router.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery):
    """Handle help button"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code if user else "en"
        
        await safe_edit_message(
            callback.message,
            get_text("help", lang),
            reply_markup=get_back_keyboard(lang)
        )
    await callback.answer()


@router.callback_query(F.data == "tutorial")
async def tutorial_callback(callback: CallbackQuery):
    """Handle tutorial button"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code if user else "en"
        
        tutorial_text = """
📚 <b>Быстрый старт NEXUS WALLET</b>

<b>1️⃣ Просмотр баланса</b>
Нажмите "💼 Кошелёк" для просмотра всех ваших активов.

<b>2️⃣ Получение криптовалюты</b>
Нажмите "📥 Получить" и выберите сеть. Скопируйте адрес или покажите QR-код.

<b>3️⃣ Отправка криптовалюты</b>
Нажмите "📤 Отправить", выберите сеть, введите адрес и сумму.

<b>4️⃣ Обмен токенов</b>
Нажмите "💱 Swap" для мгновенного обмена между токенами.

<b>5️⃣ P2P Торговля</b>
Нажмите "🤝 P2P" для покупки/продажи криптовалюты за фиат.

<b>⚠️ Важно:</b>
• Никогда не делитесь своим PIN-кодом
• Сделайте резервную копию в настройках
• Отправляйте токены только в правильную сеть
"""
        
        await safe_edit_message(
            callback.message,
            tutorial_text,
            reply_markup=get_back_keyboard(lang)
        )
    await callback.answer()


# ==================== UTILITY FUNCTIONS ====================

async def show_main_menu(
    message: Message, 
    user: User, 
    lang: str = "en", 
    edit: bool = False
):
    """Show main menu"""
    name = user.first_name or user.username or "User"
    
    # Get portfolio value
    try:
        async with db_manager.session() as session:
            portfolio_usd = await wallet_service.get_total_portfolio_usd(session, user.id)
            portfolio_text = f"💰 Portfolio: <b>${portfolio_usd:,.2f}</b>\n\n" if portfolio_usd > 0 else ""
    except Exception:
        portfolio_text = ""
    
    menu_text = f"👋 {get_text('main_menu', lang, name=name)}\n\n{portfolio_text}"
    keyboard = get_main_menu_keyboard(lang)
    
    if edit:
        await safe_edit_message(message, menu_text, reply_markup=keyboard)
    else:
        await message.answer(menu_text, reply_markup=keyboard, parse_mode="HTML")


async def safe_delete_message(message: Message):
    """Safely delete a message, ignoring errors"""
    try:
        await message.delete()
    except Exception:
        pass


async def safe_edit_message(
    message: Message, 
    text: str, 
    reply_markup: InlineKeyboardMarkup = None
):
    """Safely edit a message, handling common errors"""
    try:
        await message.edit_text(
            text, 
            reply_markup=reply_markup, 
            parse_mode="HTML"
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logger.warning("Failed to edit message", error=str(e))
    except Exception as e:
        logger.error("Message edit failed", error=str(e))
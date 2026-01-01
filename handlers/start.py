import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
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
from locales.messages import get_text, get_user_lang

logger = structlog.get_logger(__name__)
router = Router(name="start")


class RegistrationStates(StatesGroup):
    choosing_language = State()
    setting_pin = State()
    confirming_pin = State()


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
    """Main menu with Web App button"""
    
    # Use URL from settings
    web_app_url = settings.WEB_APP_URL
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="💎 OPEN WEB WALLET",
                web_app=WebAppInfo(url=web_app_url)
            )
        ],
        [
            InlineKeyboardButton(text=get_text("btn_wallet", lang), callback_data="wallet"),
            InlineKeyboardButton(text=get_text("btn_send", lang), callback_data="send"),
            InlineKeyboardButton(text=get_text("btn_receive", lang), callback_data="receive_menu")
        ],
        [
            InlineKeyboardButton(text=get_text("btn_swap", lang), callback_data="swap"),
            InlineKeyboardButton(text=get_text("btn_p2p", lang), callback_data="p2p")
        ],
        [
            InlineKeyboardButton(text=get_text("btn_history", lang), callback_data="history"),
            InlineKeyboardButton(text=get_text("btn_settings", lang), callback_data="settings")
        ],
        [
            InlineKeyboardButton(text=get_text("btn_help", lang), callback_data="help")
        ]
    ])


def get_welcome_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Welcome keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🚀 " + get_text("btn_open_wallet", lang), 
            web_app=WebAppInfo(url=settings.WEB_APP_URL)
        )],
        [InlineKeyboardButton(text=get_text("btn_tutorial", lang), callback_data="tutorial")]
    ])


def get_back_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Back button keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="main_menu")]
    ])


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Handle /start command"""
    user_id = message.from_user.id

    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, user_id)

        if user:
            lang = user.language_code or "en"
            await show_main_menu(message, user, lang)
        else:
            await start_registration(message, state)


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

    try:
        await message.delete()
    except Exception:
        pass

    if not pin.isdigit() or len(pin) != 6:
        await message.answer(get_text("pin_invalid", lang))
        return

    await state.update_data(pin=pin)
    await message.answer(get_text("pin_confirm", lang), parse_mode="HTML")
    await state.set_state(RegistrationStates.confirming_pin)


@router.message(RegistrationStates.confirming_pin)
async def process_pin_confirm(message: Message, state: FSMContext):
    """Confirm PIN and create user"""
    confirm_pin = message.text.strip()
    data = await state.get_data()
    lang = data.get("language", "en")

    try:
        await message.delete()
    except Exception:
        pass

    original_pin = data.get("pin")

    if confirm_pin != original_pin:
        await message.answer(get_text("pin_mismatch", lang))
        await state.set_state(RegistrationStates.setting_pin)
        return

    creating_msg = await message.answer(
        get_text("creating_wallet", lang),
        parse_mode="HTML"
    )

    try:
        async with db_manager.session() as session:
            user_repo = UserRepository()

            pin_hash = encryption_manager.hash_pin(original_pin)
            referral_code = encryption_manager.generate_referral_code()

            user = await user_repo.create(
                session=session,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                language_code=lang,
                pin_hash=pin_hash,
                referral_code=referral_code
            )
            await session.commit()

        success_text = get_text("wallet_created", lang, referral_code=user.referral_code)

        await creating_msg.edit_text(
            success_text,
            reply_markup=get_welcome_keyboard(lang),
            parse_mode="HTML"
        )

        await state.clear()

        logger.info(
            "New user registered",
            user_id=user.id,
            telegram_id=message.from_user.id
        )

    except Exception as e:
        logger.error("Registration failed", error=str(e))
        await creating_msg.edit_text(
            get_text("error_generic", lang),
            parse_mode="HTML"
        )
        await state.clear()


@router.callback_query(F.data == "open_wallet")
async def open_wallet(callback: CallbackQuery):
    """Open main wallet menu"""
    # This might be deprecated if we use WebApp button directly, 
    # but good to keep as fallback logic
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)

        if user:
            lang = user.language_code or "en"
            await show_main_menu(callback.message, user, lang, edit=True)
        else:
            await callback.answer("Please /start first", show_alert=True)
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: CallbackQuery):
    """Return to main menu"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)

        if user:
            lang = user.language_code or "en"
            await show_main_menu(callback.message, user, lang, edit=True)
    await callback.answer()


async def show_main_menu(message: Message, user: User, lang: str = "en", edit: bool = False):
    """Show main menu"""
    name = user.first_name or user.username or "User"

    menu_text = get_text("main_menu", lang, name=name)
    keyboard = get_main_menu_keyboard(lang)

    try:
        if edit:
            await message.edit_text(menu_text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message.answer(menu_text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    except Exception as e:
        logger.error("Failed to show main menu", error=e)


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    """Handle /menu command"""
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
        await message.answer(get_text("help", lang), parse_mode="HTML")


@router.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery):
    """Handle help button"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code if user else "en"

        try:
            await callback.message.edit_text(
                get_text("help", lang),
                reply_markup=get_back_keyboard(lang),
                parse_mode="HTML"
            )
        except TelegramBadRequest:
            pass
    await callback.answer()


@router.callback_query(F.data == "tutorial")
async def tutorial_callback(callback: CallbackQuery):
    """Handle tutorial button"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code if user else "en"

        try:
            await callback.message.edit_text(
                get_text("help", lang),
                reply_markup=get_back_keyboard(lang),
                parse_mode="HTML"
            )
        except TelegramBadRequest:
            pass
    await callback.answer()
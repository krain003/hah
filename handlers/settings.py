"""
NEXUS WALLET - Settings Handler
User preferences and wallet settings
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from io import BytesIO
import structlog

from database.connection import db_manager
from database.repositories.user_repository import UserRepository
from database.repositories.wallet_repository import WalletRepository
from security.encryption_manager import encryption_manager
from locales.messages import get_text
from keyboards.inline import get_back_keyboard

logger = structlog.get_logger()
router = Router(name="settings")

# Check if pyotp is available
try:
    import pyotp
    import qrcode
    TOTP_AVAILABLE = True
except ImportError:
    TOTP_AVAILABLE = False
    logger.warning("pyotp or qrcode not installed, 2FA disabled")


class SettingsStates(StatesGroup):
    changing_pin_old = State()
    changing_pin_new = State()
    changing_pin_confirm = State()
    enabling_2fa = State()
    disabling_2fa = State()


# Available languages
LANGUAGES = {
    "en": "🇬🇧 English",
    "ru": "🇷🇺 Русский",
    "zh": "🇨🇳 中文",
    "es": "🇪🇸 Español",
}

# Available currencies
CURRENCIES = {
    "USD": "🇺🇸 US Dollar",
    "EUR": "🇪🇺 Euro",
    "GBP": "🇬🇧 British Pound",
    "RUB": "🇷🇺 Russian Ruble",
    "UAH": "🇺🇦 Ukrainian Hryvnia",
    "CNY": "🇨🇳 Chinese Yuan",
    "TRY": "🇹🇷 Turkish Lira",
}


async def safe_edit_text(message, text, reply_markup=None, parse_mode="HTML"):
    """Safely edit message text, handle photo messages"""
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        if "there is no text in the message" in str(e):
            # Message is a photo, delete and send new
            try:
                await message.delete()
            except Exception:
                pass
            await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
        elif "message is not modified" in str(e):
            pass
        else:
            raise


@router.callback_query(F.data == "settings")
async def settings_menu(callback: CallbackQuery, state: FSMContext):
    """Show settings menu"""
    await state.clear()
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
        
        current_lang = LANGUAGES.get(user.language_code, "🇬🇧 English")
        current_currency = CURRENCIES.get(user.default_currency, "🇺🇸 US Dollar")
        notifications = "✅ On" if user.notifications_enabled else "❌ Off"
        two_fa = "✅ Enabled" if user.two_factor_enabled else "❌ Disabled"
    
    text = get_text("settings_menu", lang) + "\n\n"
    text += f"📍 Current settings:\n"
    text += f"• Language: {current_lang}\n"
    text += f"• Currency: {current_currency}\n"
    text += f"• Notifications: {notifications}\n"
    text += f"• 2FA: {two_fa}\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🌐 " + get_text("settings_language", lang),
                callback_data="settings:language"
            ),
            InlineKeyboardButton(
                text="💵 " + get_text("settings_currency", lang),
                callback_data="settings:currency"
            ),
        ],
        [
            InlineKeyboardButton(
                text="🔐 " + get_text("settings_change_pin", lang),
                callback_data="settings:change_pin"
            ),
            InlineKeyboardButton(
                text="🛡 " + get_text("settings_2fa", lang),
                callback_data="settings:2fa"
            ),
        ],
        [
            InlineKeyboardButton(
                text="🔔 " + get_text("settings_notifications", lang),
                callback_data="settings:notifications"
            ),
            InlineKeyboardButton(
                text="👥 " + get_text("settings_referral", lang),
                callback_data="settings:referral"
            ),
        ],
        [
            InlineKeyboardButton(
                text="📊 Statistics",
                callback_data="settings:stats"
            ),
            InlineKeyboardButton(
                text="ℹ️ About",
                callback_data="settings:about"
            ),
        ],
        [
            InlineKeyboardButton(
                text=get_text("btn_back", lang),
                callback_data="main_menu"
            )
        ]
    ])
    
    await safe_edit_text(callback.message, text, keyboard)
    await callback.answer()


@router.callback_query(F.data == "settings:language")
async def change_language(callback: CallbackQuery):
    """Change language settings"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
    
    text = "🌐 <b>Select Language</b>\n\nChoose your preferred language:"
    
    buttons = []
    for code, name in LANGUAGES.items():
        if code == user.language_code:
            btn_text = f"• {name} •"
        else:
            btn_text = name
        
        buttons.append([InlineKeyboardButton(
            text=btn_text,
            callback_data=f"settings:set_lang:{code}"
        )])
    
    buttons.append([InlineKeyboardButton(
        text=get_text("btn_back", lang),
        callback_data="settings"
    )])
    
    await safe_edit_text(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("settings:set_lang:"))
async def set_language(callback: CallbackQuery):
    """Set new language"""
    new_lang = callback.data.split(":")[2]
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        
        await user_repo.update_language(session, user.id, new_lang)
        await session.commit()
    
    await safe_edit_text(
        callback.message,
        get_text("settings_language_changed", new_lang),
        get_back_keyboard("settings", new_lang)
    )
    await callback.answer("✅")


@router.callback_query(F.data == "settings:currency")
async def change_currency(callback: CallbackQuery):
    """Change default currency"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
    
    text = "💵 <b>Select Default Currency</b>\n\nChoose your preferred fiat currency:"
    
    buttons = []
    row = []
    for code, name in CURRENCIES.items():
        if code == user.default_currency:
            btn_text = f"• {code} •"
        else:
            btn_text = code
        
        row.append(InlineKeyboardButton(
            text=btn_text,
            callback_data=f"settings:set_curr:{code}"
        ))
        
        if len(row) == 3:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(
        text=get_text("btn_back", lang),
        callback_data="settings"
    )])
    
    await safe_edit_text(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("settings:set_curr:"))
async def set_currency(callback: CallbackQuery):
    """Set new currency"""
    new_currency = callback.data.split(":")[2]
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
        
        await user_repo.update(session, user.id, default_currency=new_currency)
        await session.commit()
    
    await safe_edit_text(
        callback.message,
        f"✅ Default currency changed to <b>{CURRENCIES[new_currency]}</b>",
        get_back_keyboard("settings", lang)
    )
    await callback.answer("✅")


@router.callback_query(F.data == "settings:notifications")
async def toggle_notifications(callback: CallbackQuery):
    """Toggle notifications on/off"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
        
        new_state = not user.notifications_enabled
        await user_repo.update(session, user.id, notifications_enabled=new_state)
        await session.commit()
    
    status = "enabled" if new_state else "disabled"
    emoji = "✅" if new_state else "❌"
    
    await safe_edit_text(
        callback.message,
        f"{emoji} Notifications <b>{status}</b>",
        get_back_keyboard("settings", lang)
    )
    await callback.answer(f"Notifications {status}")


@router.callback_query(F.data == "settings:change_pin")
async def start_change_pin(callback: CallbackQuery, state: FSMContext):
    """Start PIN change process"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
    
    await state.update_data(lang=lang)
    
    await safe_edit_text(
        callback.message,
        "🔐 <b>Change PIN</b>\n\nEnter your current PIN:",
        get_back_keyboard("settings", lang)
    )
    await state.set_state(SettingsStates.changing_pin_old)
    await callback.answer()


@router.message(SettingsStates.changing_pin_old)
async def verify_old_pin(message: Message, state: FSMContext):
    """Verify current PIN"""
    old_pin = message.text.strip()
    data = await state.get_data()
    lang = data.get("lang", "en")
    
    try:
        await message.delete()
    except Exception:
        pass
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, message.from_user.id)
        
        if not encryption_manager.verify_pin(old_pin, user.pin_hash):
            await message.answer(
                get_text("pin_incorrect", lang),
                reply_markup=get_back_keyboard("settings", lang),
                parse_mode="HTML"
            )
            await state.clear()
            return
    
    await message.answer(
        "✅ PIN verified\n\nEnter your new 6-digit PIN:",
        parse_mode="HTML"
    )
    await state.set_state(SettingsStates.changing_pin_new)


@router.message(SettingsStates.changing_pin_new)
async def enter_new_pin(message: Message, state: FSMContext):
    """Enter new PIN"""
    new_pin = message.text.strip()
    data = await state.get_data()
    lang = data.get("lang", "en")
    
    try:
        await message.delete()
    except Exception:
        pass
    
    if not new_pin.isdigit() or len(new_pin) != 6:
        await message.answer(
            get_text("pin_invalid", lang),
            parse_mode="HTML"
        )
        return
    
    await state.update_data(new_pin=new_pin)
    await message.answer(
        "🔄 Confirm your new PIN:",
        parse_mode="HTML"
    )
    await state.set_state(SettingsStates.changing_pin_confirm)


@router.message(SettingsStates.changing_pin_confirm)
async def confirm_new_pin(message: Message, state: FSMContext):
    """Confirm new PIN"""
    confirm_pin = message.text.strip()
    data = await state.get_data()
    lang = data.get("lang", "en")
    new_pin = data.get("new_pin")
    
    try:
        await message.delete()
    except Exception:
        pass
    
    if confirm_pin != new_pin:
        await message.answer(
            get_text("pin_mismatch", lang),
            reply_markup=get_back_keyboard("settings", lang),
            parse_mode="HTML"
        )
        await state.clear()
        return
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, message.from_user.id)
        
        new_pin_hash = encryption_manager.hash_pin(new_pin)
        await user_repo.update_pin(session, user.id, new_pin_hash)
        await session.commit()
    
    await message.answer(
        "✅ <b>PIN changed successfully!</b>\n\nUse your new PIN for all secure operations.",
        reply_markup=get_back_keyboard("settings", lang),
        parse_mode="HTML"
    )
    await state.clear()


@router.callback_query(F.data == "settings:2fa")
async def two_factor_menu(callback: CallbackQuery):
    """Two-factor authentication settings"""
    if not TOTP_AVAILABLE:
        await callback.answer("2FA not available. Install: pip install pyotp qrcode", show_alert=True)
        return
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
    
    if user.two_factor_enabled:
        text = "🛡 <b>Two-Factor Authentication</b>\n\n"
        text += "✅ 2FA is currently <b>ENABLED</b>\n\n"
        text += "Your account has an extra layer of security."
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="❌ Disable 2FA",
                callback_data="settings:2fa:disable"
            )],
            [InlineKeyboardButton(
                text=get_text("btn_back", lang),
                callback_data="settings"
            )]
        ])
    else:
        text = "🛡 <b>Two-Factor Authentication</b>\n\n"
        text += "❌ 2FA is currently <b>DISABLED</b>\n\n"
        text += "Enable 2FA to add an extra layer of security to your wallet."
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Enable 2FA",
                callback_data="settings:2fa:enable"
            )],
            [InlineKeyboardButton(
                text=get_text("btn_back", lang),
                callback_data="settings"
            )]
        ])
    
    await safe_edit_text(callback.message, text, keyboard)
    await callback.answer()


@router.callback_query(F.data == "settings:2fa:enable")
async def enable_2fa(callback: CallbackQuery, state: FSMContext):
    """Enable 2FA - show QR code"""
    if not TOTP_AVAILABLE:
        await callback.answer("2FA not available", show_alert=True)
        return
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
        
        # Generate secret
        secret = pyotp.random_base32()
        await state.update_data(secret=secret, lang=lang)
        
        # Generate provisioning URI
        totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=f"@{user.username or user.telegram_id}",
            issuer_name="NEXUS WALLET"
        )
        
        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(totp_uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        bio = BytesIO()
        img.save(bio, format="PNG")
        bio.seek(0)
    
    text = "🛡 <b>Enable Two-Factor Authentication</b>\n\n"
    text += "1️⃣ Install Google Authenticator or similar app\n"
    text += "2️⃣ Scan this QR code\n"
    text += "3️⃣ Enter the 6-digit code from the app\n\n"
    text += f"Manual entry key:\n<code>{secret}</code>"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=get_text("btn_cancel", lang),
            callback_data="settings:2fa"
        )]
    ])
    
    # Delete old message and send photo
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    await callback.message.answer_photo(
        photo=BufferedInputFile(bio.read(), filename="2fa_qr.png"),
        caption=text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    await state.set_state(SettingsStates.enabling_2fa)
    await callback.answer()


@router.message(SettingsStates.enabling_2fa)
async def verify_2fa_code(message: Message, state: FSMContext):
    """Verify 2FA code and enable"""
    code = message.text.strip()
    data = await state.get_data()
    lang = data.get("lang", "en")
    secret = data.get("secret")
    
    if not TOTP_AVAILABLE or not secret:
        await message.answer("Error enabling 2FA. Try again.")
        await state.clear()
        return
    
    # Verify code
    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        await message.answer(
            "❌ Invalid code. Please try again:",
            parse_mode="HTML"
        )
        return
    
    # Enable 2FA
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, message.from_user.id)
        
        # Encrypt secret before storing
        encrypted_secret = encryption_manager.encrypt_private_key(secret)
        
        await user_repo.update(
            session,
            user.id,
            two_factor_enabled=True,
            two_factor_secret=encrypted_secret
        )
        await session.commit()
    
    await message.answer(
        "✅ <b>2FA Enabled Successfully!</b>\n\n"
        "Your account now has two-factor authentication.\n"
        "You'll need to enter a code from your authenticator app for sensitive operations.",
        reply_markup=get_back_keyboard("settings", lang),
        parse_mode="HTML"
    )
    await state.clear()


@router.callback_query(F.data == "settings:2fa:disable")
async def disable_2fa(callback: CallbackQuery, state: FSMContext):
    """Disable 2FA - ask for code"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
    
    await state.update_data(lang=lang)
    
    await safe_edit_text(
        callback.message,
        "🛡 <b>Disable 2FA</b>\n\n"
        "Enter your 6-digit authenticator code to disable 2FA:",
        get_back_keyboard("settings:2fa", lang)
    )
    await state.set_state(SettingsStates.disabling_2fa)
    await callback.answer()


@router.message(SettingsStates.disabling_2fa)
async def verify_disable_2fa(message: Message, state: FSMContext):
    """Verify code and disable 2FA"""
    code = message.text.strip()
    data = await state.get_data()
    lang = data.get("lang", "en")
    
    if not TOTP_AVAILABLE:
        await message.answer("Error. Try again.")
        await state.clear()
        return
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, message.from_user.id)
        
        # Decrypt and verify
        if user.two_factor_secret:
            try:
                secret = encryption_manager.decrypt_private_key(user.two_factor_secret)
                totp = pyotp.TOTP(secret)
                
                if not totp.verify(code, valid_window=1):
                    await message.answer(
                        "❌ Invalid code. Please try again:",
                        parse_mode="HTML"
                    )
                    return
            except Exception as e:
                logger.error("2FA verify failed", error=str(e))
                await message.answer("Error verifying code. Try again.")
                await state.clear()
                return
        
        # Disable 2FA
        await user_repo.update(
            session,
            user.id,
            two_factor_enabled=False,
            two_factor_secret=None
        )
        await session.commit()
    
    await message.answer(
        "✅ <b>2FA Disabled</b>\n\n"
        "Two-factor authentication has been disabled.\n"
        "⚠️ Your account is now less secure.",
        reply_markup=get_back_keyboard("settings", lang),
        parse_mode="HTML"
    )
    await state.clear()


@router.callback_query(F.data == "settings:referral")
async def referral_program(callback: CallbackQuery):
    """Show referral program info"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
        
        referral_count = 0
        referral_earnings = 0.0
    
    text = "👥 <b>Referral Program</b>\n\n"
    text += "Invite friends and earn rewards!\n\n"
    text += f"🔗 Your referral code:\n<code>{user.referral_code}</code>\n\n"
    text += f"📊 Statistics:\n"
    text += f"• Referrals: {referral_count}\n"
    text += f"• Earnings: ${referral_earnings:.2f}\n\n"
    text += "💎 <b>Rewards:</b>\n"
    text += "• Get 10% of trading fees from your referrals\n"
    text += "• Bonus rewards for active traders\n"
    text += "• VIP tier upgrades"
    
    referral_link = f"https://t.me/NEXUS_WALLET_bot?start={user.referral_code}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📤 Share Referral Link",
            url=f"https://t.me/share/url?url={referral_link}&text=Join%20NEXUS%20WALLET!"
        )],
        [InlineKeyboardButton(
            text=get_text("btn_back", lang),
            callback_data="settings"
        )]
    ])
    
    await safe_edit_text(callback.message, text, keyboard)
    await callback.answer()


@router.callback_query(F.data == "settings:stats")
async def show_statistics(callback: CallbackQuery):
    """Show user statistics"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
        
        wallet_repo = WalletRepository()
        wallets = await wallet_repo.get_user_wallets(session, user.id)
        wallet_count = len(wallets)
    
    text = "📊 <b>Your Statistics</b>\n\n"
    text += f"👤 User ID: <code>{user.telegram_id}</code>\n"
    text += f"📅 Member since: {user.created_at.strftime('%d %b %Y')}\n"
    text += f"⭐ VIP Tier: {user.vip_tier}\n\n"
    text += f"💼 Wallets: {wallet_count}\n"
    text += f"📈 Total volume: ${float(user.total_volume_usd or 0):,.2f}\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=get_text("btn_back", lang),
            callback_data="settings"
        )]
    ])
    
    await safe_edit_text(callback.message, text, keyboard)
    await callback.answer()


@router.callback_query(F.data == "settings:about")
async def show_about(callback: CallbackQuery):
    """Show about info"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
    
    text = "ℹ️ <b>About NEXUS WALLET</b>\n\n"
    text += "Version: 1.0.0\n"
    text += "Build: 2024.12.29\n\n"
    text += "🌟 <b>Features:</b>\n"
    text += "• Multi-chain wallet support\n"
    text += "• Instant token swaps\n"
    text += "• P2P trading marketplace\n"
    text += "• Military-grade encryption\n"
    text += "• 2FA protection\n\n"
    text += "🔗 <b>Links:</b>\n"
    text += "• Support: @Nexus_Support_wallet_bot\n\n"
    text += "Made with ❤️ by NEXUS Team"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Support", url="https://t.me/Nexus_Support_wallet_bot")],
        [InlineKeyboardButton(
            text=get_text("btn_back", lang),
            callback_data="settings"
        )]
    ])
    
    await safe_edit_text(callback.message, text, keyboard)
    await callback.answer()
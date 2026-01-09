"""
NEXUS WALLET - Receive Handler
Show addresses and QR codes for receiving crypto
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
import qrcode
from io import BytesIO
import structlog

from database.connection import db_manager
from database.repositories.user_repository import UserRepository
from database.repositories.wallet_repository import WalletRepository
from blockchain.wallet_manager import NETWORKS
from locales.messages import get_text
from keyboards.inline import get_back_keyboard, get_networks_keyboard

logger = structlog.get_logger()
router = Router(name="receive")


async def safe_edit_text(callback: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup):
    """
    Safely edit message text. 
    If message is a photo (QR code), delete it and send new text message.
    """
    try:
        await callback.message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    except TelegramBadRequest as e:
        if "there is no text in the message to edit" in str(e):
            # It was a photo/QR code, delete and send new
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        elif "message is not modified" in str(e):
            pass  # Ignore if content hasn't changed
        else:
            logger.error("Failed to edit message", error=str(e))


@router.callback_query(F.data == "receive_menu")
async def receive_menu(callback: CallbackQuery):
    """Show receive menu - select network"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
        
        wallet_repo = WalletRepository()
        wallets = await wallet_repo.get_user_wallets(session, user.id)
        
        if not wallets:
            await safe_edit_text(
                callback,
                get_text("wallet_empty", lang),
                get_back_keyboard("main_menu", lang)
            )
            await callback.answer()
            return
        
        await safe_edit_text(
            callback,
            get_text("receive_choose_network", lang),
            get_networks_keyboard(lang, "receive", wallets)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("receive:"))
async def show_receive_address(callback: CallbackQuery):
    """Show address for selected network"""
    parts = callback.data.split(":")
    network = parts[1]
    
    # Handle QR request separately
    if network == "qr":
        if len(parts) >= 3:
            real_network = parts[2]
            await show_qr_code(callback, real_network)
        return
    
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
        
        wallet_repo = WalletRepository()
        wallet = await wallet_repo.get_user_wallet_by_network(session, user.id, network)
        
        if not wallet:
            await callback.answer("Wallet not found", show_alert=True)
            return
        
        config = NETWORKS.get(network)
        if not config:
            await callback.answer("Network not supported", show_alert=True)
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📱 " + get_text("receive_show_qr", lang),
                    callback_data=f"receive:qr:{network}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 " + get_text("receive_copy_address", lang),
                    callback_data=f"copy:{wallet.address}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=get_text("btn_back", lang),
                    callback_data="receive_menu"
                )
            ]
        ])
        
        text = get_text("receive_address", lang,
                       symbol=config.symbol,
                       icon=config.icon,
                       network=config.name,
                       address=wallet.address)
        
        await safe_edit_text(callback, text, keyboard)
        
    await callback.answer()


async def show_qr_code(callback: CallbackQuery, network: str):
    """Generate and send QR code"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"
        
        wallet_repo = WalletRepository()
        wallet = await wallet_repo.get_user_wallet_by_network(session, user.id, network)
        
        if not wallet:
            await callback.answer("Wallet not found", show_alert=True)
            return
        
        config = NETWORKS.get(network)
        
        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(wallet.address)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Save to bytes
        bio = BytesIO()
        img.save(bio, format="PNG")
        bio.seek(0)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=get_text("btn_back", lang),
                callback_data=f"receive:{network}"
            )]
        ])
        
        caption = f"{config.icon} <b>{config.name}</b>\n\n"
        caption += f"📋 <code>{wallet.address}</code>"
        
        # Delete old message (whether text or photo) and send new photo
        try:
            await callback.message.delete()
        except Exception:
            pass
            
        await callback.message.answer_photo(
            photo=BufferedInputFile(bio.read(), filename="qr.png"),
            caption=caption,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    await callback.answer()


@router.callback_query(F.data.startswith("copy:"))
async def copy_address(callback: CallbackQuery):
    """Handle copy button - just show notification"""
    address = callback.data.replace("copy:", "")
    # In Telegram, tapping `code` text copies it automatically.
    # This button is visual aid, or for older clients.
    await callback.answer(f"📋 Copied: {address[:6]}...{address[-4:]}", show_alert=True)